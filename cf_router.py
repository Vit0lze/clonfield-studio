"""Capability router: which Studio app should handle this request next?

Contract adapted from BillionsBobby/JevRouter (MIT, b1cdf80): a decision provider returns a probability distribution
over typed candidates; the router owns availability, permissions and confirmation around it. Filtered candidates are
never re-normalised: the provider's probabilities stay untouched and availability lives under `router`.
Decision-only: nothing is executed here.

Provider in use: LocalProvider (keyword + media-kind evidence, deterministic, offline). The remote Jev provider is NOT
wired: it needs a TYPESAFE_API_KEY/OPENROUTER_API_KEY that this project does not have, and this module makes no claim
about its output.
"""

import math
import re
import unicodedata

# app id -> (media kinds the app needs among the user's attachments, evidence keywords, risk)
CAPABILITIES = {
    "create": (set(), "criar gerar imagem foto desenho ilustracao arte create generate image picture draw render", "low"),
    "edit": ({"image"}, "editar mudar trocar alterar tirar remover adicionar edit change replace remove add modify", "low"),
    "relight": ({"image"}, "luz iluminacao iluminar sombra relight lighting light shadow", "low"),
    "portrait": ({"image"}, "rosto identidade pessoa retrato pose face identity portrait person same", "low"),
    "region": ({"image"}, "mascara pintar regiao area retocar apenas somente so mask inpaint region retouch only", "low"),
    "animate": ({"image"}, "animar movimento mover camera video animate motion move", "low"),
    "text2video": (set(), "video clipe cena filmar text2video clip film movie", "low"),
    "upscale": ({"image"}, "ampliar aumentar resolucao upscale enlarge bigger resolution", "low"),
    "seedvr2": ({"image"}, "restaurar nitidez detalhe melhorar qualidade restore sharpen enhance detail", "low"),
    "seethrough": ({"image"}, "camadas psd anime layers transparencia separar partes rigging live2d decompose", "low"),
    "look": ({"image"}, "cor contraste filtro look grade tom color contrast filter tone", "low"),
    "frame": ({"image"}, "enquadrar proporcao recortar story reels feed frame crop ratio aspect", "low"),
    "clip": ({"video"}, "cortar trecho recortar clip cut trim", "low"),
    "still": ({"video"}, "extrair quadro frame captura still screenshot", "low"),
    "board": ({"video"}, "prancha storyboard momentos cenas board contact sheet", "low"),
    "sequence": ({"video"}, "juntar unir concatenar sequencia montar join merge concatenate sequence", "low"),
    "compare": ({"image"}, "comparar antes depois lado compare before after side", "low"),
    "openjutsu": ({"video", "image"}, "trocar personagem swap substituir pessoa no video replace character", "high"),
}


def tokens(text):
    text = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return set(re.findall(r"[a-z0-9]+", text))


def local_provider(request, media):
    """Probabilities over every capability. Media kinds are hard evidence, keywords soft evidence."""
    words = tokens(request)
    scores = {}
    for app_id, (needs, keywords, _risk) in CAPABILITIES.items():
        hits = len(words & tokens(keywords))
        score = 1.2 * hits
        if needs and needs <= media:
            score += 0.8
        elif needs:
            score -= 3.0  # cannot run without that media
        elif not needs and not media and app_id == "create":
            score += 0.5
        scores[app_id] = score
    top = max(scores.values())
    exp = {k: math.exp(v - top) for k, v in scores.items()}
    total = sum(exp.values())
    return {k: v / total for k, v in exp.items()}


def route(request, media, registry, tier, installed_nodes=None, provider=local_provider):
    """Return ranked candidates. `media` is a set of kinds: image, video, audio."""
    request = (request or "").strip()
    if not request and not media:
        raise ValueError("Descreva o que quer fazer ou anexe uma mídia.")
    media = set(media or ())
    probs = provider(request, media)
    ranked = []
    for app_id, p in sorted(probs.items(), key=lambda kv: -kv[1]):
        app = registry.get(app_id)
        if app is None:
            continue
        reasons = []
        if app.min_vram and tier.vram_gb < app.min_vram:
            reasons.append(f"precisa de ~{app.min_vram} GB de VRAM; a placa tem {tier.vram_gb:.0f} GB")
        needs = CAPABILITIES[app_id][0]
        if needs and not needs <= media:
            reasons.append("faltam mídias: " + ", ".join(sorted(needs - media)))
        risk = CAPABILITIES[app_id][2]
        ranked.append(dict(app=app_id, title=app.title, probability=round(p, 4),
                           router=dict(available=not reasons, reasons=reasons, risk=risk,
                                       confirm=risk in ("medium", "high"))))
    available = [c for c in ranked if c["router"]["available"]]
    return dict(request=request, media=sorted(media), provider="local", candidates=ranked,
                choice=available[0]["app"] if available else None)
