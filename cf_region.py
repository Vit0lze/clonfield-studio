"""Prepare and composite a mask-guided local edit with Pillow."""

from PIL import Image, ImageChops, ImageFilter, ImageOps

SIZES = (512, 768, 1024)


def prepare(source_path, mask_path, size, padding):
    if not source_path or not mask_path:
        raise ValueError("Envie a imagem e a máscara.")
    if size not in SIZES or not 0 <= padding <= 256:
        raise ValueError("Escolha uma resolução e uma margem válidas.")
    with Image.open(source_path) as image:
        source = ImageOps.exif_transpose(image).convert("RGB")
    with Image.open(mask_path) as image:
        mask = ImageOps.exif_transpose(image).convert("L")
    if source.size != mask.size:
        raise ValueError("A máscara deve ter as mesmas dimensões da imagem.")
    box = mask.getbbox()
    if not box:
        raise ValueError("Marque a região com branco. A máscara está vazia.")
    left, top, right, bottom = box
    bounds = (max(0, left - padding), max(0, top - padding),
              min(source.width, right + padding), min(source.height, bottom + padding))
    crop = source.crop(bounds)
    scale = size / max(crop.size)
    target = tuple(max(128, round(edge * scale / 32) * 32) for edge in crop.size)
    reference = crop.resize(target, Image.Resampling.LANCZOS)
    return source, mask, bounds, reference


def composite(source, mask, bounds, edit, feather):
    if not 0 <= feather <= 64:
        raise ValueError("Escolha uma suavização entre 0 e 64 pixels.")
    # Blur across the full canvas so edges at the crop boundary get consistent weights.
    if feather:
        mask = ImageChops.multiply(mask.point(lambda value: 255 if value else 0),
                                   mask.filter(ImageFilter.GaussianBlur(feather)))
    original_crop = source.crop(bounds)
    edit = edit.convert("RGB").resize(original_crop.size, Image.Resampling.LANCZOS)
    result = source.copy()
    result.paste(Image.composite(edit, original_crop, mask.crop(bounds)), bounds[:2])
    return result
