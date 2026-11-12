"""Universal component search behind every slot's «Pesquisar…»: local files, Civitai, Hugging Face.

Discovery is not installation and installation is not execution. Each result carries an honest `status`:
instalado / compatível (Civitai, base model matches the recipe) / descoberto (Hugging Face: compatibility unknown).
"""

from pathlib import Path

import requests

import cf_civitai as civitai
import cf_model_lab as lab

HF_API = "https://huggingface.co/api/models"
ROLE_HINT = {"VAE": "vae", "Encoder": "text encoder", "Upscaler": "upscale", "Difusão": "diffusion", "Checkpoint": "checkpoint"}
SOURCES = ("local", "civitai", "huggingface")


def local(role, family, civitai_dir, query):
    preset = lab.PRESETS[family]
    wanted = query.strip().lower()
    items = []
    folder = lab.models_root() / civitai.ROLE_TYPES.get(role, "")
    if civitai.ROLE_TYPES.get(role) and folder.is_dir():
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix in (".safetensors", ".gguf", ".pth") and wanted in path.name.lower():
                items.append(dict(source="local", id=path.name, title=path.name, author="", size_mb=round(path.stat().st_size / 1024**2),
                                  status="instalado", compatible="não verificada (arquivo avulso)", url=None, install=None,
                                  value=f"file:{path.name}"))
    for key, data, path in civitai.inventory(civitai_dir, preset, role):
        title = data.get("title") or data.get("name") or path.name
        if wanted in title.lower() or wanted in path.name.lower():
            items.append(dict(source="local", id=key, title=title, author=data.get("creator", ""), size_mb=round(path.stat().st_size / 1024**2),
                              status="instalado", compatible=f"base {data.get('base', '')} validada", url=None, install=None, value=key))
    return items, None


def civitai_search(role, family, civitai_dir, query, cursor):
    preset = lab.PRESETS[family]
    if role not in civitai.QUERY_TYPES or role == "Workflow":
        return [], None
    cards, nxt = civitai.browse_loras(preset, query, cursor, "downloads", role=role)
    have = {path.name for _k, _d, path in civitai.inventory(civitai_dir, preset, role)}
    items = []
    for card in cards:
        files = sorted(card["files"], key=lambda f: (f.get("size_bytes") or 0))[:6]  # one item per FILE: nothing is picked silently
        many = len(card["files"]) > 1
        for file in files:
            installed = any(name.startswith(f'{card["version"]}-{file["file"]}-') for name in have)
            tag = file.get("quant_label") or ""
            variant = dict(provider="civitai", model_id=card["model"], version_id=card["version"], file_id=file["file"], sha256=file.get("sha256"),
                           quant=file.get("quant"), size_bytes=file.get("size_bytes"), file_name=file["name"])
            expect = dict(name=file["name"], quant=file.get("quant"), size_bytes=file.get("size_bytes"), sha256=file.get("sha256"))
            items.append(dict(source="civitai", id=f'{card["model"]}/{card["version"]}/{file["file"]}', title=card["title"] + (f" · {tag}" if tag and many else ""), author=card["creator"],
                              size_mb=round((file.get("size_bytes") or 0) / 1e6), downloads=card["stats"]["downloads"], status="instalado" if installed else "compatível",
                              compatible=f"base {card['base']} = receita", url=card["page"], adult=bool(card.get("adult")), variant=variant,
                              file_name=file["name"], quant_label=tag, primary=bool(file.get("primary")),
                              install=None if installed else dict(model=card["model"], version=card["version"], file=file["file"], expect=expect)))
    return items, nxt


UPSCALER_QUERIES = ("esrgan", "swinir", "4x upscaler", "super resolution", "hat upscaler")
# Weights the Studio's spandrel loader cannot read (other runtimes) and things that are not image upscalers at all.
NOT_UPSCALERS = ("qwen", "flux", "wan", "ltx", "edit", "lora", "sdxl", "stable-diffusion", "video", "onnx", "coreml", "tflite", "litert", "gguf", "mlx", "qualcomm", "tensorrt", "openvino", "nomos-1", "awq", "keras", "axera", "ldm-super", "-int4", "-int8")


def hf_ask(text, limit=20):
    response = requests.get(HF_API, params={"search": text, "sort": "downloads", "direction": "-1", "limit": limit}, timeout=15)
    response.raise_for_status()
    return response.json()


def hf_search(role, family, query):
    preset = lab.PRESETS[family]
    if role == "Upscaler":  # upscalers do not depend on the diffusion family: search real upscaler names, drop other runtimes
        queries = [f"{query.strip()} upscale".strip()] if query.strip() else list(UPSCALER_QUERIES)
        pool = {}
        for text in queries:
            for model in hf_ask(text, 15):
                repo = model.get("id") or model.get("modelId") or ""
                if repo and not any(bad in repo.lower() for bad in NOT_UPSCALERS):
                    pool.setdefault(repo, model)
        found = sorted(pool.values(), key=lambda m: -(m.get("downloads") or 0))[:20]
    else:
        words = " ".join(x for x in (query.strip(), ROLE_HINT.get(role, "")) if x)
        if not query.strip():
            words = " ".join((preset.api_bases[0] if preset.api_bases else family, ROLE_HINT.get(role, ""))).strip()
        found = hf_ask(words)
        if not found and not query.strip():  # the family name was too specific: fall back to its first word + the role
            token = "".join(ch for ch in (preset.api_bases[0] if preset.api_bases else family).split()[0] if ch.isalpha())
            found = hf_ask(f"{token} {ROLE_HINT.get(role, '')}".strip())
    defaults = {spec[0] for spec in preset.files.values()}
    items = []
    for model in found:
        repo = model.get("id") or model.get("modelId")
        if not repo:
            continue
        standard = repo in defaults
        items.append(dict(source="huggingface", id=repo, title=repo, author=repo.split("/")[0], size_mb=None, downloads=model.get("downloads", 0),
                          status="padrão da receita" if standard else "descoberto", compatible="desconhecida — validar loader e arquitetura",
                          url=f"https://huggingface.co/{repo}", install=None))
    return items, None


def search(role, family, source, query, civitai_dir, cursor=None):
    if family not in lab.PRESETS:
        raise ValueError("Modelo desconhecido.")
    if source not in SOURCES:
        raise ValueError("Fonte desconhecida.")
    if source == "local":
        return local(role, family, civitai_dir, query)
    if source == "civitai":
        return civitai_search(role, family, civitai_dir, query, cursor)
    return hf_search(role, family, query)
