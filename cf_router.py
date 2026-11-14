"""Capability router: which Studio app should handle this request next?

Contract adapted from BillionsBobby/JevRouter (MIT, b1cdf80): a decision provider returns a probability distribution
over typed candidates; the router owns availability, permissions and confirmation around it. Filtered candidates are
never re-normalised: the provider's probabilities stay untouched and availability lives under `router`.
Decision-only: nothing is executed here.

Providers: jev_provider (TypeSafe Jev, one typed Choice question; token from TYPESAFE_API_TOKEN / TYPESAFE_API_KEY /
JEV_API_KEY) and local_provider (keyword + media-kind evidence, offline, used when no token or the call fails).
Jev is text-only: only the request text and the NAMES of attached media kinds are sent, never the media.
"""

import os
import requests

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
    "outpaint": ({"image"}, "expandir estender aumentar o fundo bordas lados cena outpaint expand extend canvas wider", "low"),
    "restore": ({"image"}, "restaurar foto antiga riscos poeira desfoque ruido recuperar restore old scratches dust denoise", "low"),
    "outfit": ({"image"}, "roupa vestir trocar roupa figurino outfit dress clothes swap wear", "low"),
    "faceswap": ({"image"}, "trocar rosto cara face swap deepfake colocar rosto substituir rosto", "medium"),
    "audio": (set(), "audio som efeito sonoro musica trilha ambiente loop sfx barulho sound music track ambience", "low"),
    "image3d": ({"image"}, "3d modelo malha glb objeto tridimensional mesh trellis pixal3d model", "low"),
    "moss": (set(), "caixas layout posicionar letreiro texto na imagem bbox boxes layout cartaz poster redesenhar area", "low"),
    "scail2": ({"video", "image"}, "substituir personagem trocar personagem no video scail pose replace character swap actor", "medium"),
    "animate2": ({"video", "image"}, "animar personagem seguir movimento dancar imitar movimento animate character motion transfer dance", "low"),
    "bfs": ({"image"}, "trocar cabeca corpo inteiro cabeca bfs head swap body swap substituir cabeca", "medium"),
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


JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"


def jev_token():
    import cf_env
    return cf_env.secret("jev")


def systemone_target():
    """(url, headers, label) of the typed-decision endpoint: the local colibri server when it is the active backend (same request and reply as
    TypeSafe's Jev, nothing leaves the machine), else Jev with a token. Raises RuntimeError when neither is available."""
    import cf_llm
    found = cf_llm.pick()
    if found and found[0] == "colibri":
        return found[1] + "/v1/systemone", {}, "colibri"
    token = jev_token()
    if not token:
        raise RuntimeError("sem token do Jev")
    return JEV_ENDPOINT, {"Authorization": f"Bearer {token}"}, "jev"


def local_systemone():
    import cf_llm
    found = cf_llm.pick()
    return bool(found and found[0] == "colibri")


def jev_provider(request, media, registry=None):
    """One Choice question over all capabilities. Raises on any failure so the caller can fall back explicitly."""
    url, headers, _label = systemone_target()
    criteria = {}
    for app_id, (needs, keywords, _risk) in CAPABILITIES.items():
        title = registry[app_id].tagline if registry and app_id in registry else app_id
        need = f" Requires attached: {', '.join(sorted(needs))}." if needs else ""
        criteria[app_id] = f"{title}{need}"
    body = {"state": {"request": request, "attached_media_kinds": sorted(media)}, "model": JEV_MODEL,
            "questions": {"app": {"type": "choice", "criteria": criteria,
                                  "instructions": "Which Studio app should handle this request next? Respect required attachments."}}}
    response = requests.post(url, json=body, headers=headers, timeout=20 if _label == "jev" else 120)
    if response.status_code in (401, 403):
        raise RuntimeError("Jev recusou o token")
    response.raise_for_status()
    answer = response.json()["answers"]["app"]
    probs = {k: float(v) for k, v in answer["probabilities"].items() if k in CAPABILITIES}
    if answer.get("type") != "choice" or not probs:
        raise RuntimeError("resposta do Jev fora do contrato")
    return probs


def route(request, media, registry, tier, installed_nodes=None, provider=None):
    """Return ranked candidates. `media` is a set of kinds: image, video, audio."""
    request = (request or "").strip()
    fallback = None
    if not request and not media:
        raise ValueError("Descreva o que quer fazer ou anexe uma mídia.")
    media = set(media or ())
    used = "local"
    if provider is None:
        try:
            probs, used = jev_provider(request, media, registry), systemone_target()[2]
        except (RuntimeError, requests.RequestException, KeyError, ValueError, TypeError) as exc:
            fallback = str(exc)[:160]
            probs = local_provider(request, media)
    else:
        probs = provider(request, media)
        used = getattr(provider, "__name__", "custom")
    ranked = []
    for app_id, p in sorted(probs.items(), key=lambda kv: -kv[1]):
        app = registry.get(app_id)
        if app is None:
            continue
        reasons = []
        if app.blocked_for(tier):
            reasons.append(f"precisa de ~{app.min_vram} GB de VRAM; a placa tem {tier.vram_gb:.0f} GB")
        needs = CAPABILITIES[app_id][0]
        if needs and not needs <= media:
            reasons.append("faltam mídias: " + ", ".join(sorted(needs - media)))
        risk = CAPABILITIES[app_id][2]
        ranked.append(dict(app=app_id, title=app.title, probability=round(p, 4),
                           router=dict(available=not reasons, reasons=reasons, risk=risk,
                                       confirm=risk in ("medium", "high"))))
    available = [c for c in ranked if c["router"]["available"]]
    return dict(request=request, media=sorted(media), provider=used, fallback=(fallback if used == "local" and provider is None else None), candidates=ranked,
                choice=available[0]["app"] if available else None)


# What each app hands to the next step (media kinds), used to chain a plan.
PRODUCES = {"bfs": "image", "scail2": "video", "animate2": "video", "moss": "image", "image3d": "file", "audio": "audio", "faceswap": "image", "outpaint": "image", "restore": "image", "outfit": "image", "clip": "video", "sequence": "video", "text2video": "video", "animate": "video", "openjutsu": "video",
            "board": "image", "compare": "image", "seethrough": "image"}
MAX_STEPS = 5
FINISHED_AT = 0.35  # Noul is weakly calibrated (0.43 right after a fulfilled one-step request), so stop early
MIN_NEXT = 0.65
TASK_AT = 0.4  # below this (and no media attached) the message is conversation, not a job


def jev_step(request, media, done, registry, ask_task=False):
    """One call, two typed questions: which app next (Choice) and is the request already fulfilled (Noul)."""
    url, headers, _label = systemone_target()
    criteria = {}
    for app_id, (needs, _k, _r) in CAPABILITIES.items():
        need = f" Requires attached: {', '.join(sorted(needs))}." if needs else ""
        criteria[app_id] = f"{registry[app_id].tagline}{need}"
    body = {"state": {"request": request, "steps_already_done": done, "available_media_kinds": sorted(media)},
            "model": JEV_MODEL,
            "questions": {
                "app": {"type": "choice", "criteria": criteria,
                        "instructions": "Which Studio app should run NEXT to move this request forward? Do not repeat steps already done. Respect required attachments."},
                "finished": {"type": "noul", "instructions": "Is every part of the request already fulfilled by the steps already done?"},
                **({"task": {"type": "noul", "instructions": "Is the user asking the Studio to create, edit, transform or process an image, video or audio (a job to run)? Answer false for greetings, thanks, or questions about the tool itself."}} if ask_task else {})}}
    response = requests.post(url, json=body, headers=headers, timeout=25 if _label == "jev" else 120)
    if response.status_code in (401, 403):
        raise RuntimeError("Jev recusou o token")
    response.raise_for_status()
    answers = response.json()["answers"]
    probs = {k: float(v) for k, v in answers["app"]["probabilities"].items() if k in CAPABILITIES}
    return probs, float(answers["finished"]["noul"]), (float(answers["task"]["noul"]) if "task" in answers else None)


def plan(request, media, registry, tier):
    """Serial plan: repeatedly ask Jev for the next app until it says the request is fulfilled. Decision-only."""
    request = (request or "").strip()
    media = set(media or ())
    if not request:
        raise ValueError("Descreva o que quer fazer.")
    steps, done = [], []
    for _ in range(MAX_STEPS):
        probs, finished, task = jev_step(request, media, done, registry, ask_task=not done)
        if task is not None and task < TASK_AT:
            return dict(request=request, media=sorted(media), provider=systemone_target()[2], steps=[], complete=False, conversation=True, task_p=round(task, 3))
        if done and finished >= FINISHED_AT:
            break
        options = []
        for app_id, p in sorted(probs.items(), key=lambda kv: -kv[1]):
            if app_id in done:
                continue  # a plan never repeats an app
            app = registry[app_id]
            needs = CAPABILITIES[app_id][0]
            ok = (not app.blocked_for(tier)) and needs <= media
            options.append((app_id, p, ok))
        pick = next(((a, p) for a, p, ok in options if ok), None)
        if pick is None:
            steps.append(dict(app=None, reason="nenhum app disponível para o próximo passo", finished_p=round(finished, 3)))
            break
        top = options[0]
        app_id, p = pick
        if done and p < MIN_NEXT:
            break  # Jev is unsure there is a next step: stop instead of padding the plan
        steps.append(dict(app=app_id, title=registry[app_id].title, probability=round(p, 4), finished_p=round(finished, 3),
                          rerouted=(top[0] != app_id), jev_top=top[0]))
        done.append(app_id)
        media = media | {PRODUCES.get(app_id, "image" if CAPABILITIES[app_id][0] <= {"image"} else "video")}
    return dict(request=request, media=sorted(set(media or ())), provider=systemone_target()[2], steps=steps,
                complete=bool(steps) and all(s["app"] for s in steps), conversation=False)
