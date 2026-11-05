"""Browse compatible Civitai files and keep a manifest of local installs."""

import hashlib
import time
import io
import json
import os
import re
import tempfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import requests
from PIL import Image, ImageOps

from cf_assets import API, CivitaiHTTPError, request

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
MEDIA_HOSTS = {"image.civitai.com", "image-b2.civitai.com"}
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
        download = url._replace(netloc="civitai.com").geturl()
        accepted.append({"version": version["id"], "file": file["id"], "name": name, "role": role,
                         "preset": preset.key, "base": base, "title": str(model.get("name") or "Recurso"),
                         "revision": str(version.get("name") or version["id"]),
                         "model": model.get("id"), "sha256": digest, "size_kb": file.get("sizeKB"),
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
    params = {"limit": 24, "types": QUERY_TYPES[role], "nsfw": "false", "sort": "Most Downloaded"}
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
        if (not image_url(url) or image.get("nsfw") not in (None, False, "false", "None", "PG")
                or image.get("nsfwLevel") not in (None, 0, 1, "0", "1", "None", "PG")
                or image.get("browsingLevel") not in (None, 1, "1")):
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
    params = {"modelId": model, "nsfw": "None", "limit": 12}
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


def register_cover(model, version, covers):
    key = hashlib.sha256(json.dumps([model, version, covers], sort_keys=True).encode()).hexdigest()
    with _cover_lock:
        _cover_sources[key] = (model, version, covers)
        _cover_sources.move_to_end(key)
        if len(_cover_sources) > 1024:
            _cover_sources.popitem(last=False)
    return key


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
    with _cover_lock:
        registered = _cover_sources.get(key)
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
