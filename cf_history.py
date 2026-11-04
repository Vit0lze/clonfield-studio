"""Index reusable results in the Studio output directory."""

import json
import re
import time
import unicodedata
from pathlib import Path

from cf_workflows import AUDIO_SUFFIXES, IMAGE_SUFFIXES, VIDEO_SUFFIXES

TYPES = ("Todas", "Imagem", "Vídeo", "Áudio")
MAX_RESULTS = 150
FINISH_TOOLS = {
    "imagem": "Acabamento", "quadro": "Quadro de vídeo", "prancha": "Prancha de cenas",
    "clipe": "Corte de vídeo", "sequencia": "Sequência", "regiao": "Edição de região",
    "comparacao": "Comparação de imagens",
}
QWEN_NAME = re.compile(r"(\d{8}_\d{6}_[0-9a-f]{8})(?:_final)?\.png\Z")


def media_type(path):
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "Imagem"
    if suffix in VIDEO_SUFFIXES:
        return "Vídeo"
    if suffix in AUDIO_SUFFIXES:
        return "Áudio"
    return None


def read_record(path):
    try:
        if path.is_symlink():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_media(directory, key):
    if not key:
        raise ValueError("Selecione um resultado primeiro.")
    relative = Path(key)
    if relative.is_absolute() or ".." in relative.parts or not 1 <= len(relative.parts) <= 2:
        raise ValueError("Resultado fora da pasta de mídia do Studio.")
    root = Path(directory).resolve()
    path = root / relative
    if path.resolve() != path or not path.is_file() or not media_type(path):
        raise ValueError("O resultado não está disponível na pasta de mídia do Studio.")
    return path


def qwen_pair(path):
    match = QWEN_NAME.fullmatch(path.name)
    if not match or not path.with_name(match[1] + ".json").is_file():
        return None
    original, final = (path.with_name(match[1] + suffix) for suffix in (".png", "_final.png"))
    if all(file.is_file() and not file.is_symlink() for file in (original, final)):
        return str(original), str(final)
    return None


def describe(directory, path, records):
    if path.parent == directory:
        match = QWEN_NAME.fullmatch(path.name)
        if match:
            record = path.with_name(match[1] + ".json")
            if record not in records:
                records[record] = read_record(record)
            data = records[record]
            if data:
                variant = "Pós-processada" if path.stem.endswith("_final") else "Original"
                return f"Qwen · {variant}", data
        if path.name.startswith("upscale_manual_"):
            return "Upscale rápido", {}
        return "Saída local", {}
    folder = path.parent
    if folder.name == "acabamento":
        return FINISH_TOOLS.get(path.stem.partition("-")[0], "Acabamento"), {}
    if folder not in records:
        records[folder] = read_record(folder / "job.json")
    job = records[folder]
    title = "SeedVR2" if folder.name.startswith("seedvr2_") else job.get("title") or "ComfyUI"
    fields = ("title", "status", "id", "prompt_id", "kind", "model", "seed", "scale", "output")
    return str(title), {field: job[field] for field in fields if field in job}


def normalized(value):
    return "".join(char for char in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(char))


def choices(directory, kind, query):
    root = Path(directory).resolve()
    terms = normalized(query or "").split()
    files = []
    for folder in root.iterdir():
        if folder.is_symlink():
            continue
        if folder.is_dir() and (folder.name == "acabamento" or
                                folder.name.startswith(("workflow_", "seedvr2_"))):
            candidates = folder.iterdir()
        else:
            candidates = (folder,)
        for path in candidates:
            media = media_type(path)
            if not media or kind not in ("Todas", media) or path.is_symlink():
                continue
            try:
                if path.is_file():
                    files.append((path.stat().st_mtime, path, media))
            except FileNotFoundError:
                continue
    result, records = [], {}
    for modified, path, media in sorted(files, reverse=True):
        title, data = describe(root, path, records)
        prompt = " ".join(str(data.get("prompt") or "").split())
        date = time.strftime("%d/%m %H:%M", time.localtime(modified))
        seed = f" · seed {data['seed']}" if "seed" in data else ""
        short_path = path.relative_to(root).as_posix()
        if not all(term in normalized(f"{title} {prompt} {media} {short_path} {seed}") for term in terms):
            continue
        snippet = f" · {prompt[:72]}" if prompt else ""
        label = f"{date} · {media} · {title}{seed}{snippet} · {path.stem[-10:]}"
        result.append((label, short_path))
        if len(result) == MAX_RESULTS:
            break
    return result
