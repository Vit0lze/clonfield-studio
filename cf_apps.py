"""App registry for the Studio API: field schemas that adapt to the GPU tier, plus the runners behind them."""

import os
import random
import shutil
import time
from functools import partial
from pathlib import Path

from PIL import Image, ImageOps

import cf_download as download
import cf_factory as factory_pipeline
import cf_finish as finish
import cf_jobs
import cf_civitai
import cf_loras
import cf_model_lab as lab
import cf_openjutsu as openjutsu
import cf_refine as refine
import cf_registry as registry_mod
import dataclasses
import cf_region as region
import cf_seedvr2 as seedvr2
import cf_seethrough as seethrough
import cf_upscale as upscale
import cf_wan as wan
import cf_workflows as workflows
from cf_jobs import JobError

ENV = {"base": Path(os.environ.get("CLONFIELD_DIR", "/content/ClonField_Lab")), "out": None, "civitai": None}


def configure(base, out_dir):
    ENV.update(base=Path(base), out=Path(out_dir), civitai=Path(base) / "civitai" / "lab")
    factory_pipeline.configure(base)


# name -> (label, where it is used, group). Order is the order of the dropdown.
ASPECT_INFO = {
    "auto": ("Auto", "Segue a 1ª referência", "Automático"),
    "1:1": ("Quadrado · 1:1", "Post, avatar, capa de álbum", "Redes sociais"),
    "4:5": ("Retrato · 4:5", "Post de feed (Instagram)", "Redes sociais"),
    "9:16": ("Vertical · 9:16", "Stories, Reels, TikTok, Shorts", "Redes sociais"),
    "1.91:1": ("Link · 1.91:1", "Prévia de link e anúncios", "Redes sociais"),
    "3:1": ("Banner · 3:1", "Capa do X e do LinkedIn", "Redes sociais"),
    "16:9": ("Paisagem · 16:9", "YouTube, TV, apresentação", "Vídeo e tela"),
    "21:9": ("Cinema · 21:9", "Ultrawide, cena de filme", "Vídeo e tela"),
    "4:3": ("Clássico · 4:3", "Slides e telas antigas", "Vídeo e tela"),
    "3:2": ("Foto · 3:2", "Câmera DSLR, impressão 10×15", "Foto e impressão"),
    "2:3": ("Pôster · 2:3", "Pinterest, pôster, capa de livro", "Foto e impressão"),
    "3:4": ("Retrato clássico · 3:4", "Retrato impresso", "Foto e impressão"),
}
RATIOS = {"auto": (0, 0), "1.91:1": (191, 100)}
ASPECTS = [(name, *(RATIOS.get(name) or tuple(int(x) for x in name.split(":")))) for name in ASPECT_INFO]
SIZE_USES = {(16, 9): "YouTube, TV, apresentação", (9, 16): "Stories, Reels, TikTok, Shorts", (1, 1): "Post, avatar",
             (4, 5): "Post de feed (Instagram)"}
QUALITIES = [("draft", "Rascunho", 512), ("standard", "Padrão", None), ("high", "Alta", None)]

# Qualitative guidance only: sizes of these checkpoints are not published in the presets.
MODEL_INFO = {
    "qwen21": dict(name="Qwen Image 2.1", tagline="Edição fiel e texto legível em imagem", weight="pesado", min_vram=24, speed=2, quality=5,
                   page="https://huggingface.co/Qwen/Qwen-Image-2.1"),
    "flux2": dict(name="FLUX.2 Klein 4B", tagline="Rápido, destilado, ótimo para iterar", weight="leve", min_vram=8, speed=5, quality=3,
                  page="https://huggingface.co/Comfy-Org/Flux-2-Klein-4B"),
    "flux3": dict(name="FLUX.3 Klein", tagline="Klein de nova geração com expansor de prompt", weight="leve", min_vram=10, speed=4, quality=4,
                  page="https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy"),
    "krea2": dict(name="Krea 2", tagline="Estética autoral, base para estilos", weight="médio", min_vram=16, speed=3, quality=4,
                  page="https://huggingface.co/Comfy-Org/Krea-2"),
    "krea2-turbo": dict(name="Krea 2 Turbo", tagline="Krea 2 em poucos passos", weight="médio", min_vram=16, speed=4, quality=4,
                        page="https://huggingface.co/Comfy-Org/Krea-2"),
    "z-image": dict(name="Z-Image", tagline="Realismo limpo, ótima aderência ao prompt", weight="médio", min_vram=12, speed=3, quality=4,
                    page="https://huggingface.co/Comfy-Org/Z-Image"),
    "z-image-turbo": dict(name="Z-Image Turbo", tagline="Z-Image em 8 passos", weight="médio", min_vram=12, speed=5, quality=4,
                          page="https://huggingface.co/Comfy-Org/Z-Image-Turbo"),
}
IMAGE_MODELS = [key for key in MODEL_INFO if key in lab.PRESETS]


def model_card(key, tier=None, sizes=None):
    preset, info = lab.PRESETS[key], MODEL_INFO[key]
    root = lab.models_root()
    files = []
    for role, (repo, filename, *_rest) in preset.files.items():
        target = root / Path(filename).parts[-2] / Path(filename).name
        files.append({"role": role, "name": Path(filename).name, "repo": repo,
                      "installed": target.is_file() and target.stat().st_size > 0,
                      "size": (sizes or {}).get(f"{repo}/{filename}")})
    card = {"key": key, "title": info["name"], "subtitle": preset.title, "refs": preset.refs,
            "steps": preset.steps, "cfg": preset.cfg, "files": files, "installed": all(f["installed"] for f in files),
            "download_bytes": sum(f["size"] or 0 for f in files if not f["installed"]) or None,
            "size_known": all(f["size"] for f in files),
            "family": key, **info}
    if tier is not None:
        card["fits"] = tier.vram_gb >= info["min_vram"]
        card["advice"] = ("" if card["fits"] else
                          f"Recomendado ≥ {info['min_vram']} GB de VRAM; na sua placa ({tier.vram_gb:.0f} GB) usa offload e fica mais lento.")
    return card


FINAL_SIDES = {"veryhigh": 2048, "ultra": 4096}  # final file long side; generated natively only up to the tier limit


def long_side(quality, tier):
    """Long side of the *generated* image. Final sizes above the tier limit are reached by upscaling (resolution_plan)."""
    return {"draft": 512, "standard": tier.default_side}.get(quality, tier.max_side)


def reference_ratio(files):
    """Width/height of the first reference, so "auto" keeps the framing of the photo being edited."""
    for path in files or []:
        try:
            with Image.open(path) as image:
                return image.size
        except (OSError, ValueError):
            continue
    return None


def dimensions(aspect, quality, tier, files=None):
    ratio = next(((a, b) for name, a, b in ASPECTS if name == aspect), (1, 1))
    if aspect == "auto":
        ratio = reference_ratio(files) or (1, 1)
        low, high = 9 / 21, 21 / 9
        value = min(high, max(low, ratio[0] / ratio[1]))
        ratio = (value, 1)
    side = long_side(quality, tier)
    big, small = (side, side * min(ratio) / max(ratio))
    w, h = (big, small) if ratio[0] >= ratio[1] else (small, big)
    snap = lambda v: int(min(2048, max(256, round(v / 32) * 32)))
    return snap(w), snap(h)


def resolution_plan(aspect, quality, tier, files=None, gen_factor=1.0):
    """Native generation size, final delivered size and the upscale between them. Quality names the FINAL file."""
    native = dimensions(aspect, quality, tier, files)
    if gen_factor < 1 and quality in ("standard", "high"):  # "Rápido" generates smaller; final size is kept by upscaling
        native = tuple(int(max(256, round(v * gen_factor / 32) * 32)) for v in native)
        final_long = max(dimensions(aspect, quality, tier, files))
        if max(native) < final_long:
            factor = final_long / max(native)
            final = dimensions(aspect, quality, tier, files)
            return dict(native=native, final=final, scale=round(factor, 4),
                        text=f"Geração {native[0]}×{native[1]} → ampliação {factor:g}× → saída {final[0]}×{final[1]}")
    final_long = FINAL_SIDES.get(quality)
    native_long = max(native)
    if not final_long or final_long <= native_long:
        return dict(native=native, final=native, scale=1.0,
                    text=f"Geração {native[0]}×{native[1]} · sem ampliação")
    factor = final_long / native_long
    final = tuple(int(round(v * factor / 2) * 2) for v in native)
    return dict(native=native, final=final, scale=round(factor, 4),
                text=f"Geração {native[0]}×{native[1]} → ampliação {factor:g}× → saída {final[0]}×{final[1]}")


UPSCALE_METHODS = ["Auto (recomendado)", *upscale.MODELS, "Clássico (Lanczos)"]


def reach_final_size(ctx, outputs, plan, method):
    """Tiled upscale from the native result to the exact final size. Never calls a 4096 px file 'native 4K'."""
    if plan["scale"] <= 1:
        return outputs
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        device = "cpu"
    chosen = method or UPSCALE_METHODS[0]
    note = ""
    if chosen.startswith("Auto"):
        chosen = "RealESRGAN_x4plus (fotografia)" if (device == "cuda" or plan["scale"] <= 2) else "Clássico (Lanczos)"
        if chosen.startswith("Clássico"):
            note = " (sem GPU: ampliação clássica em vez de Real-ESRGAN)"
    mode = "Lanczos (rápido, sem IA)" if chosen.startswith("Clássico") else chosen
    finals = []
    for index, path in enumerate(outputs):
        ctx.check()
        ctx.progress(0.9, desc=f"Ampliando {index + 1}/{len(outputs)} · {plan['text']}")
        with Image.open(path) as image:
            result = upscale.process(image.convert("RGB"), mode, plan["scale"], 128, 16, device, 0, ENV["base"], ctx.progress)
        if result.size != tuple(plan["final"]):
            result = result.resize(tuple(plan["final"]), Image.Resampling.LANCZOS)
        final = path.with_name(path.stem + f"_{plan['final'][0]}x{plan['final'][1]}.png")
        result.save(final)
        finals.append(final)
    ctx.job.update(message=f"{plan['text']} · {chosen}{note}")
    return finals


def opt(value, label, hint="", disabled=False, reason=""):
    return {"value": value, "label": label, "hint": hint, "disabled": disabled, "reason": reason}


def quality_options(tier):
    return [opt("draft", "Rascunho", "512 px · rápido"),
            opt("standard", "Padrão", f"{tier.default_side} px"),
            opt("high", "Alta", f"{tier.max_side} px", tier.max_side == tier.default_side,
                "Sua placa já roda no limite no modo Padrão."),
            opt("veryhigh", "Muito alta", "2048 px · gera até " + str(tier.max_side) + " e amplia"),
            opt("ultra", "Ultra", "4096 px · gera até " + str(tier.max_side) + " e amplia em blocos")]


def image_fields(tier, refs_required=0, prompt_default="", prompt_label="Descreva a imagem", refs_label="Referências"):
    models = [opt(k, MODEL_INFO[k]["name"], MODEL_INFO[k]["tagline"]) for k in IMAGE_MODELS]
    default_model = "flux2" if tier.vram_gb < 16 else "qwen21"
    return [
        dict(id="prompt", section="Pedido", type="textarea", label=prompt_label, default=prompt_default, required=True, rows=4),
        dict(id="refs", section="Pedido", type="files", label=refs_label, accept="image", max=16, min=refs_required,
             help="A ordem importa: a primeira imagem é a principal."),
        dict(id="set", section="Modelo", type="set", label="Conjunto", default="Moderado", options=registry_mod.describe_sets(tier, MODEL_INFO, IMAGE_MODELS, refs_required > 0),
             help="Um pacote pronto: escolhe o modelo, quantos passos e o tamanho da geração. Rápido gasta menos tempo, Qualidade busca mais fidelidade. Em Manual você escolhe tudo."),
        dict(id="model", section="Modelo", type="model", label="Modelo", default=default_model, options=models),
        dict(id="gen_factor", type="hidden", default=1.0),
        dict(id="slots", type="hidden", default={}),
        dict(id="sampler", type="hidden", default=""), dict(id="scheduler", type="hidden", default=""),
        dict(id="aspect", section="Formato", type="chips", label="Enquadramento", default="auto",
             options=[dict(opt(n, ASPECT_INFO[n][0], ASPECT_INFO[n][1]), ratio=[a, b], group=ASPECT_INFO[n][2])
                      for n, a, b in ASPECTS]),
        dict(id="quality", section="Formato", type="chips", label="Resolução final", default="standard", options=quality_options(tier)),
        dict(id="variations", section="Formato", type="seg", label="Variações", default=1,
             options=[opt(n, str(n), "") for n in range(1, 5)], help="Quantas imagens gerar do mesmo pedido. Cada uma usa uma semente (seed) nova e roda uma depois da outra."),
        dict(id="loras", section="Estilo", type="loras", label="LoRAs", default=[], max=4, help="Ajuste a força de cada estilo."),
        dict(id="upscale_method", type="select", label="Como ampliar até a resolução final", default=UPSCALE_METHODS[0], advanced=True,
             options=[dict(opt(v, upscale.short(v)), fav_kind="upscaler") if v in upscale.MODELS else opt(v, v) for v in UPSCALE_METHODS], help="Só vale para Muito alta e Ultra. Em blocos, para caber na placa."),
        dict(id="upscale", type="select", label="Ampliar depois", default="Nenhum", advanced=True,
             options=[opt(v, v) for v in ("Nenhum", "Lanczos 2×", "Real-ESRGAN 2×")]),
        dict(id="refine", type="switch", label="Refino técnico automático", default=False, advanced=True,
             help="Confere vazio, nitidez, exposição e tamanho; corrige com filtro ou nova seed (até 2 rodadas). Não julga estética nem identidade."),
        dict(id="steps", type="slider", label="Passos", default=0, min=0, max=100, step=1, manual=True,
             help="Quantas etapas de refinamento o modelo faz. Mais passos costumam dar mais detalhe e levam mais tempo. 0 usa o recomendado do modelo."),
        dict(id="cfg", type="slider", label="CFG (fidelidade ao prompt)", default=0, min=0, max=12, step=0.1, decimals=1, manual=True,
             help="Quanto o modelo obedece ao texto. Valores altos seguem o prompt ao pé da letra, mas podem deixar a imagem artificial. 0 usa o recomendado do modelo."),
        dict(id="shift", type="slider", label="Shift (Z-Image)", default=3.0, min=0.5, max=10, step=0.1, decimals=1, manual=True,
             models=["z-image", "z-image-turbo"], help="Deslocamento do agendador. Só os modelos Z-Image usam."),
        dict(id="negative", type="textarea", label="Evitar", default="", manual=True, rows=2, help="Só tem efeito com CFG maior que 1."),
        dict(id="expand", type="switch", label="Expansor de prompt local", default=False, manual=True, models=["flux3"],
             help="FLUX.3 expande o pedido numa legenda detalhada antes de gerar."),
        dict(id="seed", type="number", label="Seed", default=-1, manual=True, help="-1 sorteia a cada geração."),
        dict(id="free_vram", type="switch", label="Liberar a VRAM ao terminar", default=False, manual=True,
             help="Descarrega os modelos do worker quando o job acaba."),
    ]


# ---------------------------------------------------------------- runners

def scaled(ctx, index, total):
    def report(fraction=None, desc=None, **_):
        base = (index + (fraction or 0)) / total
        ctx.progress(base, desc=(f"Imagem {index + 1}/{total} · {desc}" if total > 1 and desc else desc))
    return report


def collect_job(ctx, job):
    if job["status"] != "concluído":
        raise JobError(job.get("message") or "O ComfyUI não concluiu o job.", job["status"] if job["status"] in cf_jobs.FINAL else "falhou")
    folder = ctx.out_dir / job["id"]
    return [folder / name for name in job["results"] if (folder / name).is_file()]


def run_graph_images(ctx, preset, p, files, width, height, count, progress_total=None):
    steps = int(p.get("steps") or preset.steps)
    cfg = float(p.get("cfg") or preset.cfg)
    negative = (p.get("negative") or "").strip() if cfg > 1 else ""
    seed = int(p.get("seed", -1))
    seed = random.randrange(2**32) if seed < 0 else seed
    loras = [item for item in (p.get("loras") or []) if item.get("name") and item.get("on", True)]
    preset = dataclasses.replace(preset, sampler=p.get("sampler") or preset.sampler, scheduler=p.get("scheduler") or preset.scheduler)
    picked = {role: key for role, key in (p.get("slots") or {}).items() if key}
    plain = {role: key[5:] for role, key in picked.items() if key.startswith("file:")}  # a file already in the worker's folder
    picked = {role: key for role, key in picked.items() if not key.startswith("file:")}
    try:
        chosen = lab.selections(ENV["civitai"], preset, picked, []) if picked else {}
    except ValueError as exc:
        raise JobError(str(exc)) from None
    expand = bool(p.get("expand")) and preset.key == "flux3"  # local prompt expander only exists for FLUX.3
    names, sources = lab.names_and_sources(preset, chosen, expand)
    for role, name in plain.items():
        folder = cf_civitai.ROLE_TYPES.get(role)
        if role not in preset.roles or not folder or Path(name).name != name or not (lab.models_root() / folder / name).is_file():
            raise JobError(f"O arquivo escolhido para {role} não está na pasta do worker.")
        names[role] = [name]
        sources[:] = [src for src in sources if src[0] != folder or src[1] != Path(preset.files.get(role, ("", ""))[1]).name]
    weights = []
    if loras:
        names["LoRA"] = []
        for item in loras:
            ctx.progress(0.02, desc=f"Preparando LoRA {item['name']}")
            path = cf_loras.ensure(ENV["base"], item["name"], ctx.progress)
            names["LoRA"].append(path.name)
            sources.append(("loras", path.name, path))
            weights.append((float(item.get("strength", 1.0)), float(item.get("clip", item.get("strength", 1.0)))))
    outputs = []
    for index in range(count):
        ctx.check()
        try:
            graph, uploads, used = lab.make_graph(preset, names, p["prompt"], negative, width, height, steps, cfg,
                                                  seed + index, files, 1.0, expand, weights,
                                                  shift=float(p.get("shift") or 3.0))
        except ValueError as exc:
            raise JobError(str(exc)) from None
        prepare = partial(lab.prepare, sources=sources, uploads=uploads, pending=(), asset_directory=ENV["civitai"])
        job = workflows.run(graph, ctx.out_dir, scaled(ctx, index, count), prepare=prepare,
                            title=f"{preset.title} · seed {used}", control=ctx.control, family=preset.key)
        outputs.extend(collect_job(ctx, job))
    if p.get("free_vram"):
        import requests
        with requests.Session() as session:
            session.trust_env = False
            workflows.free_models(session)
    return outputs


def post_upscale(ctx, outputs, choice):
    if choice == "Nenhum":
        return outputs
    mode = "Lanczos (rápido, sem IA)" if choice.startswith("Lanczos") else "RealESRGAN_x4plus (fotografia)"
    finals = []
    for index, path in enumerate(outputs):
        ctx.progress(0.9, desc=f"Ampliando {index + 1}/{len(outputs)}")
        with Image.open(path) as image:
            result = upscale.process(image.convert("RGB"), mode, 2, 128, 16, "cpu", 0, ENV["base"], ctx.progress)
        final = path.with_name(path.stem + "_2x.png")
        result.save(final)
        finals.append(final)
    return finals


def run_image(ctx, p, tier):
    preset = lab.PRESETS[p["model"]]
    files = p.get("refs") or []
    plan = resolution_plan(p.get("aspect", "auto"), p.get("quality", "standard"), tier, files, float(p.get("gen_factor") or 1.0))
    width, height = plan["native"]
    outputs = run_graph_images(ctx, preset, p, files, width, height, max(1, min(4, int(p.get("variations", 1)))))
    if p.get("refine"):
        outputs = refine_outputs(ctx, preset, p, files, width, height, outputs)
    outputs = reach_final_size(ctx, outputs, plan, p.get("upscale_method"))
    return post_upscale(ctx, outputs, p.get("upscale", "Nenhum"))


def refine_outputs(ctx, preset, p, files, width, height, outputs):
    """Technical gate + capped loop (cf_refine). Measurable properties only: no aesthetic/identity judgement."""
    base_seed = int(p.get("seed", -1))
    base_seed = random.randrange(2**32 - 16) if base_seed < 0 else base_seed
    names = ["not_blank", "sharp", "exposure"]
    context = {}
    finals, notes = [], []
    for index, first in enumerate(outputs):
        pending = [first]  # the baseline was already generated; only later rounds spend GPU

        def generate(params, pending=pending):
            if pending:
                return pending.pop()
            return run_graph_images(ctx, preset, {**p, "seed": params["seed"]}, files, width, height, 1)[0]
        report = refine.refine(generate, {"seed": base_seed + index * 100}, context, names,
                               ctx.out_dir / f"refino_{index + 1}", max_rounds=2)
        finals.append(report["best"]["path"])
        notes.append(f"Imagem {index + 1}: " + refine.summarize(report))
    ctx.job.update(message=" | ".join(notes)[:900])
    return finals


LIGHT_KINDS = {"point": "point light", "softbox": "large soft area light", "rim": "rim light", "spot": "focused spotlight beam"}
HUES = [(15, "red"), (40, "orange"), (65, "yellow"), (95, "lime green"), (165, "green"), (195, "cyan"), (255, "blue"),
        (290, "violet"), (330, "magenta"), (361, "red")]


def color_name(value):
    import colorsys
    value = str(value or "#ffffff").lstrip("#")
    try:
        r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return "white"
    hue, sat, val = colorsys.rgb_to_hsv(r, g, b)
    if sat < 0.12:
        return "white" if val > 0.75 else "dim neutral"
    name = next(label for limit, label in HUES if hue * 360 < limit)
    if name == "orange" and sat < 0.6:
        name = "warm amber"
    return f"{'pale ' if sat < 0.45 else ''}{name}"


def band(value, words):
    return words[min(len(words) - 1, int(max(0.0, min(0.999, value)) * len(words)))]


def describe_light(light):
    x, y, z = (float(light.get(k, 0.5)) for k in ("x", "y", "z"))
    power = float(light.get("intensity", 70)) / 100
    soft = float(light.get("size", 50)) / 100
    kind = LIGHT_KINDS.get(light.get("kind"), LIGHT_KINDS["point"])
    place = f"{band(y, ['top', 'upper', 'middle', 'lower', 'bottom'])} {band(x, ['far left', 'left', 'center', 'right', 'far right'])} of the frame"
    depth = band(z, ["behind the subject, as a backlight", "beside the subject", "in front of the subject"])
    return (f"a {band(power, ['faint', 'soft', 'strong', 'very intense'])} {color_name(light.get('color'))} "
            f"({str(light.get('color', '#ffffff')).lower()}) {band(soft, ['hard-edged', 'medium-soft', 'very soft and diffused'])} {kind}, "
            f"{place}, {depth}")


def run_relight(ctx, p, tier):
    lights = [item for item in (p.get("lights") or []) if isinstance(item, dict)][:8]
    if not lights:
        raise JobError("Adicione pelo menos uma luz.")
    listing = "; ".join(f"{i}. {describe_light(item)}" for i, item in enumerate(lights, 1))
    notes = (p.get("prompt") or "").strip()
    prompt = ("Relight this photograph. Keep the subject, identity, pose, expression, clothing, composition, framing and "
              "background exactly as they are and change only the lighting. Add these light sources and let each one cast "
              f"physically plausible highlights, shadows, colored spill and reflections on the subject and the scene: {listing}. "
              "Blend them into one coherent natural photographic result" + (f". Scene notes: {notes}" if notes else "."))
    ctx.job.update(message=f"{len(lights)} luz(es) enviadas à IA.")
    return run_image(ctx, {**p, "prompt": prompt}, tier)


def run_benchmark(ctx, p, tier):
    """GPU benchmark: one cold run (model load included), then warm runs with fresh seeds so ComfyUI's cache cannot
    answer. Wall-clock per run; VRAM from ComfyUI's own stats right after the run. History in <base>/benchmarks.json."""
    import json as _json
    import statistics
    import requests
    preset = lab.PRESETS["flux2"]
    prompt = "A red sphere on a white table, studio light"
    plan = [("frio · 512²", 512, True), ("quente · 512² #1", 512, False), ("quente · 512² #2", 512, False),
            ("quente · 512² #3", 512, False)]
    side = min(1024, tier.max_side)
    if side > 512:
        plan.append((f"quente · {side}²", side, False))
    seeds = random.sample(range(2**31), len(plan))
    runs, last = [], []
    for index, (label, size, cold) in enumerate(plan):
        ctx.check()
        ctx.progress(index / len(plan), desc=f"Benchmark · {label}")
        begin = time.monotonic()
        last = run_graph_images(ctx, preset, {"prompt": prompt, "steps": 4, "cfg": 1, "seed": seeds[index]}, [], size, size, 1)
        seconds = time.monotonic() - begin
        vram_used = None
        try:
            stats = requests.get(f"{workflows.SERVER}/system_stats", timeout=3).json()["devices"][0]
            vram_used = round((stats["vram_total"] - stats["vram_free"]) / 1024**3, 2)
        except (requests.RequestException, KeyError, IndexError, ValueError):
            pass
        runs.append(dict(label=label, side=size, cold=cold, seconds=round(seconds, 2), vram_gb=vram_used))
    warm512 = [r["seconds"] for r in runs if not r["cold"] and r["side"] == 512]
    big = next((r for r in runs if r["side"] > 512), None)
    record = dict(time=int(time.time()), gpu=tier.gpu, vram_gb=round(tier.vram_gb, 1), tier=tier.label, model=preset.title, steps=4,
                  cold_seconds=runs[0]["seconds"], warm_seconds=round(statistics.median(warm512), 2),
                  steps_per_second=round(4 / statistics.median(warm512), 2), big=big, vram_used_gb=max((r["vram_gb"] or 0) for r in runs) or None,
                  runs=runs)
    path = ENV["base"] / "benchmarks.json"
    try:
        history = _json.loads(path.read_text())
    except (OSError, ValueError):
        history = []
    path.write_text(_json.dumps((history + [record])[-20:], ensure_ascii=False, indent=1))
    ctx.job.update(message=f"{tier.gpu}: frio {record['cold_seconds']} s · quente {record['warm_seconds']} s ({record['steps_per_second']} passos/s)"
                           + (f" · {big['side']}² em {big['seconds']} s" if big else ""))
    return last


def run_region(ctx, p, tier):
    try:
        original, stencil, bounds, reference = region.prepare(p["source"][0], p["mask"][0], int(p.get("size", 768)), int(p.get("padding", 96)))
    except (OSError, ValueError) as exc:
        raise JobError(str(exc)) from None
    low = min(reference.size)
    if low < 256:
        factor = 256 / low
        reference = reference.resize(tuple(round(e * factor / 32) * 32 for e in reference.size), Image.Resampling.LANCZOS)
    folder = ctx.out_dir / "regiao"
    folder.mkdir(exist_ok=True)
    ref_path = folder / f"ref-{ctx.job.id}.png"
    reference.save(ref_path)
    width, height = reference.size
    outputs = run_graph_images(ctx, lab.PRESETS["qwen21"], {**p, "steps": int(p.get("steps") or 0)}, [str(ref_path)],
                               width, height, 1)
    edit = Image.open(outputs[0]).convert("RGB")
    result = region.composite(original, stencil, bounds, edit, int(p.get("feather", 8)))
    destination = finish.output_path(ctx.out_dir, "regiao", ".png")
    result.save(destination)
    return [destination]


def run_wan(ctx, p, tier):
    mode = p["mode"]
    image = (p.get("image") or [None])[0]
    seed = int(p.get("seed", -1))
    try:
        graph = wan.make_graph(mode, image, p["prompt"], p.get("negative", ""), p["size"], p["frames"],
                               int(p.get("steps", 20)), seed)
    except ValueError as exc:
        raise JobError(str(exc)) from None
    job = workflows.run(graph, ctx.out_dir, ctx.progress, prepare=partial(wan.prepare, image=image), title=mode,
                        control=ctx.control, family="wan", stall=1500)
    return collect_job(ctx, job)


def compute_device():
    """The device torch can really use in THIS process (the card's VRAM says nothing about the studio's own torch build)."""
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def run_upscale(ctx, p, tier):
    source = p["image"][0]
    with Image.open(source) as image:
        result = upscale.process(ImageOps.exif_transpose(image).convert("RGBA" if image.mode in ("RGBA", "LA") else "RGB"),
                                 p["mode"], float(p.get("scale", 2)), int(p.get("tile", 128)), 16,
                                 compute_device(), int(p.get("sharpen", 0)), ENV["base"], ctx.progress)
    destination = finish.output_path(ctx.out_dir, "upscale", ".png")
    result.save(destination)
    return [destination]


def run_seedvr2(ctx, p, tier):
    path = p["media"][0]
    kind = "Vídeo" if Path(path).suffix.lower() in (".mp4", ".mov", ".webm", ".mkv") else "Imagem"
    try:
        job = seedvr2.run(path, kind, p.get("model", seedvr2.DEFAULT), float(p.get("scale", 2)), int(p.get("seed", 42)),
                          seedvr2.DEFAULT_TILE, ctx.out_dir, ctx.progress)
    except (OSError, ValueError, RuntimeError) as exc:
        raise JobError(str(exc)) from None
    if not job.get("result"):
        raise JobError(job.get("error") or job["status"], job["status"] if job["status"] in cf_jobs.FINAL else "falhou")
    return [ctx.out_dir / job["id"] / job["result"]]


def run_look(ctx, p, tier):
    path, _ = finish.image_edit(p["image"][0], finish.LOOK, p["look"], float(p.get("strength", 75)), None, None,
                                p.get("format", "PNG"), ctx.out_dir)
    return [path]


def run_frame(ctx, p, tier):
    path, _ = finish.image_edit(p["image"][0], finish.FRAME, None, 0, p["ratio"], p.get("fit", "Preencher"),
                                p.get("format", "PNG"), ctx.out_dir, tuple(p.get("focus") or (0.5, 0.5)))
    return [path]


def run_clip(ctx, p, tier, mode):
    video, image, _ = finish.video_edit(p["video"][0], mode, float(p.get("start", 0)), float(p.get("duration", 5)),
                                        p.get("ratio", "Original"), p.get("fit", "Preencher"), bool(p.get("mute")), ctx.out_dir)
    return [video or image]


def run_sequence(ctx, p, tier):
    path, _ = finish.video_sequence(p["videos"], p.get("order", ""), p["ratio"], p.get("fit", "Manter imagem inteira"),
                                    bool(p.get("mute")), ctx.out_dir)
    return [path]


def run_compare(ctx, p, tier):
    _, path, _ = finish.compare_images(p["before"][0], p["after"][0], ctx.out_dir)
    return [path]


def run_openjutsu(ctx, p, tier):
    try:
        graph = openjutsu.build_graph(float(p.get("start", 0)), float(p.get("seconds", 5)), int(p.get("quality", 480)),
                                      p.get("direction", ""), int(p.get("seed", -1)), bool(p.get("anchor")))
    except ValueError as exc:
        raise JobError(str(exc)) from None
    prepare = partial(openjutsu.prepare, video=p["video"][0], character=p["character"][0],
                      anchor=(p.get("anchor") or [None])[0])
    job = workflows.run(graph, ctx.out_dir, ctx.progress, prepare=prepare, title="OpenJutsu H3", control=ctx.control,
                        family="openjutsu", stall=1800)
    return collect_job(ctx, job)


def run_seethrough(ctx, p, tier):
    import requests
    profile = p.get("profile") or seethrough.DEFAULT_PROFILE
    seed = int(p.get("seed", -1))
    seed = random.randrange(2**32) if seed < 0 else seed
    try:
        graph = seethrough.build_graph(profile, seed, int(p.get("steps", 30)), "pending.png", p.get("resolution") or None,
                                       bool(p.get("lama", True)), bool(p.get("split", True)))
    except ValueError as exc:
        raise JobError(str(exc)) from None
    prepare = partial(seethrough.prepare, image=p["image"][0])
    job = workflows.run(graph, ctx.out_dir, ctx.progress, prepare=prepare, title=f"Camadas · {profile}", control=ctx.control,
                        family="seethrough", stall=1800)
    outputs = collect_job(ctx, job)
    ctx.progress(0.95, desc="Montando PSD e pacote de camadas")
    try:
        with requests.Session() as session:
            session.trust_env = False
            info, layers = seethrough.fetch_layers(session, ctx.out_dir)
    except (requests.RequestException, OSError, ValueError, KeyError) as exc:
        raise JobError(f"Camadas geradas, mas o pacote não pôde ser lido do worker: {exc}") from None
    ctx.job.update(message=f"{len(layers)} camadas reais geradas (o número varia por imagem).")
    return seethrough.write_package(info, layers, ctx.out_dir / job["id"]) + [o for o in outputs if o.suffix != ".psd"]


def run_factory(ctx, p, tier):
    import json as _json
    raw = (p.get("script") or "").strip()
    try:
        script = _json.loads(raw) if raw else factory_pipeline.example_script()
    except ValueError as exc:
        raise JobError(f"O roteiro não é um JSON válido: {exc}") from None
    script["voice"] = bool(p.get("voice"))
    if not script["voice"]:
        for beat in script.get("beats", []):
            beat.pop("vo", None)
    try:
        slug = factory_pipeline.create(script, p.get("title") or None)
        result = factory_pipeline.run(slug, ctx.progress)
    except ValueError as exc:
        raise JobError(str(exc)) from None
    except SystemExit as exc:  # the engine reports missing tools/voices this way
        raise JobError(str(exc) or "O motor do Content Factory recusou o pedido.") from None
    except Exception as exc:
        raise JobError(f"Falha na fábrica de vídeo: {str(exc)[:600]}") from None
    if not result["video"]:
        raise JobError("A fábrica terminou sem gerar o vídeo.")
    destination = finish.output_path(ctx.out_dir, "fabrica", ".mp4")
    shutil.copyfile(result["video"], destination)
    issues = [i["message"] for i in (result["qa"] or {}).get("checks", []) if i.get("level") in ("warn", "error")] if isinstance(result["qa"], dict) else []
    ctx.job.update(message=("Controle de qualidade: " + "; ".join(issues[:4])) if issues else "Controle de qualidade sem alertas.")
    return [destination]


def run_workflow(ctx, p, tier):
    try:
        graph = workflows.read_graph(p["graph"][0])
    except (OSError, ValueError) as exc:
        raise JobError(str(exc)) from None
    job = workflows.run(graph, ctx.out_dir, ctx.progress, files=p.get("media") or None, title="Workflow API",
                        control=ctx.control, family="custom")
    return collect_job(ctx, job)


def install_model(ctx, key):
    preset = lab.PRESETS[key]
    token = os.environ.get("HF_TOKEN") or None
    pending = [(role, spec) for role, spec in preset.files.items()]
    for index, (role, (repo, filename, *rest)) in enumerate(pending):
        target = lab.models_root() / Path(filename).parts[-2] / Path(filename).name
        if target.is_file() and target.stat().st_size:
            continue
        ctx.check()
        try:
            download.fetch_hf(repo, filename, target, revision=(rest or [lab.REVISIONS.get(repo, "main")])[0], token=token,
                              progress=lambda f, desc=None, **_: ctx.progress((index + 0.5) / len(pending), desc=desc))
        except download.DownloadError as exc:
            raise JobError(str(exc)) from None
        ctx.progress((index + 1) / len(pending), desc=f"{target.name} instalado")
    return []


LORA_FAMILIES = {"sdxl": ["sdxl"], "sd15": ["sd15"],
                 "qwen21": ["qwen21"], "krea2": ["krea2", "krea2-turbo"], "krea2-turbo": ["krea2", "krea2-turbo"],
                 "flux2": ["flux2"], "flux3": ["flux3"], "z-image": ["z-image", "z-image-turbo"],
                 "z-image-turbo": ["z-image", "z-image-turbo"]}


def install_civitai_lora(ctx, family, model, version, file):
    """Download one Civitai LoRA (SHA-256 checked) and register it in base/loras with its card data."""
    from cf_civitai import entry_for, install
    try:
        preset = lab.PRESETS[family]
        entry, record = entry_for(preset, model, version, file)
        ctx.progress(0.05, desc=f"Baixando {entry['title']} do Civitai")
        source = install(entry, ENV["civitai"], ctx.progress)
        card = cf_civitai.model_card(record, next(v for v in record["modelVersions"] if v["id"] == entry["version"]), [entry], preset)
        cf_loras.link_civitai(ENV["base"], entry, source, LORA_FAMILIES.get(family, [family]), card["covers"], card["page"])
    except (ValueError, KeyError, StopIteration) as exc:
        raise JobError(str(exc) or "Não foi possível instalar este LoRA.") from None
    ctx.progress(1.0, desc="LoRA instalado")
    return []


def install_civitai_component(ctx, family, role, model, version, file):
    """Download one Civitai component (VAE, encoder, upscaler, checkpoint...) SHA-256 checked, into the shared inventory."""
    from cf_civitai import entry_for, install
    try:
        entry, _record = entry_for(lab.PRESETS[family], model, version, file, role)
        ctx.progress(0.05, desc=f"Baixando {entry['title']} do Civitai")
        install(entry, ENV["civitai"], ctx.progress)
    except (ValueError, KeyError, StopIteration) as exc:
        raise JobError(str(exc) or "Não foi possível instalar este componente.") from None
    ctx.progress(1.0, desc=f"{role} instalado")
    return []


def install_upscaler(ctx, name):
    if name not in upscale.MODELS:
        raise JobError("Upscaler desconhecido.")
    ctx.progress(0.05, desc=f"Baixando {upscale.short(name)}")
    try:
        upscale.load(name, ENV["base"], ctx.progress)
    except (ValueError, download.DownloadError, OSError) as exc:
        raise JobError(str(exc)) from None
    ctx.progress(1.0, desc="Upscaler instalado")
    return []


def install_recipe_file(ctx, repo, filename):
    """Download one recipe weight (a VAE or an encoder on its own) from its pinned Hugging Face revision."""
    known = {(r, f) for preset in lab.PRESETS.values() for r, f, *_ in preset.files.values()}
    if (repo, filename) not in known:
        raise JobError("Esse arquivo não faz parte das receitas do Studio.")
    target = lab.models_root() / Path(filename).parts[-2] / Path(filename).name
    try:
        ctx.progress(0.05, desc=f"Baixando {target.name}")
        download.fetch_hf(repo, filename, target, revision=lab.REVISIONS.get(repo, "main"), token=os.environ.get("HF_TOKEN") or None, progress=ctx.progress)
    except (ValueError, download.DownloadError, OSError) as exc:
        raise JobError(str(exc)) from None
    ctx.progress(1.0, desc="Instalado")
    return []


def install_lora(ctx, name):
    try:
        cf_loras.ensure(ENV["base"], name, ctx.progress)
    except (ValueError, download.DownloadError) as exc:
        raise JobError(str(exc)) from None
    return []


# ---------------------------------------------------------------- registry

def sizes_options(sizes):
    """Dropdown options for named output sizes: ratio glyph, where it is used and the pixel size."""
    from math import gcd
    options = []
    for name, (w, h) in sizes.items():
        d = gcd(w, h)
        use = SIZE_USES.get((w // d, h // d), "")
        size = "" if "×" in name else f"{w} × {h}"
        options.append(dict(opt(name, name, " · ".join(x for x in (use, size) if x)), ratio=[w, h]))
    return options


class App:
    def __init__(self, id, title, group, tagline, art, runner, fields, lane="gpu", min_vram=0, note="", hidden=False):
        self.id, self.title, self.group, self.tagline, self.art = id, title, group, tagline, art
        self.runner, self.fields, self.lane, self.min_vram, self.note, self.hidden = runner, fields, lane, min_vram, note, hidden

    def describe(self, tier):
        blocked = self.min_vram and tier.vram_gb < self.min_vram
        return {"id": self.id, "title": self.title, "group": self.group, "tagline": self.tagline, "art": self.art,
                "lane": self.lane, "min_vram": self.min_vram, "note": self.note,
                "blocked": bool(blocked),
                "blocked_reason": (f"Precisa de uma placa com ~{self.min_vram} GB; a sua tem {tier.vram_gb:.0f} GB." if blocked else ""),
                "fields": self.fields(tier)}


def relight_fields(tier):
    fields = image_fields(tier, 1, prompt_label="Notas de cena (opcional)", refs_label="Imagem base")
    fields[0]["required"] = False
    fields[0]["rows"] = 2
    fields[1]["max"] = 1
    fields[1]["help"] = ""
    model = next(f for f in fields if f["id"] == "model")
    model["options"] = [m for m in model["options"] if lab.PRESETS[m["value"]].refs > 0]
    model["default"] = "flux2" if tier.vram_gb < 16 else "qwen21"
    prompt, refs, *rest = fields
    return [refs, dict(id="lights", type="lights", label="Luzes", default=[], min=1, max=8), prompt, *rest]


def build_registry():
    wan_frames = lambda t: [opt(k, k) for k in wan.FRAMES]
    return [
        App("create", "Criar imagem", "Imagem", "Do texto à imagem com o modelo que você escolher.", "image",
            run_image, lambda t: image_fields(t)),
        App("edit", "Editar com referências", "Imagem", "Mude o que importa e preserve o resto.", "image",
            run_image, lambda t: image_fields(t, 1, prompt_label="O que deve mudar?", refs_label="Imagem a editar")),
        App("relight", "Luz ambiente", "Imagem", "Posicione luzes, escolha cor e intensidade e a IA integra à foto.", "image",
            run_relight, relight_fields),
        App("portrait", "Retrato por referência", "Identidade", "Identidade da primeira imagem, pose e luz da segunda.", "identity",
            run_image, lambda t: image_fields(t, 2, lab_prompt(), "Descreva o retrato", "Pessoa e composição")),
        App("region", "Editar região", "Imagem", "Pinte uma máscara e retoque só aquela área.", "image", run_region,
            lambda t: [dict(id="source", type="files", label="Imagem original", accept="image", max=1, min=1),
                       dict(id="mask", type="files", label="Máscara (branco = editar)", accept="image", max=1, min=1),
                       dict(id="prompt", type="textarea", label="Alteração", default="", required=True, rows=3),
                       dict(id="size", type="chips", label="Detalhe do recorte", default=768 if t.vram_gb >= 16 else 512,
                            options=[opt(s, f"{s}px") for s in region.SIZES]),
                       dict(id="padding", type="slider", label="Contexto ao redor", default=96, min=0, max=256, step=8, advanced=True),
                       dict(id="feather", type="slider", label="Suavizar borda", default=8, min=0, max=64, step=1, advanced=True)],
            min_vram=0),
        App("animate", "Foto em movimento", "Vídeo", "Anime uma foto com movimento e câmera.", "video", run_wan,
            lambda t: [dict(id="mode", type="hidden", default=wan.IMAGE_MODE),
                       dict(id="image", type="files", label="Foto inicial", accept="image", max=1, min=1),
                       dict(id="prompt", type="textarea", label="Cena e movimento", default="", required=True, rows=3),
                       dict(id="size", type="chips", label="Proporção", default=next(iter(wan.SIZES)), options=sizes_options(wan.SIZES)),
                       dict(id="frames", type="chips", label="Duração", default="33 quadros" if t.video_frames < 49 else "49 quadros",
                            options=wan_frames(t)),
                       dict(id="negative", type="textarea", label="Evitar", default="flicker, artifacts, blurry, subtitles", advanced=True, rows=2),
                       dict(id="steps", type="slider", label="Passos", default=20, min=8, max=30, step=1, advanced=True),
                       dict(id="seed", type="number", label="Seed", default=-1, advanced=True)],
            note="No primeiro uso o Studio baixa ~18 GB de pesos."),
        App("text2video", "Texto em vídeo", "Vídeo", "Descreva a cena e receba um clipe.", "video", run_wan,
            lambda t: [dict(id="mode", type="hidden", default=wan.TEXT_MODE),
                       dict(id="prompt", type="textarea", label="Cena e movimento", default="", required=True, rows=4),
                       dict(id="size", type="chips", label="Proporção", default=next(iter(wan.SIZES)), options=sizes_options(wan.SIZES)),
                       dict(id="frames", type="chips", label="Duração", default="33 quadros", options=wan_frames(t)),
                       dict(id="negative", type="textarea", label="Evitar", default="flicker, artifacts, blurry, subtitles", advanced=True, rows=2),
                       dict(id="steps", type="slider", label="Passos", default=20, min=8, max=30, step=1, advanced=True),
                       dict(id="seed", type="number", label="Seed", default=-1, advanced=True)]),
        App("upscale", "Ampliar imagem", "Melhorar", "Lanczos ou Real-ESRGAN, sem esperar o ComfyUI.", "upscale", run_upscale,
            lambda t: [dict(id="image", type="files", label="Imagem", accept="image", max=1, min=1),
                       dict(id="mode", type="chips", label="Método", default="Lanczos (rápido, sem IA)",
                            options=[opt("Lanczos (rápido, sem IA)", "Lanczos", "instantâneo")] + [dict(opt(k, upscale.short(k), f"{v['use']} · {v['license']}"), fav_kind="upscaler") for k, v in upscale.MODELS.items()]),
                       dict(id="scale", type="slider", label="Escala", default=2, min=1, max=4, step=0.5),
                       dict(id="tile", type="slider", label="Bloco", default=128 if t.vram_gb < 16 else 256, min=64, max=512, step=32, advanced=True),
                       dict(id="sharpen", type="slider", label="Nitidez", default=0, min=0, max=200, step=10, advanced=True)],
            lane="cpu"),
        App("seedvr2", "Restaurar com SeedVR2", "Melhorar", "Recupere detalhe em imagem ou clipe curto.", "upscale", run_seedvr2,
            lambda t: [dict(id="media", type="files", label="Imagem ou vídeo (até 2 s)", accept="image,video", max=1, min=1),
                       dict(id="model", type="select", label="Modelo", default=seedvr2.LIGHT if t.vram_gb < 24 else seedvr2.DEFAULT,
                            options=[opt(k, k) for k in seedvr2.PROFILES]),
                       dict(id="scale", type="slider", label="Escala", default=2, min=1, max=4, step=0.25),
                       dict(id="seed", type="number", label="Seed", default=42, advanced=True)]),
        App("seethrough", "Camadas de anime", "Editar", "Ilustração anime em camadas reais com transparência, profundidade e PSD.", "layers", run_seethrough,
            lambda t: [dict(id="image", type="files", label="Ilustração anime", accept="image", max=1, min=1),
                       dict(id="profile", type="select", label="Perfil de memória", default=seethrough.DEFAULT_PROFILE,
                            options=[opt(k, k, f"Estimativa do autor: {v['claim']} de VRAM (não medido aqui)") for k, v in seethrough.PROFILES.items()]),
                       dict(id="steps", type="slider", label="Passos", default=30, min=10, max=60, step=1, advanced=True),
                       dict(id="resolution", type="slider", label="Resolução (px)", default=1024, min=512, max=1536, step=64, advanced=True),
                       dict(id="split", type="switch", label="Separar olhos, orelhas e mãos em esquerda/direita", default=True, advanced=True),
                       dict(id="lama", type="switch", label="Preencher cabelo com LaMa", default=True, advanced=True),
                       dict(id="seed", type="number", label="Seed (-1 = aleatória)", default=-1, advanced=True)],
            min_vram=8, note="Camadas por imagem variam; o app não promete um número fixo. Pesos LayerDiff: licença OpenRAIL++."),
        App("factory", "Fábrica de vídeo", "Vídeo", "Roteiro em vídeo vertical com cache por etapa: edite uma cena e só ela refaz.", "workflow", run_factory,
            lambda t: [dict(id="script", type="textarea", label="Roteiro (JSON de beats)", default="", rows=10,
                            help="Vazio usa o exemplo «What if the Sun went out?» (modo desenhado, sem gerar imagens)."),
                       dict(id="title", type="text", label="Nome do episódio", default="", advanced=True),
                       dict(id="voice", type="switch", label="Narração", default=True,
                            help="Kokoro (CPU, inglês e outros) + Whisper alinham a fala às legendas. Baixa ~270 MB na primeira vez. Desligada, o vídeo sai mudo.")],
            lane="cpu", note="Motor: Content Factory (MIT). Renderizador Remotion tem licença própria."),
        App("look", "Cor e contraste", "Melhorar", "Looks prontos com intensidade ajustável.", "finish", run_look,
            lambda t: [dict(id="image", type="files", label="Imagem", accept="image", max=1, min=1),
                       dict(id="look", type="chips", label="Look", default=finish.LOOKS[0], options=[opt(v, v) for v in finish.LOOKS]),
                       dict(id="strength", type="slider", label="Intensidade", default=75, min=0, max=100, step=1),
                       dict(id="format", type="chips", label="Formato", default="PNG", options=[opt(v, v) for v in finish.FORMATS], advanced=True)],
            lane="cpu"),
        App("frame", "Enquadrar imagem", "Imagem", "Feed, stories ou paisagem em um toque.", "finish", run_frame,
            lambda t: [dict(id="image", type="files", label="Imagem", accept="image", max=1, min=1),
                       dict(id="ratio", type="chips", label="Proporção", default=next(iter(finish.SIZES)), options=sizes_options(finish.SIZES)),
                       dict(id="fit", type="chips", label="Encaixe", default="Preencher", options=[opt("Preencher", "Preencher"), opt("Manter imagem inteira", "Inteira")]),
                       dict(id="focus", type="hidden", default=[0.5, 0.5]),
                       dict(id="format", type="chips", label="Formato", default="PNG", options=[opt(v, v) for v in finish.FORMATS], advanced=True)],
            lane="cpu"),
        App("clip", "Cortar vídeo", "Vídeo", "Recorte o trecho e ajuste a proporção.", "finish", partial(run_clip, mode=finish.CLIP),
            lambda t: [dict(id="video", type="files", label="Vídeo", accept="video", max=1, min=1),
                       dict(id="start", type="number", label="Início (s)", default=0),
                       dict(id="duration", type="slider", label="Duração (s)", default=5, min=0.5, max=60, step=0.5),
                       dict(id="ratio", type="select", label="Proporção", default="Original", options=[opt("Original", "Original")] + sizes_options(finish.SIZES)),
                       dict(id="fit", type="chips", label="Encaixe", default="Preencher", options=[opt("Preencher", "Preencher"), opt("Manter imagem inteira", "Inteira")], advanced=True),
                       dict(id="mute", type="switch", label="Remover áudio", default=False, advanced=True)],
            lane="cpu"),
        App("still", "Extrair quadro", "Vídeo", "Salve qualquer instante como imagem.", "finish", partial(run_clip, mode=finish.STILL),
            lambda t: [dict(id="video", type="files", label="Vídeo", accept="video", max=1, min=1),
                       dict(id="start", type="number", label="Instante (s)", default=0)], lane="cpu"),
        App("board", "Prancha de cenas", "Vídeo", "Seis momentos do clipe com timecode.", "finish", partial(run_clip, mode=finish.BOARD),
            lambda t: [dict(id="video", type="files", label="Vídeo", accept="video", max=1, min=1),
                       dict(id="start", type="number", label="Início (s)", default=0),
                       dict(id="duration", type="slider", label="Trecho (s)", default=6, min=1, max=60, step=1)], lane="cpu"),
        App("sequence", "Montar sequência", "Vídeo", "Junte de 2 a 8 clipes em um MP4.", "finish", run_sequence,
            lambda t: [dict(id="videos", type="files", label="Clipes (2 a 8)", accept="video", max=8, min=2),
                       dict(id="order", type="text", label="Ordem", default="", help="Ex.: 2, 1, 3. Vazio segue a lista."),
                       dict(id="ratio", type="chips", label="Proporção", default="Paisagem · 16:9", options=sizes_options(finish.SEQUENCE_SIZES)),
                       dict(id="fit", type="chips", label="Encaixe", default="Manter imagem inteira", options=[opt("Preencher", "Preencher"), opt("Manter imagem inteira", "Inteira")], advanced=True),
                       dict(id="mute", type="switch", label="Sem áudio", default=False, advanced=True)], lane="cpu"),
        App("compare", "Comparar imagens", "Melhorar", "Antes e depois lado a lado.", "finish", run_compare,
            lambda t: [dict(id="before", type="files", label="Antes", accept="image", max=1, min=1),
                       dict(id="after", type="files", label="Depois", accept="image", max=1, min=1)], lane="cpu"),
        App("openjutsu", "Trocar personagem", "Identidade", "Aplique uma referência a um clipe (OpenJutsu H3).", "identity", run_openjutsu,
            lambda t: [dict(id="video", type="files", label="Clipe de atuação", accept="video", max=1, min=1),
                       dict(id="character", type="files", label="Personagem", accept="image", max=1, min=1),
                       dict(id="anchor", type="files", label="Primeiro quadro pronto (opcional)", accept="image", max=1, min=0, advanced=True),
                       dict(id="start", type="number", label="Início (s)", default=0),
                       dict(id="seconds", type="slider", label="Duração (s)", default=5, min=5, max=15, step=0.5),
                       dict(id="quality", type="chips", label="Resolução", default=480, options=[opt(480, "480"), opt(768, "768")]),
                       dict(id="direction", type="textarea", label="Direção adicional", default="", rows=2, advanced=True),
                       dict(id="seed", type="number", label="Seed", default=-1, advanced=True)],
            min_vram=90, note="Exige worker da classe de 96 GB."),
        App("workflow", "Workflow ComfyUI", "Avançado", "Execute um grafo em API JSON.", "workflow", run_workflow,
            lambda t: [dict(id="graph", type="files", label="Workflow API JSON", accept=".json", max=1, min=1),
                       dict(id="media", type="files", label="Mídias de entrada", accept="image,video,audio", max=8, min=0)]),
        App("benchmark", "Benchmark da placa", "Sistema", "Frio, quente e VRAM medidos com seeds novas.", "workflow", run_benchmark,
            lambda t: [], hidden=True),
    ]


def lab_prompt():
    return ("Crie um retrato usando a pessoa da primeira imagem como referência de identidade. "
            "Use a segunda imagem como referência de pose, enquadramento, luz e cenário. "
            "Preserve os traços do rosto da primeira pessoa.")


REGISTRY = None


def registry():
    global REGISTRY
    if REGISTRY is None:
        REGISTRY = {app.id: app for app in build_registry()}
    return REGISTRY
