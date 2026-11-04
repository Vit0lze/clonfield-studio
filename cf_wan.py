"""Local adaptation of the ComfyUI Wan 2.2 5B Video Generation template.

Source: https://docs.comfy.org/tutorials/video/wan/wan2_2
API graph: https://comfy.org/hub/workflows/wan-2-2-5b-video-generation-f83ee3caa04e/
The Studio adds direct image input, smaller presets, and download on demand.
"""

import os
import secrets
from pathlib import Path

from cf_workflows import require_nodes
from cf_seedvr2 import upload_input

TEXT_MODE = "Texto em vídeo"
IMAGE_MODE = "Foto em movimento"
SIZES = {"Horizontal · 512 × 288": (512, 288), "Vertical · 288 × 512": (288, 512),
         "Quadrado · 384 × 384": (384, 384)}
FRAMES = {"33 quadros": 33, "49 quadros": 49}
WEIGHTS = {
    "37": ("unet_name", "Comfy-Org/Wan-2.2", "diffusion_models/wan2.2_ti2v_5B_fp16.safetensors"),
    "38": ("clip_name", "Comfy-Org/Wan-2.1", "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
    "39": ("vae_name", "Comfy-Org/Wan-2.2", "vae/wan2.2_vae.safetensors"),
}


def make_graph(mode, image, prompt, negative, size, frames, steps, seed):
    if mode not in (TEXT_MODE, IMAGE_MODE) or size not in SIZES or frames not in FRAMES:
        raise ValueError("Escolha um modo, uma proporção e uma duração disponíveis.")
    if not prompt or not prompt.strip():
        raise ValueError("Descreva a cena ou o movimento.")
    if mode == IMAGE_MODE and not image:
        raise ValueError("Envie uma foto para animar.")
    if steps != int(steps) or not 8 <= steps <= 30 or seed != int(seed) or not -1 <= seed < 2**53:
        raise ValueError("Use de 8 a 30 passos e uma seed inteira válida.")
    seed = secrets.randbelow(2**32) if seed == -1 else int(seed)
    width, height = SIZES[size]

    def node(kind, **inputs):
        return {"class_type": kind, "inputs": inputs}

    graph = {
        "37": node("UNETLoader", unet_name=Path(WEIGHTS["37"][2]).name, weight_dtype="default"),
        "38": node("CLIPLoader", clip_name=Path(WEIGHTS["38"][2]).name, type="wan", device="default"),
        "39": node("VAELoader", vae_name=Path(WEIGHTS["39"][2]).name),
        "6": node("CLIPTextEncode", clip=["38", 0], text=prompt.strip()),
        "7": node("CLIPTextEncode", clip=["38", 0], text=(negative or "").strip()),
        "48": node("ModelSamplingSD3", model=["37", 0], shift=8),
        "55": node("Wan22ImageToVideoLatent", vae=["39", 0], width=width, height=height,
                   length=FRAMES[frames], batch_size=1),
        "3": node("KSampler", model=["48", 0], positive=["6", 0], negative=["7", 0],
                  latent_image=["55", 0], seed=seed, steps=int(steps), cfg=5,
                  sampler_name="uni_pc", scheduler="simple", denoise=1),
        "8": node("VAEDecode", vae=["39", 0], samples=["3", 0]),
        "57": node("CreateVideo", images=["8", 0], fps=24),
        "58": node("SaveVideo", video=["57", 0], filename_prefix="ClonField/Wan",
                   format="mp4", **{"format.codec": "h264"}),
    }
    if mode == IMAGE_MODE:
        graph["56"] = node("LoadImage", image="entrada.png")
        graph["55"]["inputs"]["start_image"] = ["56", 0]
    return graph


def prepare(session, graph, progress, *, image):
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import HfHubHTTPError

    schemas = require_nodes(session, graph)
    directory = Path(os.environ.get("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models"))
    for node_id, (key, repo, filename) in WEIGHTS.items():
        node = graph[node_id]
        name = node["inputs"][key]
        combo = schemas[node["class_type"]]["input"]["required"][key]
        choices = combo[0] if isinstance(combo[0], list) else combo[1].get("options", [])
        if name in choices:
            continue
        progress(0.1, desc=f"Baixando {name}")
        try:
            source = hf_hub_download(repo, "split_files/" + filename,
                                     local_dir=directory / ".clonfield-downloads",
                                     token=os.environ.get("HF_TOKEN") or None)
        except HfHubHTTPError as exc:
            raise ValueError(f"O Hugging Face não entregou o peso {name}. Confira a conexão e o acesso.") from exc
        target = directory / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        Path(source).replace(target)
    if "56" in graph:
        graph["56"]["inputs"]["image"] = upload_input(session, image)
