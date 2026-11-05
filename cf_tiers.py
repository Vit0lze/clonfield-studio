"""Pick defaults and ComfyUI flags from the GPU that is actually attached."""

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    key: str
    label: str
    vram_gb: float
    gpu: str
    max_side: int
    default_side: int
    max_variations: int
    video_side: int
    video_frames: int
    seedvr2: str
    openjutsu: bool
    comfy_flags: tuple
    precision: str  # "gguf" on cards without fast fp8/int8, else "int8"

    def public(self):
        return {key: getattr(self, key) for key in self.__dataclass_fields__ if key != "comfy_flags"}


def read_gpu():
    fake = os.environ.get("CLONFIELD_FAKE_VRAM")
    if fake:
        return os.environ.get("CLONFIELD_FAKE_GPU", "GPU simulada"), float(fake), 8.0
    if not shutil.which("nvidia-smi"):
        return "Sem GPU", 0.0, 0.0
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,compute_cap", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.splitlines()[0]
        name, mib, cap = (part.strip() for part in out.split(","))
        return name, int(mib) / 1024, float(cap)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return "Sem GPU", 0.0, 0.0


def detect():
    name, vram, capability = read_gpu()
    old_card = capability and capability < 8.0
    if vram >= 40:
        return Tier("pro", "Pro", vram, name, 2048, 1536, 4, 768, 97, "7B", True,
                    ("--highvram", "--use-pytorch-cross-attention"), "int8")
    if vram >= 16:
        return Tier("medio", "Médio", vram, name, 1536, 1024, 2, 512, 49, "7B", False,
                    ("--normalvram", "--use-pytorch-cross-attention"), "gguf" if old_card else "int8")
    return Tier("leve", "Leve", vram, name, 1024, 768, 1, 384, 33, "3B", False,
                ("--normalvram", "--reserve-vram", "1", "--use-pytorch-cross-attention"), "gguf" if old_card else "int8")


def estimate_vram_gb(model_params_b, side_pixels, precision="int8"):
    """Rough peak: weights plus activation that grows with pixels. Good enough to warn before a long job."""
    weights = model_params_b * (0.5 if precision == "gguf" else 1.0)
    return round(weights + 1.5 + 2.2 * (side_pixels / (1024 * 1024)), 1)
