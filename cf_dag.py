"""Typed, versioned DAG executor with a content-hash cache, partial re-run, cancel and resume.

A graph is {"nodes": [{"id", "cap", "inputs": {port: {"media": id} | {"from": "node.output"}}, "params": {...}}]}.
  * validate() explains every incompatibility (never silently hides one): unknown capability, missing input, type mismatch,
    cycle, bad parameter, not enough VRAM, unresolved media.
  * execute() runs nodes in topological order. A node's hash is sha256(capability id + version + params + the content hash of
    every input), so an unchanged node is a cache hit and only changed nodes (and their descendants) recompute. That is the
    partial re-run, and also resume: after a cancel or a crash the same graph reuses everything that finished.
  * Every run writes a provenance record: which capability version ran, with which inputs/params, which nodes were cached.
Outputs live under <out_dir>/dag/cache/<hash>/ so the job manager can publish them like any other result.

Control flow (all optional, all explained by validate()):
  * `"each": "<input or bound param>"` runs the node ONCE PER ITEM of a list (a queue of items). Every item has its own cache entry, so
    changing one item recomputes that item only. Its outputs become lists, which feed `many` ports or another `each` node.
  * a capability output marked `many` (frames of a video, the cells of a scenario matrix) is a list source for `each`.
  * `"bind": {param: "node.port"}` takes a node parameter from an upstream text/json output (`{"from": ..., "path": "a.b"}` digs into json).
  * `"when": {"from": "node.port", "path": "passed", "equals": true}` runs the node only if the condition holds; otherwise the node is
    «ignorado», and so is every node that needs its output. Nothing is faked for a skipped branch.
"""

import hashlib
import json
import shutil
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

import cf_capabilities as caps

_hash_lock = threading.Lock()
_file_hashes = {}


class DagInvalid(ValueError):
    def __init__(self, errors):
        super().__init__("; ".join(e["message"] for e in errors))
        self.errors = errors


def file_sha256(path):
    path = Path(path)
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _hash_lock:
        if key in _file_hashes:
            return _file_hashes[key]
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    with _hash_lock:
        _file_hashes[key] = digest.hexdigest()
    return _file_hashes[key]


def artifact_hash(artifact):
    if artifact.get("path"):
        return file_sha256(artifact["path"])
    return hashlib.sha256(json.dumps(artifact.get("value"), sort_keys=True, default=str).encode()).hexdigest()


def error(node, code, message):
    return dict(node=node, code=code, message=message)


def parse_ref(ref):
    node, _, port = str(ref).partition(".")
    return node, port


def bind_ref(ref):
    """A bind entry is "node.port" or {"from": "node.port", "path": "a.b"} -> (ref, path)."""
    if isinstance(ref, dict):
        return str(ref.get("from", "")), str(ref.get("path") or "")
    return str(ref), ""


def sources_of(node):
    """Every "node.port" this node reads: inputs, bound params and the `when` condition (they all order the run)."""
    out = []
    for value in (node.get("inputs") or {}).values():
        for src in value if isinstance(value, list) else [value]:
            if isinstance(src, dict) and "from" in src:
                out.append(src["from"])
    out += [bind_ref(ref)[0] for ref in (node.get("bind") or {}).values()]
    when = node.get("when")
    if isinstance(when, dict) and when.get("from"):
        out.append(when["from"])
    return out


def coerce_param(spec, value):
    """A bound value from a text list ("40") fits a number/bool parameter ("40" -> 40, "sim" -> True); anything else is left for check_params to judge."""
    kind = (spec or {}).get("type")
    if isinstance(value, str) and kind == "number":
        try:
            number = float(value.strip().replace(",", "."))
        except ValueError:
            return value
        return int(number) if number == int(number) else number
    if isinstance(value, str) and kind == "bool":
        word = value.strip().lower()
        return True if word in ("true", "sim", "1", "yes") else False if word in ("false", "nao", "não", "0", "no") else value
    return value


def dig(value, path):
    for part in [p for p in str(path).split(".") if p]:
        if isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise ValueError(f"o caminho «{path}» não existe no valor ({part!r} faltando)")
    return value


def condition_holds(when, value):
    got = dig(value, when.get("path") or "")
    if "equals" in when:
        return got == when["equals"]
    if "gte" in when:
        return isinstance(got, (int, float)) and got >= when["gte"]
    if "lte" in when:
        return isinstance(got, (int, float)) and got <= when["lte"]
    return bool(got)


def validate(graph, registry, tier=None, resolve_media=None):
    """-> dict(ok, errors, order, resources). `resolve_media(id)` returns {"type", "path"} or None."""
    errors, nodes = [], {}
    for node in (graph or {}).get("nodes") or []:
        nid = node.get("id")
        if not isinstance(nid, str) or not nid.strip():
            errors.append(error(None, "bad_node", "todo nó precisa de um id de texto"))
            continue
        if nid in nodes:
            errors.append(error(nid, "duplicate_id", f"o id «{nid}» aparece duas vezes"))
            continue
        nodes[nid] = node
    if not nodes and not errors:
        errors.append(error(None, "empty", "o grafo não tem nós"))
    edges = defaultdict(set)
    resources = dict(vram_gb=0, ram_gb=0, disk_gb=0.0, lanes=set(), risk="low")

    def source_output(nid, ref, what):
        """The (capability, output port, is_list) behind a "node.port" reference, or None after recording why not."""
        other, out_name = parse_ref(ref)
        if other not in nodes:
            errors.append(error(nid, "unknown_source", f"{nid}: a origem «{ref}» não existe"))
            return None
        try:
            other_cap = registry.get(nodes[other].get("cap"))
        except KeyError:
            return None
        out = next((o for o in other_cap.outputs if o.name == out_name), None)
        if out is None:
            errors.append(error(nid, "unknown_output", f"{nid}: «{other}» ({other_cap.id}) não produz «{out_name}» (produz: {', '.join(o.name for o in other_cap.outputs)})"))
            return None
        edges[other].add(nid)
        return other_cap, out, bool(out.many or nodes[other].get("each"))

    for nid, node in nodes.items():
        try:
            cap = registry.get(node.get("cap"))
        except KeyError:
            errors.append(error(nid, "unknown_capability", f"«{node.get('cap')}» não existe no catálogo de capacidades"))
            continue
        bound = node.get("bind") or {}
        for problem in caps.check_params(cap, {k: v for k, v in (node.get("params") or {}).items() if k not in bound}):
            errors.append(error(nid, "bad_param", f"{nid}: {problem}"))
        given = node.get("inputs") or {}
        ports = {p.name: p for p in cap.inputs}
        each = node.get("each")
        if each is not None and each not in ports and each not in bound:
            errors.append(error(nid, "bad_each", f"{nid}: «each» aponta para «{each}», que não é uma entrada nem um parâmetro ligado de {cap.id}"))
        for name in given:
            if name not in ports:
                errors.append(error(nid, "unknown_input", f"{nid}: «{name}» não é uma entrada de {cap.id} (entradas: {', '.join(ports) or 'nenhuma'})"))
        for name, ref in bound.items():
            if name not in cap.params:
                errors.append(error(nid, "bad_bind", f"{nid}: «{name}» não é um parâmetro de {cap.id} (aceita: {', '.join(cap.params) or 'nenhum'})"))
            elif name in (node.get("params") or {}):
                errors.append(error(nid, "bind_conflict", f"{nid}: «{name}» está em params e em bind ao mesmo tempo"))
            found = source_output(nid, bind_ref(ref)[0], "bind")
            if found is None:
                continue
            _, out, listy = found
            if out.type not in ("text", "json"):
                errors.append(error(nid, "bad_bind", f"{nid}: «{name}» só pode vir de uma saída de texto ou json, não de {out.type}"))
            if listy and each != name:
                errors.append(error(nid, "list_to_single", f"{nid}: «{name}» recebe uma lista; use \"each\": \"{name}\" para rodar uma vez por item"))
        when = node.get("when")
        if when is not None:
            if not isinstance(when, dict) or not when.get("from"):
                errors.append(error(nid, "bad_when", f"{nid}: «when» precisa de {{\"from\": \"no.saida\", \"equals\"|\"gte\"|\"lte\": valor}}"))
            else:
                found = source_output(nid, when["from"], "when")
                if found is not None and found[1].type not in ("json", "text"):
                    errors.append(error(nid, "bad_when", f"{nid}: a condição lê json ou texto, não {found[1].type}"))
        for port in cap.inputs:
            sources = given.get(port.name)
            if sources is None:
                if port.required:
                    errors.append(error(nid, "missing_input", f"{nid}: falta a entrada «{port.name}» ({port.type}) de {cap.id}"))
                continue
            sources = sources if isinstance(sources, list) else [sources]
            if len(sources) > 1 and not port.many and each != port.name:
                errors.append(error(nid, "too_many", f"{nid}: «{port.name}» aceita só uma origem"))
            for src in sources:
                have, listy = None, False
                if isinstance(src, dict) and "from" in src:
                    found = source_output(nid, src["from"], "input")
                    if found is None:
                        continue
                    have, listy = found[1].type, found[2]
                elif isinstance(src, dict) and "media" in src:
                    found = resolve_media(src["media"]) if resolve_media else None
                    if not found:
                        errors.append(error(nid, "unresolved_media", f"{nid}: a mídia «{src['media']}» não existe nesta sessão"))
                        continue
                    have = found["type"]
                else:
                    errors.append(error(nid, "bad_input", f"{nid}: «{port.name}» precisa de {{from}} ou {{media}}"))
                    continue
                if have != port.type:
                    errors.append(error(nid, "type_mismatch", f"{nid}: «{port.name}» de {cap.id} espera {port.type}, mas recebe {have}"
                                                             + (" (use uma capacidade que converta antes)" if have in caps.MEDIA else "")))
                if listy and not port.many and each != port.name:
                    errors.append(error(nid, "list_to_single", f"{nid}: «{port.name}» de {cap.id} recebe uma lista; use \"each\": \"{port.name}\" para rodar uma vez por item, ou um passo que junte a lista"))
        req = cap.requires
        if tier is not None and req.get("vram_gb") and tier.vram_gb < req["vram_gb"]:
            if req.get("offload"):
                resources.setdefault("slow", []).append(nid)  # runs by streaming weights to RAM/disk: allowed, but reported
            else:
                errors.append(error(nid, "resource", f"{nid}: {cap.id} precisa de ~{req['vram_gb']} GB de VRAM; a placa tem {tier.vram_gb:.0f} GB"))
        resources["vram_gb"] = max(resources["vram_gb"], req.get("vram_gb", 0))
        resources["ram_gb"] = max(resources["ram_gb"], req.get("ram_gb", 0))
        resources["disk_gb"] += req.get("disk_gb", 0)
        resources["lanes"].add(req.get("lane", "cpu"))
        if cap.risk != "low":
            resources["risk"] = cap.risk
    order = toposort(nodes, edges)
    if order is None:
        errors.append(error(None, "cycle", "o grafo tem um ciclo: um nó depende dele mesmo"))
        order = []
    resources["lanes"] = sorted(resources["lanes"])
    resources["lane"] = "gpu" if "gpu" in resources["lanes"] else "cpu"
    return dict(ok=not errors, errors=errors, order=order, resources=resources)


def toposort(nodes, edges):
    indeg = {n: 0 for n in nodes}
    for src, targets in edges.items():
        for t in targets:
            indeg[t] += 1
    queue = deque(sorted(n for n, d in indeg.items() if d == 0))
    order = []
    while queue:
        n = queue.popleft()
        order.append(n)
        for t in sorted(edges.get(n, ())):
            indeg[t] -= 1
            if indeg[t] == 0:
                queue.append(t)
    return order if len(order) == len(nodes) else None


def descendants(graph, start):
    kids = defaultdict(set)
    for node in graph["nodes"]:
        for ref in sources_of(node):
            kids[parse_ref(ref)[0]].add(node["id"])
    seen, stack = set(), [start]
    while stack:
        for k in kids.get(stack.pop(), ()):
            if k not in seen:
                seen.add(k)
                stack.append(k)
    return seen


class Env:
    """What a run needs from the outside: where things live, the GPU tier, and how an uploaded media id becomes a file."""

    def __init__(self, base, out_dir, tier, resolve_media):
        self.base, self.out_dir, self.tier, self.resolve_media = Path(base), Path(out_dir), tier, resolve_media

    @property
    def cache(self):
        path = self.out_dir / "dag" / "cache"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def runs(self):
        path = self.out_dir / "dag" / "runs"
        path.mkdir(parents=True, exist_ok=True)
        return path


def node_hash(cap, params, input_hashes):
    payload = json.dumps(dict(cap=cap.id, version=cap.version, params=params, inputs=input_hashes), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _decode(root, a):
    art = dict(type=a["type"], value=a.get("value"), path=str(root / a["file"]) if a.get("file") else None)
    return None if art["path"] and not Path(art["path"]).is_file() else art


def load_cached(env, digest):
    meta = env.cache / digest / "meta.json"
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        root = env.cache / digest / "out"
        outputs = {}
        for name, a in data["outputs"].items():
            if "items" in a:
                items = [_decode(root, i) for i in a["items"]]
                if any(i is None for i in items):
                    return None
                outputs[name] = items
            else:
                outputs[name] = _decode(root, a)
                if outputs[name] is None:
                    return None
        return outputs
    except (OSError, ValueError, KeyError):
        return None


def _encode(a, staging, stem):
    entry = dict(type=a["type"], value=a.get("value"))
    if a.get("path"):
        src = Path(a["path"])
        target = staging / "out" / f"{stem}{src.suffix}"
        shutil.copyfile(src, target)
        entry["file"] = target.name
    return entry


def store(env, digest, cap, outputs, seconds):
    final = env.cache / digest
    staging = env.cache / f".{digest}.{uuid.uuid4().hex[:6]}"
    (staging / "out").mkdir(parents=True)
    meta = {}
    for name, a in outputs.items():
        if isinstance(a, list):
            meta[name] = dict(items=[_encode(item, staging, f"{name}-{i + 1}") for i, item in enumerate(a)])
        else:
            meta[name] = _encode(a, staging, name)
    (staging / "meta.json").write_text(json.dumps(dict(capability=cap.id, version=cap.version, seconds=round(seconds, 3), outputs=meta), ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(final, ignore_errors=True)
    staging.replace(final)  # atomic: a cancelled node never leaves a half-written cache entry
    return load_cached(env, digest)


def write_run(env, run):
    path = env.runs / f"{run['id']}.json"
    partial = path.with_suffix(".part")
    partial.write_text(json.dumps(run, ensure_ascii=False, default=str), encoding="utf-8")
    partial.replace(path)


def load_run(env, run_id):
    return json.loads((env.runs / f"{run_id}.json").read_text(encoding="utf-8"))


def _summary(a):
    if isinstance(a, list):
        return [_summary(i) for i in a]
    return dict(type=a["type"], path=a.get("path"), value=a.get("value"), sha256=artifact_hash(a))


def _as_list(x):
    return x if isinstance(x, list) else [x]


MAX_ITEMS = 64  # one node never fans out past this: a queue that long is a batch, not a graph


def execute(graph, registry, env, ctx, run_id=None, force=(), check=None):
    """Run the graph. `force` node ids (and their descendants) ignore the cache. Returns the run record.
    Raises DagInvalid before running anything; raises whatever ctx.check() raises on cancel (the run record says where it stopped)."""
    report = validate(graph, registry, env.tier, env.resolve_media)
    if not report["ok"]:
        raise DagInvalid(report["errors"])
    nodes = {n["id"]: n for n in graph["nodes"]}
    forced = set(force)
    for f in list(forced):
        forced |= descendants(graph, f)
    run = dict(id=run_id or uuid.uuid4().hex[:12], created=time.time(), status="executando", order=report["order"], resources={**report["resources"]},
               nodes={nid: dict(status="pendente", capability=nodes[nid]["cap"], version=registry.get(nodes[nid]["cap"]).version) for nid in report["order"]},
               graph=graph)
    if run_id:
        try:
            run["created"] = load_run(env, run_id).get("created", run["created"])
            run["resumed"] = True
        except (OSError, ValueError):
            pass
    write_run(env, run)
    values, total = {}, max(1, len(report["order"]))
    try:
        for index, nid in enumerate(report["order"]):
            ctx.check()
            node, cap = nodes[nid], registry.get(nodes[nid]["cap"])
            rec = run["nodes"][nid]
            skip, gathered, hashes, bound, listy_bound = None, {}, {}, {}, set()
            when = node.get("when")
            if when:
                other, out_name = parse_ref(when["from"])
                if values.get(other) is None:
                    skip = f"«{other}» foi ignorado"
                else:
                    source = values[other][out_name]
                    if isinstance(source, list):
                        raise ValueError(f"{nid}: a condição lê uma lista; use um passo que reduza a lista a um valor")
                    try:
                        if not condition_holds(when, source.get("value")):
                            skip = "condição não atendida"
                    except ValueError as exc:
                        raise ValueError(f"{nid}: condição: {exc}") from None
            for name, ref in (node.get("bind") or {}).items():
                text, path = bind_ref(ref)
                other, out_name = parse_ref(text)
                if values.get(other) is None:
                    skip = skip or f"«{other}» foi ignorado"
                    continue
                source = values[other][out_name]
                spec = cap.params.get(name)
                if isinstance(source, list):
                    bound[name] = [coerce_param(spec, dig(i.get("value"), path)) for i in source]
                    listy_bound.add(name)
                else:
                    bound[name] = coerce_param(spec, dig(source.get("value"), path))
            for port in cap.inputs:
                sources = (node.get("inputs") or {}).get(port.name)
                if sources is None:
                    continue
                items = []
                for src in sources if isinstance(sources, list) else [sources]:
                    if "from" in src:
                        other, out_name = parse_ref(src["from"])
                        if values.get(other) is None:
                            if port.required:
                                skip = skip or f"«{other}» foi ignorado"
                            continue
                        items.extend(_as_list(values[other][out_name]))
                    else:
                        found = env.resolve_media(src["media"])
                        items.append(dict(type=found["type"], path=found["path"], value=None))
                if len(items) > MAX_ITEMS:
                    raise ValueError(f"{nid}: «{port.name}» tem {len(items)} itens; o máximo por passo é {MAX_ITEMS}")
                gathered[port.name] = items if (port.many or node.get("each") == port.name) else (items[0] if items else None)
                hashes[port.name] = [artifact_hash(a) for a in items]
            if skip:
                rec.update(status="ignorado", reason=skip, started=time.time(), finished=time.time())
                values[nid] = None
                write_run(env, run)
                continue
            each = node.get("each")
            params0 = {**(node.get("params") or {}), **{k: v for k, v in bound.items() if k not in listy_bound}}
            if each is None:
                plan = [(gathered, params0, hashes)]
            else:
                if each in gathered:
                    entries = _as_list(gathered[each]) if gathered[each] is not None else []
                else:
                    entries = bound[each]
                if len(entries) > MAX_ITEMS:
                    raise ValueError(f"{nid}: «each» tem {len(entries)} itens; o máximo por passo é {MAX_ITEMS}")
                plan = []
                for i, entry in enumerate(entries):
                    g, p, h = dict(gathered), dict(params0), dict(hashes)
                    if each in gathered:
                        port = next(pt for pt in cap.inputs if pt.name == each)
                        g[each] = [entry] if port.many else entry
                        h[each] = [hashes[each][i]]
                    else:
                        p[each] = entry
                    plan.append((g, p, h))
            missing = [pt.name for pt in cap.inputs if pt.required and each is None and gathered.get(pt.name) in (None, [])]
            if missing:
                raise ValueError(f"{nid}: a entrada «{missing[0]}» ficou vazia")
            for _g, p, _h in plan:
                problems = caps.check_params(cap, p)
                if problems:
                    raise ValueError(f"{nid}: " + "; ".join(problems))
            digests = [node_hash(cap, p, h) for _g, p, h in plan]
            rec.update(hash=digests[0] if each is None else hashlib.sha256("|".join(digests).encode()).hexdigest(), inputs=hashes, params=params0)
            if each is not None:
                rec.update(each=each, items=len(plan))
            runner = cap.run or app_runner(registry, cap)
            results, cached_count = [], 0
            rec.update(status="executando", started=time.time())
            write_run(env, run)
            for k, ((g, p, _h), digest) in enumerate(zip(plan, digests)):
                ctx.check()
                cached = None if nid in forced else load_cached(env, digest)
                if cached is not None:
                    cached_count += 1
                    results.append(cached)
                    continue
                label = f"{cap.title} ({index + 1}/{len(report['order'])})" + (f" · item {k + 1}/{len(plan)}" if each is not None else "")
                ctx.progress((index + k / max(1, len(plan))) / total, desc=label)
                work = env.cache / f".work-{digest[:12]}-{uuid.uuid4().hex[:6]}"
                work.mkdir(parents=True)
                started = time.monotonic()
                try:
                    produced = runner(env_dict(env), ctx, g, p, work)
                    results.append(store(env, digest, cap, produced, time.monotonic() - started))
                finally:
                    shutil.rmtree(work, ignore_errors=True)
            if each is None:
                values[nid] = results[0]
            else:
                values[nid] = {o.name: [x for r in results for x in _as_list(r[o.name])] for o in cap.outputs}
            rec.update(status="em cache" if cached_count == len(plan) else "concluído", finished=time.time(), cached_items=cached_count)
            rec["outputs"] = {name: _summary(a) for name, a in values[nid].items()}
            write_run(env, run)
        run["status"] = "concluído"
    except BaseException as exc:
        status = getattr(exc, "status", "falhou")
        run["status"] = status if status in ("cancelado", "falhou") else "falhou"
        for nid, rec in run["nodes"].items():
            if rec["status"] == "executando":
                rec.update(status="interrompido" if run["status"] == "cancelado" else "falhou", error=str(exc)[:300])
        run["error"] = str(exc)[:300]
        write_run(env, run)
        raise
    run["finished"] = time.time()
    run["recomputed"] = [n for n, r in run["nodes"].items() if r["status"] == "concluído"]
    run["cached"] = [n for n, r in run["nodes"].items() if r["status"] == "em cache"]
    run["skipped"] = [n for n, r in run["nodes"].items() if r["status"] == "ignorado"]
    run["final"] = {nid: run["nodes"][nid]["outputs"] for nid in sinks(graph) if run["nodes"][nid].get("outputs")}
    write_run(env, run)
    return run


def sinks(graph):
    used = {parse_ref(ref)[0] for n in graph["nodes"] for ref in sources_of(n)}
    return [n["id"] for n in graph["nodes"] if n["id"] not in used]


def env_dict(env):
    return dict(base=env.base, out_dir=env.out_dir, tier=env.tier)


def final_files(run):
    """Paths to publish as the job's results: file outputs of the sink nodes (lists included)."""
    out = []
    for outputs in run["final"].values():
        for o in outputs.values():
            out += [Path(x["path"]) for x in _as_list(o) if x.get("path")]
    return out


def chain(stages, registry):
    """Wire a list of stages into a graph: each stage takes the previous stage's result in its first free input of the same type.
    stages: [{"cap", "params"?, "inputs"?: {port: "media id" | {"media"|"from": ...}}, "each"?, "bind"?, "when"?, "id"?, "label"?}].
    A list from the previous stage (frames, a matrix, an `each` node) feeding a single port makes the stage run once per item.
    Raises ValueError saying which stage cannot take what the previous one produces."""
    if not isinstance(stages, list) or not stages:
        raise ValueError("stages precisa ser uma lista com pelo menos um passo")
    nodes, prev = [], None  # prev = (node id, capability, node)
    for index, stage in enumerate(stages, 1):
        if not isinstance(stage, dict) or not stage.get("cap"):
            raise ValueError(f"passo {index}: falta o campo «cap»")
        try:
            cap = registry.get(stage["cap"])
        except KeyError:
            raise ValueError(f"passo {index}: «{stage['cap']}» não existe no catálogo (use list_capabilities)") from None
        nid = str(stage.get("id") or f"{caps.slug(cap.id)}_{index}")
        node = dict(id=nid, cap=cap.id, params=dict(stage.get("params") or {}))
        for key in ("each", "bind", "when", "label"):
            if stage.get(key) is not None:
                node[key] = stage[key]
        inputs = {}
        for port, source in (stage.get("inputs") or {}).items():
            inputs[port] = {"media": source} if isinstance(source, str) else source
        if prev is not None:
            pid, pcap, pnode = prev
            taken = set(inputs)
            options = [p for p in cap.inputs if p.name not in taken]
            link = None
            for port in sorted(options, key=lambda p: not p.required):
                out = next((o for o in pcap.outputs if o.name == port.name and o.type == port.type), None) or next((o for o in pcap.outputs if o.type == port.type), None)
                if out is not None:
                    link = (port, out)
                    break
            if link is None and not any("from" in v for v in inputs.values() if isinstance(v, dict)):
                raise ValueError(f"passo {index}: {cap.id} não aceita o que {pcap.id} produz ({', '.join(o.type for o in pcap.outputs)}); ele aceita {', '.join(f'{p.name}:{p.type}' for p in cap.inputs) or 'nada'}")
            if link is not None:
                port, out = link
                inputs[port.name] = {"from": f"{pid}.{out.name}"}
                if (out.many or pnode.get("each")) and not port.many and "each" not in node:
                    node["each"] = port.name
        if inputs:
            node["inputs"] = inputs
        nodes.append(node)
        prev = (nid, cap, node)
    return {"nodes": nodes}


def _rewire(nodes, old, new, skip=()):
    """Point every reference to `old` ("node.port") at `new`, except inside the nodes in `skip`."""
    for node in nodes:
        if node.get("id") in skip:
            continue
        for value in (node.get("inputs") or {}).values():
            for src in value if isinstance(value, list) else [value]:
                if isinstance(src, dict) and src.get("from") == old:
                    src["from"] = new
        for key, ref in list((node.get("bind") or {}).items()):
            if isinstance(ref, dict) and ref.get("from") == old:
                ref["from"] = new
            elif ref == old:
                node["bind"][key] = new
        when = node.get("when")
        if isinstance(when, dict) and when.get("from") == old:
            when["from"] = new


def edit(graph, ops, registry):
    """Revise a graph without rewriting it. Returns a NEW graph; raises ValueError (plain language) when an operation cannot be applied.
    ops: [{"op": "set_param", "node", "name", "value"} | {"op": "set_params", "node", "params"} | {"op": "remove", "node"} (consumers are
    re-pointed to what the node itself read, when the type matches) | {"op": "insert_after", "node", "cap", "params"?, "id"?, "output"?}
    (the new step reads that output and takes over its consumers) | {"op": "replace_cap", "node", "cap", "params"?} | {"op": "set_each", "node",
    "each"} (null clears it) | {"op": "set_when", "node", "when"} | {"op": "set_bind", "node", "param", "ref"}]."""
    import copy
    graph = copy.deepcopy(graph)
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not isinstance(ops, list) or not ops:
        raise ValueError("passe um grafo com «nodes» e uma lista de operações")

    def find(nid):
        for n in nodes:
            if n.get("id") == nid:
                return n
        raise ValueError(f"o nó «{nid}» não existe no grafo ({', '.join(str(n.get('id')) for n in nodes)})")

    def capability(cap_id):
        try:
            return registry.get(cap_id)
        except KeyError:
            raise ValueError(f"«{cap_id}» não existe no catálogo (use list_capabilities)") from None

    for number, op in enumerate(ops, 1):
        kind = (op or {}).get("op")
        try:
            if kind == "set_param":
                find(op["node"]).setdefault("params", {})[op["name"]] = op["value"]
            elif kind == "set_params":
                find(op["node"]).setdefault("params", {}).update(op["params"])
            elif kind == "set_each":
                node = find(op["node"])
                if op.get("each"):
                    node["each"] = op["each"]
                else:
                    node.pop("each", None)
            elif kind == "set_when":
                node = find(op["node"])
                if op.get("when"):
                    node["when"] = op["when"]
                else:
                    node.pop("when", None)
            elif kind == "set_bind":
                node = find(op["node"])
                if op.get("ref"):
                    node.setdefault("bind", {})[op["param"]] = op["ref"]
                else:
                    (node.get("bind") or {}).pop(op["param"], None)
            elif kind == "replace_cap":
                node = find(op["node"])
                capability(op["cap"])
                node["cap"] = op["cap"]
                node["params"] = dict(op.get("params") or {})
            elif kind == "remove":
                node = find(op["node"])
                cap = capability(node["cap"])
                for out in cap.outputs:
                    ref = f"{node['id']}.{out.name}"
                    users = [n for n in nodes if n is not node and ref in sources_of(n)]
                    if not users:
                        continue
                    feed = next((src for p in cap.inputs if p.type == out.type for src in [((node.get("inputs") or {}).get(p.name))] if isinstance(src, dict)), None)
                    if feed is None:
                        raise ValueError(f"«{node['id']}» alimenta {', '.join(u['id'] for u in users)} e não tem uma entrada do tipo {out.type} para repassar; remova ou troque esses passos também")
                    if "from" in feed:
                        _rewire(nodes, ref, feed["from"], skip=(node["id"],))
                    else:  # a media id: consumers that read this output read the media directly
                        for u in users:
                            for pname, value in (u.get("inputs") or {}).items():
                                if isinstance(value, dict) and value.get("from") == ref:
                                    u["inputs"][pname] = dict(feed)
                nodes.remove(node)
            elif kind == "insert_after":
                node = find(op["node"])
                cap, new_cap = capability(node["cap"]), capability(op["cap"])
                out = next((o for o in cap.outputs if o.name == op.get("output")), None) if op.get("output") else (cap.outputs[0] if cap.outputs else None)
                if out is None:
                    raise ValueError(f"«{node['id']}» não tem a saída «{op.get('output')}»")
                port = next((p for p in new_cap.inputs if p.type == out.type), None)
                back = next((o for o in new_cap.outputs if o.type == out.type), None)
                if port is None or back is None:
                    raise ValueError(f"{new_cap.id} não recebe e devolve {out.type}, então não cabe depois de «{node['id']}.{out.name}»")
                new_id = str(op.get("id") or f"{caps.slug(new_cap.id)}_{len(nodes) + 1}")
                if any(n.get("id") == new_id for n in nodes):
                    raise ValueError(f"o id «{new_id}» já existe; escolha outro em «id»")
                fresh = dict(id=new_id, cap=new_cap.id, params=dict(op.get("params") or {}), inputs={port.name: {"from": f"{node['id']}.{out.name}"}})
                if (out.many or node.get("each")) and not port.many:
                    fresh["each"] = port.name
                _rewire(nodes, f"{node['id']}.{out.name}", f"{new_id}.{back.name}", skip=(new_id,))
                nodes.insert(nodes.index(node) + 1, fresh)
            else:
                raise ValueError(f"operação «{kind}» desconhecida (use set_param, set_params, set_each, set_when, set_bind, replace_cap, remove, insert_after)")
        except KeyError as exc:
            raise ValueError(f"operação {number} ({kind}): falta o campo {exc}") from None
        except ValueError as exc:
            raise ValueError(f"operação {number} ({kind}): {exc}") from None
    return graph


class AppCtx:
    """The job context an app runner expects, with its output folder pointed at the node's own work dir."""

    def __init__(self, ctx, out_dir):
        self._ctx, self.out_dir = ctx, Path(out_dir)

    def __getattr__(self, name):
        return getattr(self._ctx, name)


def app_runner(registry, cap):
    """Adapter: run a whole App as a DAG node. File inputs become the lists of paths the app's form would have produced."""
    app = registry.apps.get(cap.id.removeprefix("app."))
    if app is None:
        raise ValueError(f"{cap.id} não tem runner")

    def run(env, ctx, inputs, params, work):
        fields = app.fields(env["tier"])
        values = {f["id"]: (f.get("default") if f["type"] != "files" else []) for f in fields if f["type"] not in ("lights",)}
        for f in fields:
            if f["type"] == "files" and f["id"] in inputs:
                items = inputs[f["id"]] if isinstance(inputs[f["id"]], list) else [inputs[f["id"]]]
                values[f["id"]] = [a["path"] for a in items]
        values.update(params)
        outputs = app.runner(AppCtx(ctx, work), values, env["tier"]) or []
        files = [Path(o) for o in outputs if Path(o).is_file()]
        if not files:
            raise ValueError(f"{app.title} não gerou nenhum arquivo")
        return {"result": art_of(cap.outputs[0].type, files[0])}

    return run


def art_of(type_, path):
    return caps.art(type_, path)
