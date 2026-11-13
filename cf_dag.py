"""Typed, versioned DAG executor with a content-hash cache, partial re-run, cancel and resume.

A graph is {"nodes": [{"id", "cap", "inputs": {port: {"media": id} | {"from": "node.output"}}, "params": {...}}]}.
  * validate() explains every incompatibility (never silently hides one): unknown capability, missing input, type mismatch,
    cycle, bad parameter, not enough VRAM, unresolved media.
  * execute() runs nodes in topological order. A node's hash is sha256(capability id + version + params + the content hash of
    every input), so an unchanged node is a cache hit and only changed nodes (and their descendants) recompute. That is the
    partial re-run, and also resume: after a cancel or a crash the same graph reuses everything that finished.
  * Every run writes a provenance record: which capability version ran, with which inputs/params, which nodes were cached.
Outputs live under <out_dir>/dag/cache/<hash>/ so the job manager can publish them like any other result.
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
    for nid, node in nodes.items():
        try:
            cap = registry.get(node.get("cap"))
        except KeyError:
            errors.append(error(nid, "unknown_capability", f"«{node.get('cap')}» não existe no catálogo de capacidades"))
            continue
        for problem in caps.check_params(cap, node.get("params") or {}):
            errors.append(error(nid, "bad_param", f"{nid}: {problem}"))
        given = node.get("inputs") or {}
        ports = {p.name: p for p in cap.inputs}
        for name in given:
            if name not in ports:
                errors.append(error(nid, "unknown_input", f"{nid}: «{name}» não é uma entrada de {cap.id} (entradas: {', '.join(ports) or 'nenhuma'})"))
        for port in cap.inputs:
            sources = given.get(port.name)
            if sources is None:
                if port.required:
                    errors.append(error(nid, "missing_input", f"{nid}: falta a entrada «{port.name}» ({port.type}) de {cap.id}"))
                continue
            sources = sources if isinstance(sources, list) else [sources]
            if len(sources) > 1 and not port.many:
                errors.append(error(nid, "too_many", f"{nid}: «{port.name}» aceita só uma origem"))
            for src in sources:
                have = None
                if isinstance(src, dict) and "from" in src:
                    other, out_name = parse_ref(src["from"])
                    if other not in nodes:
                        errors.append(error(nid, "unknown_source", f"{nid}: a origem «{src['from']}» não existe"))
                        continue
                    edges[other].add(nid)
                    try:
                        other_cap = registry.get(nodes[other].get("cap"))
                    except KeyError:
                        continue
                    out = next((o for o in other_cap.outputs if o.name == out_name), None)
                    if out is None:
                        errors.append(error(nid, "unknown_output", f"{nid}: «{other}» ({other_cap.id}) não produz «{out_name}» (produz: {', '.join(o.name for o in other_cap.outputs)})"))
                        continue
                    have = out.type
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
        req = cap.requires
        if tier is not None and req.get("vram_gb") and tier.vram_gb < req["vram_gb"]:
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
        for sources in (node.get("inputs") or {}).values():
            for src in sources if isinstance(sources, list) else [sources]:
                if isinstance(src, dict) and "from" in src:
                    kids[parse_ref(src["from"])[0]].add(node["id"])
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


def node_hash(cap, node, input_hashes):
    payload = json.dumps(dict(cap=cap.id, version=cap.version, params=node.get("params") or {}, inputs=input_hashes), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def load_cached(env, digest):
    meta = env.cache / digest / "meta.json"
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        root = env.cache / digest / "out"
        outputs = {}
        for name, a in data["outputs"].items():
            outputs[name] = dict(type=a["type"], value=a.get("value"), path=str(root / a["file"]) if a.get("file") else None)
            if outputs[name]["path"] and not Path(outputs[name]["path"]).is_file():
                return None
        return outputs
    except (OSError, ValueError, KeyError):
        return None


def store(env, digest, cap, outputs, seconds):
    final = env.cache / digest
    staging = env.cache / f".{digest}.{uuid.uuid4().hex[:6]}"
    (staging / "out").mkdir(parents=True)
    meta = {}
    for name, a in outputs.items():
        entry = dict(type=a["type"], value=a.get("value"))
        if a.get("path"):
            src = Path(a["path"])
            target = staging / "out" / f"{name}{src.suffix}"
            shutil.copyfile(src, target)
            entry["file"] = target.name
        meta[name] = entry
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
    resumed = None
    if run_id:
        try:
            resumed = load_run(env, run_id)
            run["created"] = resumed.get("created", run["created"])
            run["resumed"] = True
        except (OSError, ValueError):
            pass
    write_run(env, run)
    values, total = {}, max(1, len(report["order"]))
    try:
        for index, nid in enumerate(report["order"]):
            ctx.check()
            node, cap = nodes[nid], registry.get(nodes[nid]["cap"])
            gathered, hashes = {}, {}
            for port in cap.inputs:
                sources = (node.get("inputs") or {}).get(port.name)
                if sources is None:
                    continue
                items = []
                for src in sources if isinstance(sources, list) else [sources]:
                    if "from" in src:
                        other, out_name = parse_ref(src["from"])
                        items.append(values[other][out_name])
                    else:
                        found = env.resolve_media(src["media"])
                        items.append(dict(type=found["type"], path=found["path"], value=None))
                gathered[port.name] = items if port.many else items[0]
                hashes[port.name] = [artifact_hash(a) for a in items]
            digest = node_hash(cap, node, hashes)
            rec = run["nodes"][nid]
            rec.update(hash=digest, inputs={k: v for k, v in hashes.items()}, params=node.get("params") or {})
            cached = None if nid in forced else load_cached(env, digest)
            if cached is not None:
                rec.update(status="em cache", started=time.time(), finished=time.time())
                values[nid] = cached
            else:
                rec.update(status="executando", started=time.time())
                write_run(env, run)
                ctx.progress(index / total, desc=f"{cap.title} ({index + 1}/{len(report['order'])})")
                runner = cap.run or app_runner(registry, cap)
                work = env.cache / f".work-{digest[:12]}-{uuid.uuid4().hex[:6]}"
                work.mkdir(parents=True)
                started = time.monotonic()
                try:
                    produced = runner(env_dict(env), ctx, gathered, node.get("params") or {}, work)
                    values[nid] = store(env, digest, cap, produced, time.monotonic() - started)
                finally:
                    shutil.rmtree(work, ignore_errors=True)
                rec.update(status="concluído", finished=time.time())
            rec["outputs"] = {name: dict(type=a["type"], path=a.get("path"), value=a.get("value"), sha256=artifact_hash(a)) for name, a in values[nid].items()}
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
    run["final"] = {nid: run["nodes"][nid]["outputs"] for nid in sinks(graph)}
    write_run(env, run)
    return run


def sinks(graph):
    used = {parse_ref(s["from"])[0] for n in graph["nodes"] for v in (n.get("inputs") or {}).values() for s in (v if isinstance(v, list) else [v]) if "from" in s}
    return [n["id"] for n in graph["nodes"] if n["id"] not in used]


def env_dict(env):
    return dict(base=env.base, out_dir=env.out_dir, tier=env.tier)


def final_files(run):
    """Paths to publish as the job's results: file outputs of the sink nodes."""
    return [Path(o["path"]) for outputs in run["final"].values() for o in outputs.values() if o.get("path")]


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
