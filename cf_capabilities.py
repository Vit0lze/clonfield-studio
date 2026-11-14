"""Central capability registry: what the Studio can DO, independent of which app screen shows it.

A capability is a typed, versioned unit with one or more operations, typed inputs and outputs, model slots, resource
requirements, a validation state and the places that use it. The same capability can be a shared engine, a step in a DAG,
a universal action (chat / agent / UI), a mode of an app or a dedicated app. Apps do not own capabilities: they bind to
them (`BINDINGS`) and declare where more steps may be inserted (`INSERTION_POINTS`).

Two sources feed the registry:
  * NATIVE capabilities written here, with runners that work on CPU (upscale, quality gate, look, frame, compare, still,
    resolution plan).
  * APP capabilities generated from `cf_apps.registry()`: every app becomes `app.<id>` so the DAG and the agent can run any
    of them. Their I/O types are derived from the app's form fields.

Validation vocabulary (honest): NÃO INICIADO, CÓDIGO ESCRITO, TESTADO CPU, TESTADO API REAL, TESTADO GPU, INTEGRADO E VALIDADO,
BLOQUEADO_GPU. Nothing here claims a GPU result that was not measured.
"""

import dataclasses
import re
from pathlib import Path

MEDIA = ("image", "video", "audio", "mask", "text", "json", "psd", "file")
STATES = ("NÃO INICIADO", "CÓDIGO ESCRITO", "TESTADO CPU", "TESTADO API REAL", "TESTADO GPU", "INTEGRADO E VALIDADO", "BLOQUEADO_GPU")
KINDS = ("engine", "step", "action", "mode", "app")


@dataclasses.dataclass(frozen=True)
class Port:
    name: str
    type: str
    required: bool = True
    many: bool = False
    note: str = ""


@dataclasses.dataclass
class Capability:
    id: str
    title: str
    version: str
    kind: str
    tagline: str
    source: str
    license: str
    ops: tuple
    inputs: tuple
    outputs: tuple
    params: dict = dataclasses.field(default_factory=dict)
    slots: tuple = ()
    requires: dict = dataclasses.field(default_factory=lambda: dict(vram_gb=0, ram_gb=1, disk_gb=0, lane="cpu"))
    validation: dict = dataclasses.field(default_factory=lambda: dict(state="CÓDIGO ESCRITO", evidence=""))
    risk: str = "low"
    run: object = None  # run(env, ctx, inputs, params, workdir) -> {output name: artifact}

    def public(self, bindings=(), insertion=()):
        return dict(id=self.id, title=self.title, version=self.version, kind=self.kind, tagline=self.tagline, source=self.source,
                    license=self.license, ops=list(self.ops), risk=self.risk,
                    inputs=[dataclasses.asdict(p) for p in self.inputs], outputs=[dataclasses.asdict(p) for p in self.outputs],
                    params=self.params, slots=list(self.slots), requires=self.requires, validation=self.validation,
                    consumers=[dict(app=b[1], mode=b[2], note=b[3]) for b in bindings if b[0] == self.id],
                    insertable_in=[dict(app=app, point=p["point"]) for app, points in insertion for p in points if self.id in p["accepts"]])


def art(type_, path=None, value=None):
    """One artifact flowing along a DAG edge: a file (path) or a small JSON value."""
    return dict(type=type_, path=str(path) if path else None, value=value)


# ---------------------------------------------------------------- native runners (CPU)
def _image_in(inputs, name="image"):
    item = inputs[name]
    return item[0] if isinstance(item, list) else item


def run_upscale(env, ctx, inputs, params, workdir):
    from PIL import Image, ImageOps

    import cf_upscale
    source = _image_in(inputs)["path"]
    mode = params.get("mode", "Lanczos (rápido, sem IA)")
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        image = image.convert("RGBA" if image.mode in ("RGBA", "LA") else "RGB")
        out = cf_upscale.process(image, mode, float(params.get("scale", 2)), int(params.get("tile", 128)), 16, "cpu",
                                 int(params.get("sharpen", 0)), env["base"], ctx.progress)
    target = Path(workdir) / "upscaled.png"
    out.save(target)
    return {"image": art("image", target)}


def run_quality_gate(env, ctx, inputs, params, workdir):
    import cf_refine
    source = _image_in(inputs)
    names = params.get("checks") or ["not_blank", "sharp", "exposure"]
    context = dict(params.get("context") or {})
    if inputs.get("reference"):
        from PIL import Image
        context["reference"] = Image.open(_image_in(inputs, "reference")["path"]).convert("RGB")
    verdicts = cf_refine.judge(source["path"], context, names)
    report = dict(passed=not cf_refine.failures(verdicts), verdicts=[dataclasses.asdict(v) for v in verdicts])
    return {"image": art("image", source["path"]), "report": art("json", value=report)}


def run_look(env, ctx, inputs, params, workdir):
    import cf_finish
    path, note = cf_finish.image_edit(_image_in(inputs)["path"], cf_finish.LOOK, params.get("look", "Cinema quente"), float(params.get("strength", 75)),
                                      None, None, params.get("format", "PNG"), workdir)
    return {"image": art("image", path, note)}


def run_frame(env, ctx, inputs, params, workdir):
    import cf_finish
    path, note = cf_finish.image_edit(_image_in(inputs)["path"], cf_finish.FRAME, None, 0, params.get("ratio"), params.get("fit", "Preencher"),
                                      params.get("format", "PNG"), workdir, tuple(params.get("focus") or (0.5, 0.5)))
    return {"image": art("image", path, note)}


def run_compare(env, ctx, inputs, params, workdir):
    import cf_finish
    _, path, note = cf_finish.compare_images(inputs["before"]["path"], inputs["after"]["path"], workdir)
    return {"image": art("image", path, note)}


def run_still(env, ctx, inputs, params, workdir):
    import cf_finish
    target = Path(workdir) / "still.png"
    cf_finish.extract_frame(inputs["video"]["path"], float(params.get("time", 0)), target)
    return {"image": art("image", target)}


def run_outpaint_pad(env, ctx, inputs, params, workdir):
    import cf_edits
    from PIL import Image
    source = _image_in(inputs)["path"]
    with Image.open(source) as image:
        plan = cf_edits.outpaint_plan(image.size, params.get("left", 0), params.get("top", 0), params.get("right", 0), params.get("bottom", 0))
        canvas, mask = cf_edits.pad_canvas(image, plan)
    canvas.save(Path(workdir) / "canvas.png")
    mask.save(Path(workdir) / "mask.png")
    return {"image": art("image", Path(workdir) / "canvas.png"), "mask": art("mask", Path(workdir) / "mask.png"), "plan": art("json", value=plan)}


def run_outpaint_stitch(env, ctx, inputs, params, workdir):
    import cf_edits
    from PIL import Image
    plan = inputs["plan"]["value"]
    with Image.open(inputs["original"]["path"]) as original, Image.open(inputs["generated"]["path"]) as generated:
        out = cf_edits.stitch(original, generated, plan, int(params.get("feather", 2)))
    out.save(Path(workdir) / "stitched.png")
    return {"image": art("image", Path(workdir) / "stitched.png")}


def run_bbox_mask(env, ctx, inputs, params, workdir):
    import cf_edits
    from PIL import Image
    with Image.open(_image_in(inputs)["path"]) as image:
        mask = cf_edits.boxes_mask(image.size, params.get("boxes") or [], int(params.get("feather", 0)))
    mask.save(Path(workdir) / "mask.png")
    return {"mask": art("mask", Path(workdir) / "mask.png")}


def run_resolution_plan(env, ctx, inputs, params, workdir):
    import cf_apps
    plan = cf_apps.resolution_plan(params.get("aspect", "1:1"), params.get("quality", "high"), env["tier"], None, float(params.get("gen_factor", 1.0)))
    return {"plan": art("json", value=plan)}


# ---- list-making and list-folding steps (fan-out sources and fan-in joins for the DAG)
MAX_LIST = 32


def _items(inputs, name):
    got = inputs.get(name)
    return got if isinstance(got, list) else ([got] if got else [])


def run_video_frames(env, ctx, inputs, params, workdir):
    import cf_finish
    path = inputs["video"]["path"]
    every = float(params.get("every_s", 1))
    limit = int(params.get("max", 8))
    duration = cf_finish.video_duration(path)
    times = [round(i * every, 3) for i in range(limit) if i * every < duration - 0.05] or [0.0]
    out = []
    for i, moment in enumerate(times, 1):
        target = Path(workdir) / f"frame-{i:02d}.png"
        cf_finish.extract_frame(path, moment, target)
        out.append(art("image", target, dict(second=moment)))
    return {"frames": out}


def expand_matrix(template, axes, limit):
    """Cartesian product of the axes filled into the template -> [(text, {axis: value})]. Raises ValueError on a bad template/axis."""
    import itertools
    names = list(axes)
    used = set(re.findall(r"\{(\w+)\}", template))
    if not used:
        raise ValueError("O modelo de frase precisa de pelo menos um {eixo}, por exemplo «um {sujeito} em {lugar}».")
    unknown = used - set(names)
    if unknown:
        raise ValueError(f"O modelo usa {{{sorted(unknown)[0]}}}, que não está nos eixos ({', '.join(names) or 'nenhum'}).")
    for name in names:
        if not isinstance(axes[name], list) or not axes[name]:
            raise ValueError(f"O eixo «{name}» precisa de uma lista com pelo menos um valor.")
    names = [n for n in names if n in used]
    total = 1
    for name in names:
        total *= len(axes[name])
    if total > limit:
        raise ValueError(f"A matriz tem {total} combinações; o limite por passo é {limit}. Reduza os valores de algum eixo.")
    rows = []
    for combo in itertools.product(*(axes[n] for n in names)):
        picked = dict(zip(names, map(str, combo)))
        rows.append((re.sub(r"\{(\w+)\}", lambda m: picked[m.group(1)], template), picked))
    return rows


def run_scenario_matrix(env, ctx, inputs, params, workdir):
    rows = expand_matrix(str(params.get("template") or ""), params.get("axes") or {}, MAX_LIST)
    return {"texts": [art("text", value=text) for text, _ in rows], "table": art("json", value=[dict(text=t, **p) for t, p in rows])}


def run_text_list(env, ctx, inputs, params, workdir):
    lines = [x.strip() for x in re.split(r"[\n;]+", str(params.get("text") or "")) if x.strip()]
    if not lines:
        raise ValueError("Escreva pelo menos uma linha de texto.")
    if len(lines) > MAX_LIST:
        raise ValueError(f"A lista tem {len(lines)} linhas; o limite por passo é {MAX_LIST}.")
    return {"texts": [art("text", value=x) for x in lines]}


def run_contact_sheet(env, ctx, inputs, params, workdir):
    import cf_character
    images = _items(inputs, "images")
    labels = list(params.get("labels") or [])
    pics = [((labels[i] if i < len(labels) else f"{i + 1}"), a["path"]) for i, a in enumerate(images)]
    sheet = cf_character.sheet(pics, int(params.get("columns", 4)))
    target = Path(workdir) / "folha.png"
    sheet.save(target)
    return {"image": art("image", target)}


def score_image(path, by):
    import numpy as np
    from PIL import Image

    import cf_refine
    with Image.open(path) as opened:
        gray = cf_refine.luma(opened)
    if by == "contrast":
        return float(gray.std())
    if by == "exposure":
        return float(-abs(float(gray.mean()) - 128.0))
    return cf_refine.laplacian_variance(np.asarray(gray))


def run_pick_best(env, ctx, inputs, params, workdir):
    by = params.get("by", "sharp")
    images = _items(inputs, "images")
    scored = sorted(((score_image(a["path"], by), i) for i, a in enumerate(images)), reverse=True)
    best = images[scored[0][1]]
    report = dict(by=by, best_index=scored[0][1], ranking=[dict(index=i, score=round(v, 3)) for v, i in scored])
    target = Path(workdir) / f"melhor{Path(best['path']).suffix}"
    shutil_copy(best["path"], target)
    return {"image": art("image", target), "report": art("json", value=report)}


def shutil_copy(src, dst):
    import shutil
    shutil.copyfile(src, dst)


def run_video_join(env, ctx, inputs, params, workdir):
    import cf_finish
    clips = [a["path"] for a in _items(inputs, "videos")]
    path, note = cf_finish.video_sequence(clips, "", params.get("ratio", "Paisagem · 16:9"), params.get("fit", "Preencher"), bool(params.get("mute", True)), workdir)
    return {"video": art("video", path, note)}


def run_loop_check(env, ctx, inputs, params, workdir):
    import cf_loop
    measured = cf_loop.seam(inputs["video"]["path"])
    measured["passed"] = measured["verdict"] in ("sem emenda visível", "emenda leve") and measured["ratio"] <= float(params.get("max_ratio", cf_loop.OK))
    return {"video": art("video", inputs["video"]["path"]), "report": art("json", value=measured)}


def run_caption(env, ctx, inputs, params, workdir):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    text = str(params.get("text") or "").strip()
    if not text:
        raise ValueError("Escreva o texto da legenda.")
    with Image.open(_image_in(inputs)["path"]) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    size = max(14, round(image.height * float(params.get("size", 5)) / 100))
    try:
        font = ImageFont.load_default(size)
    except TypeError:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(image, "RGBA")
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= image.width * 0.92 or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    lines.append(line)
    pad = round(size * 0.5)
    box = len(lines) * round(size * 1.25) + 2 * pad
    top = params.get("position", "baixo") == "cima"
    y0 = 0 if top else image.height - box
    draw.rectangle((0, y0, image.width, y0 + box), fill=(0, 0, 0, 150))
    for i, row in enumerate(lines):
        draw.text((image.width / 2, y0 + pad + i * round(size * 1.25)), row, fill=(255, 255, 255), font=font, anchor="mt")
    target = Path(workdir) / "legenda.png"
    image.save(target)
    return {"image": art("image", target)}


def run_split_grid(env, ctx, inputs, params, workdir):
    from PIL import Image, ImageOps
    cols, rows = int(params.get("columns", 2)), int(params.get("rows", 2))
    with Image.open(_image_in(inputs)["path"]) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    out = []
    for r in range(rows):
        for c in range(cols):
            box = (c * image.width // cols, r * image.height // rows, (c + 1) * image.width // cols, (r + 1) * image.height // rows)
            target = Path(workdir) / f"parte-{r * cols + c + 1:02d}.png"
            image.crop(box).save(target)
            out.append(art("image", target))
    return {"tiles": out}


def run_direction(env, ctx, inputs, params, workdir):
    import cf_director
    prompt = str(inputs["text"]["value"] if inputs.get("text") else params.get("prompt", ""))
    chosen = {cf_director.field_id(a): params.get(cf_director.field_id(a), cf_director.AUTO) for a in cf_director.AXES}
    return {"text": art("text", value=cf_director.apply(prompt, chosen))}


def run_cast_expand(env, ctx, inputs, params, workdir):
    import cf_cast
    prompt = str(inputs["text"]["value"] if inputs.get("text") else params.get("prompt", ""))
    out = cf_cast.expand(env["base"], prompt, int(params.get("ref_slots", 0)))
    return {"text": art("text", value=out["prompt"]), "info": art("json", value=out)}


def _params_upscale():
    import cf_upscale
    return {"mode": dict(type="enum", default="Lanczos (rápido, sem IA)", options=["Lanczos (rápido, sem IA)", *cf_upscale.MODELS]),
            "scale": dict(type="number", default=2, min=1, max=4), "tile": dict(type="number", default=128, min=64, max=512),
            "sharpen": dict(type="number", default=0, min=0, max=200)}



def cf_director_axes():
    import cf_director
    return list(cf_director.AXES)


def cf_director_field(axis):
    import cf_director
    return cf_director.field_id(axis)


def cf_director_options(axis):
    import cf_director
    return [v for v, _ in cf_director.options(axis)]


def native():
    import cf_finish
    cpu = dict(vram_gb=0, ram_gb=2, disk_gb=0, lane="cpu")
    tested = dict(state="TESTADO CPU", evidence="tests/test_capabilities.py: execução real em CPU com imagens reais")
    return [
        Capability("upscale", "Ampliar imagem", "1.0", "engine", "Amplia uma imagem por Lanczos ou por um modelo (Real-ESRGAN, Nomos…), em blocos.",
                   "cf_upscale (spandrel)", "pesos: licença de cada modelo; código MIT", ("enlarge", "tiled"),
                   (Port("image", "image"),), (Port("image", "image"),), _params_upscale(), ("Upscaler",),
                   dict(vram_gb=0, ram_gb=3, disk_gb=0.1, lane="cpu"), dict(state="TESTADO CPU", evidence="Lanczos e 9 modelos em CPU (V7); GPU T4 não medida"), "low", run_upscale),
        Capability("quality_gate", "Conferir qualidade técnica", "1.0", "step", "Mede nitidez, exposição, vazio e estrutura; não julga estética nem identidade.",
                   "cf_refine (método do scenario-labs, MIT)", "MIT", ("judge",),
                   (Port("image", "image"), Port("reference", "image", required=False)), (Port("image", "image"), Port("report", "json")),
                   {"checks": dict(type="list", default=["not_blank", "sharp", "exposure"], options=["not_blank", "sharp", "exposure", "size", "structure"])},
                   (), cpu, tested, "low", run_quality_gate),
        Capability("look", "Look de cor", "1.0", "step", "Aplica um look (cinema quente, frio suave, P&B, contraste).", "cf_finish", "MIT", ("grade",),
                   (Port("image", "image"),), (Port("image", "image"),),
                   {"look": dict(type="enum", default="Cinema quente", options=list(cf_finish.LOOKS)), "strength": dict(type="number", default=75, min=0, max=100),
                    "format": dict(type="enum", default="PNG", options=list(cf_finish.FORMATS))}, (), cpu, tested, "low", run_look),
        Capability("frame", "Enquadrar", "1.0", "step", "Recorta ou encaixa a imagem numa proporção de saída.", "cf_finish", "MIT", ("crop", "fit"),
                   (Port("image", "image"),), (Port("image", "image"),),
                   {"ratio": dict(type="enum", default=next(iter(cf_finish.SIZES)), options=list(cf_finish.SIZES)),
                    "fit": dict(type="enum", default="Preencher", options=["Preencher", "Manter imagem inteira"]),
                    "format": dict(type="enum", default="PNG", options=list(cf_finish.FORMATS))}, (), cpu, tested, "low", run_frame),
        Capability("compare", "Comparar antes e depois", "1.0", "step", "Monta uma prancha lado a lado com duas imagens.", "cf_finish", "MIT", ("side_by_side",),
                   (Port("before", "image"), Port("after", "image")), (Port("image", "image"),), {}, (), cpu, tested, "low", run_compare),
        Capability("still", "Extrair quadro", "1.0", "step", "Tira um quadro de um vídeo em um instante.", "cf_finish (ffmpeg)", "MIT", ("extract_frame",),
                   (Port("video", "video"),), (Port("image", "image"),), {"time": dict(type="number", default=0, min=0, max=36000)}, (), cpu, tested, "low", run_still),
        Capability("outpaint_pad", "Preparar expansão (canvas cinza)", "1.0", "step", "Coloca a imagem num canvas cinza #808080 com lados múltiplos de 32 (até 2 MP) e gera a máscara da área original.",
                   "cf_edits (receita do LoRA Outpaint do Qwen 2.1)", "MIT", ("pad", "mask"), (Port("image", "image"),),
                   (Port("image", "image"), Port("mask", "mask"), Port("plan", "json")),
                   {side: dict(type="number", default=0, min=0, max=1024) for side in ("left", "top", "right", "bottom")}, (), cpu, tested, "low", run_outpaint_pad),
        Capability("outpaint_stitch", "Colar o original de volta", "1.0", "step", "Cola os pixels originais sobre o resultado gerado, com emenda suavizada.", "cf_edits", "MIT", ("stitch",),
                   (Port("original", "image"), Port("generated", "image"), Port("plan", "json")), (Port("image", "image"),),
                   {"feather": dict(type="number", default=2, min=0, max=16)}, (), cpu, tested, "low", run_outpaint_stitch),
        Capability("bbox_mask", "Máscara a partir de caixas", "1.0", "step", "Desenha uma máscara (branco = editar) a partir de caixas em frações da imagem.", "cf_edits", "MIT", ("boxes_to_mask",),
                   (Port("image", "image"),), (Port("mask", "mask"),),
                   {"boxes": dict(type="list", default=[]), "feather": dict(type="number", default=0, min=0, max=64)}, (), cpu, tested, "low", run_bbox_mask),
        Capability("resolution_plan", "Plano de resolução", "1.0", "action", "Calcula geração nativa, ampliação e saída para uma proporção e qualidade.", "cf_apps.resolution_plan", "MIT",
                   ("plan",), (), (Port("plan", "json"),),
                   {"aspect": dict(type="string", default="1:1"), "quality": dict(type="enum", default="high", options=["standard", "high", "very_high", "ultra"]),
                    "gen_factor": dict(type="number", default=1.0, min=0.25, max=1.0)}, (), cpu, tested, "low", run_resolution_plan),

        Capability("video_frames", "Quadros de um vídeo", "1.0", "step", "Tira um quadro a cada N segundos: vira uma lista para rodar um passo por quadro.", "cf_finish (ffmpeg)", "MIT", ("extract_frames",),
                   (Port("video", "video"),), (Port("frames", "image", many=True),),
                   {"every_s": dict(type="number", default=1, min=0.1, max=60), "max": dict(type="number", default=8, min=1, max=MAX_LIST)}, (), cpu, tested, "low", run_video_frames),
        Capability("scenario_matrix", "Matriz de cenários", "1.0", "step", "Combina eixos (sujeito × lugar × hora…) num modelo de frase e devolve uma lista de pedidos.", "cf_capabilities", "MIT", ("combine",),
                   (), (Port("texts", "text", many=True), Port("table", "json")),
                   {"template": dict(type="string", default="", required=True), "axes": dict(type="dict", default={})}, (), cpu, tested, "low", run_scenario_matrix),
        Capability("text_list", "Lista de textos", "1.0", "step", "Uma linha por pedido (ou separados por «;»): a fila de prompts de um fluxo.", "cf_capabilities", "MIT", ("list",),
                   (), (Port("texts", "text", many=True),), {"text": dict(type="string", default="", required=True)}, (), cpu, tested, "low", run_text_list),
        Capability("contact_sheet", "Folha de contatos", "1.0", "step", "Junta uma lista de imagens numa grade com rótulos.", "cf_character", "MIT", ("grid",),
                   (Port("images", "image", many=True),), (Port("image", "image"),),
                   {"columns": dict(type="number", default=4, min=1, max=8), "labels": dict(type="list", default=[])}, (), cpu, tested, "low", run_contact_sheet),
        Capability("pick_best", "Escolher a melhor", "1.0", "step", "Entre várias imagens, fica com a de maior nitidez, contraste ou melhor exposição (medida técnica, não estética).", "cf_refine", "MIT", ("select",),
                   (Port("images", "image", many=True),), (Port("image", "image"), Port("report", "json")),
                   {"by": dict(type="enum", default="sharp", options=["sharp", "contrast", "exposure"])}, (), cpu, tested, "low", run_pick_best),
        Capability("video_join", "Juntar vídeos", "1.0", "step", "Emenda de 2 a 8 clipes numa sequência (ffmpeg).", "cf_finish (ffmpeg)", "MIT", ("concat",),
                   (Port("videos", "video", many=True),), (Port("video", "video"),),
                   {"ratio": dict(type="enum", default="Paisagem · 16:9", options=list(cf_finish.SEQUENCE_SIZES)), "fit": dict(type="enum", default="Preencher", options=["Preencher", "Manter imagem inteira"]),
                    "mute": dict(type="bool", default=True)}, (), cpu, tested, "low", run_video_join),
        Capability("loop_check", "Medir emenda do loop", "1.0", "step", "Mede o salto do último para o primeiro quadro contra o passo normal; `report.passed` serve de condição.", "cf_loop", "MIT", ("judge",),
                   (Port("video", "video"),), (Port("video", "video"), Port("report", "json")),
                   {"max_ratio": dict(type="number", default=3.0, min=1, max=20)}, (), cpu, tested, "low", run_loop_check),
        Capability("caption", "Legenda na imagem", "1.0", "step", "Escreve um texto numa faixa no topo ou na base.", "cf_capabilities", "MIT", ("overlay",),
                   (Port("image", "image"),), (Port("image", "image"),),
                   {"text": dict(type="string", default="", required=True), "position": dict(type="enum", default="baixo", options=["baixo", "cima"]),
                    "size": dict(type="number", default=5, min=2, max=15)}, (), cpu, tested, "low", run_caption),
        Capability("split_grid", "Fatiar em partes", "1.0", "step", "Corta a imagem em colunas × linhas iguais (o inverso da folha de contatos).", "cf_capabilities", "MIT", ("tile",),
                   (Port("image", "image"),), (Port("tiles", "image", many=True),),
                   {"columns": dict(type="number", default=2, min=1, max=6), "rows": dict(type="number", default=2, min=1, max=6)}, (), cpu, tested, "low", run_split_grid),
        Capability("direction", "Direção de cinema", "1.0", "action", "Acrescenta gênero, câmera, luz e movimento (vocabulário de cinema) ao texto.", "cf_director (OpenField, MIT)", "MIT", ("compile",),
                   (Port("text", "text", required=False),), (Port("text", "text"),),
                   {"prompt": dict(type="string", default=""), **{cf_director_field(a): dict(type="enum", default="auto", options=cf_director_options(a)) for a in cf_director_axes()}}, (), cpu, tested, "low", run_direction),
        Capability("cast_expand", "Expandir @nomes do Elenco", "1.0", "action", "Troca @nome pela descrição do personagem e devolve as fotos de referência.", "cf_cast", "MIT", ("expand",),
                   (Port("text", "text", required=False),), (Port("text", "text"), Port("info", "json")),
                   {"prompt": dict(type="string", default=""), "ref_slots": dict(type="number", default=0, min=0, max=4)}, (), cpu, tested, "low", run_cast_expand),
    ]


# ---------------------------------------------------------------- generated from the apps
PRODUCES = {"clip": "video", "sequence": "video", "text2video": "video", "animate": "video", "openjutsu": "video", "board": "image",
            "compare": "image", "seethrough": "file", "still": "image"}
RISKY = {"openjutsu": "high", "faceswap": "medium", "scail2": "medium", "bfs": "medium"}  # the agent never runs these without the user confirming in the application
APP_GPU_STATE = dict(state="BLOQUEADO_GPU", evidence="o app roda no Colab; nenhuma execução em GPU foi medida nesta máquina")


def _port_type(accept):
    kinds = {a.strip() for a in str(accept or "").split(",")}
    for kind in ("image", "video", "audio"):
        if kind in kinds:
            return kind
    return "file"


def app_capability(app, tier):
    """Wrap one App as a capability so a DAG node (and the agent) can run it. I/O types come from its form fields."""
    fields = app.fields(tier)
    inputs, params = [], {}
    for f in fields:
        if f["type"] == "files":
            inputs.append(Port(f["id"], _port_type(f.get("accept")), required=int(f.get("min", 0)) > 0, many=int(f.get("max", 1)) > 1, note=f.get("label", "")))
        elif f["type"] == "boxes":
            params[f["id"]] = dict(type="list", default=[])
        elif f["type"] == "model" and f.get("options"):  # the model is a choice the agent must be able to make
            params[f["id"]] = dict(type="enum", default=f.get("default"), options=[o["value"] if isinstance(o, dict) else o for o in f["options"]])
        elif f["type"] == "loras":
            params[f["id"]] = dict(type="list", default=[])
        elif f["type"] in ("lights", "model", "hidden"):
            continue
        elif f["type"] in ("number", "slider"):
            params[f["id"]] = dict(type="number", default=f.get("default"), min=f.get("min"), max=f.get("max"))
        elif f["type"] in ("chips", "select", "segmented", "dropdown") or f.get("options"):
            params[f["id"]] = dict(type="enum", default=f.get("default"), options=[o["value"] if isinstance(o, dict) else o for o in f.get("options", [])])
        elif f["type"] in ("switch", "checkbox", "toggle"):
            params[f["id"]] = dict(type="bool", default=bool(f.get("default")))
        else:
            params[f["id"]] = dict(type="string", default=f.get("default", ""), required=bool(f.get("required")))
    out_type = PRODUCES.get(app.id) or ("video" if app.group == "Vídeo" else "image")
    lane = "gpu" if app.lane == "gpu" else "cpu"
    state = APP_GPU_STATE if lane == "gpu" else dict(state="TESTADO CPU", evidence="app de CPU executado nos testes de V6/V7")
    return Capability(f"app.{app.id}", app.title, "1.0", "app", app.tagline, "cf_apps", "ver a nota do app", (app.id,), tuple(inputs),
                      (Port("result", out_type),), params, (), dict(vram_gb=app.min_vram, ram_gb=3 if lane == "cpu" else 8, disk_gb=0, lane=lane, offload=bool(app.offload)),
                      state, RISKY.get(app.id, "low"), None)


# ---------------------------------------------------------------- bindings: who uses what
# (capability, app, mode, note). `mode`: "app" = the app is this capability's own screen, "step" = used inside the app,
# "insertion" = the app lets the user (or the agent) add it around its own result. Checked against the real registry by tests.
BINDINGS = [
    ("upscale", "upscale", "app", "tela dedicada de ampliação"),
    ("upscale", "create", "step", "«Resolução final» amplia em blocos até o tamanho pedido"),
    ("upscale", "edit", "step", "«Ampliar depois»"),
    ("quality_gate", "create", "step", "conferência técnica e laço de reparo com teto de rodadas"),
    ("quality_gate", "edit", "step", "mesma conferência, com referência de estrutura"),
    ("look", "look", "app", "tela dedicada de look"),
    ("frame", "frame", "app", "tela dedicada de enquadramento"),
    ("compare", "compare", "app", "tela dedicada de comparação"),
    ("still", "still", "app", "tela dedicada de quadro"),
    ("resolution_plan", "create", "step", "mostra «Geração → ampliação → saída»"),
    ("bbox_mask", "region", "step", "as caixas desenhadas viram a máscara da edição"),
    ("outpaint_pad", "outpaint", "step", "prepara o canvas cinza antes do Qwen + LoRA"),
    ("outpaint_stitch", "outpaint", "step", "cola o original de volta depois da geração"),
]
# Where an app accepts more steps around its result: after producing `point`, these capabilities may be chained.
INSERTION_POINTS = [
    ("create", [dict(point="after:image", accepts=["upscale", "quality_gate", "look", "frame", "compare"])]),
    ("edit", [dict(point="after:image", accepts=["upscale", "quality_gate", "look", "frame", "compare"])]),
    ("animate", [dict(point="before:image", accepts=["frame", "look", "upscale"]), dict(point="after:video", accepts=["still"])]),
    ("text2video", [dict(point="after:video", accepts=["still"])]),
]


class Registry:
    def __init__(self, apps=None, tier=None):
        self.items = {c.id: c for c in native()}
        if apps:
            for app in apps.values():
                if not app.hidden:
                    cap = app_capability(app, tier)
                    self.items[cap.id] = cap
        self.apps = apps or {}

    def get(self, cap_id):
        if cap_id not in self.items:
            raise KeyError(cap_id)
        return self.items[cap_id]

    def describe(self, cap_id):
        return self.items[cap_id].public(BINDINGS, INSERTION_POINTS)

    def catalog(self, kind=None, query=None, produces=None, accepts=None):
        """Filterable listing. `produces`/`accepts` are media types; a query matches id, title and tagline."""
        out = []
        for cap in self.items.values():
            if kind and cap.kind != kind:
                continue
            if query and not all(w in f"{cap.id} {cap.title} {cap.tagline} {' '.join(cap.ops)}".lower() for w in query.lower().split()):
                continue
            if produces and not any(p.type == produces for p in cap.outputs):
                continue
            if accepts and not any(p.type == accepts for p in cap.inputs):
                continue
            out.append(self.describe(cap.id))
        return out


def check_params(cap, params):
    """Reasons a params dict is not acceptable for the capability (unknown name, out of range, not in the options)."""
    problems = []
    for name, value in (params or {}).items():
        spec = cap.params.get(name)
        if spec is None:
            problems.append(f"«{name}» não é um parâmetro de {cap.id} (aceita: {', '.join(cap.params) or 'nenhum'})")
            continue
        kind = spec.get("type")
        if kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append(f"«{name}» precisa ser número")
            elif (spec.get("min") is not None and value < spec["min"]) or (spec.get("max") is not None and value > spec["max"]):
                problems.append(f"«{name}»={value} fora de {spec.get('min')}–{spec.get('max')}")
        elif kind == "enum" and spec.get("options") and value not in spec["options"]:
            problems.append(f"«{name}»={value!r} não está nas opções ({', '.join(map(str, spec['options'][:6]))}…)")
        elif kind == "list" and not isinstance(value, list):
            problems.append(f"«{name}» precisa ser uma lista")
        elif kind == "list" and spec.get("options") and any(v not in spec["options"] for v in value):
            problems.append(f"«{name}» tem valor fora das opções ({', '.join(spec['options'])})")
        elif kind == "dict" and not isinstance(value, dict):
            problems.append(f"«{name}» precisa ser um objeto {{nome: valores}}")
        elif kind == "string" and not isinstance(value, str):
            problems.append(f"«{name}» precisa ser texto")
        elif kind == "bool" and not isinstance(value, bool):
            problems.append(f"«{name}» precisa ser verdadeiro ou falso")
    return problems


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
