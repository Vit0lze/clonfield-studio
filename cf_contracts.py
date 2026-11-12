"""Contracts: one shape for everything the Studio can list, search, install and use.

CatalogItem   what every card/row shows, whatever it is (a recipe model, a LoRA, a VAE, an upscaler, a Civitai file...)
Action        what the user can DO with it. The UI renders actions; it never guesses them from the item's source.
Category      one kind of component and which views/sources/actions it supports
InstallJob    the states an install goes through (the same for every kind)

Rules every provider must follow (enforced by `check()` and by tests/test_contracts.py):
  * status is one of STATUSES and says how far we KNOW the item is usable: found < discovered < compatible < installed < validated.
    "descoberto/encontrado" never means executable; only "validado" (tested on this worker) does.
  * size is bytes or None, never a guess. `size_parts` lists what makes the total (model, encoder, VAE...), each with
    `shared_with` when another recipe uses the same file, so «baixar» counts only what is still missing.
  * every action has an id from ACTION_IDS, `enabled`, and a human `reason` when disabled.
  * `favorite` is {kind, id, meta}: the same id everywhere the item appears, so one star is one star.
"""

STATUSES = ("encontrado", "descoberto", "compatível", "instalado", "validado")
SOURCES = ("receita", "embutido", "civitai", "huggingface", "worker")
ACTION_IDS = ("install", "use", "open", "cancel")
VIEWS = ("recommended", "installed", "explore")
INSTALL_STATES = ("na fila", "baixando", "verificando", "registrando", "instalado", "falhou", "cancelado")


class ContractError(ValueError):
    pass


CATEGORIES = [
    dict(id="model", title="Modelos", hint="Receitas completas: modelo, encoder e VAE", views=("recommended", "installed", "explore"),
         sources=("civitai", "huggingface", "worker"), family_filter=True, roles=("Difusão", "Checkpoint")),
    dict(id="lora", title="LoRAs", hint="Estilos e personagens para o seu modelo", views=("recommended", "installed", "explore"),
         sources=("civitai",), family_filter=True, roles=("LoRA",)),
    dict(id="vae", title="VAEs", hint="Codificador/decodificador de imagem", views=("recommended", "installed", "explore"),
         sources=("civitai", "huggingface", "worker"), family_filter=True, roles=("VAE",)),
    dict(id="encoder", title="Encoders de texto", hint="CLIP, Qwen-VL e afins", views=("recommended", "installed", "explore"),
         sources=("civitai", "huggingface", "worker"), family_filter=True, roles=("Encoder",)),
    dict(id="upscaler", title="Upscalers", hint="Ampliam a imagem depois de gerada", views=("recommended", "installed", "explore"),
         sources=("civitai", "huggingface", "worker"), family_filter=False, roles=("Upscaler",)),
]
CATEGORY_IDS = tuple(c["id"] for c in CATEGORIES)


def action(id, label, enabled=True, reason="", **extra):
    if id not in ACTION_IDS:
        raise ContractError(f"ação desconhecida: {id}")
    return dict(id=id, label=label, enabled=bool(enabled), reason=reason or "", **extra)


def part(label, size, shared_with=None, installed=False):
    return dict(label=label, size=size, shared_with=list(shared_with or []), installed=bool(installed))


VARIANT_KEYS = ("provider", "model_id", "version_id", "file_id", "sha256", "quant", "size_bytes", "file_name")


def item(kind, id, title, source, status, *, subtitle="", cover=None, badges=(), facts=(), size=None, size_parts=(), license=None,
         compat=None, favorite=None, actions=(), links=(), adult=False, value=None, art=None, variant=None):
    """Build one CatalogItem. `value` is what a form slot stores to use it; `art` names a bundled illustration."""
    out = dict(kind=kind, id=str(id), title=str(title), subtitle=subtitle or "", source=source, status=status, cover=cover, art=art,
               badges=list(badges), facts=[dict(label=a, value=str(b)) for a, b in facts], size=size, size_parts=list(size_parts),
               license=license, compat=compat or dict(family=None, note="", validated=False),
               favorite=favorite or dict(kind=kind, id=f"{source}:{id}", meta=dict(title=str(title))),
               actions=list(actions), links=list(links), adult=bool(adult), value=value, variant=variant)
    check(out)
    return out


def check(entry):
    """Raise ContractError unless `entry` obeys the contract. Used on every item before it leaves the server."""
    for key in ("kind", "id", "title", "source", "status", "favorite", "actions", "compat", "size_parts"):
        if key not in entry:
            raise ContractError(f"item sem {key}: {entry.get('title')}")
    if entry["kind"] not in CATEGORY_IDS:
        raise ContractError(f"tipo desconhecido: {entry['kind']}")
    if entry["source"] not in SOURCES:
        raise ContractError(f"fonte desconhecida: {entry['source']}")
    if entry["status"] not in STATUSES:
        raise ContractError(f"status desconhecido: {entry['status']}")
    if entry["size"] is not None and (not isinstance(entry["size"], int) or entry["size"] < 0):
        raise ContractError("tamanho precisa ser bytes inteiros ou None")
    if entry["size_parts"] and entry["size"] is not None and entry["size"] > sum(p["size"] or 0 for p in entry["size_parts"]):
        raise ContractError("tamanho maior que a soma das partes")
    variant = entry.get("variant")
    if variant is not None:  # one immutable identity per file: a partial one would let the wrong file pass as the right one
        missing = [k for k in VARIANT_KEYS if k not in variant]
        if missing or not variant.get("provider") or variant.get("file_id") is None:
            raise ContractError(f"variante incompleta ({', '.join(missing) or 'provider/file_id vazio'}): {entry.get('title')}")
    fav = entry["favorite"]
    if not isinstance(fav, dict) or not fav.get("kind") or not fav.get("id"):
        raise ContractError("favorito sem kind/id")
    for a in entry["actions"]:
        if a.get("id") not in ACTION_IDS or "enabled" not in a or "label" not in a:
            raise ContractError(f"ação inválida em {entry['title']}: {a}")
        if not a["enabled"] and not a.get("reason"):
            raise ContractError(f"ação desabilitada sem motivo em {entry['title']}")
    if entry["status"] == "validado" and not entry["compat"].get("validated"):
        raise ContractError("status validado exige compat.validated")
    return entry
