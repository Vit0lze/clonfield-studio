"""See-through V3: anime illustration -> transparent layers -> editable PSD.

Reuses, unmodified, the ComfyUI custom node pack jtydhr88/ComfyUI-See-through (MIT per its pyproject.toml; it
wraps shitagaki-lab/see-through, Apache-2.0). The pack is cloned at a pinned commit by ``prepare_seethrough.py``;
this module only builds the API graph, runs it through the shared job runner and packs the result.

Weights are NOT under the code licence: LayerDiff 3D is OpenRAIL++ (use restrictions apply, see the model card).
"""

import io
import json
import zipfile
from pathlib import Path

import requests

from cf_seedvr2 import SERVER, upload_input
from cf_workflows import require_nodes

PACK_REPO = "https://github.com/jtydhr88/ComfyUI-See-through"
PACK_COMMIT = "98d754b"  # pinned; verified by prepare_seethrough.py
LAYERDIFF = "layerdifforg/seethroughv0.0.2_layerdiff3d"
DEPTH = "layerdifforg/seethroughv0.0.1_marigold"

# Whole-set profiles. VRAM figures are the upstream README claims at 1280 px, NOT measured by ClonField.
PROFILES = {
    "T4 · NF4 (leve)": dict(quant="nf4", offload=True, resolution=1024, depth_resolution=720, claim="~8 GB"),
    "BF16 + offload": dict(quant="none", offload=True, resolution=1280, depth_resolution=-1, claim="~10 GB"),
    "BF16 completo": dict(quant="none", offload=False, resolution=1280, depth_resolution=-1, claim="12-16 GB"),
}
DEFAULT_PROFILE = next(iter(PROFILES))


def build_graph(profile, seed, steps, image_name, resolution=None, lama=True, split=True):
    if profile not in PROFILES:
        raise ValueError("Perfil desconhecido: " + str(profile))
    if seed != int(seed) or not 0 <= seed <= 2**32 - 1 or not 1 <= steps <= 100:
        raise ValueError("Use seed 0..2³²−1 e passos entre 1 e 100.")
    cfg = PROFILES[profile]
    res = int(resolution or cfg["resolution"])
    if res % 64 or not 512 <= res <= 2048:
        raise ValueError("Resolução deve ser múltiplo de 64 entre 512 e 2048.")
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "SeeThrough_LoadLayerDiffModel",
              "inputs": {"model": LAYERDIFF, "quant_mode": cfg["quant"], "cache_tag_embeds": True,
                         "group_offload": cfg["offload"], "auto_download": True}},
        "3": {"class_type": "SeeThrough_LoadDepthModel",
              "inputs": {"model": DEPTH, "quant_mode": cfg["quant"], "cache_tag_embeds": True,
                         "group_offload": cfg["offload"], "auto_download": True}},
        "4": {"class_type": "SeeThrough_GenerateLayers",
              "inputs": {"image": ["1", 0], "layerdiff_model": ["2", 0], "seed": seed, "resolution": res,
                         "num_inference_steps": steps}},
        "5": {"class_type": "SeeThrough_GenerateDepth",
              "inputs": {"layers": ["4", 0], "depth_model": ["3", 0], "seed": seed,
                         "resolution_depth": cfg["depth_resolution"]}},
        "6": {"class_type": "SeeThrough_PostProcess",
              "inputs": {"layers_depth": ["5", 0], "tblr_split": bool(split), "use_lama": bool(lama)}},
        "7": {"class_type": "PreviewImage", "inputs": {"images": ["6", 1]}},
        "8": {"class_type": "SeeThrough_SavePSD", "inputs": {"parts": ["6", 0], "filename_prefix": "clonfield_layers"}},
    }


def prepare(session, graph, progress, *, image):
    require_nodes(session, graph)
    progress(0.1, desc="Enviando ilustração")
    graph["1"]["inputs"]["image"] = upload_input(session, image)


def fetch_layers(session, output_dir):
    """Read the layers.json written by SeeThrough_SavePSD plus every PNG it references (via ComfyUI /view)."""
    def view(name):
        if name != Path(name).name or "\\" in name:
            raise ValueError("Nome de arquivo inválido vindo do worker.")
        r = session.get(f"{SERVER}/view", params={"filename": name, "type": "output"}, timeout=60)
        r.raise_for_status()
        return r.content

    info_name = view("seethrough_psd_info.log").decode().strip()
    info = json.loads(view(info_name))
    layers = []
    for entry in info["layers"]:
        layers.append(dict(entry, png=view(entry["filename"]),
                           depth_png=view(entry["depth_filename"]) if entry.get("depth_filename") else None))
    return info, layers


def write_package(info, layers, folder, stem="camadas"):
    """Write PSD (psd-tools), ZIP with PNG layers + depth + json, and a flattened preview. Returns paths."""
    from PIL import Image

    folder = Path(folder)
    width, height = int(info["width"]), int(info["height"])
    zip_path = folder / f"{stem}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("layers.json", json.dumps({k: v for k, v in info.items()}, indent=2))
        for layer in layers:
            bundle.writestr(f"layers/{layer['name']}.png", layer["png"])
            if layer.get("depth_png"):
                bundle.writestr(f"depth/{layer['name']}.png", layer["depth_png"])
    # Drawing order: farthest (largest depth_median) first = bottom of the stack.
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    placed = []
    for layer in layers:
        image = Image.open(io.BytesIO(layer["png"])).convert("RGBA")
        full = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        full.paste(image, (int(layer["left"]), int(layer["top"])))
        placed.append((layer["name"], full))
        canvas.alpha_composite(full)
    preview = folder / f"{stem}_previa.png"
    canvas.save(preview)
    outputs = [preview, zip_path]
    try:
        from psd_tools import PSDImage
    except ImportError:
        return outputs  # PSD is optional; the ZIP already carries every layer
    psd = PSDImage.new("RGBA", (width, height))
    for name, full in placed:
        psd.create_pixel_layer(full, name=name)
    psd_path = folder / f"{stem}.psd"
    psd.save(psd_path)
    return [preview, psd_path, zip_path]
