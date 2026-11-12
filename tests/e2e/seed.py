"""Seeds a fresh data dir with real (tiny) safetensors LoRAs: Civitai-style downloads with sidecars + loose ComfyUI files."""
import json
import sys
from pathlib import Path

import numpy as np
from safetensors.numpy import save_file


def lora(path, meta=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    save_file({"lora_down.weight": np.zeros((2, 4), dtype=np.float32), "lora_up.weight": np.zeros((4, 2), dtype=np.float32)}, str(path), metadata=meta)


def civitai(base, stem, version, title, families):
    lora(base / "loras" / f"{stem}__cv{version}.safetensors")
    (base / "loras" / f"{stem}__cv{version}.json").write_text(json.dumps({"title": title, "families": families, "model": version, "version": version, "creator": "e2e"}))


data = Path(sys.argv[1])
base, comfy = data, data / "comfy-models"
civitai(base, "pixel_style", 11, "Pixel style", ["qwen21"])
civitai(base, "film_grain", 13, "Film grain", ["z-image", "z-image-turbo"])
lora(comfy / "loras" / "my_flux2_portrait.safetensors")
lora(comfy / "loras" / "mystery.safetensors")
print("seeded", data)
