"""Asset Graph (AssetRef.v1, contrato em docs/V9_ASSET_GRAPH_CONTRACT.md): ativos versionados, endereçados por conteúdo.

Layout: `<base>/assets/blobs/<sha256>.<ext>` (imutável, 0o444, gravado uma vez) e `<base>/assets/index.json` (gravação atômica sob lock).
Um ativo (`a_<16hex>`) tem versões (`v_<16hex>`); uma versão aponta para um blob. Publicar COPIA o arquivo para o blob: a origem nunca é
alterada. Consumir uma versão resolve para o caminho do próprio blob (sem cópia). O executor continua sendo cf_dag.py: o cache dele já é
por hash de conteúdo, então trocar v1 por v2 recomputa só o que depende daquela mídia.
Duração de vídeo/áudio só é preenchida quando o ffprobe existe; sem ele fica null (nada é estimado).
"""

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

import cf_jobs

SCHEMA = "AssetRef.v1"
KIND_VALUES = ("image", "video", "audio", "character")
ASSET_ID = re.compile(r"a_[0-9a-f]{16}")
VERSION_ID = re.compile(r"v_[0-9a-f]{16}")
_lock = threading.RLock()


class NotFound(LookupError):
    """Unknown asset or version id (the API answers 404)."""


def folder(base):
    return Path(base) / "assets"


def _index_path(base):
    return folder(base) / "index.json"


def _load(base):
    try:
        data = json.loads(_index_path(base).read_text(encoding="utf-8"))
        if isinstance(data.get("assets"), dict) and isinstance(data.get("versions"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"assets": {}, "versions": {}}


def _save(base, data):
    target = _index_path(base)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    partial.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    partial.replace(target)


def _new_id(prefix, taken):
    while True:
        ident = prefix + secrets.token_hex(8)
        if ident not in taken:
            return ident


def media_kind(path):
    """image | video | audio from the extension (same table the jobs use), or None."""
    return cf_jobs.KINDS.get(Path(path).suffix.lower())


def _inside(path, roots):
    return any(path.is_relative_to(Path(r).resolve()) for r in roots)


def _probe_media(path, kind):
    media = dict(width=None, height=None, duration_s=None)
    if kind in ("image", "character"):
        try:
            from PIL import Image
            with Image.open(path) as opened:
                media["width"], media["height"] = opened.size
        except Exception:
            pass
        return media
    exe = shutil.which("ffprobe")
    if not exe:
        return media
    try:
        out = subprocess.run([exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                             capture_output=True, text=True, timeout=30)
        info = json.loads(out.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return media
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video" and media["width"] is None:
            media["width"], media["height"] = stream.get("width"), stream.get("height")
    try:
        media["duration_s"] = round(float(info.get("format", {}).get("duration")), 3)
    except (TypeError, ValueError):
        pass
    return media


def _store_blob(base, source):
    """Copy `source` into the content-addressed store. -> (sha256, storage_ref, bytes). An existing blob is never rewritten."""
    blobs = folder(base) / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    partial = blobs / f".{secrets.token_hex(6)}.part"
    try:
        with source.open("rb") as src, partial.open("wb") as dst:
            while block := src.read(1 << 20):
                digest.update(block)
                dst.write(block)
                size += len(block)
        sha = digest.hexdigest()
        target = blobs / f"{sha}{source.suffix.lower()}"
        if target.exists():
            partial.unlink(missing_ok=True)
        else:
            os.chmod(partial, 0o444)
            partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return sha, f"blobs/{target.name}", size


def _clean_source(source, roots, kind):
    path = Path(source).resolve()
    if not path.is_file():
        raise ValueError("Arquivo de origem não encontrado.")
    if not _inside(path, roots):
        raise ValueError("A origem precisa estar nas pastas de resultados, envios ou elenco.")
    found = media_kind(path)
    if found is None:
        raise ValueError(f"Formato não aceito como ativo: {path.suffix or 'sem extensão'}.")
    if kind is None:
        kind = found
    if kind not in KIND_VALUES:
        raise ValueError(f"Tipo de ativo inválido: {kind}.")
    if kind == "character":
        if found != "image":
            raise ValueError("Um personagem precisa de uma imagem.")
    elif kind != found:
        raise ValueError(f"O arquivo é {found}, não {kind}.")
    if path.stat().st_size <= 0:
        raise ValueError("Arquivo vazio.")
    return path, kind


def _ref(base, asset_id, number, version_id, kind, path, sha, ref, size, parents, producer, recipe, metadata):
    return {"schema": SCHEMA, "asset_id": asset_id, "version_id": version_id, "number": number, "kind": kind,
            "mime": _mime(path), "sha256": sha, "bytes": size, "storage_ref": ref, "parents": parents,
            "producer": {"kind": "upload", "job_id": None, "app": None, "capability_id": None, "graph_run_id": None, **(producer or {})},
            "recipe": {"params": {}, "seed": None, "model_variant": None, **(recipe or {})},
            "media": _probe_media(folder(base) / ref, kind),
            "metadata": {"title": None, "name": None, "description": None, "license": None, "consent": None, "note": None, **(metadata or {})},
            "state": "ready", "created": int(time.time())}


def _mime(path):
    import mimetypes
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def _commit(base, source, roots, kind, asset_id, title, producer, recipe, metadata, parents_extra, only_new_asset):
    if asset_id:
        known = _load(base)["assets"].get(asset_id)
        if known is None:
            raise NotFound("Ativo não encontrado.")
        kind = known["kind"]
    path, kind = _clean_source(source, roots, kind)
    with _lock:
        sha, ref, size = _store_blob(base, path)
        data = _load(base)
        asset = data["assets"].get(asset_id) if asset_id else None
        if asset_id and asset is None:
            raise NotFound("Ativo não encontrado.")
        if asset is not None:
            current = data["versions"][asset["current"]]
            if current["sha256"] == sha:
                return dict(asset=asset, version=current, deduplicated=True)
            if kind != asset["kind"]:
                raise ValueError(f"O ativo é {asset['kind']}; o arquivo novo é {kind}.")
        elif only_new_asset:
            for other in data["assets"].values():
                cur = data["versions"][other["current"]]
                if other["kind"] == kind and cur["sha256"] == sha:
                    return dict(asset=other, version=cur, deduplicated=True)
        new_asset = asset is None
        if new_asset:
            asset_id = _new_id("a_", data["assets"])
            asset = dict(asset_id=asset_id, kind=kind, title=title or (metadata or {}).get("name") or path.stem, created=int(time.time()), versions=[], current=None)
        parents = list(parents_extra or [])
        if not new_asset:
            parents.insert(0, dict(asset_id=asset_id, version_id=asset["current"], role="previous"))
        version_id = _new_id("v_", data["versions"])
        meta = {"title": asset["title"], **(metadata or {})}
        version = _ref(base, asset_id, len(asset["versions"]) + 1, version_id, kind, path, sha, ref, size, parents, producer, recipe, meta)
        asset["versions"].append(version_id)
        asset["current"] = version_id
        data["assets"][asset_id] = asset
        data["versions"][version_id] = version
        _save(base, data)
        return dict(asset=asset, version=version, deduplicated=False)


def publish(base, source, roots, kind=None, title=None, producer=None, recipe=None, metadata=None, parents=None):
    """New asset (version 1) from a file inside `roots`. Same SHA as the current version of an asset of the same kind -> that asset (idempotent).
    -> dict(asset, version, deduplicated)."""
    return _commit(base, source, roots, kind, None, title, producer, recipe, metadata, parents, True)


def add_version(base, asset_id, source, roots, producer=None, recipe=None, metadata=None, parents=None):
    """Append a version to an asset; `current` moves to it and the previous versions stay resolvable. Same SHA as `current` -> no new version."""
    if not isinstance(asset_id, str) or not ASSET_ID.fullmatch(asset_id):
        raise NotFound("Ativo não encontrado.")
    return _commit(base, source, roots, None, asset_id, None, producer, recipe, metadata, parents, False)


def publish_cast(base, ident, roots):
    """The picture of a cast character as a `character` asset (metadata.name / description)."""
    import cf_cast
    item = next((i for i in cf_cast.load(base) if i["id"] == ident), None)
    if item is None:
        raise NotFound("Personagem não encontrado.")
    path = cf_cast.image_path(base, item)
    if path is None or not path.is_file():
        raise ValueError("Este personagem não tem imagem para publicar.")
    return publish(base, path, roots, kind="character", title=item["name"], producer=dict(kind="cast"),
                   metadata=dict(name=item["name"], description=item.get("description") or None))


def get(base, asset_id):
    with _lock:
        asset = _load(base)["assets"].get(asset_id)
    if asset is None:
        raise NotFound("Ativo não encontrado.")
    return asset


def get_version(base, version_id):
    with _lock:
        version = _load(base)["versions"].get(version_id)
    if version is None:
        raise NotFound("Versão não encontrada.")
    return version


def list_assets(base):
    """Assets, newest first, each with its `current` version summary."""
    with _lock:
        data = _load(base)
    out = [dict(a, current_version=data["versions"].get(a["current"])) for a in data["assets"].values()]
    return sorted(out, key=lambda a: a["created"], reverse=True)


def versions(base, asset_id):
    """Every AssetRef of an asset, in creation order."""
    with _lock:
        data = _load(base)
    asset = data["assets"].get(asset_id)
    if asset is None:
        raise NotFound("Ativo não encontrado.")
    return [data["versions"][v] for v in asset["versions"]]


def blob_path(base, version):
    return folder(base) / version["storage_ref"]


def resolve_ref(base, ident):
    """`v_…` (exact version) or `a_…` (the version that is `current` right now) -> (blob Path, version AssetRef), or None."""
    if not isinstance(ident, str):
        return None
    with _lock:
        data = _load(base)
    if VERSION_ID.fullmatch(ident):
        version = data["versions"].get(ident)
    elif ASSET_ID.fullmatch(ident):
        asset = data["assets"].get(ident)
        version = data["versions"].get(asset["current"]) if asset else None
    else:
        return None
    if version is None:
        return None
    path = blob_path(base, version)
    return (path, version) if path.is_file() else None


def resolve(base, ident):
    found = resolve_ref(base, ident)
    return found[0] if found else None


def verify(base, version_id):
    """True when the blob exists and its SHA-256 still matches the version."""
    version = get_version(base, version_id)
    path = blob_path(base, version)
    if not path.is_file():
        return False
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest() == version["sha256"]
