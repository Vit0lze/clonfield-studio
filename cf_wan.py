"""Wan 2.2 video: text-to-video and image-to-video, on GGUF quantised weights, with seconds / FPS / free size controls.

Sources (all real, checked against the Hugging Face API by tests/test_wan.py):
  * Comfy-Org/Wan-2.2 and Comfy-Org/Wan-2.1 repackaged: text encoder, VAEs and the original 5B FP16 weights.
  * QuantStack/Wan2.2-{T2V,I2V}-A14B-GGUF (HighNoise + LowNoise, Q6_K = high quality) and QuantStack/Wan2.2-TI2V-5B-GGUF (Q6_K / Q8_0).
  * city96/ComfyUI-GGUF (node `UnetLoaderGGUF`), installed by prepare_gguf.py at a pinned commit.
Graph shapes follow the official ComfyUI Wan 2.2 templates (docs.comfy.org/tutorials/video/wan/wan2_2): the 5B model is one
sampler; the A14B model is TWO samplers over two weight files (high-noise steps first, low-noise steps after).

STATE: CÓDIGO ESCRITO. The graphs are checked on CPU against the real ComfyUI v0.44.0 / ComfyUI-GGUF source (node names and input
names). Nothing here has generated a video on a GPU: speed, VRAM peak (an A14B Q6_K file is 12 GB, two of them), quality and the
conservative size limits below are NOT measured (BLOQUEADO_GPU).
"""

import os
import secrets
from pathlib import Path

from cf_workflows import require_nodes
from cf_seedvr2 import upload_input

TEXT_MODE = "Texto em vídeo"
IMAGE_MODE = "Foto em movimento"

WAN22 = ("Comfy-Org/Wan-2.2", "ee6f4a4073")
WAN21 = ("Comfy-Org/Wan-2.1", "123acf1cc7")
GGUF_PACK = ("https://github.com/city96/ComfyUI-GGUF", "6ea2651e7df66d7585f6ffee804b20e92fb38b8a")

# One file a graph needs: (folder under ComfyUI/models, repo, path in the repo, revision, bytes, sha256 prefix)
TEXT_ENCODER = ("text_encoders", "Comfy-Org/Wan-2.1", "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", "123acf1cc7", 6_736_000_000, "c3355d30191f")
VAE_21 = ("vae", "Comfy-Org/Wan-2.1", "split_files/vae/wan_2.1_vae.safetensors", "123acf1cc7", 254_000_000, "2fc39d31359a")
VAE_22 = ("vae", "Comfy-Org/Wan-2.2", "split_files/vae/wan2.2_vae.safetensors", "ee6f4a4073", 1_410_000_000, "e40321bd36b9")

# model key -> everything the form and the graph need. `vram` is the file size to hold at once (an honest lower bound, not a measurement).
MODELS = {
    "a14b-q6": dict(label="Wan 2.2 A14B · Q6_K (alta qualidade)", kind="a14b", quant="Q6_K", fps=16, vram=12, align=16,
                    note="Dois modelos de 12 GB que se alternam; exige descarregar um antes do outro.",
                    t2v=[("unet", "QuantStack/Wan2.2-T2V-A14B-GGUF", "HighNoise/Wan2.2-T2V-A14B-HighNoise-Q6_K.gguf", "73eafba53a1a8f29254e4c77f92e74ea27d7cd6f", 12_000_000_000, "504340d1d4eb"),
                         ("unet", "QuantStack/Wan2.2-T2V-A14B-GGUF", "LowNoise/Wan2.2-T2V-A14B-LowNoise-Q6_K.gguf", "73eafba53a1a8f29254e4c77f92e74ea27d7cd6f", 12_000_000_000, "db3506181004")],
                    i2v=[("unet", "QuantStack/Wan2.2-I2V-A14B-GGUF", "HighNoise/Wan2.2-I2V-A14B-HighNoise-Q6_K.gguf", "6c6717459277b9cd1f72579d78a0fd62a79e57dc", 12_000_000_000, "33ab8d99b5be"),
                         ("unet", "QuantStack/Wan2.2-I2V-A14B-GGUF", "LowNoise/Wan2.2-I2V-A14B-LowNoise-Q6_K.gguf", "6c6717459277b9cd1f72579d78a0fd62a79e57dc", 12_000_000_000, "962d9c937a6e")],
                    vae=VAE_21),
    "5b-q6": dict(label="Wan 2.2 5B · Q6_K (leve)", kind="5b", quant="Q6_K", fps=24, vram=4.2, align=32, note="",
                  both=[("unet", "QuantStack/Wan2.2-TI2V-5B-GGUF", "Wan2.2-TI2V-5B-Q6_K.gguf", "57437632ddd08bdcbd1508c866aa22e126ed51d2", 4_210_000_000, "355f6bee35c4")], vae=VAE_22),
    "5b-q8": dict(label="Wan 2.2 5B · Q8_0", kind="5b", quant="Q8_0", fps=24, vram=5.4, align=32, note="",
                  both=[("unet", "QuantStack/Wan2.2-TI2V-5B-GGUF", "Wan2.2-TI2V-5B-Q8_0.gguf", "57437632ddd08bdcbd1508c866aa22e126ed51d2", 5_400_000_000, "57bece983817")], vae=VAE_22),
    "5b-fp16": dict(label="Wan 2.2 5B · FP16 (original)", kind="5b", quant="FP16", fps=24, vram=10, align=32, note="O mesmo de antes: 10 GB só de pesos.",
                    both=[("diffusion_models", "Comfy-Org/Wan-2.2", "split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors", "ee6f4a4073", 10_000_000_000, "456f901338bd")], vae=VAE_22),
}
DEFAULT_MODEL = "5b-q6"
SIZES = {"Horizontal · 832 × 480": (832, 480), "Vertical · 480 × 832": (480, 832), "Quadrado · 640 × 640": (640, 640),
         "Horizontal · 512 × 288 (rápido)": (512, 288), "HD · 1280 × 704": (1280, 704), "Personalizado": None}
FRAMES = {"33 quadros": 33, "49 quadros": 49}  # kept for the old two-field form and for old saved jobs
SECONDS = (1.0, 10.0)
FPS = (8, 30)
STEPS = (8, 40)
# Conservative guard rails (NOT measured on a GPU): total pixels x frames the sampler is asked to hold, by model kind and card size.
BUDGET = {"5b": [(24, 1280 * 704 * 121), (0, 832 * 480 * 121)], "a14b": [(24, 1280 * 720 * 81), (0, 832 * 480 * 81)]}


def frames_for(seconds, fps):
    """Wan needs a length of 4n+1 frames (the VAE compresses time by 4). Round to the nearest valid length."""
    n = max(0, round((float(seconds) * int(fps) - 1) / 4))
    return int(4 * n + 1)


def budget(kind, vram_gb):
    for floor, pixels in BUDGET[kind]:
        if vram_gb >= floor:
            return pixels
    return BUDGET[kind][-1][1]


def files_for(model_key, mode):
    spec = MODELS[model_key]
    unets = spec["both"] if "both" in spec else spec["t2v" if mode == TEXT_MODE else "i2v"]
    return [*unets, TEXT_ENCODER, spec["vae"]]


def download_gb(model_key, mode, models_root=None):
    """(total GB, missing GB) for the files this model needs. Shown before anything downloads."""
    root = Path(models_root or os.environ.get("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models"))
    total = sum(f[4] for f in files_for(model_key, mode))
    missing = sum(f[4] for f in files_for(model_key, mode) if not (root / f[0] / Path(f[2]).name).is_file())
    return round(total / 1e9, 1), round(missing / 1e9, 1)


def resolve_size(size, width, height, align, kind, vram_gb, frames):
    if size == "Personalizado":
        width, height = int(width or 0), int(height or 0)
    elif size in SIZES and SIZES[size]:
        width, height = SIZES[size]
    else:
        raise ValueError("Escolha uma proporção da lista ou «Personalizado».")
    if width % align or height % align or not 256 <= width <= 1920 or not 256 <= height <= 1920:
        raise ValueError(f"Largura e altura precisam ser múltiplos de {align}, entre 256 e 1920 (recebi {width} × {height}).")
    limit = budget(kind, vram_gb)
    if width * height * frames > limit:
        raise ValueError(f"{width} × {height} com {frames} quadros passa do limite conservador para uma placa de {vram_gb:.0f} GB. Reduza o tamanho ou a duração.")
    return width, height


def make_graph(model_key, mode, image, prompt, negative, size, seconds, fps, steps, cfg, seed, width=None, height=None, vram_gb=15):
    if model_key not in MODELS:
        raise ValueError("Escolha um modelo de vídeo da lista.")
    spec = MODELS[model_key]
    if mode not in (TEXT_MODE, IMAGE_MODE):
        raise ValueError("Escolha texto em vídeo ou foto em movimento.")
    if not prompt or not prompt.strip():
        raise ValueError("Descreva a cena ou o movimento.")
    if mode == IMAGE_MODE and not image:
        raise ValueError("Envie uma foto para animar.")
    if not SECONDS[0] <= float(seconds) <= SECONDS[1] or int(fps) != float(fps) or not FPS[0] <= int(fps) <= FPS[1]:
        raise ValueError(f"Use de {SECONDS[0]:g} a {SECONDS[1]:g} segundos e de {FPS[0]} a {FPS[1]} quadros por segundo.")
    if int(steps) != steps or not STEPS[0] <= steps <= STEPS[1] or not 0 < float(cfg) <= 15:
        raise ValueError(f"Use de {STEPS[0]} a {STEPS[1]} passos e CFG entre 0 e 15.")
    if seed != int(seed) or not -1 <= seed < 2**53:
        raise ValueError("Use uma seed inteira válida.")
    seed = secrets.randbelow(2**32) if seed == -1 else int(seed)
    frames = frames_for(seconds, fps)
    width, height = resolve_size(size, width, height, spec["align"], spec["kind"], vram_gb, frames)

    def node(kind, **inputs):
        return {"class_type": kind, "inputs": inputs}

    def unet(entry):
        name = Path(entry[2]).name
        return node("UnetLoaderGGUF", unet_name=name) if name.endswith(".gguf") else node("UNETLoader", unet_name=name, weight_dtype="default")

    graph = {
        "38": node("CLIPLoader", clip_name=Path(TEXT_ENCODER[2]).name, type="wan", device="default"),
        "39": node("VAELoader", vae_name=Path(spec["vae"][2]).name),
        "6": node("CLIPTextEncode", clip=["38", 0], text=prompt.strip()),
        "7": node("CLIPTextEncode", clip=["38", 0], text=(negative or "").strip()),
    }
    if spec["kind"] == "5b":
        graph["37"] = unet(spec["both"][0])
        graph["48"] = node("ModelSamplingSD3", model=["37", 0], shift=8)
        graph["55"] = node("Wan22ImageToVideoLatent", vae=["39", 0], width=width, height=height, length=frames, batch_size=1)
        graph["3"] = node("KSampler", model=["48", 0], positive=["6", 0], negative=["7", 0], latent_image=["55", 0], seed=seed, steps=int(steps),
                          cfg=float(cfg), sampler_name="uni_pc", scheduler="simple", denoise=1)
        latent = ["3", 0]
        if mode == IMAGE_MODE:
            graph["56"] = node("LoadImage", image="entrada.png")
            graph["55"]["inputs"]["start_image"] = ["56", 0]
    else:
        unets = spec["t2v"] if mode == TEXT_MODE else spec["i2v"]
        graph["37"], graph["47"] = unet(unets[0]), unet(unets[1])  # high noise, low noise
        graph["48"] = node("ModelSamplingSD3", model=["37", 0], shift=8)
        graph["49"] = node("ModelSamplingSD3", model=["47", 0], shift=8)
        if mode == TEXT_MODE:
            graph["55"] = node("EmptyHunyuanLatentVideo", width=width, height=height, length=frames, batch_size=1)
            positive, negative_ref, start = ["6", 0], ["7", 0], ["55", 0]
        else:
            graph["56"] = node("LoadImage", image="entrada.png")
            graph["55"] = node("WanImageToVideo", positive=["6", 0], negative=["7", 0], vae=["39", 0], width=width, height=height, length=frames,
                               batch_size=1, start_image=["56", 0])
            positive, negative_ref, start = ["55", 0], ["55", 1], ["55", 2]
        split = max(1, int(steps) // 2)
        graph["3"] = node("KSamplerAdvanced", model=["48", 0], add_noise="enable", noise_seed=seed, steps=int(steps), cfg=float(cfg), sampler_name="euler",
                          scheduler="simple", positive=positive, negative=negative_ref, latent_image=start, start_at_step=0, end_at_step=split,
                          return_with_leftover_noise="enable")
        graph["4"] = node("KSamplerAdvanced", model=["49", 0], add_noise="disable", noise_seed=seed, steps=int(steps), cfg=float(cfg), sampler_name="euler",
                          scheduler="simple", positive=positive, negative=negative_ref, latent_image=["3", 0], start_at_step=split, end_at_step=10000,
                          return_with_leftover_noise="disable")
        latent = ["4", 0]
    graph["8"] = node("VAEDecode", vae=["39", 0], samples=latent)
    graph["57"] = node("CreateVideo", images=["8", 0], fps=int(fps))
    graph["58"] = node("SaveVideo", video=["57", 0], filename_prefix="ClonField/Wan", format="mp4", **{"format.codec": "h264"})
    return graph


def downloads(model_key, mode):
    """The files to fetch, as (key of the node input, folder, repo, filename, revision) for prepare()."""
    return [(f[0], f[1], f[2], f[3]) for f in files_for(model_key, mode)]


def prepare(session, graph, progress, *, image, model_key=DEFAULT_MODEL, mode=TEXT_MODE):
    """Make every weight the graph names exist under ComfyUI/models (download on demand, pinned revision, size and SHA-256 checked)."""
    import cf_download
    try:
        require_nodes(session, graph)
    except ValueError as exc:
        if "UnetLoaderGGUF" in str(exc):
            raise ValueError("O nó UnetLoaderGGUF não está no ComfyUI. Rode prepare_gguf.py (célula do Colab) e reinicie o worker.") from None
        raise
    root = Path(os.environ.get("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models"))
    files = files_for(model_key, mode)
    for index, (folder, repo, filename, revision, size, sha) in enumerate(files):
        target = root / folder / Path(filename).name
        if not (target.is_file() and target.stat().st_size):
            try:
                cf_download.fetch_hf(repo, filename, target, revision=revision, token=os.environ.get("HF_TOKEN") or None,
                                     progress=(lambda f, desc=None, **_: progress((index + f) / len(files), desc=desc)) if progress else None)
            except cf_download.DownloadError as exc:
                raise ValueError(str(exc)) from None
        if abs(target.stat().st_size - size) > max(8_000_000, size // 50):
            target.unlink(missing_ok=True)
            raise ValueError(f"{target.name} baixou com tamanho diferente do publicado; removido. Tente de novo.")
    if "56" in graph:
        graph["56"]["inputs"]["image"] = upload_input(session, image)
