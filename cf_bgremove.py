"""Remover fundo: a transparent PNG (or a flat colour behind the subject) from any picture, on the CPU, with U^2-Net.

Models (Apache-2.0, ONNX, pinned by repository revision, size and SHA-256 from the Hugging Face API): `u2net` (176 MB, general) and `u2netp` (4.6 MB, fast
and rougher), BritishWerewolf's ONNX exports of U^2-Net (Qin et al., Pattern Recognition 2020). The pre- and post-processing is the standard
U^2-Net recipe: resize to 320x320, scale by the picture's maximum, ImageNet mean/std, take the first output, min-max it, resize back as the alpha.

Measured here: runs on a 3 GB CPU box in seconds; the mask quality on hair, glass and thin structures is whatever U^2-Net gives (not measured against a
benchmark here).
"""

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

import cf_download as download

MODELS = {
    "u2net": dict(label="U²-Net (geral)", repo="BritishWerewolf/U-2-Net", revision="c08042b462485d8597c89d3ce831d00be8582c5c", file="onnx/model.onnx", size=175_997_641,
                  sha256="8d10d2f3bb75ae3b6d527c77944fc5e7dcd94b29809d47a739a7a728a912b491"),
    "u2netp": dict(label="U²-Net pequeno (rápido)", repo="BritishWerewolf/U-2-Netp", revision="7112208dbac3a3642496c8d54e2f0f9bb3dc1dc8", file="onnx/model.onnx", size=4_574_861,
                   sha256="309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8"),
}
DEFAULT = "u2net"
SIDE = 320
MEAN, STD = np.array([0.485, 0.456, 0.406], dtype=np.float32), np.array([0.229, 0.224, 0.225], dtype=np.float32)
_sessions = {}


def model_path(base, key):
    return Path(base) / "models" / "bgremove" / f"{key}.onnx"


def sha256_of(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1 << 24):
            digest.update(block)
    return digest.hexdigest()


def ensure(base, key=DEFAULT, progress=None):
    """The pinned model file, downloaded once; a file whose SHA-256 differs is removed and refused."""
    if key not in MODELS:
        raise ValueError("Escolha um modelo de recorte da lista.")
    spec, path = MODELS[key], model_path(base, key)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        download.fetch_hf(spec["repo"], spec["file"], path, revision=spec["revision"], progress=progress)
    if path.stat().st_size != spec["size"] or sha256_of(path) != spec["sha256"]:
        path.unlink(missing_ok=True)
        raise ValueError(f"O arquivo de {spec['label']} não confere com o publicado; foi removido. Tente de novo.")
    return path


def session(path):
    key = str(path)
    if key not in _sessions:
        try:
            import onnxruntime
        except ImportError:
            raise ValueError("Falta o pacote onnxruntime (pip install onnxruntime) para remover o fundo.") from None
        _sessions[key] = onnxruntime.InferenceSession(key, providers=["CPUExecutionProvider"])
    return _sessions[key]


def matte(image, path):
    """The alpha matte (uint8, same size as `image`) U^2-Net predicts for a picture."""
    rgb = ImageOps.exif_transpose(image).convert("RGB")
    small = np.asarray(rgb.resize((SIDE, SIDE), Image.Resampling.LANCZOS), dtype=np.float32)
    small = small / max(float(small.max()), 1e-6)
    tensor = ((small - MEAN) / STD).transpose(2, 0, 1)[None].astype(np.float32)
    sess = session(path)
    pred = sess.run(None, {sess.get_inputs()[0].name: tensor})[0][0, 0]
    pred = (pred - pred.min()) / max(float(pred.max() - pred.min()), 1e-6)
    return Image.fromarray((pred * 255).astype(np.uint8)).resize(rgb.size, Image.Resampling.LANCZOS)


def remove(image, path, background=None, crop=False, cutoff=0):
    """RGBA with the matte as alpha; `background` (r, g, b) flattens it onto that colour; `crop` trims to the subject; `cutoff` (0-254) hardens the edge."""
    rgb = ImageOps.exif_transpose(image).convert("RGB")
    alpha = matte(rgb, path)
    if cutoff:
        alpha = alpha.point(lambda v: 0 if v <= cutoff else 255)
    out = rgb.copy()
    out.putalpha(alpha)
    if crop:
        box = alpha.point(lambda v: 255 if v > 24 else 0).getbbox()
        if box:
            pad = round(0.04 * max(rgb.size))
            out = out.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(rgb.width, box[2] + pad), min(rgb.height, box[3] + pad)))
    if background is not None:
        flat = Image.new("RGB", out.size, tuple(background))
        flat.paste(out, mask=out.getchannel("A"))
        return flat
    return out
