"""Browse compatible Civitai files and keep a manifest of local installs."""

import hashlib
import time
import io
import json
import os
import re
import struct
import tempfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit

import requests
from PIL import Image, ImageOps

from cf_assets import API, HOST, CivitaiHTTPError, request

ROLE_TYPES = {
    "Checkpoint": "checkpoints", "Difusão": "diffusion_models", "LoRA": "loras",
    "VAE": "vae", "Encoder": "text_encoders", "ControlNet": "controlnet",
    "Upscaler": "upscale_models", "Embedding": "embeddings", "CLIP Vision": "clip_vision",
    "Motion Module": "animatediff_models", "Workflow": "",
}
QUERY_TYPES = {
    "Checkpoint": ("Checkpoint",), "Difusão": ("UNet", "Checkpoint"), "LoRA": ("LORA", "LoCon", "DoRA"),
    "VAE": ("VAE", "Checkpoint"), "Encoder": ("TextEncoder", "Checkpoint"), "ControlNet": ("Controlnet",),
    "Upscaler": ("Upscaler",), "Embedding": ("TextualInversion",), "Workflow": ("Workflows",),
    "CLIP Vision": ("CLIPVision",), "Motion Module": ("MotionModule",),
}
WEIGHT_SUFFIX = ".safetensors"
MEDIA_HOSTS = {"image.civitai.com", "image-b2.civitai.com", "blobs-b2.civitai.com"}
COVER_IMAGES = {".gif", ".png", ".jpg", ".jpeg", ".webp", ".avif"}
COVER_LIMIT = 4
COVER_MAX_BYTES = 12 * 1024**2
COVER_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif", "video/mp4", "video/webm"}
_cover_lock = Lock()
_cover_sources = OrderedDict()


def normalized(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def api_json(endpoint, params=None):
    url = f"{API}/api/v1/{endpoint}"
    if params:
        url += "?" + urlencode(params, doseq=True)
    try:
        with requests.Session() as session, request(session, url, os.getenv("CIVITAI_TOKEN")) as response:
            return response.json()
    except requests.RequestException:
        raise ValueError("Não foi possível consultar o Civitai. Confira a conexão do runtime.") from None


def file_role(model_type, file):
    kind = normalized(file.get("type"))
    name = str(file.get("name", ""))
    suffix = Path(name).suffix.lower()
    if normalized(model_type) in {"workflow", "workflows"}:
        return "Workflow" if suffix in {".json", ".zip", ".png"} else None
    if suffix != WEIGHT_SUFFIX:
        return None
    if kind == "vae":
        return "VAE"
    if kind in {"clip", "textencoder", "encoder"}:
        return "Encoder"
    if kind != "model":
        return None
    role = {"lora": "LoRA", "locon": "LoRA", "dora": "LoRA", "vae": "VAE", "controlnet": "ControlNet",
            "upscaler": "Upscaler", "textualinversion": "Embedding", "checkpoint": "Checkpoint",
            "textencoder": "Encoder", "unet": "Difusão", "clipvision": "CLIP Vision",
            "motionmodule": "Motion Module"}.get(normalized(model_type))
    if role == "Checkpoint" and normalized((file.get("metadata") or {}).get("size")) in {
        "unet", "diffusion", "transformer", "unetonly"
    }:
        return "Difusão"
    return role



# ---------------------------------------------------------------- variant identity
# One Civitai version often holds many files of the SAME weights in different quantisations (NVFP4 ~4 GB, FP8 / INT8 ~6.9 GB,
# BF16 ~13.6 GB). Each file is its own variant: provider + model + version + file id + sha256 + quantisation + size.
QUANTS = (("nvfp4", "NVFP4", r"nv[-_ ]?fp4"), ("mxfp8", "MXFP8", r"mxfp8"), ("int8", "INT8", r"int8"), ("int6", "INT6", r"int6|w6a8"),
          ("int4", "INT4", r"int4|w4a8|a4w4"), ("fp8", "FP8", r"fp8|e4m3|e5m2"), ("bf16", "BF16", r"bf16"), ("fp16", "FP16", r"fp16|f16"),
          ("fp32", "FP32", r"fp32"))
QUANT_LABEL = {key: label for key, label, _ in QUANTS}


def quant_of(*texts):
    """The quantisation a file name (then version name) announces, or None."""
    for text in texts:
        lowered = str(text or "").lower()
        for key, _label, pattern in QUANTS:
            if re.search(pattern, lowered):
                return key
    return None


def quant_label(name, quant):
    if not quant:
        return ""
    return QUANT_LABEL[quant] + (" ConvRot" if quant == "int8" and "convrot" in str(name).lower() else "")


def human_bytes(n):
    return (f"{n / 1e9:.1f}".replace(".", ",") + " GB") if n >= 1e9 else f"{round(n / 1e6)} MB"


def variant_of(entry):
    """The immutable identity of one downloadable file."""
    return dict(provider="civitai", model_id=entry["model"], version_id=entry["version"], file_id=entry["file"], sha256=entry.get("sha256"),
                quant=entry.get("quant"), size_bytes=entry.get("size_bytes"), file_name=entry["name"])


def check_delivery(entry, headers):
    """Compare what the CDN says it is about to deliver with what the list announced. Refuses before a single GB is downloaded."""
    announced, problems = entry.get("quant"), []
    disposition = next((v for k, v in headers.items() if k.lower() == "content-disposition"), "")
    match = re.search(r"filename\*?=(?:UTF-8\'\')?\"?([^\";]+)\"?", str(disposition), re.I)
    delivered_name = Path(unquote(match[1]).replace("\\", "/")).name if match else None
    length = next((v for k, v in headers.items() if k.lower() == "content-range"), "")
    total = int(length.rpartition("/")[2]) if re.search(r"/\d+$", length or "") else int(next((v for k, v in headers.items() if k.lower() == "content-length"), 0) or 0)
    if delivered_name and delivered_name.casefold() != entry["name"].casefold():
        got = quant_of(delivered_name)
        problems.append(f"o arquivo entregue é «{delivered_name}»" + (f" ({QUANT_LABEL[got]})" if got else "") + f", não «{entry['name']}»" + (f" ({QUANT_LABEL[announced]})" if announced else ""))
    wanted = entry.get("size_bytes") or 0
    if total and wanted and abs(total - wanted) > max(1 << 20, wanted // 100):
        problems.append(f"o tamanho entregue é {human_bytes(total)} e o anunciado era {human_bytes(wanted)}")
    if problems:
        raise ValueError("Divergência entre o que a lista anunciou e o que o Civitai entrega: " + "; ".join(problems) + ". Nada foi baixado.")


def sniff_quant(path):
    """Coarse family of a safetensors file from its own header (dtypes / scale tensors); None when it cannot tell."""
    try:
        with Path(path).open("rb") as handle:
            size = struct.unpack("<Q", handle.read(8))[0]
            if size > 64 << 20:
                return None
            header = json.loads(handle.read(size))
    except (OSError, ValueError, struct.error):
        return None
    weight = {}
    for name, info in header.items():
        if name == "__metadata__" or not isinstance(info, dict):
            continue
        start, end = info.get("data_offsets", [0, 0])
        weight[info.get("dtype")] = weight.get(info.get("dtype"), 0) + (end - start)
    if not weight:
        return None
    if any(str(name).endswith("weight_scale_2") for name in header):
        return "nvfp4"
    dtype = max(weight, key=weight.get)
    return {"I8": "int8", "F8_E4M3": "fp8", "F8_E5M2": "fp8", "F16": "fp16", "BF16": "bf16", "F32": "fp32"}.get(dtype)


# declared -> sniffed families that agree with it. Only quantisations whose bytes are unambiguous are compared.
AGREES = {"nvfp4": {"nvfp4"}, "int8": {"int8"}, "fp8": {"fp8"}, "mxfp8": {"fp8", "mxfp8"}, "bf16": {"bf16"}, "fp16": {"fp16", "bf16"}, "fp32": {"fp32"}}


def verify_variant(path, entry):
    declared, seen = entry.get("quant"), sniff_quant(path)
    if declared in AGREES and seen and seen not in AGREES[declared]:
        raise ValueError(f"Divergência: a lista anunciou {QUANT_LABEL[declared]}, mas os tensores baixados são {QUANT_LABEL.get(seen, seen)}. O arquivo foi descartado.")


def matching_files(model, version, preset, role):
    base = str(version.get("baseModel") or "")
    # Upscale operates on rendered pixels and is independent of the diffusion family.
    if role != "Upscaler" and normalized(base) not in preset.bases:
        return []
    accepted = []
    covers = catalog_covers(version.get("images") or [])
    for file in version.get("files") or []:
        actual_role = file_role(model.get("type"), file)
        ambiguous_split = role == "Difusão" and actual_role == "Checkpoint" and preset.clip_type
        if actual_role != role and not ambiguous_split:
            continue
        original = str(file.get("name") or "")
        name = Path(original.replace("\\", "/")).name
        url = urlsplit(str(file.get("downloadUrl") or ""))
        if (not name or type(version.get("id")) is not int or type(file.get("id")) is not int
                or url.scheme != "https" or url.hostname not in {"civitai.com", "www.civitai.com", "civitai.red"}
                or url.username or url.password or not re.fullmatch(r"/api/download/models/\d+", url.path)
                or int(url.path.rsplit("/", 1)[1]) != version["id"]):
            continue
        digest = next((value for key, value in (file.get("hashes") or {}).items()
                       if key.casefold() == "sha256"), None)
        if digest and not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            continue
        download = url._replace(netloc=HOST).geturl()
        accepted.append({"version": version["id"], "file": file["id"], "name": name, "role": role,
                         "preset": preset.key, "base": base, "title": str(model.get("name") or "Recurso"),
                         "revision": str(version.get("name") or version["id"]),
                         "model": model.get("id"), "sha256": digest, "size_kb": file.get("sizeKB"),
                         "size_bytes": int((file.get("sizeKB") or 0) * 1024), "primary": bool(file.get("primary")),
                         "quant": quant_of(name, version.get("name")), "quant_label": quant_label(name, quant_of(name, version.get("name"))),
                         "download": download, "split_check": bool(ambiguous_split), "covers": covers,
                         "availability": version.get("availability")})
    return accepted


@lru_cache(maxsize=256)
def split_header(url, file_identity):
    # The Checkpoint label can also mean split diffusion. Check a bounded SafeTensors header.
    limit = 2 * 1024**2
    with requests.Session() as session, request(session, url, os.getenv("CIVITAI_TOKEN"), stream=True,
                                                byte_range=f"bytes=0-{limit - 1}", timeout=(4, 6)) as response:
        if response.status_code != 206 or not response.headers.get("Content-Range", "").startswith("bytes 0-"):
            raise ValueError("Cabeçalho indisponível por byte range.")
        length = int.from_bytes(response.raw.read(8), "little")
        if not 2 <= length <= limit - 8:
            raise ValueError("Cabeçalho fora do limite da consulta.")
        header = json.loads(response.raw.read(length))
        if not isinstance(header, dict):
            raise ValueError("Cabeçalho inválido.")
    validate_keys(tuple(key.lower() for key in header if key != "__metadata__"), "Difusão")


def verified_entries(entries):
    def verify(entry):
        try:
            split_header(entry["download"], entry["sha256"] or str(entry["file"]))
            return (entry["version"], entry["file"])
        except (OSError, ValueError, requests.RequestException):
            return None

    ambiguous = [entry for entry in entries if entry["split_check"]][:24]
    if not ambiguous:
        return entries
    with ThreadPoolExecutor(max_workers=6) as pool:
        checked = set(pool.map(verify, ambiguous))
    return [entry for entry in entries if not entry["split_check"] or (entry["version"], entry["file"]) in checked]


def search(preset, role, query, cursor=None):
    if role not in QUERY_TYPES:
        raise ValueError("Escolha um tipo de componente.")
    if (role == "Checkpoint" and preset.clip_type) or (role in {"Difusão", "Encoder"} and not preset.clip_type):
        raise ValueError("Escolha um componente disponível neste preset.")
    params = {"limit": 24, "types": QUERY_TYPES[role], "nsfw": "true", "sort": "Most Downloaded"}
    query = (query or "").strip()
    if query.startswith(("https://", "http://")):
        parsed = urlsplit(query)
        match = re.match(r"^/models/(\d+)(?:/|$)", parsed.path)
        if parsed.hostname not in {"civitai.com", "www.civitai.com", "civitai.red", "www.civitai.red"} or not match:
            raise ValueError("Use o link de uma página de modelo do Civitai.")
        model = api_json(f"models/{int(match[1])}")
        version_id = (parse_qs(parsed.query).get("modelVersionId") or [""])[0]
        entries = [entry for version in model.get("modelVersions") or []
                   if not version_id or str(version.get("id")) == version_id
                   for entry in matching_files(model, version, preset, role)]
        return verified_entries(entries), None
    if query:
        params["query"] = query[:180]
    if cursor:
        params["cursor"] = cursor
    if preset.api_bases and role != "Upscaler":
        params["baseModels"] = preset.api_bases
    result = api_json("models", params)
    entries = []
    for model in result.get("items") or []:
        for version in model.get("modelVersions") or []:
            entries.extend(matching_files(model, version, preset, role))
    return verified_entries(entries), (result.get("metadata") or {}).get("nextCursor")


def image_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.netloc in MEDIA_HOSTS


def catalog_covers(images):
    covers = []
    for image in images:
        if not isinstance(image, dict):
            continue
        url = image.get("url")
        # The model API uses a numeric rating. The image API uses labels and a separate bitmask.
        if not image_url(url):
            continue
        parsed = urlsplit(url)
        suffix = Path(parsed.path).suffix.lower()
        kind = str(image.get("type") or "image").lower()
        video = suffix in {".mp4", ".webm"} or (kind == "video" and suffix not in COVER_IMAGES)
        if video:
            covers.append({"type": "video", "url": url})
            thumbnail = image.get("thumbnail")
            if isinstance(thumbnail, dict) and image_url(thumbnail.get("url")):
                covers.append({"type": "image", "url": thumbnail["url"]})
        elif kind in {"image", "gif", "video"}:
            # Ask the edge CDN for a card-sized still. Keep originals as a fallback
            # and leave animated GIFs alone.
            if parsed.netloc == "image.civitai.com" and suffix in COVER_IMAGES - {".gif"}:
                path = re.sub(r"/original=true(?:,[^/]*)?/", "/width=450,optimized=true/", parsed.path, count=1)
                if path != parsed.path:
                    covers.append({"type": "image", "url": parsed._replace(path=path).geturl()})
            covers.append({"type": "image", "url": url})
        if len(covers) >= COVER_LIMIT:
            break
    return covers[:COVER_LIMIT]


@lru_cache(maxsize=256)
def gallery_covers(model, version):
    # The catalog endpoint's preview sample can be empty even when a gallery has public images.
    params = {"modelId": model, "nsfw": "X", "limit": 12}
    with requests.Session() as session, request(
        session, f"{API}/api/v1/images?{urlencode(params)}", None, timeout=(3, 4)
    ) as response:
        data = response.json()
    images = [image for image in (data.get("items") or []) if isinstance(image, dict)]

    def is_other_version(image):
        versions = image.get("modelVersionIds")
        return not isinstance(versions, list) or version not in versions

    images.sort(key=is_other_version)
    return catalog_covers(images)


def catalog_cards(records, installed, page_models):
    by_model = {}
    for key, entry in records.items():
        model = entry.get("model")
        if type(model) is not int or model <= 0:
            continue
        if model not in by_model:
            by_model[model] = {"key": key, "title": entry["title"], "covers": [],
                               "page": f'{API}/models/{model}?modelVersionId={entry["version"]}',
                               "installed": (entry["version"], entry["file"]) in installed}
        covers = by_model[model]["covers"]
        for cover in entry.get("covers") or ():
            if cover not in covers and len(covers) < COVER_LIMIT:
                covers.append(cover)

    for model, card in by_model.items():
        entry = records[card["key"]]
        if model in page_models or not entry.get("cover_id"):
            entry["cover_id"] = register_cover(model, entry["version"], card["covers"])
        card["cover_id"] = entry["cover_id"]
    return list(by_model.values())


COVER_CACHE = {"dir": None}
NEGATIVE_TTL = {"forbidden": 600, "failed": 60, "none": 3600}
_cover_negative = {}  # key -> (until, kind, message)


def set_cover_cache(path):
    """Where fetched covers live on disk, so they survive a restart and are never downloaded twice."""
    COVER_CACHE["dir"] = Path(path) if path else None
    if COVER_CACHE["dir"]:
        COVER_CACHE["dir"].mkdir(parents=True, exist_ok=True)


def _cache_file(key, suffix):
    directory = COVER_CACHE["dir"]
    return directory / f"{key}{suffix}" if directory and re.fullmatch(r"[0-9a-f]{64}", key) else None


def register_cover(model, version, covers):
    key = hashlib.sha256(json.dumps([model, version, covers], sort_keys=True).encode()).hexdigest()
    with _cover_lock:
        _cover_sources[key] = (model, version, covers)
        _cover_sources.move_to_end(key)
        if len(_cover_sources) > 1024:
            _cover_sources.popitem(last=False)
    path = _cache_file(key, ".src.json")
    if path and not path.exists():
        try:
            path.write_text(json.dumps([model, version, covers]), encoding="utf-8")
        except OSError:
            pass
    return key


def _registered(key):
    with _cover_lock:
        found = _cover_sources.get(key)
    if found is None and (path := _cache_file(key, ".src.json")) and path.is_file():  # after a restart
        try:
            model, version, covers = json.loads(path.read_text(encoding="utf-8"))
            found = (model, version, covers)
            with _cover_lock:
                _cover_sources[key] = found
        except (OSError, ValueError):
            found = None
    return found


@lru_cache(maxsize=256)
def version_covers(version):
    with requests.Session() as session, request(
        session, f"{API}/api/v1/model-versions/{version}", os.getenv("CIVITAI_TOKEN"), timeout=(3, 4)
    ) as response:
        data = response.json()
    return catalog_covers(data.get("images") or [])


def fetch_cover_bytes(session, url):
    for _ in range(4):
        if not image_url(url):
            raise ValueError("Redirecionamento fora do CDN do Civitai.")
        with session.get(url, stream=True, allow_redirects=False, timeout=(3, 5)) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["Location"])
                continue
            response.raise_for_status()
            media_type = response.headers.get("Content-Type", "").partition(";")[0].strip().lower()
            if media_type not in COVER_TYPES:
                raise ValueError("O CDN retornou um formato de capa não suportado.")
            data = bytearray()
            for chunk in response.iter_content(128 * 1024):
                data.extend(chunk)
                if len(data) > COVER_MAX_BYTES:
                    raise ValueError("A capa excede 12 MiB.")
            if data:
                return bytes(data), media_type
            raise ValueError("O CDN retornou uma capa vazia.")
    raise ValueError("Redirecionamentos demais na capa.")


def read_catalog_cover(key):
    """Cover bytes for a registered key: disk cache first, then the CDN once; failures are remembered briefly so a 403 is not retried on every repaint."""
    data_file, type_file = _cache_file(key, ".bin"), _cache_file(key, ".type")
    if data_file and data_file.is_file() and type_file and type_file.is_file():
        try:
            return data_file.read_bytes(), type_file.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    now = time.time()
    with _cover_lock:
        blocked = _cover_negative.get(key)
    if blocked and blocked[0] > now:
        raise (FileNotFoundError if blocked[1] == "none" else OSError)(blocked[2])
    try:
        data, media_type = _download_cover(key)
    except FileNotFoundError as exc:
        if "Atualize a busca" not in str(exc):
            with _cover_lock:
                _cover_negative[key] = (now + NEGATIVE_TTL["none"], "none", str(exc))
        raise
    except OSError as exc:
        kind = "forbidden" if "403" in str(exc) else "failed"
        with _cover_lock:
            _cover_negative[key] = (now + NEGATIVE_TTL[kind], kind, str(exc))
        raise
    if data_file and type_file:
        try:
            data_file.write_bytes(data)
            type_file.write_text(media_type, encoding="utf-8")
        except OSError:
            pass
    return data, media_type


def _download_cover(key):
    registered = _registered(key)
    if registered is None:
        raise FileNotFoundError("Atualize a busca para carregar esta capa.")
    model, version, embedded = registered
    tried = set()
    metadata_failed = False
    denied = False
    with requests.Session() as session:
        for source in (lambda: embedded, lambda: version_covers(version), lambda: gallery_covers(model, version)):
            try:
                covers = source()
            except (requests.RequestException, ValueError):
                metadata_failed = True
                continue
            for cover in covers:
                url = cover["url"]
                if url in tried:
                    continue
                tried.add(url)
                try:
                    return fetch_cover_bytes(session, url)
                except requests.HTTPError as exc:
                    denied |= exc.response is not None and exc.response.status_code == 403
                except (requests.RequestException, ValueError):
                    continue
    if denied:
        raise OSError("O CDN do Civitai recusou a prévia (403).")
    if tried or metadata_failed:
        raise OSError("A prévia do Civitai não carregou.")
    raise FileNotFoundError("Sem prévia pública no Civitai.")


def previews(entry):
    result = api_json("images", {"modelVersionId": entry["version"], "nsfw": "None", "limit": 24})
    return [image for image in result.get("items", []) if image_url(image.get("url"))
            and image.get("type", "image") == "image" and not image.get("nsfw")
            and image.get("nsfwLevel") in (None, 0, 1, "None")][:12]


def fetch_image(url, directory, identifier):
    if not image_url(url):
        raise ValueError("URL de imagem fora do CDN do Civitai.")
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:12]
    path = directory / f"civitai-{int(identifier)}-{key}.jpg"
    if path.is_file() and path.stat().st_size:
        return str(path)
    try:
        with requests.get(url, stream=True, timeout=(8, 20), allow_redirects=False) as response:
            if not response.ok or response.is_redirect:
                raise ValueError("O CDN não entregou a imagem.")
            data = bytearray()
            for chunk in response.iter_content(256 * 1024):
                data.extend(chunk)
                if len(data) > 20 * 1024**2:
                    raise ValueError("A imagem de catálogo excede 20 MiB.")
        with Image.open(io.BytesIO(data)) as opened:
            if opened.width * opened.height > 32_000_000:
                raise ValueError("A imagem de catálogo excede 32 megapixels.")
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((1536, 1536))
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".jpg", delete=False) as file:
            partial = Path(file.name)
            try:
                image.save(file, format="JPEG", quality=92)
                file.flush()
                partial.replace(path)
            finally:
                partial.unlink(missing_ok=True)
        return str(path)
    except (requests.RequestException, OSError, Image.DecompressionBombError):
        raise ValueError("Não consegui abrir a imagem do catálogo.") from None


def asset_key(entry):
    return f'{entry["version"]}-{entry["file"]}-{entry["preset"]}'


def asset_path(entry, directory):
    name = Path(entry["name"])
    safe_stem = re.sub(r"[^a-zA-Z0-9._-]", "_", name.stem)[:120]
    return directory / "files" / f'{entry["version"]}-{entry["file"]}-{safe_stem}{name.suffix.lower()}'


def install(entry, directory, progress=None):
    role = entry["role"]
    dest = asset_path(entry, directory)
    dest.parent.mkdir(parents=True, exist_ok=True)
    checksum = entry["sha256"]
    if not dest.is_file() or not dest.stat().st_size:
        with tempfile.NamedTemporaryFile(dir=dest.parent, suffix=".part", delete=False) as output:
            temporary = Path(output.name)
            digest = hashlib.sha256()
            try:
                with requests.Session() as session, request(session, entry["download"], os.getenv("CIVITAI_TOKEN"), stream=True) as response:
                    if response.headers.get("Content-Type", "").startswith(("text/", "application/json")):
                        raise ValueError("O servidor devolveu uma página em vez de um arquivo.")
                    check_delivery(entry, response.headers)  # name and size must be what the list announced, before downloading
                    got, window = 0, time.monotonic()
                    total = int(response.headers.get("Content-Length") or 0)
                    for chunk in response.iter_content(1024 * 1024):
                        digest.update(chunk)
                        output.write(chunk)
                        got += len(chunk)
                        if progress and time.monotonic() - window >= 1:
                            window = time.monotonic()
                            share = f"{got / total:.0%} de {got / 1024**2 if not total else total / 1024**2:.0f} MB" if total else f"{got / 1024**2:.0f} MB"
                            progress(0.1, desc=f"Baixando do Civitai · {share}")
                output.flush()
                if not temporary.stat().st_size or (checksum and digest.hexdigest() != checksum.lower()):
                    raise ValueError("Arquivo vazio ou SHA-256 diferente do publicado.")
                if role != "Workflow":
                    check_tensor(temporary, role)
                    verify_variant(temporary, entry)
                temporary.replace(dest)
            except CivitaiHTTPError as exc:
                if exc.status == 401:
                    raise ValueError("Civitai recusou a autenticação (401). Confira o CIVITAI_TOKEN no Colab.") from None
                if exc.status == 403:
                    if normalized(entry.get("availability")) == "earlyaccess":
                        raise ValueError("Civitai negou o download (403). A versão está marcada como acesso antecipado; confira o acesso na página dela.") from None
                    raise ValueError("Civitai negou o download (403). Confira na página da versão se tua conta pode baixar e se o CIVITAI_TOKEN pertence a ela.") from None
                raise
            except requests.RequestException:
                raise ValueError("O Civitai interrompeu o download. Confira a conexão e tente novamente.") from None
            finally:
                temporary.unlink(missing_ok=True)
    if role != "Workflow":
        check_tensor(dest, role)
    record = directory / "inventory" / f"{asset_key(entry)}.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    data = {key: value for key, value in entry.items() if key != "download"}
    with tempfile.NamedTemporaryFile(dir=record.parent, suffix=".part", delete=False, mode="w", encoding="utf-8") as handle:
        marker = Path(handle.name)
        try:
            json.dump({**data, "stored": dest.name}, handle, ensure_ascii=False)
            handle.flush()
            marker.replace(record)
        finally:
            marker.unlink(missing_ok=True)
    return dest


def check_tensor(path, role):
    from safetensors import SafetensorError, safe_open

    try:
        with safe_open(str(path), framework="numpy") as weights:
            keys = tuple(key.lower() for key in weights.keys())
    except (SafetensorError, OSError):
        raise ValueError("O arquivo não tem um cabeçalho SafeTensors válido.") from None
    validate_keys(keys, role)


def validate_keys(keys, role):
    if not keys:
        raise ValueError("O arquivo não contém tensores.")
    lora = any(any(marker in key for marker in ("lora_", ".lora", "hada_", "lokr_", "oft_blocks"))
               for key in keys)
    if role == "LoRA" and not lora:
        raise ValueError("Os nomes dos tensores não identificam uma LoRA suportada.")
    if role != "LoRA" and lora and all(
        any(marker in key for marker in ("lora", "hada_", "lokr_", "alpha", "oft_")) for key in keys
    ):
        raise ValueError("O arquivo parece uma LoRA, mas está em outro slot.")
    if role == "VAE" and not (any("encoder." in key for key in keys) and any("decoder." in key for key in keys)):
        raise ValueError("O cabeçalho não mostra encoder e decoder de VAE.")
    if role == "Checkpoint" and not (any(key.startswith("model.diffusion_model.") for key in keys)
                                     and any("first_stage_model." in key for key in keys)):
        raise ValueError("O arquivo não parece um checkpoint completo com VAE integrado.")
    if role == "Difusão":
        if any("first_stage_model." in key or "conditioner.embedders." in key for key in keys):
            raise ValueError("O arquivo parece um checkpoint completo, não difusão separada.")
        markers = ("diffusion_model.", "transformer_blocks.", "double_blocks.", "single_blocks.",
                   "joint_blocks.", "context_refiner.", "noise_refiner.", "img_in.", "x_embedder.")
        if not any(any(marker in key for marker in markers) for key in keys):
            raise ValueError("O cabeçalho não identifica um modelo de difusão separado.")
    if role == "Encoder" and not any("embed_tokens." in key or "token_embedding." in key for key in keys):
        raise ValueError("O arquivo não mostra os embeddings esperados de um encoder de texto.")


def inventory(directory, preset, role):
    result = []
    for record in sorted((directory / "inventory").glob("*.json")):
        try:
            if record.is_symlink():
                continue
            data = json.loads(record.read_text(encoding="utf-8"))
            if data["role"] != role:
                continue
            if role != "Upscaler" and normalized(data["base"]) not in preset.bases:
                continue
            name = data["stored"]
            path = directory / "files" / name
            if Path(name).name != name or path.is_symlink() or not path.is_file():
                continue
            result.append((record.stem, data, path))
        except (OSError, KeyError, TypeError, ValueError):
            continue
    # The same downloaded file can have manifests from several compatible presets.
    result.sort(key=lambda row: row[1].get("preset") != preset.key)
    unique = {}
    for key, data, path in result:
        unique.setdefault(path, (key, data, path))
    return list(unique.values())


# ---------------------------------------------------------------- Studio browsing (cards as the site shows them)

SORTS = {"downloads": "Most Downloaded", "rated": "Highest Rated", "newest": "Newest"}
BASE_BADGES = {"qwen21": "QWEN 2.1", "krea2": "KR2", "krea2-turbo": "KR2", "flux2": "FLUX.2", "flux3": "FLUX.3",
               "z-image": "ZIMG", "z-image-turbo": "ZIMG"}


def model_card(model, version, files, preset):
    stats = model.get("stats") or {}
    creator = model.get("creator") or {}
    covers = catalog_covers(version.get("images") or [])
    return {
        "model": model["id"], "version": version["id"], "version_name": str(version.get("name") or ""),
        "title": str(model.get("name") or "LoRA"), "creator": str(creator.get("username") or ""),
        "avatar": creator.get("image") if image_url(creator.get("image")) else None,
        "base": str(version.get("baseModel") or ""), "badge": BASE_BADGES.get(preset.key, preset.key.upper()),
        "stats": {"downloads": int(stats.get("downloadCount") or 0), "likes": int(stats.get("thumbsUpCount") or 0),
                  "saves": int(stats.get("favoriteCount") or stats.get("collectedCount") or 0),
                  "comments": int(stats.get("commentCount") or 0)},
        "files": [{"file": f["file"], "name": f["name"], "size_mb": round((f.get("size_kb") or 0) / 1024, 1), "quant": f.get("quant"), "quant_label": f.get("quant_label"),
                   "primary": f.get("primary", False), "sha256": f.get("sha256"), "size_bytes": f.get("size_bytes")} for f in files],
        "covers": covers, "cover_id": register_cover(model["id"], version["id"], covers),
        "adult": bool(model.get("nsfw")) or any(int(i.get("nsfwLevel") or 0) >= 4 for i in (version.get("images") or [])[:1] if isinstance(i, dict)),
        "page": f'{API}/models/{model["id"]}?modelVersionId={version["id"]}', "preset": preset.key,
    }


def browse_loras(preset, query="", cursor=None, sort="downloads", role="LoRA"):
    """One card per Civitai model, with the newest version that fits the preset's base model."""
    params = {"limit": 24, "types": QUERY_TYPES[role], "nsfw": "true", "sort": SORTS.get(sort, SORTS["downloads"])}
    if query.strip():
        params["query"] = query.strip()[:180]
    if cursor:
        params["cursor"] = cursor
    if preset.api_bases and role != "Upscaler":  # upscalers are independent of the diffusion family
        params["baseModels"] = preset.api_bases
    result = api_json("models", params)
    cards = []
    for model in result.get("items") or []:
        for version in model.get("modelVersions") or []:
            files = matching_files(model, version, preset, role)
            if files:
                cards.append(model_card(model, version, files, preset))
                break
    return cards, (result.get("metadata") or {}).get("nextCursor")


def entry_for(preset, model_id, version_id, file_id, role="LoRA", expect=None):
    """Rebuild a downloadable entry from the Civitai record, never from client-sent fields. `expect` is what the list showed
    the user (name, quantisation, size, sha256): if the record now says something else the install is refused, not adapted."""
    model = api_json(f"models/{int(model_id)}")
    for version in model.get("modelVersions") or []:
        if version.get("id") != int(version_id):
            continue
        for entry in matching_files(model, version, preset, role):
            if entry["file"] == int(file_id):
                if expect:
                    differs = [label for label, key in (("nome", "name"), ("quantização", "quant"), ("sha256", "sha256")) if expect.get(key) and str(expect[key]).lower() != str(entry.get(key) or "").lower()]
                    if expect.get("size_bytes") and abs(int(expect["size_bytes"]) - int(entry.get("size_bytes") or 0)) > max(1 << 20, int(entry.get("size_bytes") or 0) // 100):
                        differs.append("tamanho")
                    if differs:
                        shown = f"{QUANT_LABEL.get(expect.get('quant'), expect.get('quant') or '?')} · {human_bytes(int(expect.get('size_bytes') or 0))}"
                        now = f"{QUANT_LABEL.get(entry.get('quant'), entry.get('quant') or '?')} · {human_bytes(int(entry.get('size_bytes') or 0))}"
                        raise ValueError(f"Divergência de variante ({', '.join(differs)}): a lista mostrou {shown}, o Civitai agora oferece {now} para este arquivo. Atualize a busca.")
                return {**entry, "creator": str((model.get("creator") or {}).get("username") or "")}, model
    raise ValueError("Esse arquivo não está mais disponível para este modelo no Civitai.")
