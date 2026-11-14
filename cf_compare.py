"""Compare image models on ONE brief: the same prompt and size run through each model, timed, then laid side by side with the numbers.

What it measures (honest by construction):
  * `cold_seconds`: the first run of a model, weights loading included.
  * `warm_seconds`: a second run with a fresh seed right after, weights already resident (a fresh seed so ComfyUI's cache cannot answer).
  * `seconds_per_step`: warm (else cold) divided by the number of denoising steps. Distilled recipes (a fixed sigma schedule) use that
    schedule's length, not the form's step count.
  * `vram_gb`: the device's used memory right after the run, from ComfyUI's /system_stats (it includes whatever else is resident).
The numbers come from the machine that runs it; nothing here estimates them. Seeds do not transfer between models, so each model keeps its own.
The sheet and the table are CPU-only code and are tested with real images.
"""

import json
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

MIN_MODELS, MAX_MODELS = 2, 3
CELL_HEIGHT = 512
CAPTION_LINES = 3
GAP = 16
FONT_PATHS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf")


def steps_of(preset, requested=0):
    """Denoising steps a recipe really runs: the sigma schedule's length for distilled models, else the requested or default count."""
    if getattr(preset, "sigmas", ()):
        return len(preset.sigmas) - 1
    return int(requested or preset.steps)


def pick_models(*keys, valid):
    """Distinct model keys in the order given, ignoring empty / 'none' entries. Raises ValueError with the reason."""
    chosen = []
    for key in keys:
        if not key or key == "none":
            continue
        if key not in valid:
            raise ValueError(f"Modelo desconhecido: {key}.")
        if key in chosen:
            raise ValueError("Escolha modelos diferentes: o mesmo modelo duas vezes não compara nada.")
        chosen.append(key)
    if not MIN_MODELS <= len(chosen) <= MAX_MODELS:
        raise ValueError(f"Escolha de {MIN_MODELS} a {MAX_MODELS} modelos para comparar.")
    return chosen


def measure(cold, warm, steps):
    """Timing record from the cold run and the (optional) warm run. `basis` says which one the per-step figure comes from."""
    basis, seconds = ("quente", warm) if warm else ("frio (inclui carregar os pesos)", cold)
    return dict(cold_seconds=round(cold, 1), warm_seconds=round(warm, 1) if warm else None, steps=steps,
                seconds_per_step=round(seconds / steps, 2) if steps else None, basis=basis)


def caption(item):
    """Three short lines under each picture."""
    timing = item["timing"]
    per_step = f"{timing['seconds_per_step']:g} s/passo ({timing['basis'].split(' ')[0]})" if timing["seconds_per_step"] is not None else "—"
    total = f"{timing['warm_seconds'] if timing['warm_seconds'] else timing['cold_seconds']:g} s"
    vram = f" · {item['vram_gb']:g} GB VRAM" if item.get("vram_gb") else ""
    return [item["title"], f"{timing['steps']} passos · CFG {item['cfg']:g} · {item['size'][0]}×{item['size'][1]}", f"{total} · {per_step}{vram}"]


def _font(size):
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def sheet(items, prompt=""):
    """Side-by-side contact sheet. `items`: [{image: path, title, cfg, size, timing, vram_gb}]. Returns an RGB image."""
    if not items:
        raise ValueError("Nada para comparar.")
    cells = []
    for item in items:
        with Image.open(item["image"]) as opened:
            picture = ImageOps.exif_transpose(opened).convert("RGB")
        scale = CELL_HEIGHT / picture.height
        cells.append(picture.resize((max(64, round(picture.width * scale)), CELL_HEIGHT), Image.Resampling.LANCZOS))
    body, small = _font(20), _font(16)
    width = sum(cell.width for cell in cells) + GAP * (len(cells) + 1)
    header = 44 if prompt else GAP
    caption_h = CAPTION_LINES * 26 + GAP
    canvas = Image.new("RGB", (width, header + CELL_HEIGHT + caption_h + GAP), (24, 24, 27))
    draw = ImageDraw.Draw(canvas)
    if prompt:
        text = " ".join(prompt.split())
        while text and draw.textlength(text, font=small) > width - 2 * GAP:
            text = text[:-2]
        draw.text((GAP, 12), text + ("…" if text != " ".join(prompt.split()) else ""), fill=(190, 190, 196), font=small)
    x = GAP
    for item, cell in zip(items, cells):
        canvas.paste(cell, (x, header))
        for line, text in enumerate(caption(item)):
            font = body if line == 0 else small
            while text and draw.textlength(text, font=font) > cell.width:
                text = text[:-2]
            draw.text((x, header + CELL_HEIGHT + 8 + line * 26), text, fill=(236, 236, 240) if line == 0 else (170, 170, 178), font=font)
        x += cell.width + GAP
    return canvas


def record(items, prompt, gpu, vram_gb):
    return dict(time=int(time.time()), gpu=gpu, vram_gb=vram_gb, prompt=prompt,
                models=[dict(model=i["model"], title=i["title"], seed=i["seed"], cfg=i["cfg"], size=list(i["size"]), vram_gb=i.get("vram_gb"), **i["timing"]) for i in items])


def append_history(path, entry, keep=20):
    path = Path(path)
    try:
        history = json.loads(path.read_text())
    except (OSError, ValueError):
        history = []
    path.write_text(json.dumps((history + [entry])[-keep:], ensure_ascii=False, indent=1))
    return path


def summary_line(items):
    """One line for the job message: 'Qwen 2.1: 2.8 s/passo · Qwen 2.1 Turbo: 2.9 s/passo'."""
    return " · ".join(f"{i['title']}: " + (f"{i['timing']['seconds_per_step']:g} s/passo" if i["timing"]["seconds_per_step"] is not None else "—") for i in items)


def faster(items):
    """(title of the quickest by total seconds, ratio against the slowest) or None."""
    totals = [(i["timing"]["warm_seconds"] or i["timing"]["cold_seconds"], i["title"]) for i in items]
    if len(totals) < 2:
        return None
    totals.sort()
    return totals[0][1], round(totals[-1][0] / totals[0][0], 1) if totals[0][0] else None
