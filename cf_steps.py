"""More native flow steps (all real work on the CPU): list handling, text, slideshow, boomerang, blend.

They exist to make queues richer: the agent (or a recipe) can cut a list down, merge two lists, keep only what passes a technical gate,
turn stills into a video, build a loop out of a clip, and rewrite each prompt of a list with a template.
Runners follow the capability contract: run(env, ctx, inputs, params, workdir) -> {output name: artifact}.
"""

import re
import subprocess
from pathlib import Path

MAX_LIST = 32


def art(type_, path=None, value=None):
    return dict(type=type_, path=str(path) if path else None, value=value)


def _items(inputs, name):
    got = inputs.get(name)
    return got if isinstance(got, list) else ([got] if got else [])


# ---------------------------------------------------------------- list handling
def run_take_images(env, ctx, inputs, params, workdir):
    images = _items(inputs, "images")
    if params.get("reverse"):
        images = images[::-1]
    step = max(1, int(params.get("every", 1)))
    images = images[int(params.get("skip", 0))::step][:int(params.get("count", 8))]
    if not images:
        raise ValueError("A lista ficou vazia depois de pular e cortar; use «pular» menor ou «quantas» maior.")
    return {"images": [dict(a) for a in images]}


def run_merge_images(env, ctx, inputs, params, workdir):
    merged = _items(inputs, "a") + _items(inputs, "b") + _items(inputs, "c")
    if not merged:
        raise ValueError("Ligue pelo menos uma lista de imagens.")
    if len(merged) > MAX_LIST:
        raise ValueError(f"Juntando as listas dá {len(merged)} imagens; o limite por passo é {MAX_LIST}.")
    return {"images": [dict(a) for a in merged]}


def run_keep_passing(env, ctx, inputs, params, workdir):
    import cf_refine
    names = params.get("checks") or ["not_blank", "sharp", "exposure"]
    kept, rows = [], []
    for i, item in enumerate(_items(inputs, "images")):
        verdicts = cf_refine.judge(item["path"], {}, names)
        failed = cf_refine.failures(verdicts)
        rows.append(dict(index=i, passed=not failed, failed=[v.line for v in failed]))
        if not failed:
            kept.append(dict(item))
    if not kept:
        raise ValueError(f"Nenhuma das {len(rows)} imagens passou na conferência ({', '.join(names)}). Afrouxe as conferências ou gere de novo.")
    return {"images": kept, "report": art("json", value=dict(kept=len(kept), total=len(rows), rows=rows))}


# ---------------------------------------------------------------- text
def run_text_template(env, ctx, inputs, params, workdir):
    template = str(params.get("template") or "")
    if "{text}" not in template:
        raise ValueError("O modelo precisa conter {text}, por exemplo «{text}, luz de fim de tarde».")
    text = str(inputs["text"]["value"] if inputs.get("text") else params.get("text", "")).strip()
    if not text:
        raise ValueError("Falta o texto de entrada: ligue um texto ou escreva em «text».")
    return {"text": art("text", value=template.replace("{text}", text))}


def run_text_join(env, ctx, inputs, params, workdir):
    texts = [str(a["value"]) for a in _items(inputs, "texts") if a.get("value") is not None]
    if not texts:
        raise ValueError("Ligue uma lista de textos.")
    sep = {"vírgula": ", ", "linha": "\n", "ponto e vírgula": "; "}.get(params.get("separator", "vírgula"), ", ")
    return {"text": art("text", value=sep.join(texts))}


# ---------------------------------------------------------------- media
def _ffmpeg(args, timeout=600):
    run = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", *args], capture_output=True, text=True, timeout=timeout)
    if run.returncode:
        raise ValueError(f"ffmpeg falhou: {(run.stderr or '').strip().splitlines()[-1:] or ['sem detalhe']}")


def run_slideshow(env, ctx, inputs, params, workdir):
    import cf_finish
    images = _items(inputs, "images")
    if not 1 <= len(images) <= 12:
        raise ValueError("A apresentação aceita de 1 a 12 imagens.")
    ratio = params.get("ratio", "Paisagem · 16:9")
    if ratio not in cf_finish.SEQUENCE_SIZES:
        raise ValueError(f"Formato «{ratio}» indisponível.")
    width, height = cf_finish.SEQUENCE_SIZES[ratio]
    seconds, fps = float(params.get("seconds", 2)), 24
    frames = max(2, round(seconds * fps))
    zoom = bool(params.get("zoom", True))
    fade = min(0.4, seconds / 3) if params.get("fade", True) else 0
    args, filters, tags = [], [], []
    for i, item in enumerate(images):
        args += ["-loop", "1", "-t", f"{seconds:.3f}", "-framerate", str(fps), "-i", item["path"]]
        pre = f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,crop={width * 2}:{height * 2}"
        if zoom:
            pre += f",zoompan=z='min(zoom+{0.25 / frames:.6f},1.25)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        else:
            pre += f",scale={width}:{height}"
        chain = f"[{i}:v]{pre},setsar=1,format=yuv420p"
        if fade:
            chain += f",fade=t=in:st=0:d={fade:.3f},fade=t=out:st={seconds - fade:.3f}:d={fade:.3f}"
        filters.append(f"{chain}[v{i}]")
        tags.append(f"[v{i}]")
    filters.append(f"{''.join(tags)}concat=n={len(images)}:v=1:a=0[video]")
    target = Path(workdir) / "apresentacao.mp4"
    _ffmpeg([*args, "-filter_complex", ";".join(filters), "-map", "[video]", "-r", str(fps), "-c:v", "libx264", "-threads", "2", "-preset", "veryfast",
             "-movflags", "+faststart", str(target)])
    return {"video": art("video", target, f"{len(images)} imagens · {seconds:g} s cada · {width} × {height}")}


def run_video_fx(env, ctx, inputs, params, workdir):
    import cf_finish
    source = inputs["video"]["path"]
    op = params.get("op", "boomerang")
    target = Path(workdir) / f"{op}.mp4"
    cf_finish.video_duration(source)
    tail = ["-an", "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)]
    if op == "boomerang":
        graph = "[0:v]split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0[v]"
    elif op == "reverse":
        graph = "[0:v]reverse[v]"
    elif op == "speed":
        factor = float(params.get("factor", 2))
        graph = f"[0:v]setpts=PTS/{factor:g}[v]"
    else:
        raise ValueError("Escolha boomerang, reverse ou speed.")
    if cf_finish.video_duration(source) > 30 and op in ("boomerang", "reverse"):
        raise ValueError("Boomerang e reverso carregam o clipe na memória; use um clipe de até 30 s.")
    _ffmpeg(["-i", source, "-filter_complex", graph, "-map", "[v]", *tail])
    return {"video": art("video", target, op)}


def run_blend(env, ctx, inputs, params, workdir):
    from PIL import Image, ImageOps
    with Image.open(inputs["a"]["path"]) as a, Image.open(inputs["b"]["path"]) as b:
        left = ImageOps.exif_transpose(a).convert("RGB")
        right = ImageOps.exif_transpose(b).convert("RGB").resize(left.size)
    mix = float(params.get("mix", 50)) / 100
    out = Image.blend(left, right, mix)
    target = Path(workdir) / "mistura.png"
    out.save(target)
    return {"image": art("image", target, f"{round(mix * 100)}% da segunda")}


def run_sweep(env, ctx, inputs, params, workdir):
    """A list of numbers from start to stop (count values): bind it to a number parameter with `each` to sweep that parameter, or to `seed` for N variations."""
    start, stop, count = float(params.get("start", 0)), float(params.get("stop", 100)), int(params.get("count", 5))
    if not 1 <= count <= MAX_LIST:
        raise ValueError(f"«count» deve ficar entre 1 e {MAX_LIST}.")
    steps = [start + (stop - start) * i / max(1, count - 1) for i in range(count)]
    if params.get("integer"):
        steps = [round(v) for v in steps]
        if len(set(steps)) != len(steps):
            raise ValueError("Com números inteiros, alguns valores se repetiriam; diminua «count» ou alargue o intervalo.")
    return {"values": [art("text", value=f"{v:g}" if not params.get("integer") else str(v)) for v in steps]}


def run_first_of(env, ctx, inputs, params, workdir):
    """Joins the branches of an if/else: the first input that exists (the other branches were skipped)."""
    for name in ("a", "b", "c"):
        got = inputs.get(name)
        if got is not None and not (isinstance(got, list) and not got):
            return {"image": dict(got[0] if isinstance(got, list) else got)}
    raise ValueError("Nenhum dos ramos produziu uma imagem; confira as condições dos passos ligados a «a», «b» e «c».")
