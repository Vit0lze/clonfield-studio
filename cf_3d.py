"""Image to 3D (GLB) with the official ComfyUI TRELLIS.2 / Pixal3D workflow, built from the vendored UI template.

The template (Comfy-Org/workflow_templates, MIT) has ~60 nodes in several stages (MoGe, background removal, shape, texture, baking, remesh, GLB).
Instead of re-writing it by hand, `cf_ui2api.convert` turns it into an API graph with the worker's own `/object_info`, the engine switch is folded
at build time (so only the chosen engine's weights are required) and the result is pruned to the GLB output. The real ComfyUI 0.44.0 accepts
both converted graphs (tests/test_comfy_real.py asks it with POST /prompt).

STATE: graphs VALIDATED by a real ComfyUI on CPU; nothing was GENERATED (needs the T4: ~6 GB of weights per engine plus the texture-baking stages)
-> BLOQUEADO_GPU for speed, VRAM and quality.
"""

import json
import os
import random
from pathlib import Path

import cf_ui2api as ui2api
from cf_seedvr2 import upload_input

TEMPLATE = Path(__file__).resolve().parent / "workflows" / "3d_pixal3d_trellis2_image_to_model.json"
OUTPUT = 322          # Save3DAdvanced
ENGINE_SWITCH = 316   # PrimitiveBoolean: False = Pixal3D, True = TRELLIS.2
LOAD_IMAGE = 122
TEXTURE_SIZE = 288    # PrimitiveInt that feeds BakeTextureFromVoxel
DECIMATE = 186        # DecimateMesh
SAMPLERS = (3, 18, 12, 23)
ENGINES = {"pixal3d": ("Pixal3D (mais fiel à foto)", False), "trellis2": ("TRELLIS.2", True)}
TEXTURES = (1024, 2048, 4096)

# file name -> (folder under ComfyUI/models, repo, path in repo, revision, bytes, sha256 prefix): all MIT, all Comfy-Org repackaged
FILES = {
    "pixal3d_int8_convrot.safetensors": ("diffusion_models", "Comfy-Org/Pixal3D", "diffusion_models/pixal3d_int8_convrot.safetensors", "f37641be376725d324c56626007cc477f1249a69", 5_580_000_000, "4621eac3b7"),
    "dino_v3_L_naf_fp32.safetensors": ("clip_vision", "Comfy-Org/Pixal3D", "clip_vision/dino_v3_L_naf_fp32.safetensors", "f37641be376725d324c56626007cc477f1249a69", 1_220_000_000, "4ad2ec4e08"),
    "trellis_2_shape_vae_bf16.safetensors": ("vae", "Comfy-Org/Pixal3D", "vae/trellis_2_shape_vae_bf16.safetensors", "f37641be376725d324c56626007cc477f1249a69", 1_100_000_000, "de0cb4949a"),
    "trellis_2_texture_vae_bf16.safetensors": ("vae", "Comfy-Org/Pixal3D", "vae/trellis_2_texture_vae_bf16.safetensors", "f37641be376725d324c56626007cc477f1249a69", 950_000_000, "714e5ebf09"),
    "moge_2_vitl_normal_fp16.safetensors": ("geometry_estimation", "Comfy-Org/MoGe", "geometry_estimation/moge_2_vitl_normal_fp16.safetensors", "1484985258ba7ef45c314144fcf0e90924ffbf44", 660_000_000, "cb1a692d03"),
    "birefnet.safetensors": ("background_removal", "Comfy-Org/BiRefNet", "background_removal/birefnet.safetensors", "884af709e9b795d89dafbf97f29c8d6a2386f5c6", 440_000_000, "9ab37426bf"),
    "trellis_2_int8_convrot.safetensors": ("diffusion_models", "Comfy-Org/TRELLIS.2", "diffusion_models/trellis_2_int8_convrot.safetensors", "430a9d09b2416687018c8fe8edced2ad4858a439", 5_250_000_000, "d01952ad13"),
}
LOADER_INPUTS = {"UNETLoader": "unet_name", "VAELoader": "vae_name", "CLIPVisionLoader": "clip_name", "LoadMoGeModel": "model_name", "LoadBackgroundRemovalModel": "bg_removal_name"}


def template():
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def build(objinfo, engine="pixal3d", seed=-1, texture=2048, faces=700_000, image="entrada.png"):
    if engine not in ENGINES:
        raise ValueError("Escolha Pixal3D ou TRELLIS.2.")
    if texture not in TEXTURES:
        raise ValueError("Use textura de 1024, 2048 ou 4096.")
    if not 5_000 <= int(faces) <= 2_000_000:
        raise ValueError("Use de 5 mil a 2 milhões de faces.")
    if seed != int(seed) or not -1 <= seed < 2**53:
        raise ValueError("Use uma seed inteira válida.")
    seed = random.randrange(2**32) if seed == -1 else int(seed)
    overrides = {ENGINE_SWITCH: {"value": ENGINES[engine][1]}, LOAD_IMAGE: {"image": image}, TEXTURE_SIZE: {"value": int(texture)}, DECIMATE: {"target_face_count": int(faces)}}
    overrides.update({node: {"seed": seed + index} for index, node in enumerate(SAMPLERS)})
    return ui2api.convert(template(), objinfo, outputs=[OUTPUT], overrides=overrides)


def files_for(graph):
    """The weight files this graph loads, with where each comes from."""
    needed = []
    for node in graph.values():
        key = LOADER_INPUTS.get(node["class_type"])
        if key and node["inputs"].get(key) in FILES:
            needed.append((node["inputs"][key], *FILES[node["inputs"][key]]))
    return needed


def download_gb(graph, models_root=None):
    root = Path(models_root or os.environ.get("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models"))
    total = sum(f[5] for f in files_for(graph))
    missing = sum(f[5] for f in files_for(graph) if not (root / f[1] / f[0]).is_file())
    return round(total / 1e9, 1), round(missing / 1e9, 1)


def prepare(session, graph, progress, *, image):
    import cf_download
    from cf_workflows import require_nodes
    require_nodes(session, graph)
    root = Path(os.environ.get("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models"))
    files = files_for(graph)
    for index, (name, folder, repo, path, revision, size, _sha) in enumerate(files):
        target = root / folder / name
        if not (target.is_file() and target.stat().st_size):
            try:
                cf_download.fetch_hf(repo, path, target, revision=revision, token=os.environ.get("HF_TOKEN") or None,
                                     progress=(lambda f, desc=None, **_: progress((index + f) / len(files), desc=desc)) if progress else None)
            except cf_download.DownloadError as exc:
                raise ValueError(str(exc)) from None
        if abs(target.stat().st_size - size) > max(8_000_000, size // 50):
            target.unlink(missing_ok=True)
            raise ValueError(f"{name} baixou com tamanho diferente do publicado; removido. Tente de novo.")
    for node in graph.values():
        if node["class_type"] == "LoadImage":
            node["inputs"]["image"] = upload_input(session, image)
