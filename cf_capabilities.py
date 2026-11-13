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


def _params_upscale():
    import cf_upscale
    return {"mode": dict(type="enum", default="Lanczos (rápido, sem IA)", options=["Lanczos (rápido, sem IA)", *cf_upscale.MODELS]),
            "scale": dict(type="number", default=2, min=1, max=4), "tile": dict(type="number", default=128, min=64, max=512),
            "sharpen": dict(type="number", default=0, min=0, max=200)}


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
    ]


# ---------------------------------------------------------------- generated from the apps
PRODUCES = {"clip": "video", "sequence": "video", "text2video": "video", "animate": "video", "openjutsu": "video", "board": "image",
            "compare": "image", "seethrough": "file", "still": "image"}
RISKY = {"openjutsu": "high", "faceswap": "medium"}  # the agent never runs these without the user confirming in the application
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
        elif f["type"] in ("lights", "loras", "model", "hidden"):
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
                      (Port("result", out_type),), params, (), dict(vram_gb=app.min_vram, ram_gb=3 if lane == "cpu" else 8, disk_gb=0, lane=lane),
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
        elif kind == "bool" and not isinstance(value, bool):
            problems.append(f"«{name}» precisa ser verdadeiro ou falso")
    return problems


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
