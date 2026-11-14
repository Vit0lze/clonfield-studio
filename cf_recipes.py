"""Recipes: ready-made DAGs with a small form. Each recipe builds a typed graph (cf_dag) from a few variables, so the same engine runs it,
validates it, caches it per step and per item, and the agent can list and run it.

Fan-out (`each`) is what makes a recipe a queue: one step runs once per item, each item cached on its own.

STATE (honest): the CPU recipes run for real in tests/test_recipes.py (real images, real ffmpeg clips, real U²-Net). The GPU recipes are
validated structurally against the real capability registry (types, ports, parameters) but were never generated here: BLOQUEADO_GPU.
"""

import dataclasses
import re

import cf_character
import cf_director
import cf_finish

MAX_BATCH = 12  # variable sets queued by one request
KINDS = ("image", "images", "video", "videos", "text", "lines", "number", "enum", "bool")


@dataclasses.dataclass
class Recipe:
    id: str
    title: str
    tagline: str
    group: str
    inputs: list
    build: object
    gpu: bool = False
    state: str = "TESTADO CPU"
    evidence: str = ""

    def public(self):
        return dict(id=self.id, title=self.title, tagline=self.tagline, group=self.group, inputs=self.inputs, lane="gpu" if self.gpu else "cpu",
                    state=self.state, evidence=self.evidence, steps=len(self.build(self.defaults(), preview=True)["nodes"]))

    def defaults(self):
        out = {}
        for spec in self.inputs:
            if spec["kind"] in ("image", "images", "video", "videos"):
                out[spec["id"]] = "preview" if spec["kind"] in ("image", "video") else ["preview"]
            else:
                out[spec["id"]] = spec.get("default")
        return out


def resolve(recipe, raw):
    """Check the form values against the recipe's inputs. Raises ValueError with the reason in plain language."""
    raw = raw or {}
    out = {}
    for spec in recipe.inputs:
        key, label = spec["id"], spec.get("label", spec["id"])
        value = raw.get(key, spec.get("default"))
        kind = spec["kind"]
        if kind in ("image", "video"):
            if not isinstance(value, str) or not re.fullmatch(r"[\w-]{1,64}", value):
                raise ValueError(f"«{label}»: envie {'uma imagem' if kind == 'image' else 'um vídeo'}.")
        elif kind in ("images", "videos"):
            value = value if isinstance(value, list) else ([value] if value else [])
            low, high = spec.get("min", 1), spec.get("max", 8)
            if not low <= len(value) <= high or any(not re.fullmatch(r"[\w-]{1,64}", str(v)) for v in value):
                raise ValueError(f"«{label}»: envie de {low} a {high} arquivos.")
        elif kind in ("text", "lines"):
            value = str(value or "").strip()
            if spec.get("required", True) and not value:
                raise ValueError(f"«{label}»: escreva um texto.")
            if kind == "lines":
                rows = [x for x in re.split(r"[\n;]+", value) if x.strip()]
                if not spec.get("min", 1) <= len(rows) <= spec.get("max", 12):
                    raise ValueError(f"«{label}»: use de {spec.get('min', 1)} a {spec.get('max', 12)} linhas.")
        elif kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not spec.get("min", float("-inf")) <= value <= spec.get("max", float("inf")):
                raise ValueError(f"«{label}»: use um número de {spec.get('min')} a {spec.get('max')}.")
        elif kind == "enum":
            if value not in spec["options"]:
                raise ValueError(f"«{label}»: escolha uma das opções ({', '.join(map(str, spec['options']))}).")
        elif kind == "bool":
            value = bool(value)
        out[key] = value
    return out


def medias(ids):
    return [{"media": i} for i in ids]


# ---------------------------------------------------------------- CPU recipes
def build_polish(v, preview=False):
    return {"nodes": [
        dict(id="frame", label="Enquadrar cada imagem", cap="frame", each="image", inputs={"image": medias(v["images"])}, params=dict(ratio=v["ratio"], fit="Preencher")),
        dict(id="look", label="Aplicar o look em cada uma", cap="look", each="image", inputs={"image": {"from": "frame.image"}}, params=dict(look=v["look"], strength=v["strength"])),
        dict(id="sheet", label="Folha de contatos", cap="contact_sheet", inputs={"images": {"from": "look.image"}}, params=dict(columns=4)),
        dict(id="best", label="Escolher a mais nítida", cap="pick_best", inputs={"images": {"from": "look.image"}}, params=dict(by="sharp")),
    ]}


def build_looks(v, preview=False):
    looks = list(cf_finish.LOOKS)
    return {"nodes": [
        dict(id="names", label="Os looks", cap="text_list", params=dict(text="\n".join(looks))),
        dict(id="graded", label="Um look por vez", cap="look", each="look", inputs={"image": {"media": v["image"]}}, bind={"look": "names.texts"}, params=dict(strength=v["strength"])),
        dict(id="sheet", label="Lado a lado", cap="contact_sheet", inputs={"images": {"from": "graded.image"}}, params=dict(columns=4, labels=looks)),
        dict(id="best", label="Maior contraste", cap="pick_best", inputs={"images": {"from": "graded.image"}}, params=dict(by="contrast")),
    ]}


def build_frames(v, preview=False):
    return {"nodes": [
        dict(id="frames", label="Quadros do vídeo", cap="video_frames", inputs={"video": {"media": v["video"]}}, params=dict(every_s=v["every_s"], max=v["max"])),
        dict(id="sheet", label="Folha de quadros", cap="contact_sheet", inputs={"images": {"from": "frames.frames"}}, params=dict(columns=4)),
        dict(id="best", label="Quadro mais nítido", cap="pick_best", inputs={"images": {"from": "frames.frames"}}, params=dict(by="sharp")),
    ]}


def build_sequence(v, preview=False):
    return {"nodes": [
        dict(id="join", label="Juntar os clipes", cap="video_join", inputs={"videos": medias(v["videos"])}, params=dict(ratio=v["ratio"], fit="Preencher", mute=v["mute"])),
        dict(id="seam", label="Medir a volta ao início", cap="loop_check", inputs={"video": {"from": "join.video"}}),
    ]}


def build_cutouts(v, preview=False):
    return {"nodes": [
        dict(id="cut", label="Remover o fundo de cada uma", cap="app.removebg", each="image", inputs={"image": medias(v["images"])}, params=dict(model="u2netp", background=v["background"])),
        dict(id="sheet", label="Folha de recortes", cap="contact_sheet", inputs={"images": {"from": "cut.result"}}, params=dict(columns=4)),
    ]}


# ---------------------------------------------------------------- GPU recipes (structure validated, nothing generated here)
def build_matrix(v, preview=False):
    genre = v["genre"]
    return {"nodes": [
        dict(id="matrix", label="Combinar os cenários", cap="scenario_matrix", params=dict(
            template=v["template"], axes={"a": [x.strip() for x in re.split(r"[\n;]+", v["axis_a"]) if x.strip()], "b": [x.strip() for x in re.split(r"[\n;]+", v["axis_b"]) if x.strip()]})),
        dict(id="direct", label="Direção de cinema", cap="direction", each="text", inputs={"text": {"from": "matrix.texts"}}, params={"dir_genre": genre}),
        dict(id="make", label="Uma imagem por cenário", cap="app.create", each="prompt", bind={"prompt": "direct.text"}, params=dict(aspect=v["aspect"], quality="standard", variations=1)),
        dict(id="sheet", label="Folha de cenários", cap="contact_sheet", inputs={"images": {"from": "make.result"}}, params=dict(columns=3)),
        dict(id="best", label="Mais nítida", cap="pick_best", inputs={"images": {"from": "make.result"}}, params=dict(by="sharp")),
    ]}


def build_cast_scene(v, preview=False):
    return {"nodes": [
        dict(id="make", label="Gerar a cena", cap="app.create", params=dict(prompt=v["prompt"], aspect=v["aspect"], quality="standard", variations=1, dir_genre=v["genre"])),
        dict(id="gate", label="Conferir a qualidade", cap="quality_gate", inputs={"image": {"from": "make.result"}}, params=dict(checks=["not_blank", "sharp", "exposure"])),
        dict(id="up", label="Ampliar se passou", cap="upscale", inputs={"image": {"from": "make.result"}}, when={"from": "gate.report", "path": "passed", "equals": True}, params=dict(scale=2)),
    ]}


def build_loop(v, preview=False):
    return {"nodes": [
        dict(id="clip", label="Animar até voltar ao começo", cap="app.flf2v", inputs={"image": {"media": v["image"]}}, params=dict(loop=True, prompt=v["prompt"], seconds=v["seconds"], fast=True)),
        dict(id="seam", label="Medir a emenda", cap="loop_check", inputs={"video": {"from": "clip.result"}}),
    ]}


def build_story_clips(v, preview=False):
    return {"nodes": [
        dict(id="shots", label="Os planos", cap="text_list", params=dict(text=v["shots"])),
        dict(id="direct", label="Direção de cinema", cap="direction", each="text", inputs={"text": {"from": "shots.texts"}}, params={"dir_genre": v["genre"]}),
        dict(id="still", label="Imagem de cada plano", cap="app.create", each="prompt", bind={"prompt": "direct.text"}, params=dict(aspect="16:9", quality="standard", variations=1)),
        dict(id="move", label="Animar cada imagem", cap="app.animate", each="image", inputs={"image": {"from": "still.result"}}, params=dict(prompt=v["motion"], seconds=v["seconds"], fast=True)),
        dict(id="film", label="Juntar o filme", cap="video_join", inputs={"videos": {"from": "move.result"}}, params=dict(ratio="Paisagem · 16:9", fit="Preencher", mute=True)),
    ]}


def build_character(v, preview=False):
    return {"nodes": [
        dict(id="cut", label="Tirar o fundo", cap="app.removebg", inputs={"image": {"media": v["image"]}}, params=dict(model="u2netp", background="Transparente")),
        dict(id="sheet", label="Folha de personagem", cap="app.character_sheet", inputs={"image": {"from": "cut.result"}}, params=dict(set=v["set"])),
        dict(id="grade", label="Ampliar a folha", cap="upscale", inputs={"image": {"from": "sheet.result"}}, params=dict(scale=2)),
    ]}


def _enum(id_, label, options, default=None):
    return dict(id=id_, kind="enum", label=label, options=list(options), default=default if default is not None else list(options)[0])


RATIOS = list(cf_finish.SIZES)
GENRES = [v for v, _ in cf_director.options("genre")]

RECIPES = {r.id: r for r in [
    Recipe("polir_lote", "Polir um lote de imagens", "Enquadra e dá o mesmo look a até 16 imagens, uma de cada vez; monta a folha e separa a mais nítida.", "Lote",
           [dict(id="images", kind="images", label="Imagens", min=1, max=16), _enum("ratio", "Proporção", RATIOS), _enum("look", "Look", cf_finish.LOOKS),
            dict(id="strength", kind="number", label="Intensidade do look", min=0, max=100, default=70)], build_polish,
           evidence="tests/test_recipes.py: 4 imagens reais, 2 passos por item, cache por item"),
    Recipe("looks_lado_a_lado", "Todos os looks lado a lado", "Aplica cada look à mesma imagem e mostra a grade para você escolher.", "Lote",
           [dict(id="image", kind="image", label="Imagem"), dict(id="strength", kind="number", label="Intensidade", min=0, max=100, default=80)], build_looks,
           evidence="tests/test_recipes.py: 4 looks reais ligados por bind"),
    Recipe("folha_de_quadros", "Folha de quadros de um vídeo", "Tira um quadro a cada N segundos, monta a folha e indica o mais nítido (bom para capa).", "Vídeo",
           [dict(id="video", kind="video", label="Vídeo"), dict(id="every_s", kind="number", label="Um quadro a cada (s)", min=0.1, max=60, default=1),
            dict(id="max", kind="number", label="Quadros no máximo", min=1, max=32, default=8)], build_frames, evidence="tests/test_recipes.py: clipe real do ffmpeg"),
    Recipe("clipes_em_sequencia", "Clipes em sequência", "Emenda de 2 a 8 clipes no mesmo formato e mede a volta ao início do resultado.", "Vídeo",
           [dict(id="videos", kind="videos", label="Clipes", min=2, max=8), _enum("ratio", "Formato", cf_finish.SEQUENCE_SIZES), dict(id="mute", kind="bool", label="Sem som", default=True)],
           build_sequence, evidence="tests/test_recipes.py: 2 clipes reais emendados"),
    Recipe("recortes_em_lote", "Recortes em lote", "Remove o fundo de várias imagens (U²-Net no CPU) e junta numa folha.", "Lote",
           [dict(id="images", kind="images", label="Imagens", min=1, max=12), _enum("background", "Fundo", ["Transparente", "Branco", "Preto"])], build_cutouts,
           evidence="tests/test_recipes.py: U²-Net real (u2netp) em CPU"),
    Recipe("cenarios_em_matriz", "Cenários em matriz", "Combina dois eixos (ex.: personagem × lugar), aplica a direção de cinema e gera uma imagem por combinação.", "Criar",
           [dict(id="template", kind="text", label="Frase com {a} e {b}", default="{a} em {b}"), dict(id="axis_a", kind="lines", label="Valores de {a} (um por linha)", min=1, max=6, default="uma detetive\num robô velho"),
            dict(id="axis_b", kind="lines", label="Valores de {b} (um por linha)", min=1, max=6, default="um beco chuvoso\numa estação vazia"), _enum("genre", "Gênero", GENRES, "noir"),
            _enum("aspect", "Proporção", ["1:1", "16:9", "9:16", "4:5"], "16:9")], build_matrix, gpu=True, state="BLOQUEADO_GPU",
           evidence="grafo validado contra o registro real; nenhuma imagem gerada aqui"),
    Recipe("cena_com_elenco", "Cena com @elenco e conferência", "Gera a cena (os @nomes viram personagens do Elenco), confere a qualidade e só amplia se passar.", "Criar",
           [dict(id="prompt", kind="text", label="Cena (use @nome)", default="@Mira corre na chuva"), _enum("genre", "Gênero", GENRES, "drama"), _enum("aspect", "Proporção", ["1:1", "16:9", "9:16", "4:5"], "16:9")],
           build_cast_scene, gpu=True, state="BLOQUEADO_GPU", evidence="grafo validado; condição `when` testada em CPU com outro gerador"),
    Recipe("loop_de_imagem", "Imagem em loop perfeito", "Anima uma imagem de volta a ela mesma (Wan 2.2, rápido) e mede se a emenda aparece.", "Vídeo",
           [dict(id="image", kind="image", label="Imagem"), dict(id="prompt", kind="text", label="Movimento", default="slow gentle camera drift, subtle motion"),
            dict(id="seconds", kind="number", label="Duração (s)", min=2, max=5, default=3)], build_loop, gpu=True, state="BLOQUEADO_GPU", evidence="grafo validado; medidor testado com clipes reais"),
    Recipe("storyboard_em_filme", "Storyboard em filme", "Uma linha por plano: cada um vira imagem, depois clipe, e os clipes são emendados.", "Vídeo",
           [dict(id="shots", kind="lines", label="Planos (um por linha)", min=2, max=6, default="uma mulher abre uma porta velha\nela lê uma carta sobre a mesa\na luz da sala se apaga"),
            dict(id="motion", kind="text", label="Movimento dos clipes", default="slow push in, subtle motion"), _enum("genre", "Gênero", GENRES, "drama"),
            dict(id="seconds", kind="number", label="Segundos por clipe", min=2, max=5, default=3)], build_story_clips, gpu=True, state="BLOQUEADO_GPU",
           evidence="grafo validado; junção testada com clipes reais"),
    Recipe("personagem_pronto", "Personagem pronto para usar", "Tira o fundo, monta a folha de vistas (offload de 24 GB) e amplia.", "Criar",
           [dict(id="image", kind="image", label="Imagem do personagem"), _enum("set", "Conjunto de vistas", list(cf_character.SETS))], build_character, gpu=True, state="BLOQUEADO_GPU",
           evidence="grafo validado; recorte testado com U²-Net real"),
]}


def get(recipe_id):
    if recipe_id not in RECIPES:
        raise KeyError(recipe_id)
    return RECIPES[recipe_id]


def catalog():
    return [r.public() for r in RECIPES.values()]


def graph_for(recipe_id, raw):
    recipe = get(recipe_id)
    return recipe.build(resolve(recipe, raw))
