"""Fast upscalers that do not need the ComfyUI worker (Lanczos and Real-ESRGAN through spandrel)."""

import os
from pathlib import Path

from PIL import Image, ImageFilter

import cf_download as download

GH = "https://github.com/xinntao/Real-ESRGAN/releases/download/"
HF = "https://huggingface.co/{repo}/resolve/{rev}/{file}"
# name -> file, url, sha256 (None = published without one), licence of the weights, one-line use. The licence of the CODE
# of an upscaler is not the licence of its WEIGHTS: NC means non-commercial use only.
MODELS = {
    "RealESRGAN_x4plus (fotografia)": dict(mb=64, file="RealESRGAN_x4plus.pth", url=GH + "v0.1.0/RealESRGAN_x4plus.pth", sha256=None, license="BSD-3-Clause", use="foto, fiel e limpo"),
    "RealESRGAN anime 6B (desenho)": dict(mb=17, file="RealESRGAN_x4plus_anime_6B.pth", url=GH + "v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth", sha256=None, license="BSD-3-Clause", use="anime e ilustração"),
    "Real-ESRGAN geral v3 (leve)": dict(mb=5, file="realesr-general-x4v3.pth", url=GH + "v0.2.5.0/realesr-general-x4v3.pth", sha256=None, license="BSD-3-Clause", use="rápido, só 5 MB, bom para CPU"),
    "4x NMKD-Siax (detalhe fino)": dict(mb=67, file="4x_NMKD-Siax_200k.pth", sha256="560424d9f68625713fc47e9e7289a98aabe1d744e1cd6a9ae5a35e9957fd127e", license="MIT",
                                         url=HF.format(repo="uwg/upscaler", rev="f6bace545e358eab5491f8f39b90a2dd42e8cc77", file="ESRGAN/4x_NMKD-Siax_200k.pth"), use="textura e detalhe, fotos"),
    "4x Remacri (foto suave)": dict(mb=67, file="4x_foolhardy_Remacri.pth", sha256="e1a73bd89c2da1ae494774746398689048b5a892bd9653e146713f9df8bca86a", license="não informada",
                                     url=HF.format(repo="FacehugmanIII/4x_foolhardy_Remacri", rev="cc321d560d74ac924feac463373b8fc4f59fee31", file="4x_foolhardy_Remacri.pth"), use="fotos, menos artefato"),
    "4x UltraSharp (nitidez)": dict(mb=67, file="4x-UltraSharp.pth", sha256="a5812231fc936b42af08a5edba784195495d303d5b3248c24489ef0c4021fe01", license="não informada (original CC BY-NC-SA)",
                                     url=HF.format(repo="lokCX/4x-Ultrasharp", rev="1856559b50de25116a7c07261177dd128f1f5664", file="4x-UltraSharp.pth"), use="bordas bem nítidas"),
    "UltraSharp V2 (140 MB)": dict(mb=140, file="4x-UltraSharpV2.safetensors", sha256="2b5db674aa8f3864a696dccd1d07d7cc0500fbf220f35044cd30eee9a7f971a7", license="CC BY-NC-SA 4.0 (uso não comercial)",
                                    url=HF.format(repo="Kim2091/UltraSharpV2", rev="2d1db39ff692c111da92112d49f833e4ad7035ae", file="4x-UltraSharpV2.safetensors"), use="a versão mais recente, mais pesada"),
    "OmniSR x2 (ultraleve)": dict(mb=2, file="OmniSR_X2_DIV2K.safetensors", sha256="79408fc23203bf161faa957c4a602cc40521ed2235a72d976bd9d375e6644611", license="Apache-2.0",
                                   url=HF.format(repo="Acly/Omni-SR", rev="b28a7caa0baba8669de3e49687e76e12448ea020", file="OmniSR_X2_DIV2K.safetensors"), use="2× em 1,6 MB, muito rápido"),
    "OmniSR x4 (ultraleve)": dict(mb=2, file="OmniSR_X4_DIV2K.safetensors", sha256="dff25e4ed392cb5cbe534d920e292063a0555df9281c54c5ec321490a2a59832", license="Apache-2.0",
                                   url=HF.format(repo="Acly/Omni-SR", rev="b28a7caa0baba8669de3e49687e76e12448ea020", file="OmniSR_X4_DIV2K.safetensors"), use="4× em 1,7 MB, muito rápido"),
}


def short(name):
    return name.split(" (")[0]


def sha256_of(path):
    import hashlib
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load(name, base, progress=None):
    from spandrel import ImageModelDescriptor, ModelLoader

    spec = MODELS[name]
    weight = Path(base) / "upscalers" / spec["file"]
    if not weight.is_file():
        download.fetch(spec["url"], weight, progress=progress, label=spec["file"])
        if spec["sha256"] and sha256_of(weight) != spec["sha256"]:
            weight.unlink(missing_ok=True)
            raise ValueError(f"O arquivo de {short(name)} não confere com o SHA-256 publicado; download recusado.")
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


def status(base):
    """Every built-in upscaler with whether its weights are already on disk."""
    return [dict(name=name, short=short(name), mb=spec["mb"], license=spec["license"], use=spec["use"],
                 installed=(Path(base) / "upscalers" / spec["file"]).is_file(), source=spec["url"].split("/")[2]) for name, spec in MODELS.items()]
