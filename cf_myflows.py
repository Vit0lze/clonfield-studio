"""Saved flows ("Meus fluxos"): a graph the agent (or the user) composed, kept as a reusable recipe.

Saving turns the graph into a template:
  * every media id it reads becomes a form slot (image / images / video / videos, by the port it feeds), so the same flow runs on other files;
  * the parameters named in `expose` become form fields (number / enum / bool / text), the rest stay as they were saved.
The result is a normal `cf_recipes.Recipe`, so the same screen, queue, preview and agent tools run it. Stored as JSON in `<base>/flows/`.
STATE (honest): a saved flow is user-made, so it carries CÓDIGO ESCRITO until the person runs it; nothing here claims a GPU result.
"""

import copy
import json
import re
import time
from pathlib import Path

import cf_capabilities as caps
import cf_dag as dag
import cf_recipes

MAX_FLOWS = 50
GROUP = "Meus fluxos"
PARAM_KINDS = {"number": "number", "enum": "enum", "bool": "bool", "string": "text"}


def folder(base):
    return Path(base) / "flows"


def make_id(title):
    return "meu_" + (caps.slug(title)[:40] or "fluxo")


def _port(registry, node, name):
    cap = registry.get(node["cap"])
    port = next((p for p in cap.inputs if p.name == name), None)
    return port


def _media_slots(graph, registry, resolve_media):
    """Replace {"media": id} (single or in a list) by {"slot": "entrada_n"}; -> (template graph, [slot specs])."""
    template, slots, by_media = copy.deepcopy(graph), [], {}
    for node in template["nodes"]:
        for name, value in (node.get("inputs") or {}).items():
            refs = value if isinstance(value, list) else [value]
            medias = [r for r in refs if isinstance(r, dict) and "media" in r]
            if not medias:
                continue
            if len(medias) != len(refs):
                raise ValueError(f"«{node['id']}.{name}» mistura arquivos e passos; separe em duas entradas antes de salvar")
            key = tuple(m["media"] for m in medias)
            if key not in by_media:
                port = _port(registry, node, name)
                found = resolve_media(key[0]) if resolve_media else None
                base_kind = (port.type if port else None) or (found or {}).get("type") or "image"
                if base_kind not in ("image", "video"):
                    raise ValueError(f"«{node['id']}.{name}» recebe {base_kind}; só imagens e vídeos viram campos do formulário")
                many = isinstance(value, list) and len(value) > 1 or bool(port and port.many)
                n = len(slots) + 1
                by_media[key] = dict(id=f"entrada_{n}", kind=base_kind + ("s" if many else ""), label=f"{'Imagens' if base_kind == 'image' else 'Vídeos'}" if many else ("Imagem" if base_kind == "image" else "Vídeo"),
                                     min=1, max=16 if many else 1)
                if n > 1:
                    by_media[key]["label"] += f" ({n})"
                slots.append(by_media[key])
            slot = by_media[key]["id"]
            node["inputs"][name] = [{"slot": slot}] if isinstance(value, list) else {"slot": slot}
    return template, slots


def _exposed(registry, template, expose):
    """expose: [{"node", "name", "label"?}] -> form fields; the saved value is the default."""
    fields = []
    for item in expose or []:
        node = next((n for n in template["nodes"] if n["id"] == item.get("node")), None)
        if node is None:
            raise ValueError(f"expose: o nó «{item.get('node')}» não existe")
        spec = registry.get(node["cap"]).params.get(item.get("name"))
        if spec is None:
            raise ValueError(f"expose: {node['cap']} não tem o parâmetro «{item.get('name')}»")
        kind = PARAM_KINDS.get(spec.get("type"))
        if kind is None:
            raise ValueError(f"expose: «{item['name']}» é do tipo {spec.get('type')}, que não cabe num campo do formulário")
        default = (node.get("params") or {}).get(item["name"], spec.get("default"))
        field = dict(id=f"p_{node['id']}_{item['name']}", kind=kind, label=item.get("label") or f"{node.get('label') or node['id']}: {item['name']}", node=node["id"], param=item["name"], default=default)
        if kind == "enum":
            field["options"] = list(spec["options"])
        if kind == "number":
            field.update({k: spec[k] for k in ("min", "max") if spec.get(k) is not None})
        if kind == "text":
            field["required"] = False
        fields.append(field)
    return fields


def exposable(registry, graph, limit=40):
    """Parameters a saved flow could turn into form fields: the simple ones (number, option, yes/no, text) set on the graph's steps."""
    out = []
    for node in graph.get("nodes", []):
        cap = registry.get(node["cap"])
        for name, value in (node.get("params") or {}).items():
            spec = cap.params.get(name)
            if spec is None or spec.get("type") not in PARAM_KINDS or name in (node.get("bind") or {}):
                continue
            out.append(dict(node=node["id"], step=node.get("label") or cap.title, name=name, type=PARAM_KINDS[spec["type"]], value=value))
            if len(out) >= limit:
                return out
    return out


def save(base, registry, graph, title, tagline="", expose=(), resolve_media=None, tier=None):
    """Validate the graph, derive its form and store it. Returns the public description. Raises ValueError in plain language."""
    title = str(title or "").strip()
    if not 3 <= len(title) <= 60:
        raise ValueError("Dê um nome ao fluxo, de 3 a 60 caracteres.")
    report = dag.validate(graph, registry, tier, resolve_media)
    if not report["ok"]:
        raise ValueError("O grafo não é válido: " + "; ".join(e["message"] for e in report["errors"][:3]))
    flow_id = make_id(title)
    existing = {p.stem for p in folder(base).glob("*.json")} if folder(base).is_dir() else set()
    if flow_id not in existing and len(existing) >= MAX_FLOWS:
        raise ValueError(f"Já existem {MAX_FLOWS} fluxos salvos; apague algum antes.")
    template, slots = _media_slots(graph, registry, resolve_media)
    fields = _exposed(registry, template, expose)
    body = dict(id=flow_id, title=title, tagline=str(tagline or "").strip()[:200] or f"Fluxo salvo com {len(graph['nodes'])} passos.", template=template, slots=slots,
                fields=fields, lane=report["resources"]["lane"], saved=time.time())
    folder(base).mkdir(parents=True, exist_ok=True)
    (folder(base) / f"{flow_id}.json").write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    return recipe_from(body).public() | dict(replaced=flow_id in existing)


def delete(base, flow_id):
    path = folder(base) / f"{flow_id}.json"
    if not re.fullmatch(r"meu_[a-z0-9_]{1,60}", flow_id) or not path.is_file():
        raise KeyError(flow_id)
    path.unlink()


def build_graph(body, values):
    """Fill the template: slots become media references, exposed fields become node params."""
    graph = copy.deepcopy(body["template"])
    nodes = {n["id"]: n for n in graph["nodes"]}
    def fill(ref):
        if isinstance(ref, dict) and "slot" in ref:
            got = values[ref["slot"]]
            return [{"media": m} for m in got] if isinstance(got, list) else {"media": got}
        return ref
    for node in graph["nodes"]:
        for name, value in list((node.get("inputs") or {}).items()):
            if isinstance(value, list):
                flat = []
                for ref in value:
                    got = fill(ref)
                    flat += got if isinstance(got, list) else [got]
                node["inputs"][name] = flat
            else:
                node["inputs"][name] = fill(value)
    for field in body["fields"]:
        nodes[field["node"]].setdefault("params", {})[field["param"]] = values[field["id"]]
    return graph


def recipe_from(body):
    inputs = [dict(id=s["id"], kind=s["kind"], label=s["label"], min=s["min"], max=s["max"]) for s in body["slots"]]
    for f in body["fields"]:
        inputs.append({k: v for k, v in f.items() if k not in ("node", "param")})
    gpu = body.get("lane") == "gpu"
    return cf_recipes.Recipe(body["id"], body["title"], body["tagline"], GROUP, inputs, lambda v, preview=False, body=body: build_graph(body, v), gpu=gpu,
                             state="CÓDIGO ESCRITO", evidence="fluxo salvo pelo usuário ou pelo agente; ainda sem execução registrada aqui")


def load(base):
    out = {}
    if not folder(base).is_dir():
        return out
    for path in sorted(folder(base).glob("meu_*.json")):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            out[body["id"]] = recipe_from(body)
        except (OSError, ValueError, KeyError):
            continue  # a damaged file must not hide the other flows
    return out
