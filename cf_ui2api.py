"""Convert a ComfyUI *UI* workflow (the .json the editor saves, e.g. the official workflow_templates) into an *API* graph the Studio can queue,
using the worker's own `/object_info` for the node definitions.

Why: the official templates for new models (TRELLIS.2, Pixal3D, ...) are published only in UI format. Translating ~60 nodes by hand is where bugs
hide; this does it mechanically and `validate()` then asks the real ComfyUI (POST /prompt validation) whether the result is acceptable.

What it handles: links, widget values by definition order (including the extra `control_after_generate` value), converted-to-input widgets, muted
/bypassed nodes (dropped / passed through), Reroute and Primitive nodes (resolved), UI-only notes (dropped), pruning to the ancestors of the
output nodes you ask for, and overriding any widget value. Subgraphs are flattened first (`flatten`): nested ones too; their promoted widgets become literal inputs of the inner nodes.
"""

PRIMITIVES = {"INT", "FLOAT", "STRING", "BOOLEAN"}
# Widget types besides primitives and combos (lists). They carry a value in widgets_values and have no socket unless the editor converted them.
WIDGET_TYPES = PRIMITIVES | {"COMBO", "COLOR", "LOAD_3D", "COMFY_DYNAMICCOMBO_V3"}
VIRTUAL = {"Note", "MarkdownNote", "Reroute", "PrimitiveNode", "GroupNode"}
MODE_MUTED, MODE_BYPASS = 2, 4
SEEDLIKE = ("fixed", "increment", "decrement", "randomize")


class ConversionError(ValueError):
    pass


def ordered(definition, section):
    names = (definition.get("input_order") or {}).get(section) or list((definition.get("input", {}).get(section) or {}))
    return [(n, definition["input"][section][n]) for n in names if n in (definition.get("input", {}).get(section) or {})]


def widget_inputs(definition):
    """[(name, kind, extra)] of the inputs that are widgets, in the order the editor stores widgets_values."""
    out = []
    for section in ("required", "optional"):
        for name, spec in ordered(definition, section):
            kind = spec[0]
            extra = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            if (isinstance(kind, list) or kind in WIDGET_TYPES) and not (extra.get("forceInput")):
                out.append((name, kind, extra))
    return out


def take_widgets(entries, values, cursor, prefix, out):
    """Consume widgets_values for `entries`, expanding dynamic combos into `parent.child` inputs (the API format for V3 dynamic inputs)."""
    for name, kind, extra in entries:
        if cursor >= len(values):
            break
        value = values[cursor]
        cursor += 1
        key = prefix + name
        if kind == "COMFY_DYNAMICCOMBO_V3":
            out[key] = value
            option = next((o for o in extra.get("options", []) if o.get("key") == value), None)
            nested = []
            for section in ("required", "optional"):
                for child, spec in ((option or {}).get("inputs", {}).get(section) or {}).items():
                    cextra = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
                    if isinstance(spec[0], list) or spec[0] in WIDGET_TYPES:
                        nested.append((child, spec[0], cextra))
            cursor = take_widgets(nested, values, cursor, key + ".", out)
            continue
        out[key] = value
        if extra.get("control_after_generate") or (name in ("seed", "noise_seed") and cursor < len(values) and values[cursor] in SEEDLIKE):
            cursor += 1
    return cursor


def convert(workflow, objinfo, outputs=None, overrides=None):
    """-> {node_id: {"class_type", "inputs"}}. `outputs`: ids of the nodes to keep (with their ancestors); None keeps every output node.
    `overrides`: {node_id: {input_name: value}} applied last (a link input can be replaced by a literal too)."""
    workflow = flatten(workflow)
    nodes = {n["id"]: n for n in workflow["nodes"]}
    links = {}
    for link in workflow.get("links", []):
        if isinstance(link, list):
            links[link[0]] = (link[1], link[2], link[3], link[4], link[5])
        else:
            links[link["id"]] = (link["origin_id"], link["origin_slot"], link["target_id"], link["target_slot"], link["type"])

    def resolve(origin, slot, seen=()):
        """Follow Reroute / bypassed nodes back to a real producer."""
        node = nodes[origin]
        if node["id"] in seen:
            raise ConversionError("laço entre nós de passagem")
        if node["type"] == "Reroute" or node.get("mode") == MODE_BYPASS:
            for entry in node.get("inputs", []):
                if entry.get("link") is not None and (node["type"] == "Reroute" or entry.get("type") == node["outputs"][slot].get("type")):
                    src = links[entry["link"]]
                    return resolve(src[0], src[1], seen + (node["id"],))
            raise ConversionError(f"o nó {node['id']} ({node['type']}) está ignorado e não tem entrada para repassar")
        if node["type"] == "PrimitiveNode":
            return ("literal", (node.get("widgets_values") or [None])[0])
        return ("link", str(origin), slot)

    graph, unknown = {}, {}
    for nid, node in nodes.items():
        kind = node["type"]
        if kind in VIRTUAL or node.get("mode") in (MODE_MUTED, MODE_BYPASS):
            continue
        definition = objinfo.get(kind)
        if definition is None:
            unknown[str(nid)] = kind  # only an error if a node we keep depends on it (preview-only branches are pruned below)
            continue
        inputs = {}
        socket = {entry["name"]: entry for entry in node.get("inputs", [])}
        for name, entry in socket.items():
            if entry.get("link") is None:
                continue
            origin, slot, *_ = links[entry["link"]]
            resolved = resolve(origin, slot)
            inputs[name] = resolved[1] if resolved[0] == "literal" else [resolved[1], resolved[2]]
        for name, value in (node.get("_literals") or {}).items():
            inputs.setdefault(name, value)
        values = list(node.get("widgets_values") or [])
        found = {}
        take_widgets(widget_inputs(definition), values, 0, "", found)
        for name, value in found.items():
            if name not in inputs:
                inputs[name] = value
        graph[str(nid)] = {"class_type": kind, "inputs": inputs}
    for nid, changes in (overrides or {}).items():
        graph[str(nid)]["inputs"].update(changes)
    fold_switches(graph)
    keep = outputs if outputs is not None else [k for k, v in graph.items() if objinfo[v["class_type"]].get("output_node")]
    needed, stack = set(), [str(k) for k in keep]
    while stack:
        nid = stack.pop()
        if nid in needed:
            continue
        if nid in unknown:
            raise ConversionError(f"O nó {unknown[nid]} (id {nid}) não existe neste ComfyUI.")
        if nid not in graph:
            raise ConversionError(f"o nó {nid} não está no grafo (foi ignorado ou é só da interface)")
        needed.add(nid)
        stack += [v[0] for v in graph[nid]["inputs"].values() if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)]
    return {k: v for k, v in graph.items() if k in needed}


def constant(graph, value):
    """The literal behind an input: a plain value, or a link to a Primitive* node that holds one. Otherwise None (unknown at build time)."""
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
        node = graph.get(value[0])
        if node and node["class_type"].startswith("Primitive") and "value" in node["inputs"] and not isinstance(node["inputs"]["value"], list):
            return node["inputs"]["value"]
        return None
    return value


def fold_switches(graph):
    """ComfySwitchNode with a switch known at build time is replaced by the branch it selects, so the unused branch (and the weights it would
    load) is pruned away. Repeats until no such switch is left."""
    changed = True
    while changed:
        changed = False
        for nid, node in list(graph.items()):
            if node["class_type"] != "ComfySwitchNode":
                continue
            flag = constant(graph, node["inputs"].get("switch"))
            if not isinstance(flag, bool):
                continue
            chosen = node["inputs"].get("on_true" if flag else "on_false")
            if chosen is None:
                continue
            for other in graph.values():
                for name, value in list(other["inputs"].items()):
                    if value == [nid, 0]:
                        other["inputs"][name] = chosen
            del graph[nid]
            changed = True


def _link_records(workflow):
    out = {}
    for link in workflow.get("links", []):
        if isinstance(link, list):
            out[link[0]] = dict(id=link[0], origin_id=link[1], origin_slot=link[2], target_id=link[3], target_slot=link[4], type=link[5])
        else:
            out[link["id"]] = dict(link)
    return out


def flatten(workflow):
    """Inline every subgraph node (recursively) so the rest of the converter sees plain nodes. Inner nodes get ids "outer:inner"."""
    import copy
    subgraphs = {sg["id"]: sg for sg in (workflow.get("definitions") or {}).get("subgraphs", [])}
    if not subgraphs or not ({n["type"] for n in workflow["nodes"]} & set(subgraphs)):
        return workflow
    nodes = {n["id"]: copy.deepcopy(n) for n in workflow["nodes"]}
    links = _link_records(workflow)
    for _ in range(20):  # nesting depth
        target = next((n for n in nodes.values() if n["type"] in subgraphs), None)
        if target is None:
            break
        sg, outer, prefix = subgraphs[target["type"]], target, f"{target['id']}:"
        del nodes[outer["id"]]
        # widgets_values follows the SUBGRAPH's inputs of a widget type, in order (the outer node may not even list them as sockets);
        # a widget wired to a link still owns its slot. A link on the outer node wins over the stored value.
        widget_values = iter(outer.get("widgets_values") or [])
        wired = {e["name"]: e["link"] for e in outer.get("inputs", []) if e.get("link") is not None}
        provided = {}
        for spec in sg["inputs"]:
            is_widget = spec["type"] in ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO")
            value = next(widget_values, None) if is_widget else None
            if spec["name"] in wired:
                provided[spec["name"]] = ("link", links[wired[spec["name"]]])
            elif is_widget:
                provided[spec["name"]] = ("literal", value)
        inner_nodes = {}
        for node in sg["nodes"]:
            clone = copy.deepcopy(node)
            clone["id"] = prefix + str(node["id"])
            inner_nodes[node["id"]] = clone
            nodes[clone["id"]] = clone
        outputs = {}
        for link in sg["links"]:
            origin, slot, dest, dslot = link["origin_id"], link["origin_slot"], link["target_id"], link["target_slot"]
            if dest == -20:
                outputs[dslot] = (prefix + str(origin), slot)
                continue
            target_node = inner_nodes[dest]
            entry = target_node["inputs"][dslot]
            if origin == -10:
                name = sg["inputs"][slot]["name"]
                kind, value = provided.get(name, ("literal", None))
                if kind == "link":
                    new_id = prefix + str(link["id"])
                    links[new_id] = dict(id=new_id, origin_id=value["origin_id"], origin_slot=value["origin_slot"], target_id=clone_id(target_node), target_slot=dslot, type=value.get("type"))
                    entry["link"] = new_id
                else:
                    entry["link"] = None
                    if value is not None:
                        target_node.setdefault("_literals", {})[entry["name"]] = value
            else:
                new_id = prefix + str(link["id"])
                links[new_id] = dict(id=new_id, origin_id=prefix + str(origin), origin_slot=slot, target_id=clone_id(target_node), target_slot=dslot, type=link.get("type"))
                entry["link"] = new_id
        for node in inner_nodes.values():  # inner sockets that were wired inside the subgraph keep their (renamed) links only
            for entry in node.get("inputs", []):
                if entry.get("link") is not None and entry["link"] not in links:
                    entry["link"] = None
        for record in links.values():  # whatever read the subgraph node's outputs now reads the inner producer
            if record["origin_id"] == outer["id"] and record["origin_slot"] in outputs:
                record["origin_id"], record["origin_slot"] = outputs[record["origin_slot"]]
    return dict(workflow, nodes=list(nodes.values()), links=list(links.values()), definitions={})


def clone_id(node):
    return node["id"]
