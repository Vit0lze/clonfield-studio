"""Qwen Image 2.1 edit modes built on the author-published recipes of three LoRAs: Outpaint (expand any side), Restore, Outfit swap.

Recipes (read from the real Civitai pages and Hugging Face cards, see docs/BACKLOG_CAPACIDADES_APPS.md):
  * Outpaint v2 (ausboss, "other" licence, ~160 MB): pad the picture with flat gray #808080, each side a multiple of 32, about 1-2 MP;
    give the canvas as the reference; prompt = the trigger instruction first, word for word, then optionally `Scene: ...`;
    25 steps, CFG 1, euler / simple, LoRA 1.0; afterwards paste the ORIGINAL pixels back over the result (the LoRA keeps the picture in
    place, but the stitch makes it exact). Do not pin the known area with a latent noise mask.
  * Restore (no trigger): enlarge to ~2 MP, picture as image 1, ask the restore instruction; LoRA 1.0, or 0.5 for a blurry / shaky one.
  * Outfit swap (no trigger): person = image 1, outfit = image 2; LoRA 1.0; ask for the swap and to keep face, hair, hands, pose, background.

The padding, stitching and prompt building are pure CPU code and are tested with real images. Running the LoRA needs the T4:
the generation itself is BLOQUEADO_GPU.
"""

from PIL import Image, ImageFilter, ImageOps

GRAY = (128, 128, 128)
MAX_PIXELS = 2_000_000
MIN_SIDE, MAX_SIDE = 256, 2048
ALIGN = 32

OUTPAINT_TRIGGER = "Outpaint the image: replace the solid gray areas with a seamless continuation of the scene, keeping the existing picture unchanged."
RESTORE_PROMPTS = {
    "Foto digital (desfoque, ruído, compressão)": "Restore the photo: remove blur, noise and compression artifacts and recover sharp, natural detail, keeping the same composition, people and colors.",
    "Foto antiga (riscos, poeira, desbotada)": "Restore the old photo: remove scratches, dust, fading and grain and recover sharp, natural detail and color, keeping the same composition and people.",
}
OUTFIT_KEEP = "Keep their face, hair, hands, pose and the background exactly the same."

# catalog LoRA files (Hugging Face, pinned in cf_loras.CATALOGO)
LORAS = {"outpaint": "qwen-image-2.1-outpaint-v2.safetensors", "restore": "qwen-image-2.1-restore.safetensors", "outfit": "qwen-image-2.1-outfit-swap.safetensors"}


def snap(value, up=True):
    return int(-(-value // ALIGN) * ALIGN) if up else int(value // ALIGN * ALIGN)


def outpaint_plan(size, left=0, top=0, right=0, bottom=0, max_pixels=MAX_PIXELS):
    """Where the source goes on a gray canvas whose sides are multiples of 32 and whose area is <= max_pixels.
    Returns dict(canvas=(w, h), box=(x0, y0, x1, y1), scale). Raises ValueError with the reason when it cannot be done."""
    w, h = size
    pads = [int(v) for v in (left, top, right, bottom)]
    if any(v < 0 for v in pads) or not any(pads):
        raise ValueError("Escolha pelo menos um lado para expandir (valores de 0 para cima).")
    scale = 1.0
    for _ in range(40):  # shrink the source until the whole canvas fits the budget
        sw, sh = max(8, round(w * scale)), max(8, round(h * scale))
        cw, ch = snap(sw + round(pads[0] * scale) + round(pads[2] * scale)), snap(sh + round(pads[1] * scale) + round(pads[3] * scale))
        if cw * ch <= max_pixels and cw <= MAX_SIDE and ch <= MAX_SIDE:
            break
        scale *= 0.92
    else:
        raise ValueError("A expansão pedida não cabe em 2 megapixels nem reduzindo a imagem. Peça menos pixels de expansão.")
    if sw < 128 or sh < 128:
        raise ValueError("Com essa expansão a imagem original ficaria pequena demais no canvas (menos de 128 px). Expanda menos.")
    if cw < MIN_SIDE or ch < MIN_SIDE:
        raise ValueError(f"O canvas ficaria menor que {MIN_SIDE} px; expanda mais ou use uma imagem maior.")
    # distribute the extra space created by snapping to the sides that were asked to grow (so an unasked side stays flush)
    left_px, top_px = round(pads[0] * scale), round(pads[1] * scale)
    extra_w, extra_h = cw - (sw + left_px + round(pads[2] * scale)), ch - (sh + top_px + round(pads[3] * scale))
    grow_x = [i for i in (0, 2) if pads[i]] or [0, 2]
    grow_y = [i for i in (1, 3) if pads[i]] or [1, 3]
    if grow_x[0] == 0:
        left_px += extra_w if len(grow_x) == 1 else extra_w // 2
    if grow_y[0] == 1:
        top_px += extra_h if len(grow_y) == 1 else extra_h // 2
    box = (left_px, top_px, left_px + sw, top_px + sh)
    if box[2] > cw or box[3] > ch or min(box) < 0:
        raise ValueError("Não consegui posicionar a imagem no canvas; ajuste a expansão.")
    return dict(canvas=(cw, ch), box=box, scale=round(scale, 6), source=(w, h))


def pad_canvas(image, plan):
    """-> (canvas RGB with the (scaled) source pasted on flat gray, mask L with 255 where the source is)."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    x0, y0, x1, y1 = plan["box"]
    canvas = Image.new("RGB", plan["canvas"], GRAY)
    canvas.paste(image.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS), (x0, y0))
    mask = Image.new("L", plan["canvas"], 0)
    mask.paste(255, (x0, y0, x1, y1))
    return canvas, mask


def stitch(original, generated, plan, feather=2):
    """Paste the original pixels back over the generated canvas. With feather=0 the whole kept box is the source, byte for byte; with
    feather=N the outer N px of the seam fade into the generation (no visible step) and the rest of the box stays exact."""
    x0, y0, x1, y1 = plan["box"]
    result = ImageOps.exif_transpose(generated).convert("RGB")
    if result.size != tuple(plan["canvas"]):
        result = result.resize(plan["canvas"], Image.Resampling.LANCZOS)
    kept = ImageOps.exif_transpose(original).convert("RGB").resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
    inner = int(feather) if feather and (x1 - x0) > 2 * int(feather) + 2 and (y1 - y0) > 2 * int(feather) + 2 else 0
    mask = Image.new("L", plan["canvas"], 0)
    if inner:
        core = (x0 + inner, y0 + inner, x1 - inner, y1 - inner)
        mask.paste(255, core)
        mask = mask.filter(ImageFilter.GaussianBlur(inner / 3))
        mask.paste(255, core)
    else:
        mask.paste(255, (x0, y0, x1, y1))
    layer = Image.new("RGB", plan["canvas"])
    layer.paste(kept, (x0, y0))
    return Image.composite(layer, result, mask)


def outpaint_prompt(scene=""):
    scene = (scene or "").strip()
    return OUTPAINT_TRIGGER + (f"\n\nScene: {scene}" if scene else "")


def restore_prompt(kind):
    if kind not in RESTORE_PROMPTS:
        raise ValueError("Escolha o tipo de restauração.")
    return RESTORE_PROMPTS[kind]


def restore_strength(blurry):
    return 0.5 if blurry else 1.0


def restore_resize(image, max_pixels=MAX_PIXELS):
    """Enlarge (or fit) the picture to about 2 MP with sides that are multiples of 32, as the author recommends."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    scale = (max_pixels / (image.width * image.height)) ** 0.5
    w, h = max(MIN_SIDE, snap(image.width * scale, up=False)), max(MIN_SIDE, snap(image.height * scale, up=False))
    while w * h > max_pixels and (w > MIN_SIDE or h > MIN_SIDE):
        w, h = (w - ALIGN, h) if w >= h and w > MIN_SIDE else (w, h - ALIGN)
    return image.resize((w, h), Image.Resampling.LANCZOS)


def outfit_prompt(outfit):
    outfit = (outfit or "").strip()
    if not outfit:
        raise ValueError("Descreva a roupa em poucas palavras (ex.: casaco de couro preto).")
    return f"Dress the person in image 1 in the {outfit} shown in image 2. {OUTFIT_KEEP}"
