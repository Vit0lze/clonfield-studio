"""OpenJutsu API graph adapted to the local ComfyUI job runner."""

import json
import math
import secrets
from pathlib import Path

from cf_finish import video_duration
from cf_seedvr2 import upload_input
from cf_workflows import require_nodes

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "vendor/openjutsu/workflows/swap.api.json"
MIN_GPU_BYTES = 90 * 1024**3


def build_graph(start, seconds, resolution, direction, seed, anchor=False):
    if not math.isfinite(start) or start < 0 or not math.isfinite(seconds) or not 5 <= seconds <= 15:
        raise ValueError("Use início >= 0 e duração entre 5 e 15 segundos.")
    if resolution not in (480, 768) or seed != int(seed) or not -1 <= seed <= 2**32 - 1:
        raise ValueError("Use resolução 480 ou 768 e seed inteira de -1 a 2³²−1.")
    graph = json.loads(TEMPLATE.read_text())
    graph["trim"]["inputs"].update(start_time=round(start, 2), duration=round(seconds, 2))
    graph["31"]["inputs"].update(resolution=resolution, duration_seconds=round(seconds, 2))
    prompt = "Replace the selected person in <Video 1> with the character in <Picture 1>. Preserve the source performance, scene and audio timing."
    if anchor:
        prompt += " Start from the first frame in <Picture 2>."
    else:
        del graph["anchor_image"], graph["anchor_fit"], graph["803"]["inputs"]["anchor"]
        graph["803"]["inputs"]["use_anchor"] = False
    graph["801"]["inputs"].update(prompt=f"{prompt} {(direction or '').strip()[:500]}".strip(),
                                 seed=secrets.randbits(32) if seed == -1 else int(seed))
    return graph


def check_worker(session):
    from cf_seedvr2 import SERVER

    response = session.get(f"{SERVER}/system_stats", timeout=15)
    response.raise_for_status()
    devices = response.json().get("devices", [])
    if not any(device.get("type") == "cuda" and device.get("vram_total", 0) >= MIN_GPU_BYTES for device in devices):
        raise ValueError("OpenJutsu H3 precisa de um worker da classe de 96 GB para este perfil. Use a T4 para os outros apps.")


def prepare(session, graph, progress, *, video, character, anchor):
    check_worker(session)
    schemas = require_nodes(session, graph)
    for node_id, key in (("1", "unet_name"), ("4", "lora_name"), ("6", "clip_name"), ("7", "vae_name"),
                         ("8", "vae_name"), ("100", "ckpt_name"), ("850", "lora_name")):
        node = graph[node_id]
        name = node["inputs"][key]
        combo = schemas[node["class_type"]]["input"]["required"][key]
        options = combo[0] if isinstance(combo[0], list) else combo[1].get("options", [])
        if name not in options:
            raise ValueError(f"Peso ausente no worker: {name}. Veja docs/OPENJUTSU.md.")
    if video_duration(str(video)) + 0.05 < graph["trim"]["inputs"]["start_time"] + graph["trim"]["inputs"]["duration"]:
        raise ValueError("O trecho selecionado ultrapassa a duração do vídeo.")
    progress(0.12, desc="Enviando clipe e referência ao OpenJutsu")
    graph["30"]["inputs"]["file"] = upload_input(session, video)
    graph["9"]["inputs"]["image"] = upload_input(session, character)
    if anchor:
        graph["anchor_image"]["inputs"]["image"] = upload_input(session, anchor)
