"""Direção: cinema vocabulary (genre, lens, framing, light, film stock, look, grade) compiled into the prompt of an image or video app.

Idea and structure adapted from the Director app of OpenField (github.com/wexloops/openfield, MIT, Copyright (c) 2026 David Wexler /
Strangeloop Studios): a genre sets sensible defaults for the other axes, anything the user picks explicitly wins, and the compiled prompt is
plain text. The option wording here is the Studio's own. Pure text code, tested on CPU; whether a given model follows a "50mm f/2" or
"bleach-bypass" phrase is a property of the model and is NOT measured here (BLOQUEADO_GPU).

With every axis on "auto" the prompt is returned untouched, so existing behaviour does not change.
"""

AUTO = "auto"

# axis id -> (label in Portuguese, [(option id, label in Portuguese, English text for the model)])
AXES = {
    "genre": ("Gênero", [
        ("drama", "Drama", "intimate character drama, naturalistic performances, emotion carried by small gestures"),
        ("noir", "Noir", "film noir, deep shadows, smoke and window-blind light, a city that keeps its secrets"),
        ("horror", "Terror", "horror film, slow creeping tension, the camera lingers on what should not be there"),
        ("action", "Ação", "high-energy action film, kinetic momentum, debris and speed, bodies in motion"),
        ("comedy", "Comédia", "bright comedy, playful timing, warm open frames, expressive faces"),
        ("epic", "Épico", "sweeping epic, mythic scale, vast landscapes with tiny figures"),
        ("scifi", "Ficção científica", "science fiction, cold engineered spaces, the future made physical"),
    ]),
    "camera": ("Câmera e lente", [
        ("large-format", "Grande formato · 50 mm f/2", "shot on a large-format digital cinema camera, 50mm lens at f/2, shallow depth of field"),
        ("anamorphic", "Anamórfica · 40 mm", "anamorphic 40mm lens, oval bokeh, horizontal flares, widescreen feel"),
        ("wide-prime", "Grande-angular · 24 mm", "24mm wide prime lens, deep focus, the environment in frame"),
        ("tele", "Teleobjetiva · 135 mm", "135mm telephoto lens, compressed background, creamy falloff"),
        ("16mm", "Câmera 16 mm", "shot on a 16mm film camera, handheld intimacy, visible grain"),
        ("vintage", "Lente antiga", "vintage uncoated lens, soft halation, gentle vignette"),
    ]),
    "framing": ("Enquadramento", [
        ("wide", "Geral", "wide establishing shot"),
        ("medium", "Plano médio", "medium shot, waist up"),
        ("close", "Close-up", "close-up on the face"),
        ("ecu", "Detalhe", "extreme close-up on a detail"),
        ("ots", "Sobre o ombro", "over-the-shoulder shot"),
        ("low", "Contra-plongée", "low-angle shot looking up, heroic"),
        ("high", "Plongée", "high-angle shot looking down"),
        ("top", "Zenital", "top-down overhead shot"),
    ]),
    "light": ("Luz", [
        ("golden", "Hora dourada", "warm low golden-hour sun, long shadows"),
        ("overcast", "Nublado suave", "soft overcast daylight, gentle wraparound light"),
        ("practical", "Noite com luz de cena", "night lit only by practical lamps and signs, pools of light"),
        ("hard", "Meio-dia duro", "hard midday sun, crisp black shadows"),
        ("neon", "Neon", "saturated neon light with magenta and cyan spill"),
        ("candle", "Luz de vela", "flickering candlelight, warm falloff into darkness"),
        ("moon", "Luar", "cold blue moonlight, silver rim light"),
        ("chiaroscuro", "Claro-escuro", "a single hard key light, deep chiaroscuro shadows"),
    ]),
    "film": ("Filme", [
        ("500t", "Tungstênio 500T", "tungsten-balanced 500T motion picture film, fine grain, cool shadows"),
        ("250d", "Luz do dia 250D", "daylight 250D motion picture film, natural colour"),
        ("reversal", "Slide (reversível)", "colour reversal slide film, rich saturation, deep blacks"),
        ("bw", "Preto e branco 400", "black and white 400-speed film, strong grain, silver tones"),
        ("digital", "Digital limpo", "clean digital cinema image, no grain"),
    ]),
    "look": ("Atmosfera", [
        ("noir", "Neo-noir", "neo-noir mood, rain-slick streets, menace"),
        ("epic", "Épica", "epic scale, vastness, awe"),
        ("horror", "Pavor", "quiet dread, negative space, something wrong in the frame"),
        ("doc", "Documental", "observational documentary realism"),
        ("dream", "Onírica", "dreamlike and uncanny, soft surreal atmosphere"),
        ("scifi", "Ficção dura", "hard science fiction, practical-looking machinery"),
    ]),
    "grade": ("Correção de cor", [
        ("teal", "Azul-petróleo e laranja", "teal and orange colour grade"),
        ("bleach", "Bleach bypass", "bleach-bypass grade, low saturation, high contrast"),
        ("pastel", "Pastel quente", "warm pastel grade, lifted blacks"),
        ("steel", "Aço frio", "cold steel-blue grade"),
        ("mono", "Monocromático", "monochrome grade"),
        ("natural", "Natural", "natural, true-to-life colour"),
    ]),
}
ORDER = ("genre", "framing", "camera", "light", "film", "look", "grade")  # the order the phrases join the prompt

# What a genre fills in on the axes the user left on auto.
GENRE_DEFAULTS = {
    "drama": dict(camera="large-format", light="overcast", grade="natural"),
    "noir": dict(light="chiaroscuro", film="bw", look="noir", grade="mono"),
    "horror": dict(light="moon", look="horror", grade="steel"),
    "action": dict(camera="anamorphic", light="hard", grade="teal"),
    "comedy": dict(camera="wide-prime", light="golden", grade="pastel"),
    "epic": dict(camera="anamorphic", light="golden", look="epic"),
    "scifi": dict(light="neon", look="scifi", grade="steel"),
}
FIELD = "dir_{axis}"


def field_id(axis):
    return FIELD.format(axis=axis)


def options(axis):
    """[(value, label)] for the form, with the 'auto' entry first."""
    return [(AUTO, "Automático")] + [(oid, label) for oid, label, _ in AXES[axis][1]]


def text_of(axis, option):
    for oid, _label, text in AXES[axis][1]:
        if oid == option:
            return text
    raise ValueError(f"Opção desconhecida em {AXES[axis][0]}: {option}.")


def picks_from(params):
    """{axis: option} from a job's parameters (`dir_<axis>`), 'auto' where missing. Raises ValueError on an unknown option."""
    picks = {}
    for axis in AXES:
        value = (params.get(field_id(axis)) or AUTO)
        if value != AUTO:
            text_of(axis, value)  # validates
        picks[axis] = value
    return picks


def effective(picks):
    """The genre's defaults under the user's explicit picks: explicit wins."""
    merged = dict(GENRE_DEFAULTS.get(picks.get("genre", AUTO), {}))
    merged.update({axis: value for axis, value in picks.items() if value != AUTO})
    return merged


def direction(picks):
    merged = effective(picks)
    return [text_of(axis, merged[axis]) for axis in ORDER if merged.get(axis)]


def compile_prompt(parts):
    """Join phrases into sentences: each trimmed, ended with a full stop unless it already ends in punctuation."""
    out = []
    for part in parts:
        part = (part or "").strip()
        if part:
            out.append(part if part[-1] in ".!?" else part + ".")
    return " ".join(out)


def apply(prompt, params):
    """The user's prompt followed by the chosen direction. Unchanged when every axis is on auto."""
    phrases = direction(picks_from(params))
    return compile_prompt([prompt, *phrases]) if phrases else prompt
