"""The library: every kind of component through ONE provider interface and ONE item shape (cf_contracts).

    items, next_cursor = library(kind, view, ctx, family=..., source=..., q=..., cursor=...)

kind  model | lora | vae | encoder | upscaler        view  recommended | installed | explore
`ctx` carries what only the server knows: base folder, Civitai folder, GPU tier, a function that signs cover URLs, file sizes.
Nothing here downloads or runs anything; actions only DESCRIBE the call the UI may make.
"""

from pathlib import Path

import cf_civitai as civitai
import cf_contracts as C
import cf_loras
import cf_model_lab as lab
import cf_search
import cf_upscale

ROLE_OF = {"model": None, "lora": "LoRA", "vae": "VAE", "encoder": "Encoder", "upscaler": "Upscaler"}
KIND_OF_ROLE = {"Difusão": "model", "Checkpoint": "model", "LoRA": "lora", "VAE": "vae", "Encoder": "encoder", "Upscaler": "upscaler"}
FOLDER = civitai.ROLE_TYPES


def fav(kind, source, ident, title, **meta):
    return dict(kind=kind, id=f"{source}:{ident}", meta=dict(title=title, **meta))


def gb(n):
    return f"{n / 1e9:.1f}".replace(".", ",") + " GB" if n >= 1e9 else f"{round(n / 1e6)} MB"


# ------------------------------------------------------------------ recipe files shared between models
def owners(sizes=None):
    """{(folder, file name, size): [recipe keys]}: the Studio stores files by name, so two recipes that ship the same
    encoder (same name, same size) share one file on disk and one download."""
    out = {}
    for key, preset in lab.PRESETS.items():
        for repo, filename, *_ in preset.files.values():
            size = (sizes or {}).get(f"{repo}/{filename}")
            out.setdefault((Path(filename).parts[-2], Path(filename).name, size), []).append(key)
    return out


def installed_path(filename):
    return lab.models_root() / Path(filename).parts[-2] / Path(filename).name


def recipe_item(key, ctx):
    preset, info = lab.PRESETS[key], ctx["info"][key]
    sizes = ctx["sizes"]
    shared = owners(sizes)
    parts, any_unknown = [], False
    for role, (repo, filename, *_) in preset.files.items():
        size = sizes.get(f"{repo}/{filename}")
        any_unknown |= size is None
        others = [info_name(ctx, k) for k in shared[(Path(filename).parts[-2], Path(filename).name, size)] if k != key]
        parts.append(C.part({"Difusão": "Modelo de difusão", "Encoder": "Encoder de texto", "VAE": "VAE"}.get(role, role), size, others, installed_path(filename).is_file()))
    installed = all(p["installed"] for p in parts)
    missing = sum(p["size"] or 0 for p in parts if not p["installed"])
    fits = ctx["tier"].vram_gb >= info["min_vram"]
    facts = [("Velocidade", f"{info['speed']}/5"), ("Qualidade", f"{info['quality']}/5"), ("VRAM recomendada", f"≥ {info['min_vram']} GB"),
             ("Referências", str(preset.refs or "nenhuma")), ("Passos / CFG", f"{preset.steps} / {preset.cfg}")]
    acts = []
    if not installed:
        label = f"Instalar · {'≥ ' if any_unknown else ''}{gb(missing)}" if missing else "Instalar"
        acts.append(C.action("install", label, call=dict(method="POST", path=f"/models/{key}/install", body={}, follow=True)))
    acts.append(C.action("use", "Criar com este modelo", prefill=dict(app="create", values=dict(model=key, set="Manual"))))
    acts.append(C.action("open", "Página do modelo", href=info["page"]))
    return C.item("model", key, info["name"], "receita", "instalado" if installed else "compatível", subtitle=info["tagline"], art=f"model:{key}",
                  badges=[info["weight"]] if fits else ["pesado p/ a sua placa"], facts=facts, size=None if any_unknown else sum(p["size"] for p in parts),
                  size_parts=parts, license=None, compat=dict(family=key, note="receita validada pelo projeto; execução em GPU ainda a medir", validated=False),
                  favorite=fav("model", "receita", key, info["name"]), actions=acts, links=[dict(label="Página do modelo", url=info["page"])], value=key)


def info_name(ctx, key):
    return ctx["info"].get(key, {}).get("name", key)


def component_items(kind, ctx):
    """Recipe files of one role (VAE / encoder) as individual components, shared ones listed once with their users."""
    role = {"vae": "VAE", "encoder": "Encoder"}[kind]
    seen, items = {}, []
    for key, preset in lab.PRESETS.items():
        if role in preset.files:
            repo, filename, *_ = preset.files[role]
            seen.setdefault((Path(filename).parts[-2], Path(filename).name, None), []).append((key, repo, filename))  # one file name = one file on disk
    for (_folder, _name, _size), group in seen.items():
        users = [k for k, _r, _f in group]
        repo, filename = group[0][1], group[0][2]
        name = Path(filename).name
        size = next((ctx["sizes"].get(f"{r}/{f}") for _k, r, f in group if ctx["sizes"].get(f"{r}/{f}")), None)
        ok = installed_path(filename).is_file()
        used = ", ".join(info_name(ctx, k) for k in users)
        acts = [] if ok else [C.action("install", f"Instalar · {gb(size)}" if size else "Instalar",
                                       call=dict(method="POST", path="/components/recipe-file", body=dict(repo=repo, file=filename), follow=True))]
        acts.append(C.action("use", "Usar no Criar", prefill=dict(app="create", values=dict(set="Manual", model=users[0], slots={role: ""})), enabled=True))
        items.append(C.item(kind, f"{repo}/{filename}", name, "receita", "instalado" if ok else "compatível", subtitle=f"Usado por {used}", size=size,
                            size_parts=[C.part(name, size, [info_name(ctx, k) for k in users[1:]], ok)] if size else [], facts=[("Papel", role), ("Origem", repo)],
                            compat=dict(family=users[0], note=f"padrão de {used}", validated=False), favorite=fav(kind, "receita", f"{repo}/{filename}", name, role=role, family=users[0]),
                            actions=acts, links=[dict(label="Repositório", url=f"https://huggingface.co/{repo}")], value=""))
    return items


def upscaler_items(ctx):
    items = []
    for u in cf_upscale.status(ctx["base"]):
        acts = [] if u["installed"] else [C.action("install", f"Instalar · {u['mb']} MB", call=dict(method="POST", path="/upscalers/install", body=dict(name=u["name"]), follow=True))]
        acts.append(C.action("use", "Usar no Ampliar", prefill=dict(app="upscale", values=dict(mode=u["name"]))))
        nc = "NC" in u["license"] or "não comercial" in u["license"]
        items.append(C.item("upscaler", u["name"], u["short"], "embutido", "instalado" if u["installed"] else "compatível", subtitle=u["use"], art="app:upscale",
                            badges=["uso não comercial"] if nc else [], facts=[("Licença dos pesos", u["license"]), ("Fonte", u["source"])], size=u["mb"] * 1_000_000,
                            license=u["license"], compat=dict(family=None, note="independe do modelo de imagem", validated=False),
                            favorite=fav("upscaler", "embutido", u["name"], u["short"]), actions=acts, value=u["name"]))
    return items


# ------------------------------------------------------------------ installed things
def lora_items(ctx, installed_only):
    items, have = [], [i for i in cf_loras.scan(ctx["base"]) if i["source"] != "catálogo"]  # base/loras AND loose files in ComfyUI/models/loras
    pool = ([] if installed_only is None else cf_loras.catalog(ctx["base"])) + have
    for entry in pool:
        ok = entry["installed"]
        if installed_only and not ok:
            continue
        acts = [] if ok else [C.action("install", "Instalar", call=dict(method="POST", path="/loras/install", body=dict(name=entry["name"]), follow=True))]
        fams = entry.get("families") or []
        acts.append(C.action("use", "Usar no Criar", enabled=ok, reason="" if ok else "Instale primeiro.",
                             prefill=dict(app="create", values=dict(model=(fams or ["qwen21"])[0], loras=[dict(name=entry["name"], strength=1, clip=1, on=True)]))))
        items.append(C.item("lora", entry["name"], entry["label"], "civitai" if entry.get("model") else "huggingface" if entry.get("repo") else "worker",
                            "instalado" if ok else "compatível", subtitle=entry.get("creator") or "", art=None, badges=[f.upper() for f in fams[:2]], adult=entry.get("adult", False),
                            facts=[("Modelos compatíveis", ", ".join(fams) or "qualquer")], compat=dict(family=(fams or [None])[0], note="base conferida pelo catálogo", validated=False),
                            favorite=fav("lora", "civitai" if entry.get("model") else "huggingface" if entry.get("repo") else "worker", entry["name"], entry["label"], family=(fams or [""])[0], name=entry["name"]),
                            actions=acts, links=([dict(label="Página", url=entry["page"])] if entry.get("page") else []), value=entry["name"], cover=ctx["cover"](entry) if entry.get("covers") and entry.get("model") else None))
    return items


def installed_components(kind, ctx):
    role = ROLE_OF[kind]
    items = []
    folder = lab.models_root() / FOLDER[role]
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix in (".safetensors", ".gguf", ".pth"):
                items.append(C.item(kind, path.name, path.name, "worker", "instalado", subtitle="Arquivo na pasta de modelos do worker", size=path.stat().st_size,
                                    compat=dict(family=None, note="arquivo avulso: compatibilidade não verificada", validated=False),
                                    favorite=fav(kind, "worker", path.name, path.name, role=role), actions=[C.action("use", "Usar no Criar", prefill=dict(app="create", values=dict(set="Manual", slots={role: f"file:{path.name}"})))], value=f"file:{path.name}"))
    for preset in lab.PRESETS.values():
        for key, data, path in civitai.inventory(ctx["civitai_dir"], preset, role):
            if any(i["id"] == key for i in items):
                continue
            items.append(C.item(kind, key, data.get("title") or path.name, "civitai", "instalado", subtitle=f"base {data.get('base', '')}", size=path.stat().st_size,
                                compat=dict(family=preset.key, note=f"base {data.get('base', '')} = receita", validated=False),
                                favorite=fav(kind, "civitai", key, data.get("title") or path.name, role=role, family=preset.key),
                                actions=[C.action("use", "Usar no Criar", prefill=dict(app="create", values=dict(model=preset.key, set="Manual", slots={role: key})))], value=key))
    return items


# ------------------------------------------------------------------ explore
def search_item(entry, kind, family, role):
    ok = entry["status"] == "instalado"
    acts = []
    if entry.get("install"):
        acts.append(C.action("install", "Instalar", call=dict(method="POST", path="/components/install", body=dict(family=family, role=role, **entry["install"]), follow=True)))
    if ok and entry.get("value") is not None:
        acts.append(C.action("use", "Usar no Criar", prefill=dict(app="create", values=dict(model=family, set="Manual", slots={role: entry["value"]}))))
    if entry["source"] == "huggingface" and not acts:
        acts.append(C.action("install", "Instalar", enabled=False, reason="O Studio não baixa nada do Hugging Face sozinho: use «Página» e confira arquitetura e licença."))
    status = {"instalado": "instalado", "compatível": "compatível", "padrão da receita": "compatível"}.get(entry["status"], "descoberto")
    variant = entry.get("variant")
    facts = ([("Downloads", f"{entry['downloads']:,}".replace(",", "."))] if entry.get("downloads") else [])
    if variant:  # the file is part of what the card says: name, quantisation and whether Civitai marks it as the main file
        facts = [("Arquivo", variant["file_name"]), ("Quantização", civitai.QUANT_LABEL.get(variant.get("quant"), "não informada")),
                 *([("Na página do Civitai", "arquivo principal" if entry.get("primary") else "outro arquivo da mesma versão")] if "primary" in entry else []), *facts]
    return C.item(kind, entry["id"], entry["title"], entry["source"] if entry["source"] in C.SOURCES else "worker", status, subtitle=entry.get("author") or "",
                  variant=variant, badges=[entry["quant_label"]] if entry.get("quant_label") else [],
                  facts=facts,
                  size=int(entry["size_mb"] * 1_000_000) if entry.get("size_mb") else None, adult=entry.get("adult", False),
                  compat=dict(family=family, note=entry["compatible"], validated=False),
                  favorite=fav(kind, entry["source"], entry["id"], entry["title"], role=role, family=family, url=entry.get("url") or ""),
                  actions=acts, links=([dict(label="Página", url=entry["url"])] if entry.get("url") else []), value=entry.get("value"))


def lora_card_items(card, family, ctx, have):
    """One item per downloadable FILE of the version (ranks / quantisations), each with its own identity, size and install state."""
    files = sorted(card["files"], key=lambda f: (f.get("size_bytes") or 0))[:6]
    many = len(card["files"]) > 1
    out = []
    for file in files:
        mine = cf_loras.linked_name(file["name"], card["version"])
        ok = mine in have
        size = file.get("size_bytes") or 0
        stats = card.get("stats") or {}
        variant = dict(provider="civitai", model_id=card["model"], version_id=card["version"], file_id=file["file"], sha256=file.get("sha256"),
                       quant=file.get("quant"), size_bytes=file.get("size_bytes"), file_name=file["name"])
        expect = dict(name=file["name"], quant=file.get("quant"), size_bytes=file.get("size_bytes"), sha256=file.get("sha256"))
        acts = [] if ok else [C.action("install", "Instalar" + (f" · {gb(size)}" if size else ""),
                                       call=dict(method="POST", path="/civitai/install", body=dict(family=family, model=card["model"], version=card["version"], file=file["file"], expect=expect), follow=True))]
        acts.append(C.action("use", "Usar no Criar", enabled=ok, reason="" if ok else "Instale primeiro.", prefill=dict(app="create", values=dict(model=family, loras=[dict(name=mine, strength=1, clip=1, on=True)]))))
        label = file.get("quant_label") or Path(file["name"]).stem[:28]
        out.append(C.item("lora", f"{card['model']}/{card['version']}/{file['file']}", card["title"] + (f" · {label}" if many else ""), "civitai", "instalado" if ok else "compatível",
                          subtitle=card.get("creator") or "", cover=ctx["card_cover"](card), badges=[card.get("badge") or ""] if card.get("badge") else [], adult=card.get("adult", False),
                          variant=variant, facts=[("Arquivo", file["name"]), ("Downloads", f"{stats.get('downloads', 0):,}".replace(",", ".")), ("Curtidas", f"{stats.get('likes', 0):,}".replace(",", "."))],
                          size=size or None, compat=dict(family=family, note=f"base {card.get('base', '')} = receita", validated=False),
                          favorite=fav("lora", "civitai", f"{card['model']}/{card['version']}/{file['file']}", card["title"], family=family, model=card["model"], version=card["version"], file=file["file"], url=card.get("page") or ""),
                          actions=acts, links=([dict(label="Página", url=card["page"])] if card.get("page") else []), value=mine if ok else None))
    return out


def explore(kind, ctx, family, source, q, cursor):
    if kind == "lora":
        cards, nxt = civitai.browse_loras(lab.PRESETS[family], q, cursor, "downloads")
        have = [i["name"] for i in cf_loras.local(ctx["base"])]
        return [item for c in cards for item in lora_card_items(c, family, ctx, have)], nxt
    role = ROLE_OF[kind] or ("Checkpoint" if not lab.PRESETS[family].clip_type else "Difusão")
    items, nxt = [], None
    if kind == "upscaler" and source in (None, "", "embutido"):
        items = [i for i in upscaler_items(ctx) if q.lower() in (i["title"] + i["subtitle"]).lower()]
    else:
        found, nxt = cf_search.search(role, family, source if source in cf_search.SOURCES else "civitai", q, ctx["civitai_dir"], cursor)
        items = [search_item(e, kind, family, role) for e in found]
    return items, nxt


def library(kind, view, ctx, family="qwen21", source="civitai", q="", cursor=None):
    if kind not in C.CATEGORY_IDS or view not in C.VIEWS:
        raise ValueError("Categoria ou visão desconhecida.")
    if family not in lab.PRESETS:
        family = "qwen21"
    if view == "explore":
        return explore(kind, ctx, family, source, q, cursor)
    installed = view == "installed"
    if kind == "model":
        items = [recipe_item(k, ctx) for k in ctx["info"] if k in lab.PRESETS]
        if installed:
            items = [i for i in items if i["status"] == "instalado"]
    elif kind == "lora":
        items = lora_items(ctx, True if installed else False)
    elif kind == "upscaler":
        items = upscaler_items(ctx)
        if installed:
            items = [i for i in items if i["status"] == "instalado"] + installed_components("upscaler", ctx)
    else:
        items = installed_components(kind, ctx) if installed else component_items(kind, ctx)
    if q:
        items = [i for i in items if q.lower() in (i["title"] + " " + i["subtitle"]).lower()]
    return items, None
