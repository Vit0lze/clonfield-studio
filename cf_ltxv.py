"""LTX-Video 2B (v0.9.5) text-to-video and image-to-video from the official ComfyUI templates: the one video model here that is small enough for a 15 GB T4.

Weights: Lightricks/LTX-Video `ltx-video-2b-v0.9.5.safetensors` (6.3 GB; the licence on the model card is "other": read it before commercial use) and the
fp8-scaled T5-XXL text encoder from comfyanonymous/flux_text_encoders (5.2 GB, Apache-2.0; the template links the 9.8 GB fp16 one, the fp8 file is the
usual choice to fit RAM and is NOT what the template authors tested). Graph: the official templates, converted by cf_ui2api.
STATE: graphs ACCEPTED by a real ComfyUI 0.44.0 on CPU; nothing generated (BLOQUEADO_GPU): speed, VRAM and quality unmeasured.
"""

import os
import random
from pathlib import Path

import cf_ui2api as ui2api
from cf_seedvr2 import upload_input

DIR = Path(__file__).resolve().parent / "workflows"
CHECKPOINT = ("checkpoints", "Lightricks/LTX-Video", "ltx-video-2b-v0.9.5.safetensors", "8984fa25007f376c1a299016d0957a37a2f797bb", 6_340_729_500, "720d15c9f19f")
ENCODER = ("text_encoders", "comfyanonymous/flux_text_encoders", "t5xxl_fp8_e4m3fn_scaled.safetensors", "6af2a98e3f615bdfa612fbd85da93d1ed5f69ef5", 5_157_348_688, "a498f0485dc9")
FPS = (8, 30)
SECONDS = (1.0, 8.0)
NEGATIVE = "low quality, worst quality, deformed, distorted, disfigured, motion smear, motion artifacts, fused fingers, bad anatomy, weird hand, ugly"
# node ids in the two templates
T2V = dict(file="ltxv_text_to_video.json", checkpoint="44", encoder="38", positive="6", negative="7", latent="70", sampler="72", scheduler="71", conditioning="69", video="78", output="79")
I2V = dict(file="ltxv_image_to_video.json", checkpoint="44", encoder="38", positive="6", negative="7", latent="77", sampler="72", scheduler="71", conditioning="69", video="80", output="81", image="78")


def frames_for(seconds, fps):
    """LTX needs 8n+1 frames."""
    return int(8 * max(1, round((float(seconds) * int(fps) - 1) / 8)) + 1)


def build(objinfo, mode, prompt, seconds=4, fps=24, width=768, height=512, steps=30, cfg=3.0, seed=-1, image="entrada.png", negative=NEGATIVE):
    spec = T2V if mode == "text" else I2V if mode == "image" else None
    if spec is None:
        raise ValueError("Escolha texto em vídeo ou foto em movimento.")
    if len((prompt or "").strip()) < 20:
        raise ValueError("O LTX-Video pede um prompt longo e descritivo (a qualidade cai muito com prompts curtos).")
    if not SECONDS[0] <= float(seconds) <= SECONDS[1] or int(fps) != fps or not FPS[0] <= int(fps) <= FPS[1]:
        raise ValueError(f"Use de {SECONDS[0]:g} a {SECONDS[1]:g} segundos e de {FPS[0]} a {FPS[1]} quadros por segundo.")
    if width % 32 or height % 32 or not 256 <= width <= 1280 or not 256 <= height <= 1280:
        raise ValueError("Largura e altura: múltiplos de 32, de 256 a 1280.")
    if int(steps) != steps or not 8 <= steps <= 60 or not 0 < float(cfg) <= 15:
        raise ValueError("Use de 8 a 60 passos e CFG entre 0 e 15.")
    if seed != int(seed) or not -1 <= seed < 2**53:
        raise ValueError("Use uma seed inteira válida.")
    seed = random.randrange(2**32) if seed == -1 else int(seed)
    import json
    wf = json.loads((DIR / spec["file"]).read_text(encoding="utf-8"))
    frames = frames_for(seconds, fps)
    overrides = {spec["checkpoint"]: {"ckpt_name": CHECKPOINT[2]}, spec["encoder"]: {"clip_name": ENCODER[2]},
                 spec["positive"]: {"text": prompt.strip()}, spec["negative"]: {"text": negative},
                 spec["latent"]: {"width": width, "height": height, "length": frames}, spec["conditioning"]: {"frame_rate": float(fps)},
                 spec["sampler"]: {"noise_seed": seed, "cfg": float(cfg)}, spec["scheduler"]: {"steps": int(steps)}, spec["video"]: {"fps": float(fps)}}
    if mode == "image":
        overrides[spec["image"]] = {"image": image}
    return ui2api.convert(wf, objinfo, outputs=[spec["output"]], overrides=overrides)


def files():
    return [CHECKPOINT, ENCODER]


def download_gb(models_root=None):
    root = Path(models_root or os.environ.get("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models"))
    return round(sum(f[4] for f in files()) / 1e9, 1), round(sum(f[4] for f in files() if not (root / f[0] / f[2]).is_file()) / 1e9, 1)


def prepare(session, graph, progress, *, image=None):
    import cf_download
    from cf_workflows import require_nodes
    require_nodes(session, graph)
    root = Path(os.environ.get("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models"))
    for index, (folder, repo, name, revision, size, _sha) in enumerate(files()):
        target = root / folder / name
        if not (target.is_file() and target.stat().st_size):
            try:
                cf_download.fetch_hf(repo, name, target, revision=revision, token=os.environ.get("HF_TOKEN") or None,
                                     progress=(lambda f, desc=None, **_: progress((index + f) / 2, desc=desc)) if progress else None)
            except cf_download.DownloadError as exc:
                raise ValueError(str(exc)) from None
        if abs(target.stat().st_size - size) > max(8_000_000, size // 50):
            target.unlink(missing_ok=True)
            raise ValueError(f"{name} baixou com tamanho diferente do publicado; removido. Tente de novo.")
    for node in graph.values():
        if node["class_type"] == "LoadImage" and image:
            node["inputs"]["image"] = upload_input(session, image)
