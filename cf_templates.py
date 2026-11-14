"""Apps built from OFFICIAL ComfyUI workflow templates (Comfy-Org/workflow_templates, MIT), converted with cf_ui2api (subgraphs flattened) using the
worker's own /object_info. Each entry says which template, which node holds the driving video / character image / prompt / seed, and which node is
the output; everything else stays exactly as the template authors set it.

Weights come from `workflows/template_files.json` (read from each template's own notes + the Hugging Face API: repo, revision, bytes, SHA-256 prefix).

STATE: graphs ACCEPTED by a real ComfyUI 0.44.0 on CPU (tests/test_comfy_real.py). These are 14B models with a 16.6 GB INT8 file plus a 6.7 GB text
encoder: they cannot be expected to run on a 15 GB T4, so the apps are gated at 24 GB of VRAM and say why. Nothing here was generated (BLOQUEADO_GPU).
"""

import json
import os
import random
from pathlib import Path

import cf_ui2api as ui2api
from cf_seedvr2 import upload_input

DIR = Path(__file__).resolve().parent / "workflows"
FILES = json.loads((DIR / "template_files.json").read_text(encoding="utf-8"))
LOADERS = {"UNETLoader": "unet_name", "CLIPLoader": "clip_name", "VAELoader": "vae_name", "CLIPVisionLoader": "clip_name", "LoraLoaderModelOnly": "lora_name", "CheckpointLoaderSimple": "ckpt_name"}

TEMPLATES = {
    "scail2": dict(file="video_wan21_scail2_character_replacement_int8.json", title="Substituir personagem (SCAIL-2)", outputs=["202"], video="155", image="30",
                   prompt=("213:3", "text"), seed=("213:19", "noise_seed"), min_vram=24,
                   about="Troca o personagem de um vídeo pelo da sua foto, seguindo a pose do vídeo. Modelo INT8 de 16,6 GB (Wan 2.1 SCAIL-2)."),
    "animate2": dict(file="video_wan_animate2_distilled.json", title="Animar personagem (Wan Animate 2)", outputs=["246"], video="240", image="189",
                     prompt=("604", "value"), seed=("261:19", "noise_seed"), min_vram=24,
                     about="Faz a sua foto de personagem repetir o movimento de um vídeo (versão destilada, INT8 de 16,6 GB)."),
}


def template(key):
    return json.loads((DIR / TEMPLATES[key]["file"]).read_text(encoding="utf-8"))


def build(key, objinfo, video="entrada.mp4", image="entrada.png", prompt="", seed=-1):
    spec = TEMPLATES[key]
    if seed != int(seed) or not -1 <= seed < 2**53:
        raise ValueError("Use uma seed inteira válida.")
    seed = random.randrange(2**32) if seed == -1 else int(seed)
    overrides = {spec["video"]: {"file": video}, spec["image"]: {"image": image}, spec["seed"][0]: {spec["seed"][1]: seed}}
    if (prompt or "").strip():
        overrides[spec["prompt"][0]] = {spec["prompt"][1]: prompt.strip()}
    return ui2api.convert(template(key), objinfo, outputs=spec["outputs"], overrides=overrides)


def files_for(key, graph):
    """[(name, entry)] for every weight the graph loads; a name the template notes do not list is an error (never download a guess)."""
    needed = []
    for node in graph.values():
        field = LOADERS.get(node["class_type"])
        if field and isinstance(node["inputs"].get(field), str):
            name = node["inputs"][field]
            if name not in FILES[key]:
                raise ValueError(f"O grafo pede {name}, que não está na lista de pesos do template.")
            needed.append((name, FILES[key][name]))
    return list({n: e for n, e in needed}.items())


def download_gb(key, graph, models_root=None):
    root = Path(models_root or os.environ.get("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models"))
    files = files_for(key, graph)
    return round(sum(e["size"] for _, e in files) / 1e9, 1), round(sum(e["size"] for n, e in files if not (root / e["folder"] / n).is_file()) / 1e9, 1)


def prepare(session, graph, progress, *, key, video, image):
    import cf_download
    from cf_workflows import require_nodes
    require_nodes(session, graph)
    root = Path(os.environ.get("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models"))
    files = files_for(key, graph)
    for index, (name, entry) in enumerate(files):
        target = root / entry["folder"] / name
        if not (target.is_file() and target.stat().st_size):
            try:
                cf_download.fetch_hf(entry["repo"], entry["path"], target, revision=entry["revision"], token=os.environ.get("HF_TOKEN") or None,
                                     progress=(lambda f, desc=None, **_: progress((index + f) / len(files), desc=desc)) if progress else None)
            except cf_download.DownloadError as exc:
                raise ValueError(str(exc)) from None
        if abs(target.stat().st_size - entry["size"]) > max(8_000_000, entry["size"] // 50):
            target.unlink(missing_ok=True)
            raise ValueError(f"{name} baixou com tamanho diferente do publicado; removido. Tente de novo.")
    spec = TEMPLATES[key]
    graph[spec["video"]]["inputs"]["file"] = upload_input(session, video)
    graph[spec["image"]]["inputs"]["image"] = upload_input(session, image)
