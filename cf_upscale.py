"""Fast upscalers that do not need the ComfyUI worker (Lanczos and Real-ESRGAN through spandrel)."""

import os
from pathlib import Path

from PIL import Image, ImageFilter

import cf_download as download

MODELS = {
    "RealESRGAN_x4plus (fotografia)": ("RealESRGAN_x4plus.pth", "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"),
    "RealESRGAN anime 6B (desenho)": ("RealESRGAN_x4plus_anime_6B.pth", "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth"),
}


def load(name, base, progress=None):
    from spandrel import ImageModelDescriptor, ModelLoader

    filename, url = MODELS[name]
    weight = Path(base) / "upscalers" / filename
    if not weight.is_file():
        download.fetch(url, weight, progress=progress, label=filename)
    model = ModelLoader().load_from_file(str(weight))
    if not isinstance(model, ImageModelDescriptor):
        raise ValueError("O arquivo não é um upscaler de imagem suportado.")
    return model


def run_model(im, name, scale, tile, pad, device, base, progress=None):
    import numpy as np
    import torch

    model = load(name, base, progress).to(device).eval()
    try:
        native = int(model.scale)
        w, h = im.size
        rgb = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
        result = Image.new("RGB", (w * native, h * native))
        steps = ((h + tile - 1) // tile) * ((w + tile - 1) // tile)
        done = 0
        with torch.inference_mode():
            for y in range(0, h, tile):
                for x in range(0, w, tile):
                    x2, y2 = min(x + tile, w), min(y + tile, h)
                    left, top, right, bottom = max(0, x - pad), max(0, y - pad), min(w, x2 + pad), min(h, y2 + pad)
                    t = torch.from_numpy(np.ascontiguousarray(rgb[top:bottom, left:right])).permute(2, 0, 1).unsqueeze(0).to(device)
                    out = model(t).clamp(0, 1)[0].permute(1, 2, 0).cpu().numpy()
                    patch = Image.fromarray((out * 255.0 + 0.5).astype(np.uint8), "RGB")
                    patch = patch.crop(((x - left) * native, (y - top) * native, (x2 - left) * native, (y2 - top) * native))
                    result.paste(patch, (x * native, y * native))
                    done += 1
                    if progress:
                        progress(0.2 + 0.7 * done / steps, desc=f"Real-ESRGAN · bloco {done}/{steps}")
        size = (round(w * scale), round(h * scale))
        if result.size != size:
            result = result.resize(size, Image.Resampling.LANCZOS)
        if "A" in im.getbands():
            result.putalpha(im.getchannel("A").resize(size, Image.Resampling.LANCZOS))
        return result
    finally:
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def process(im, mode, scale, tile, pad, device, sharpen, base, progress=None):
    if mode == "Nenhum":
        out = im.copy()
    elif mode.startswith("Lanczos"):
        out = im.resize((round(im.width * scale), round(im.height * scale)), Image.Resampling.LANCZOS)
    else:
        out = run_model(im, mode, scale, tile, pad, device, base, progress)
    if sharpen > 0:
        alpha = out.getchannel("A") if "A" in out.getbands() else None
        out = out.convert("RGB").filter(ImageFilter.UnsharpMask(radius=1.2, percent=int(sharpen), threshold=3))
        if alpha is not None:
            out.putalpha(alpha)
    return out
