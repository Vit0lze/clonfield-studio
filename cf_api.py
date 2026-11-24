"""HTTP API and static hosting for the Studio web app. Pure Starlette so it runs under Gradio or alone."""

import asyncio
import hashlib
import hmac
import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

import requests
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import cf_apps
import cf_registry as registry_mod
import cf_search
import cf_sizes
import cf_upscale
import cf_router
import cf_assets
import cf_agent
import cf_capabilities
import cf_chat
import cf_dag
import cf_myflows
import cf_recipes
import cf_contracts
import cf_cast
import cf_asset_graph
import cf_cinema
import cf_env
import cf_favorites
import cf_library
import cf_llm
import cf_civitai
import cf_jobs
import cf_loras
import cf_tiers
import cf_workflows as workflows
import cf_seedvr2 as seedvr2
from cf_jobs import JobError

PREFIX = "/clonfield/api"
MAX_UPLOAD = 1024**3
UPLOAD_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif", ".mp4", ".mov", ".webm", ".mkv",
                   ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".json", ".safetensors"}
FILE_FIELDS = {"files"}


class RevalidatedFiles(StaticFiles):
    """Static files that the browser must revalidate (ETag), so a new Studio build never hides behind a cached module."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def worker_rss_gb():
    """Resident memory of the ComfyUI worker in GB, or None when it is not running."""
    import cf_worker
    import cf_workflows
    found = cf_worker.find(cf_worker.port_of(cf_workflows.SERVER))
    return cf_worker.rss_gb(found[0]) if found else None


def build_app(base, out_dir, verify, secret, portal_dir=None):
    base, out_dir = Path(base), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    uploads = base / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    cf_apps.configure(base, out_dir)
    cf_civitai.set_cover_cache(base / "cache" / "covers")
    manager = cf_jobs.Manager(out_dir)
    manager.before_gpu = cf_llm.release_gpu
    try:
        import cf_worker
        import cf_workflows
        cf_worker.capture(cf_workflows.SERVER)  # how the worker was started, so it can be restarted (memory only)
    except Exception:
        pass
    import cf_worker as _cf_worker
    cf_llm.set_gpu_guard(lambda: manager.gpu_active or _cf_worker.busy())  # a classic-mode prompt also holds the worker (V9-P0)

    def free_comfy():
        import requests as _requests
        with _requests.Session() as session:
            session.trust_env = False
            workflows.free_models(session)
    cf_llm.set_comfy_release(free_comfy)
    tier = cf_tiers.detect()
    secret = secret.encode() if isinstance(secret, str) else secret

    def sign(rel, ttl=6 * 3600):
        # The expiry is rounded to a fixed window, so the same file gets the SAME url on every poll within the window.
        # A url that changes every second makes the browser refetch (and repaint) every image on every refresh.
        window = ttl // 2
        expires = (int(time.time()) // window + 2) * window
        mac = hmac.new(secret, f"{rel}|{expires}".encode(), hashlib.sha256).hexdigest()[:32]
        return f"{PREFIX}/files/{rel}?e={expires}&s={mac}"

    def signed(rel, expires, mac):
        try:
            good = hmac.new(secret, f"{rel}|{int(expires)}".encode(), hashlib.sha256).hexdigest()[:32]
            return int(expires) > time.time() and hmac.compare_digest(good, mac)
        except (TypeError, ValueError):
            return False

    def authed(request):
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        return scheme.lower() == "bearer" and verify(token)

    def guard(handler):
        async def wrapped(request):
            if not authed(request):
                return JSONResponse({"detail": "Sessão inválida. Conecte novamente."}, 401, {"Cache-Control": "no-store"})
            try:
                return await handler(request)
            except JobError as exc:
                return JSONResponse({"detail": str(exc)}, 400)
            except ValueError as exc:
                return JSONResponse({"detail": str(exc)}, 400)
        return wrapped

    def public_job(job):
        data = job.snapshot(manager.position(job))
        data["results"] = [{**r, "url": sign(r["path"])} for r in data["results"]]
        run = (data.get("params") or {}).get("run")
        if run:
            data["run"] = run  # the DAG run record the screen reads for the per-step timeline
        plan = (data.get("params") or {}).get("plan")
        if plan:
            data["plan"] = plan  # the steps an agent job was built with (capability + params), available before the run record exists
        used = (data.get("params") or {}).get("_asset_versions")
        if used:
            data["asset_versions"] = used  # which AssetRef version each a_/v_ id resolved to (provenance)
        data.pop("params", None)
        return data

    # ---- read endpoints
    async def system(request):
        def read():
            info = {"tier": tier.public(), "version": 2}
            mem = {}
            try:
                for line in Path("/proc/meminfo").read_text().splitlines():
                    key, value = line.split(":", 1)
                    mem[key] = int(value.split()[0])
            except (OSError, ValueError):
                pass
            info["ram_gb"] = round(mem.get("MemTotal", 0) / 1024**2, 1)
            info["ram_free_gb"] = round(mem.get("MemAvailable", 0) / 1024**2, 1)
            info["worker_rss_gb"] = worker_rss_gb()  # the ComfyUI process only: shows its memory growing job after job
            usage = shutil.disk_usage(base)
            info["disk_free_gb"] = round(usage.free / 1024**3, 1)
            info["credentials"] = {"hf": bool(os.environ.get("HF_TOKEN")), "civitai": bool(os.environ.get("CIVITAI_TOKEN"))}
            try:
                with requests.Session() as session:
                    session.trust_env = False
                    stats = session.get(f"{workflows.SERVER}/system_stats", timeout=2).json()
                    queue = session.get(f"{workflows.SERVER}/queue", timeout=2).json()
                info["worker"] = {"ok": True, "running": len(queue.get("queue_running", [])),
                                  "pending": len(queue.get("queue_pending", [])),
                                  "version": stats.get("system", {}).get("comfyui_version")}
            except (requests.RequestException, ValueError):
                info["worker"] = {"ok": False, "log": workflows.worker_log_tail(8)}
            return info
        return JSONResponse(await run_in_threadpool(read), headers={"Cache-Control": "no-store"})

    async def apps(request):
        registry = cf_apps.registry()
        return JSONResponse([app.describe(tier) for app in registry.values() if not app.hidden])

    async def benchmarks(request):
        try:
            return JSONResponse(json.loads((cf_apps.ENV["base"] / "benchmarks.json").read_text()))
        except (OSError, ValueError):
            return JSONResponse([])

    async def route_request(request):
        body = await request.json()
        kinds = {k for k in (body.get("media") or []) if k in ("image", "video", "audio")}
        try:
            return JSONResponse(await run_in_threadpool(cf_router.route, str(body.get("request", ""))[:2000], kinds, cf_apps.registry(), tier))
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, 400)

    async def plan_request(request):
        body = await request.json()
        kinds = {k for k in (body.get("media") or []) if k in ("image", "video", "audio")}
        try:
            result = await run_in_threadpool(cf_router.plan, str(body.get("request", ""))[:2000], kinds, cf_apps.registry(), tier)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, 400)
        return JSONResponse(result)

    def cast_item(item):
        return dict(id=item["id"], name=item["name"], description=item.get("description", ""), created=item.get("created"),
                    image=sign(f"cast/{item['image']}") if item.get("image") else None)

    async def cast_list(request):
        return JSONResponse([cast_item(i) for i in cf_cast.load(base)])

    async def cast_create(request):
        body = await request.json()
        image = None
        ident = str(body.get("upload") or "")
        if ident:
            if not re.fullmatch(r"[0-9a-f]{32}", ident):
                raise ValueError("Arquivo enviado inválido.")
            found = next(iter((uploads / ident).iterdir()), None) if (uploads / ident).is_dir() else None
            if found is None:
                raise ValueError("A imagem enviada expirou. Envie de novo.")
            image = found
        return JSONResponse(cast_item(cf_cast.add(base, body.get("name"), body.get("description"), image)))

    async def cast_delete(request):
        cf_cast.remove(base, request.path_params["ident"])
        return JSONResponse({"ok": True})

    async def slots(request):
        key = request.query_params.get("model", "")
        if key not in cf_apps.IMAGE_MODELS:
            return JSONResponse({"detail": "Modelo desconhecido."}, 404)
        return JSONResponse(await run_in_threadpool(registry_mod.slots, key, cf_apps.ENV["civitai"]))

    # ------------------------------------------------------------ chat sessions
    async def sessions_list(request):
        return JSONResponse(cf_chat.listing(base), headers={"Cache-Control": "no-store"})

    async def sessions_create(request):
        body = await request.json() if request.headers.get("content-length") not in (None, "0") else {}
        return JSONResponse(cf_chat.create(base, str((body or {}).get("title", ""))), 201)

    def session_or_404(ident):
        try:
            return cf_chat.load(base, ident)
        except KeyError:
            return None

    def with_urls(session):
        for item in session["media"]:
            folder = uploads / item["id"]
            found = next(iter(folder.iterdir()), None) if folder.is_dir() else None
            item["url"] = sign(found.relative_to(base).as_posix()) if found else None
            item["gone"] = found is None
        return session

    async def sessions_get(request):
        session = session_or_404(request.path_params["id"])
        if session is None:
            return JSONResponse({"detail": "Conversa não encontrada."}, 404)
        return JSONResponse(with_urls(session), headers={"Cache-Control": "no-store"})

    async def sessions_delete(request):
        try:
            cf_chat.delete(base, request.path_params["id"])
        except KeyError:
            return JSONResponse({"detail": "Conversa não encontrada."}, 404)
        return JSONResponse({"ok": True})

    async def sessions_rename(request):
        session = session_or_404(request.path_params["id"])
        if session is None:
            return JSONResponse({"detail": "Conversa não encontrada."}, 404)
        title = str((await request.json()).get("title", "")).strip()[:80]
        if not title:
            return JSONResponse({"detail": "Dê um nome à conversa."}, 400)
        session["title"] = title
        cf_chat.save(base, session)
        return JSONResponse({"ok": True})

    def write_reply(session_id, reply_id, plan_id, snap):
        """Runs in a thread: the local model can take a while, so the plan is already on screen while it writes."""
        try:
            out = cf_llm.converse(snap["text"], snap["kinds"], snap["titles"], snap["conversation"], snap["history"], snap["apps"])
            error = None
        except (cf_llm.LLMError, requests.RequestException) as exc:
            out, error = None, str(exc)[:160]

        def apply(session):
            for m in session["messages"]:
                if m["id"] == reply_id:
                    m["pending"] = False
                    if out:
                        m["text"], m["question"], m["model"] = out["reply"], out["question"], cf_llm.models()[0]
                    else:
                        m["text"], m["error"] = f"Não consegui falar com o modelo local agora ({error}). O plano acima continua valendo.", True
                elif plan_id and m["id"] == plan_id and out and out.get("prompt") and m["plan"].get("prompt") == m["plan"].get("text") and not any(x["role"] == "job" for x in session["messages"]):
                    m["plan"]["prompt"] = out["prompt"]  # only fills the box if the user has not rewritten it and nothing has run yet
        cf_chat.update(base, session_id, apply)

    # ---- capabilities, DAG, agent
    def capability_registry():
        return cf_capabilities.Registry(cf_apps.registry(), tier)

    def dag_env(resolver):
        return cf_dag.Env(base, out_dir, tier, resolver)

    def media_file(ident, used=None):
        """The one place an id becomes a file: a 32-hex upload folder, or an asset id (v_ = exact version, a_ = its current one).
        Asset ids resolve to the blob itself (no copy); `used` collects {requested id: version_id} for provenance. None when unknown."""
        if not isinstance(ident, str):
            return None
        if re.fullmatch(r"[0-9a-f]{32}", ident):
            folder = uploads / ident
            return next(iter(folder.iterdir()), None) if folder.is_dir() else None
        found = cf_asset_graph.resolve_ref(base, ident)
        if found is None:
            return None
        if used is not None:
            used[ident] = found[1]["version_id"]
        return found[0]

    def upload_media(ident):
        """A media id (upload or asset version) as a DAG artifact source. Only ids that really exist resolve."""
        found = media_file(ident)
        if found is None:
            return None
        return dict(type=cf_jobs.KINDS.get(found.suffix.lower(), "file"), path=str(found), name=found.name)

    async def capabilities_list(request):
        q = request.query_params
        found = capability_registry().catalog(kind=q.get("kind") or None, query=q.get("q") or None, produces=q.get("produces") or None, accepts=q.get("accepts") or None)
        if q.get("app"):  # the capabilities one app uses or lets you insert around its result
            found = [c for c in found if any(x["app"] == q["app"] for x in c["consumers"] + c["insertable_in"])]
        return JSONResponse(found, headers={"Cache-Control": "no-store"})

    async def capability_get(request):
        try:
            return JSONResponse(capability_registry().describe(request.path_params["id"]))
        except KeyError:
            return JSONResponse({"detail": "Capacidade desconhecida."}, 404)

    async def dag_validate(request):
        body = await request.json()
        report = cf_dag.validate(body.get("graph") or {}, capability_registry(), tier, upload_media)
        return JSONResponse(dict(ok=report["ok"], errors=report["errors"], order=report["order"], resources=report["resources"]))

    async def dag_run(request):
        body = await request.json()
        registry = capability_registry()
        graph = body.get("graph") or {}
        report = cf_dag.validate(graph, registry, tier, upload_media)
        if not report["ok"]:
            return JSONResponse({"detail": "O grafo tem incompatibilidades.", "errors": report["errors"]}, 409)
        if report["resources"]["risk"] != "low" and not body.get("confirm"):
            return JSONResponse({"detail": "Este grafo usa uma capacidade de risco alto. Confirme para executar.", "needs_confirmation": True}, 409)
        env = dag_env(upload_media)
        force = [str(f) for f in body.get("force") or []]
        title = "Grafo · " + ", ".join(n["cap"] for n in graph["nodes"])[:60]

        run_id = uuid.uuid4().hex[:12]

        def runner(ctx):
            return cf_dag.job_result(cf_dag.execute(graph, registry, env, ctx, run_id=run_id, force=force))

        job = manager.submit("dag", title, {"run": run_id}, report["resources"]["lane"], runner)
        return JSONResponse(public_job(job), 202)

    async def cinema_validate(request):
        body = await request.json()
        timeline = body.get("timeline")
        try:
            sources = cf_cinema.validate(timeline, base)
        except ValueError as exc:
            return JSONResponse({"ok": False, "detail": str(exc)}, 400)
        return JSONResponse({"ok": True, "duration_s": round(cf_cinema.duration(timeline), 3), "shots": len(timeline["video"]),
                             "versions": sorted(sources)})

    async def cinema_render(request):
        """Renders a Timeline.v1 on the CPU lane. Unchanged shots, stems and mix come from <base>/cinema/cache."""
        body = await request.json()
        timeline = body.get("timeline")
        try:
            sources = cf_cinema.validate(timeline, base)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, 400)

        def runner(ctx):
            try:
                folder = ctx.out_dir / f"cinema_{ctx.job.id.removeprefix('job_')}"  # one folder per export: a later one never overwrites it
                record = cf_cinema.render(timeline, base, folder, ctx.progress, ctx.control)
            except cf_cinema.Cancelled:
                raise cf_jobs.JobError("Cancelado por você.", "cancelado")
            return cf_cinema.result_files(record, folder)

        title = "Cinema · " + str(timeline.get("title") or timeline.get("name") or "curta")[:60]
        job = manager.submit("cinema", title, {"_asset_versions": {v: v for v in sorted(sources)}}, "cpu", runner)
        return JSONResponse(public_job(job), 202)

    def cinema_project_public(project):
        """The project plus what the screen draws: each shot with its time span and the versions of its asset (signed urls),
        per cut the audio lanes and the current render signature (to tell whether an export still shows this timeline)."""
        shots, start = [], 0.0
        fps = project["timeline"].get("fps", 24)
        for shot in project["timeline"]["video"]:
            span = cf_cinema.frames(shot["dur"], fps) / fps
            item = dict(shot, start=round(start, 3), end=round(start + span, 3))
            if isinstance(shot["src"], str):
                ref = cf_asset_graph.get_version(base, shot["src"])
                asset = cf_asset_graph.get(base, ref["asset_id"])
                item.update(asset_id=ref["asset_id"], asset_title=asset.get("title"), kind=ref["kind"], version=version_public(ref),
                            natural_s=(ref.get("media") or {}).get("duration_s"),
                            versions=[version_public(v) for v in cf_asset_graph.versions(base, ref["asset_id"])])
            shots.append(item)
            start += span

        def lane(clips):
            out = []
            for clip in clips:
                ref = cf_asset_graph.get_version(base, clip["src"])
                length = clip.get("dur") or (ref.get("media") or {}).get("duration_s") or 0
                out.append(dict(at=clip.get("at", 0), dur=round(float(length), 3), title=(ref.get("metadata") or {}).get("title"),
                                note=clip.get("note"), gain_db=clip.get("gain_db", 0)))
            return out

        cuts = {cid: dict(label=cut.get("label", cid), note=cut.get("note"), mix=cut.get("mix", {}),
                          signature=cf_cinema.signature(project, cid),
                          lanes={track: lane(clips) for track, clips in cf_cinema.compose(project, cid)["audio"].items()})
                for cid, cut in project["cuts"].items()}
        return dict(project, shots=shots, cuts_view=cuts, duration_s=round(start, 3), shot_limits=list(cf_cinema.SHOT_DUR))

    def cinema_call(change, status=200):
        """Run one project change in a worker thread and answer with the whole project (or the reason it was refused)."""
        async def answer(request):
            body = await request.json() if request.method == "POST" else {}
            try:
                project = await run_in_threadpool(lambda: change(request.path_params, body or {}))
            except KeyError:
                return JSONResponse({"detail": "Projeto não encontrado."}, 404)
            except (ValueError, cf_asset_graph.NotFound) as exc:
                return JSONResponse({"detail": str(exc)}, 400)
            return JSONResponse(cinema_project_public(project), status, headers={"Cache-Control": "no-store"})
        return answer

    async def cinema_projects(request):
        if request.method == "GET":
            return JSONResponse(cf_cinema.list_projects(base), headers={"Cache-Control": "no-store"})
        return await cinema_call(lambda _, b: cf_cinema.create_project(base, b.get("title"), b.get("timeline"), b.get("cuts"), b.get("cut")), 201)(request)

    def shot_change(params, body):
        pid, shot = params["id"], params["shot"]
        if body.get("remove"):
            return cf_cinema.remove_shot(base, pid, shot)
        if "dur" in body:
            return cf_cinema.set_shot_duration(base, pid, shot, body["dur"])
        return cf_cinema.set_shot_version(base, pid, shot, body.get("version"))

    cinema_project = cinema_call(lambda p, _: cf_cinema.load_project(base, p["id"]))
    cinema_project_add = cinema_call(lambda p, b: cf_cinema.add_shot(base, p["id"], b.get("asset"), b.get("dur")))
    cinema_project_shot = cinema_call(shot_change)
    cinema_project_order = cinema_call(lambda p, b: cf_cinema.reorder(base, p["id"], b.get("order")))
    cinema_project_cut = cinema_call(lambda p, b: cf_cinema.set_cut(base, p["id"], b.get("cut")))

    async def cinema_project_export(request):
        """Export one cut, or several for an A/B session (one CPU job; the second cut reuses the whole picture).
        The attempt is logged on the project with its revision; only a finished one replaces `last_good`."""
        body = await request.json()
        try:
            project = cf_cinema.load_project(base, request.path_params["id"])
        except KeyError:
            return JSONResponse({"detail": "Projeto não encontrado."}, 404)
        if not project["timeline"]["video"]:
            return JSONResponse({"detail": "Adicione pelo menos um plano antes de exportar."}, 400)
        cuts = body.get("cuts") or [project["cut"]]
        if not isinstance(cuts, list) or any(c not in project["cuts"] for c in cuts) or len(set(cuts)) != len(cuts):
            return JSONResponse({"detail": "Cortes desconhecidos ou repetidos."}, 400)
        try:
            sources = set()
            for cut in cuts:
                sources |= set(cf_cinema.validate(cf_cinema.compose(project, cut), base))
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, 400)

        def runner(ctx):
            folder = ctx.out_dir / f"cinema_{ctx.job.id.removeprefix('job_')}"  # one folder per export: earlier A/B pairs stay intact
            try:
                records, files = cf_cinema.export_project(base, project, cuts, folder, ctx.progress, ctx.control)
            except (cf_cinema.Cancelled, cf_jobs.JobError) as exc:
                cf_cinema.finish_export(base, project["id"], ctx.job.id, "cancelado", message=str(exc))
                raise cf_jobs.JobError("Cancelado por você.", "cancelado") from None
            except Exception as exc:
                cf_cinema.finish_export(base, project["id"], ctx.job.id, "falhou", message=str(exc)[-400:])
                raise
            summary = {r["timeline"]["name"].removeprefix(project["slug"] + "-"): dict(rendered=r["rendered"], reused=r["reused"],
                                                                                        seconds=r["seconds"], loudness=r["film"]["loudness"])
                       for r in records}
            cf_cinema.finish_export(base, project["id"], ctx.job.id, "concluído", summary=summary)
            return files

        title = f"Cinema · {project['title']} · " + " + ".join(project["cuts"][c].get("label", c) for c in cuts)
        job = manager.submit("cinema", title[:90], {"_asset_versions": {v: v for v in sorted(sources)}, "project": project["id"], "cuts": cuts}, "cpu", runner)
        cf_cinema.begin_export(base, project["id"], job.id, cuts)
        return JSONResponse(public_job(job), 202)

    async def dag_run_get(request):
        try:
            return JSONResponse(cf_dag.load_run(dag_env(upload_media), request.path_params["id"]))
        except (OSError, ValueError):
            return JSONResponse({"detail": "Execução não encontrada."}, 404)

    async def dag_run_exposable(request):
        try:
            previous = cf_dag.load_run(dag_env(upload_media), request.path_params["id"])
        except (OSError, ValueError):
            return JSONResponse({"detail": "Execução não encontrada."}, 404)
        return JSONResponse(cf_myflows.exposable(capability_registry(), previous["graph"]))

    async def dag_run_save(request):
        """Keep the graph of a finished run as a reusable flow ("Meus fluxos"): media become form slots, `expose` params become fields."""
        try:
            previous = cf_dag.load_run(dag_env(upload_media), request.path_params["id"])
        except (OSError, ValueError):
            return JSONResponse({"detail": "Execução não encontrada."}, 404)
        body = await request.json()
        try:
            saved = cf_myflows.save(base, capability_registry(), previous["graph"], body.get("title"), body.get("tagline", ""), body.get("expose") or [], upload_media, tier)
        except (ValueError, KeyError, TypeError) as exc:
            return JSONResponse({"detail": str(exc)}, 400)
        return JSONResponse(saved, 201)

    async def dag_run_revise(request):
        """Re-run a finished (or failed) run: optional edit ops on its graph, optional nodes to force; everything unchanged comes from the cache."""
        env, registry = dag_env(upload_media), capability_registry()
        try:
            previous = cf_dag.load_run(env, request.path_params["id"])
        except (OSError, ValueError):
            return JSONResponse({"detail": "Execução não encontrada."}, 404)
        body = await request.json()
        try:
            graph = cf_dag.edit(previous["graph"], body["ops"], registry) if body.get("ops") else previous["graph"]
            force = [str(f) for f in (body.get("force") or [])]
            unknown = [f for f in force if f not in {n["id"] for n in graph["nodes"]}]
            if unknown:
                raise ValueError(f"o passo «{unknown[0]}» não existe neste fluxo")
            report = cf_dag.validate(graph, registry, tier, upload_media)
            if not report["ok"]:
                raise ValueError("; ".join(e["message"] for e in report["errors"][:3]))
        except (ValueError, TypeError) as exc:
            return JSONResponse({"detail": str(exc)}, 400)
        run_id = uuid.uuid4().hex[:12]

        def runner(ctx):
            return cf_dag.job_result(cf_dag.execute(graph, registry, env, ctx, run_id=run_id, force=force))
        title = str(body.get("title") or "Execução refeita")[:80]
        job = manager.submit("dag", title, {"run": run_id, "revises": previous["id"]}, report["resources"]["lane"], runner)
        return JSONResponse(public_job(job), 202)

    def recipe_graphs(recipe_id, body):
        """-> (recipe, [(vars, graph, report)]) for one form or a `batch` of forms. Raises KeyError / ValueError with a plain reason."""
        recipe = cf_recipes.get(recipe_id, base)
        sets = body.get("batch") if isinstance(body.get("batch"), list) else [body.get("vars") or {}]
        if not 1 <= len(sets) <= cf_recipes.MAX_BATCH:
            raise ValueError(f"A fila aceita de 1 a {cf_recipes.MAX_BATCH} execuções por vez.")
        registry, out = capability_registry(), []
        for index, raw in enumerate(sets, 1):
            try:
                values = cf_recipes.resolve(recipe, raw)
            except ValueError as exc:
                raise ValueError((f"Execução {index}: " if len(sets) > 1 else "") + str(exc)) from None
            graph = recipe.build(values)
            report = cf_dag.validate(graph, registry, tier, upload_media)
            if not report["ok"]:
                raise ValueError((f"Execução {index}: " if len(sets) > 1 else "") + "; ".join(e["message"] for e in report["errors"][:3]))
            out.append((values, graph, report))
        return recipe, out

    async def recipes_list(request):
        return JSONResponse(cf_recipes.catalog(base), headers={"Cache-Control": "no-store"})

    async def recipe_save(request):
        body = await request.json()
        try:
            saved = cf_myflows.save(base, capability_registry(), body.get("graph") or {}, body.get("title"), body.get("tagline", ""), body.get("expose") or [], upload_media, tier)
        except (ValueError, KeyError, TypeError) as exc:
            return JSONResponse({"detail": str(exc)}, 400)
        return JSONResponse(saved, 201)

    async def recipe_delete(request):
        try:
            cf_myflows.delete(base, request.path_params["id"])
        except KeyError:
            return JSONResponse({"detail": "Só fluxos salvos por você podem ser apagados."}, 404)
        return JSONResponse({"ok": True})

    async def recipe_preview(request):
        try:
            recipe, built = recipe_graphs(request.path_params["id"], await request.json())
        except KeyError:
            return JSONResponse({"detail": "Receita desconhecida."}, 404)
        except ValueError as exc:  # a half-filled form is not a server error: say what is missing and keep the status 200
            return JSONResponse(dict(ok=False, detail=str(exc)))
        values, graph, report = built[0]
        steps = [dict(id=n["id"], label=n.get("label") or n["cap"], cap=n["cap"], each=n.get("each"), when=bool(n.get("when")), when_not=bool((n.get("when") or {}).get("not"))) for n in graph["nodes"]]
        return JSONResponse(dict(ok=True, recipe=recipe.id, runs=len(built), steps=steps, resources=report["resources"], order=report["order"]))

    async def recipe_run(request):
        try:
            recipe, built = recipe_graphs(request.path_params["id"], await request.json())
        except KeyError:
            return JSONResponse({"detail": "Receita desconhecida."}, 404)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, 400)
        registry, env, jobs = capability_registry(), dag_env(upload_media), []
        for index, (values, graph, report) in enumerate(built, 1):
            run_id = uuid.uuid4().hex[:12]

            def runner(ctx, graph=graph, run_id=run_id):
                return cf_dag.job_result(cf_dag.execute(graph, registry, env, ctx, run_id=run_id))
            title = recipe.title + (f" · {index}/{len(built)}" if len(built) > 1 else "")
            jobs.append(public_job(manager.submit("dag", title, {"recipe": recipe.id, "run": run_id}, report["resources"]["lane"], runner)))
        return JSONResponse(dict(recipe=recipe.id, jobs=jobs), 202)

    def adopt_results(session_id, files, job):
        """Copy files a graph produced into the conversation's uploads and attach them to it, like a single-app step does."""
        fresh = []
        for path in files:
            source = Path(path)
            if not source.is_file():
                continue
            ident = uuid.uuid4().hex
            target = uploads / ident
            target.mkdir()
            copy = target / re.sub(r"[^\w.\- ]", "_", source.name)[:120]
            shutil.copyfile(source, copy)
            fresh.append({"id": ident, "name": copy.name, "kind": cf_jobs.KINDS.get(copy.suffix.lower(), "file")})
        cf_chat.update(base, session_id, lambda current: cf_chat.add_media(current, fresh, "result", app="dag", job=job.id))

    def run_agent_reply(session_id, reply_id, text, provider):
        """Runs in a thread: the model calls tools (real DAG jobs) and the conversation shows each step as it happens."""
        registry = capability_registry()

        def media_now():
            try:
                return [dict(id=m["id"], name=m["name"], kind=m["kind"], origin=m["origin"]) for m in cf_chat.load(base, session_id)["media"]]
            except KeyError:
                return []

        def resolver(ident):
            return upload_media(ident) if any(m["id"] == ident for m in media_now()) else None

        env = dag_env(resolver)
        host = cf_agent.LocalHost(registry, env, manager, media_now, on_result=lambda files, job: adopt_results(session_id, files, job),
                                  on_job=lambda job: cf_chat.update(base, session_id, lambda current: cf_chat.add_message(current, "job", job=job.id, app="dag", title=job.title)))
        history = cf_agent.history_from_session(cf_chat.load(base, session_id))[:-1]

        def on_step(entry):
            def apply(session):
                for m in session["messages"]:
                    if m["id"] == reply_id:
                        m.setdefault("agent", {"trace": []})["trace"].append(dict(entry, args=json.dumps(entry["args"], ensure_ascii=False)[:300]))
            cf_chat.update(base, session_id, apply)

        try:
            out = cf_agent.run_agent(provider, cf_agent.Toolbox(registry, env, host), text, history, on_step=on_step)
            error = None
        except (cf_agent.AgentError, requests.RequestException) as exc:
            out, error = None, str(exc)[:200]

        def finish(session):
            for m in session["messages"]:
                if m["id"] == reply_id:
                    m["pending"] = False
                    if out:
                        m["text"] = out["final"] or "Terminei os passos; confira os resultados acima."
                        m["agent"] = dict(m.get("agent") or {}, provider=out["provider"], model=out["model"], stop=out["stop"], steps=out["steps"])
                    else:
                        m["text"], m["error"] = f"Não consegui concluir com o agente ({error}).", True
        cf_chat.update(base, session_id, finish)

    async def favorites_list(request):
        return JSONResponse(cf_favorites.load(base), headers={"Cache-Control": "no-store"})

    async def favorites_toggle(request):
        body = await request.json()
        try:
            now = cf_favorites.toggle(base, str(body.get("kind", "")), body.get("id"), body.get("meta"))
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, 400)
        return JSONResponse({"favorite": now})

    async def llm_info(request):
        return JSONResponse(dict(available=cf_llm.available(), model=cf_llm.models()[0], backend=("colibri" if cf_llm.backend() == "colibri" else "llama-server") + " (local)", url=cf_llm.base_url(), agent=cf_env.flag("agent")))

    async def sessions_message(request):
        session = session_or_404(request.path_params["id"])
        if session is None:
            return JSONResponse({"detail": "Conversa não encontrada."}, 404)
        body = await request.json()
        text = str(body.get("text", "")).strip()[:2000]
        attached = [m for m in (body.get("media") or []) if isinstance(m, dict) and cf_chat.valid(m.get("id")) and m.get("kind") in ("image", "video", "audio", "file")]
        if not text and not attached:
            return JSONResponse({"detail": "Escreva algo ou anexe uma mídia."}, 400)
        for m in attached:
            if not (uploads / m["id"]).is_dir():
                return JSONResponse({"detail": "Um arquivo anexado expirou. Envie de novo."}, 400)
        cf_chat.add_media(session, [{"id": m["id"], "name": str(m.get("name", "arquivo"))[:120], "kind": m["kind"]} for m in attached], "upload")
        cf_chat.add_message(session, "user", text=text, media=[m["id"] for m in attached])
        cf_chat.retitle(session, text)
        provider = cf_agent.choose_provider() if (text and cf_env.flag("agent")) else None
        if text and provider is not None:
            reply = cf_chat.add_message(session, "assistant", text="", pending=True, kind="text", agent=dict(trace=[]))
            cf_chat.save(base, session)
            threading.Thread(target=run_agent_reply, args=(session["id"], reply["id"], text, provider), daemon=True).start()
            return JSONResponse(with_urls(session))
        if text:
            registry = cf_apps.registry()
            plan = await run_in_threadpool(cf_router.plan, text, cf_chat.kinds(session), registry, tier)
            conversation = bool(plan.get("conversation"))
            note = "" if conversation else "Sem agente neste ambiente: a heurística local sugere um passo."
            steps = []
            for step in plan["steps"]:
                if not step.get("app"):
                    continue
                app = registry[step["app"]]
                try:
                    cf_chat.build_params(app, app.fields(tier), text, session)
                    missing = []
                except cf_chat.Missing as gap:
                    missing = gap.labels
                steps.append(dict(app=step["app"], title=step["title"], probability=step.get("probability"), missing=missing))
            plan_id = None
            if steps and not conversation:
                plan_id = cf_chat.add_message(session, "assistant", plan=dict(provider=plan.get("provider", "local"), steps=steps, text=text, prompt=text, note=note))["id"]
            reply = cf_chat.add_message(session, "assistant", text="", pending=cf_llm.available(), kind="text")
            if not cf_llm.available():
                reply["text"] = ("" if steps else "Entendi, mas o modelo local do chat não está rodando neste ambiente, então só consigo sugerir passos quando o pedido for uma tarefa.")
            else:
                history = cf_chat.history_for_llm(session)[:-1]
                snapshot = dict(text=text, kinds=cf_chat.kinds(session), titles=[s["title"] for s in steps], conversation=conversation or not steps,
                                history=history, apps=[{"id": a.id, "titulo": a.title, "faz": a.tagline} for a in registry.values() if not a.hidden])
                threading.Thread(target=write_reply, args=(session["id"], reply["id"], plan_id, snapshot), daemon=True).start()
        cf_chat.save(base, session)
        return JSONResponse(with_urls(session))

    async def sessions_run(request):
        session = session_or_404(request.path_params["id"])
        if session is None:
            return JSONResponse({"detail": "Conversa não encontrada."}, 404)
        body = await request.json()
        registry = cf_apps.registry()
        app = registry.get(str(body.get("app", "")))
        if app is None:
            return JSONResponse({"detail": "App desconhecido."}, 404)
        if app.blocked_for(tier):
            return JSONResponse({"detail": app.describe(tier)["blocked_reason"]}, 409)
        text = str(body.get("text", "")).strip()[:2000]
        try:
            params = cf_chat.build_params(app, app.fields(tier), text, session)
            resolved = resolve_files(app, params)
        except cf_chat.Missing as gap:
            return JSONResponse({"detail": str(gap), "missing": gap.labels}, 409)
        lane = "gpu" if app.lane == "gpu" else "cpu"
        session_id = session["id"]

        def runner(ctx):
            outputs = app.runner(ctx, resolved, tier)
            fresh = []
            for path in outputs or []:
                source = Path(path)
                if not source.is_file():
                    continue
                ident = uuid.uuid4().hex
                target = uploads / ident
                target.mkdir()
                copy = target / re.sub(r"[^\w.\- ]", "_", source.name)[:120]
                shutil.copyfile(source, copy)
                fresh.append({"id": ident, "name": copy.name, "kind": cf_jobs.KINDS.get(copy.suffix.lower(), "file")})
            # False when the conversation was deleted while the job ran; the job result still stands.
            cf_chat.update(base, session_id, lambda current: cf_chat.add_media(current, fresh, "result", app=app.id, job=ctx.job.id))
            return outputs

        job = manager.submit(app.id, app.title + (" · " + text[:40] if text else ""), params, lane, runner)
        job_id = public_job(job)["id"]
        cf_chat.update(base, session_id, lambda current: cf_chat.add_message(current, "job", job=job_id, app=app.id, title=app.title))
        return JSONResponse(public_job(job), 202)

    async def models(request):
        sizes = await run_in_threadpool(cf_sizes.sizes_for, base)
        return JSONResponse([cf_apps.model_card(key, tier, sizes) for key in cf_apps.IMAGE_MODELS])

    async def upscalers(request):
        return JSONResponse(cf_upscale.status(base))

    async def upscaler_install(request):
        name = str((await request.json()).get("name", ""))
        if name not in cf_upscale.MODELS:
            return JSONResponse({"detail": "Upscaler desconhecido."}, 400)
        job = manager.submit("install-upscaler", f"Instalar {cf_upscale.short(name)}", {"name": name}, "cpu", lambda ctx: cf_apps.install_upscaler(ctx, name))
        return JSONResponse(public_job(job), 202)

    def library_context():
        return dict(base=base, civitai_dir=cf_apps.ENV["civitai"], tier=tier, info=cf_apps.MODEL_INFO, sizes=cf_sizes.sizes_for(base),
                    cover=lambda entry: cover_url(entry["model"], entry["version"], entry["covers"]),
                    card_cover=lambda card: sign(f"cover/{card['cover_id']}").replace("/files/", "/", 1) if card.get("cover_id") else None)

    async def library_categories(request):
        return JSONResponse([dict(c, views=list(c["views"]), sources=list(c["sources"]), roles=list(c["roles"])) for c in cf_contracts.CATEGORIES])

    async def library_items(request):
        q = request.query_params
        try:
            items, nxt = await run_in_threadpool(cf_library.library, q.get("kind", ""), q.get("view", "recommended"), library_context(),
                                                 q.get("family", "qwen21"), q.get("source", "civitai"), q.get("q", "")[:180], q.get("cursor") or None)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, 400)
        except (requests.RequestException, cf_assets.CivitaiHTTPError, OSError) as exc:
            return JSONResponse({"detail": f"A fonte não respondeu agora: {str(exc)[:160]}"}, 502)
        return JSONResponse({"items": items, "next": nxt}, headers={"Cache-Control": "no-store"})

    async def recipe_file_install(request):
        body = await request.json()
        repo, filename = str(body.get("repo", "")), str(body.get("file", ""))
        job = manager.submit("install-component", f"Instalar {Path(filename).name}", {"file": filename}, "cpu", lambda ctx: cf_apps.install_recipe_file(ctx, repo, filename))
        return JSONResponse(public_job(job), 202)

    async def lora_families(request):
        """Every recipe family that can take LoRAs, with whether its model is installed and how many LoRAs are ready."""
        out = []
        for key, preset in cf_apps.lab.PRESETS.items():
            if key not in cf_apps.LORA_FAMILIES or key not in cf_apps.MODEL_INFO:
                continue  # only the models the Studio can actually run: no SDXL / SD 1.5 in the lists
            info = cf_apps.MODEL_INFO.get(key, {})
            files = [cf_apps.lab.models_root() / Path(f[1]).parts[-2] / Path(f[1]).name for f in preset.files.values()]
            installed = bool(files) and all(p.is_file() for p in files)
            if not preset.files:  # checkpoint families: "installed" when some Civitai checkpoint is in the inventory
                installed = bool(cf_civitai.inventory(cf_apps.ENV["civitai"], preset, "Checkpoint"))
            ready = int(cf_loras.available(base, cf_loras.comfy_loras().parent, key)["counts"]["installed_for_family"])
            out.append(dict(key=key, title=info.get("name") or preset.title, tagline=info.get("tagline", "Checkpoint do Civitai"),
                            installed=installed, loras_installed=ready))
        return JSONResponse(out, headers={"Cache-Control": "no-store"})

    async def model_detail(request):
        key = request.path_params["key"]
        if key not in cf_apps.IMAGE_MODELS:
            return JSONResponse({"detail": "Modelo desconhecido."}, 404)
        sizes = await run_in_threadpool(cf_sizes.sizes_for, base, [key])
        return JSONResponse(cf_apps.model_card(key, tier, sizes))

    def cover_url(model, version, covers):
        key = cf_civitai.register_cover(model, version, covers)
        return sign(f"cover/{key}").replace("/files/", "/", 1)

    async def loras(request):
        family = request.query_params.get("family", "")
        if family not in cf_apps.LORA_FAMILIES:
            return JSONResponse({"detail": "Escolha um modelo da lista."}, 400)
        result = await run_in_threadpool(cf_loras.available, base, cf_loras.comfy_loras().parent, family)
        for item in result["items"]:
            if item.get("covers") and item.get("model"):
                item["cover"] = cover_url(item["model"], item["version"], item["covers"])
            item.pop("covers", None)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    async def civitai_loras(request):
        family = request.query_params.get("family", "qwen21")
        if family not in cf_apps.LORA_FAMILIES:
            return JSONResponse({"detail": "Escolha um modelo da lista."}, 400)
        sort = request.query_params.get("sort", "downloads")
        cards, nxt = await run_in_threadpool(cf_civitai.browse_loras, cf_apps.lab.PRESETS[family],
                                             request.query_params.get("q", ""), request.query_params.get("cursor") or None, sort)
        have = {i["name"] for i in cf_loras.local(base)}
        for card in cards:
            card["cover"] = sign(f"cover/{card['cover_id']}").replace("/files/", "/", 1)
            card["cover_kind"] = (card["covers"][0]["type"] if card["covers"] else "none")
            card["installed"] = any(n.endswith(f'__cv{card["version"]}.safetensors') for n in have)
            del card["covers"]
        return JSONResponse({"items": cards, "next": nxt}, headers={"Cache-Control": "no-store"})

    async def search_components(request):
        q = request.query_params
        try:
            items, nxt = await run_in_threadpool(cf_search.search, q.get("role", ""), q.get("family", ""), q.get("source", "local"),
                                                 q.get("q", "")[:180], cf_apps.ENV["civitai"], q.get("cursor") or None)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, 400)
        except (requests.RequestException, cf_assets.CivitaiHTTPError, OSError) as exc:
            return JSONResponse({"detail": f"A fonte não respondeu agora: {str(exc)[:160]}"}, 502)
        return JSONResponse({"items": items, "next": nxt}, headers={"Cache-Control": "no-store"})

    def expected_variant(body):
        """What the list showed the user for the file being installed. Only known keys, typed; the server re-checks it against Civitai."""
        raw = body.get("expect")
        if not isinstance(raw, dict):
            return None
        out = {}
        for key in ("name", "quant", "sha256"):
            if isinstance(raw.get(key), str):
                out[key] = raw[key][:200]
        if isinstance(raw.get("size_bytes"), int) and not isinstance(raw.get("size_bytes"), bool):
            out["size_bytes"] = raw["size_bytes"]
        return out or None

    async def install_component(request):
        body = await request.json()
        family, role = str(body.get("family", "")), str(body.get("role", ""))
        if family not in cf_apps.lab.PRESETS or role not in ("Difusão", "Checkpoint", "Encoder", "VAE", "Upscaler"):
            return JSONResponse({"detail": "Pedido de instalação inválido."}, 400)
        try:
            model, version, file = int(body["model"]), int(body["version"]), int(body["file"])
        except (KeyError, TypeError, ValueError):
            return JSONResponse({"detail": "Pedido de instalação inválido."}, 400)
        job = manager.submit("install-component", f"Instalar {role} {model}", {"model": model}, "cpu",
                             lambda ctx: cf_apps.install_civitai_component(ctx, family, role, model, version, file, expected_variant(body)))
        return JSONResponse(public_job(job), 202)

    async def civitai_install(request):
        body = await request.json()
        family = str(body.get("family", ""))
        if family not in cf_apps.LORA_FAMILIES:
            return JSONResponse({"detail": "Escolha um modelo da lista."}, 400)
        try:
            model, version, file = int(body["model"]), int(body["version"]), int(body["file"])
        except (KeyError, TypeError, ValueError):
            return JSONResponse({"detail": "Pedido de instalação inválido."}, 400)
        job = manager.submit("install-lora", f"Instalar LoRA {model}", {"model": model}, "cpu",
                             lambda ctx: cf_apps.install_civitai_lora(ctx, family, model, version, file, expected_variant(body)))
        return JSONResponse(public_job(job), 202)

    async def cover(request):
        key = request.path_params["key"]
        if not signed(f"cover/{key}", request.query_params.get("e"), request.query_params.get("s")):
            return JSONResponse({"detail": "Link da capa expirou."}, 401)
        try:
            data, media_type = await run_in_threadpool(cf_civitai.read_catalog_cover, key)
        except FileNotFoundError as exc:
            return JSONResponse({"detail": str(exc)}, 404)
        except OSError as exc:
            return JSONResponse({"detail": str(exc)}, 502)
        etag = f'"{key[:32]}"'  # the key is a hash of what the cover is, so it never changes for one key
        headers = {"Cache-Control": "private, max-age=86400", "ETag": etag, "X-Content-Type-Options": "nosniff"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(data, media_type=media_type, headers=headers)

    async def install_model(request):
        key = request.path_params["key"]
        if key not in cf_apps.IMAGE_MODELS:
            return JSONResponse({"detail": "Modelo desconhecido."}, 404)
        title = cf_apps.model_card(key)["title"]
        job = manager.submit("install-model", f"Instalar {title}", {"model": key}, "cpu",
                             lambda ctx: cf_apps.install_model(ctx, key))
        return JSONResponse(public_job(job), 202)

    async def install_lora(request):
        body = await request.json()
        name = Path(str(body.get("name", ""))).name
        job = manager.submit("install-lora", f"Instalar {name}", {"name": name}, "cpu",
                             lambda ctx: cf_apps.install_lora(ctx, name))
        return JSONResponse(public_job(job), 202)

    # ---- jobs
    def resolve_files(app, params, used=None):
        schema = {f["id"]: f for f in app.fields(tier)}
        resolved = dict(params)
        for field_id, field in schema.items():
            # API clients may omit fields the portal always sends (including hidden ones): fill the form default
            if field["type"] not in FILE_FIELDS and field["type"] != "lights" and field_id not in resolved and "default" in field:
                resolved[field_id] = field["default"]
            if field["type"] not in FILE_FIELDS:
                continue
            ids = params.get(field_id) or []
            ids = [ids] if isinstance(ids, str) else ids
            paths = []
            for ident in ids:
                ident = str(ident.get("id") if isinstance(ident, dict) else ident)
                if not re.fullmatch(r"[0-9a-f]{32}|[av]_[0-9a-f]{16}", ident):
                    raise ValueError("Arquivo enviado inválido.")
                found = media_file(ident, used)
                if found is None:
                    raise ValueError("Esse ativo não existe mais." if ident[:2] in ("a_", "v_") else "Um arquivo enviado expirou. Envie novamente.")
                paths.append(str(found))
            if len(paths) < field.get("min", 0):
                raise ValueError(f"{field['label']}: envie ao menos {field['min']} arquivo(s).")
            resolved[field_id] = paths
        return resolved

    async def create_job(request):
        body = await request.json()
        app = cf_apps.registry().get(body.get("app"))
        if app is None:
            return JSONResponse({"detail": "App desconhecido."}, 404)
        if app.blocked_for(tier):
            return JSONResponse({"detail": app.describe(tier)["blocked_reason"]}, 409)
        params = body.get("params") or {}
        used = {}
        resolved = resolve_files(app, params, used)
        if used:
            params["_asset_versions"] = used  # which asset version each a_/v_ id resolved to (provenance); not part of `resolved`
        for field in app.fields(tier):
            if field.get("required") and not str(resolved.get(field["id"], "")).strip():
                raise ValueError(f"Preencha: {field['label']}.")
        title = app.title
        prompt = str(params.get("prompt", "")).strip()
        if prompt:
            title += " · " + (prompt[:48] + "…" if len(prompt) > 48 else prompt)
        lane = "gpu" if (app.lane == "gpu" or (app.id == "upscale" and not str(resolved.get("mode", "")).startswith("Lanczos"))
                         or (app.id == "factory" and re.search(r'"render_mode"\s*:\s*"states"', str(resolved.get("script", ""))))) else "cpu"  # states scenes use the GPU
        job = manager.submit(app.id, title, params, lane, lambda ctx: app.runner(ctx, resolved, tier))
        return JSONResponse(public_job(job), 202)

    async def list_jobs(request):
        limit = min(200, int(request.query_params.get("limit", 60)))
        return JSONResponse([public_job(j) for j in manager.recent(limit)], headers={"Cache-Control": "no-store"})

    async def get_job(request):
        job = manager.get(request.path_params["id"])
        if job is None:
            return JSONResponse({"detail": "Job não encontrado."}, 404)
        return JSONResponse(public_job(job), headers={"Cache-Control": "no-store"})

    async def cancel_job(request):
        ok = manager.cancel(request.path_params["id"])
        return JSONResponse({"cancelled": ok})

    async def clear_queue(request):
        return JSONResponse({"cancelled": await run_in_threadpool(manager.clear_queue)})

    async def job_events(request):
        job = manager.get(request.path_params["id"])
        if job is None:
            return JSONResponse({"detail": "Job não encontrado."}, 404)

        async def stream():
            seen, beat = -1, time.monotonic()
            while True:
                if await request.is_disconnected():
                    return
                if job.version != seen:
                    seen = job.version
                    yield f"data: {json.dumps(public_job(job), ensure_ascii=False)}\n\n"
                    beat = time.monotonic()
                    if job.status in cf_jobs.FINAL:
                        return
                elif time.monotonic() - beat >= 10:
                    yield ": heartbeat\n\n"
                    beat = time.monotonic()
                await asyncio.sleep(0.4)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    # ---- files
    async def upload(request):
        form = await request.form(max_files=8, max_part_size=MAX_UPLOAD)
        out = []
        for item in form.getlist("files"):
            name = re.sub(r"[^\w.\- ]", "_", Path(item.filename or "arquivo").name)[:120]
            if Path(name).suffix.lower() not in UPLOAD_SUFFIXES:
                raise ValueError(f"Formato não aceito: {name}")
            ident = uuid.uuid4().hex
            folder = uploads / ident
            folder.mkdir()
            target = folder / name
            with target.open("wb") as handle:
                while block := await item.read(1 << 20):
                    handle.write(block)
            rel = target.relative_to(base).as_posix()
            kind = cf_jobs.KINDS.get(target.suffix.lower(), "file")
            out.append({"id": ident, "name": name, "kind": kind, "size": target.stat().st_size, "url": sign(rel)})
        return JSONResponse(out)

    async def upload_info(request):
        ident = request.path_params["ident"]
        found = cf_asset_graph.resolve_ref(base, ident)
        if found is not None:  # an asset version (or the current one of an asset): hydrate like an upload
            path, version = found
            return JSONResponse({"id": version["version_id"], "asset_id": version["asset_id"], "version_id": version["version_id"],
                                 "name": version["metadata"].get("title") or path.name, "kind": cf_jobs.KINDS.get(path.suffix.lower(), "file"),
                                 "asset_kind": version["kind"], "size": version["bytes"], "url": sign(path.relative_to(base).as_posix())},
                                headers={"Cache-Control": "no-store"})
        found = media_file(ident)
        if found is None:
            return JSONResponse({"detail": "Arquivo enviado não encontrado."}, 404)
        rel = found.relative_to(base).as_posix()
        return JSONResponse({"id": ident, "name": found.name, "kind": cf_jobs.KINDS.get(found.suffix.lower(), "file"),
                             "size": found.stat().st_size, "url": sign(rel)}, headers={"Cache-Control": "no-store"})

    async def import_result(request):
        """Copy a finished result into uploads so it can feed another app (the "Usar em…" action)."""
        body = await request.json()
        rel = str(body.get("path", ""))
        source = (out_dir / rel).resolve()
        if not source.is_file() or not source.is_relative_to(out_dir.resolve()):
            raise ValueError("Resultado não encontrado.")
        ident = uuid.uuid4().hex
        folder = uploads / ident
        folder.mkdir()
        target = folder / re.sub(r"[^\w.\- ]", "_", source.name)[:120]
        shutil.copyfile(source, target)
        kind = cf_jobs.KINDS.get(target.suffix.lower(), "file")
        return JSONResponse({"id": ident, "name": target.name, "kind": kind, "size": target.stat().st_size,
                             "url": sign(target.relative_to(base).as_posix())})

    async def files(request):
        rel = request.path_params["path"]
        if not signed(rel, request.query_params.get("e"), request.query_params.get("s", "")):
            return JSONResponse({"detail": "Link expirado."}, 403)
        for root in (out_dir, base):
            target = (root / rel).resolve()
            if target.is_file() and (target.is_relative_to(out_dir.resolve()) or target.is_relative_to(uploads.resolve()) or target.is_relative_to(cf_cast.folder(base).resolve()) or target.is_relative_to(cf_asset_graph.folder(base).resolve())):
                return FileResponse(target, headers={"Cache-Control": "private, max-age=3600",
                                                    "X-Content-Type-Options": "nosniff"})
        return JSONResponse({"detail": "Arquivo não encontrado."}, 404)

    # ---- asset graph (AssetRef.v1)
    asset_roots = [out_dir, uploads, cf_cast.folder(base)]

    def version_public(version):
        return dict(version, url=sign(f"assets/{version['storage_ref']}"))

    def asset_public(asset, current=None):
        out = dict(asset)
        if current is not None:
            out["current_version"] = version_public(current)
            out["url"] = out["current_version"]["url"]
        return out

    def job_producer(rel):
        """The job that wrote this result file, when it is still in the queue's memory: -> (producer, recipe)."""
        for job in manager.recent(200):
            if any(r.get("path") == rel for r in job.snapshot(0).get("results", [])):
                params = {k: v for k, v in (job.params or {}).items() if k not in ("run", "_asset_versions")}
                run = (job.params or {}).get("run")  # the DAG run id (a string) on graph jobs
                return dict(kind="job", job_id=job.id, app=job.app, graph_run_id=run if isinstance(run, str) else None), dict(params=params)
        return dict(kind="import"), {}

    def asset_source(spec):
        """{"result": rel} | {"upload": 32hex} | {"cast": id} -> (kind of the call, kwargs for cf_asset_graph)."""
        if not isinstance(spec, dict) or len(spec) != 1:
            raise ValueError('"from" precisa de exatamente um de: result, upload, cast.')
        key, value = next(iter(spec.items()))
        if key == "result":
            rel = str(value)
            source = (out_dir / rel).resolve()
            if not source.is_file() or not source.is_relative_to(out_dir.resolve()):
                raise ValueError("Resultado não encontrado nas pastas de resultados.")
            producer, recipe = job_producer(rel)
            return dict(source=source, producer=producer, recipe=recipe)
        if key == "upload":
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
                raise ValueError("Arquivo enviado inválido.")
            found = media_file(value)
            if found is None:
                raise ValueError("O arquivo enviado não existe mais. Envie de novo.")
            return dict(source=found, producer=dict(kind="upload"))
        raise ValueError("Origem não aceita: use result, upload ou cast.")

    def asset_answer(done, status=200):
        return JSONResponse(dict(asset=asset_public(done["asset"], done["version"]), version=version_public(done["version"]),
                                 url=version_public(done["version"])["url"], deduplicated=done["deduplicated"]), status)

    async def assets_create(request):
        body = await request.json()
        spec = body.get("from")
        title = str(body["title"]).strip()[:120] if body.get("title") else None
        kind = body.get("kind") or None
        if isinstance(spec, dict) and set(spec) == {"cast"}:
            if kind not in (None, "character"):
                raise ValueError("Um personagem do Elenco é publicado como character.")
            try:
                done = await run_in_threadpool(cf_asset_graph.publish_cast, base, str(spec["cast"]), asset_roots)
            except cf_asset_graph.NotFound as exc:
                return JSONResponse({"detail": str(exc)}, 404)
        else:
            source = asset_source(spec)
            done = await run_in_threadpool(lambda: cf_asset_graph.publish(base, source.pop("source"), asset_roots, kind=kind, title=title, **source))
        return asset_answer(done, 200 if done["deduplicated"] else 201)

    async def assets_list(request):
        return JSONResponse([asset_public(a, a["current_version"]) for a in cf_asset_graph.list_assets(base)], headers={"Cache-Control": "no-store"})

    async def assets_get(request):
        try:
            asset = cf_asset_graph.get(base, request.path_params["asset_id"])
            found = cf_asset_graph.versions(base, asset["asset_id"])
        except cf_asset_graph.NotFound as exc:
            return JSONResponse({"detail": str(exc)}, 404)
        return JSONResponse(dict(asset_public(asset, next(v for v in found if v["version_id"] == asset["current"])),
                                 versions=[version_public(v) for v in found]), headers={"Cache-Control": "no-store"})

    async def assets_add_version(request):
        body = await request.json()
        source = asset_source(body.get("from"))
        note = str(body["note"]).strip()[:300] if body.get("note") else None
        try:
            done = await run_in_threadpool(lambda: cf_asset_graph.add_version(base, request.path_params["asset_id"], source.pop("source"), asset_roots,
                                                                              metadata=dict(note=note) if note else None, **source))
        except cf_asset_graph.NotFound as exc:
            return JSONResponse({"detail": str(exc)}, 404)
        return asset_answer(done, 200 if done["deduplicated"] else 201)

    async def assets_version(request):
        try:
            version = cf_asset_graph.get_version(base, request.path_params["version_id"])
        except cf_asset_graph.NotFound as exc:
            return JSONResponse({"detail": str(exc)}, 404)
        verified = await run_in_threadpool(cf_asset_graph.verify, base, version["version_id"])
        return JSONResponse(dict(version_public(version), verified=verified), headers={"Cache-Control": "no-store"})

    async def logs(request):
        return JSONResponse({"worker": workflows.worker_log_tail(60, sep="\n", limit=12000)})

    routes = [
        Route(f"{PREFIX}/system", guard(system)),
        Route(f"{PREFIX}/apps", guard(apps)),
        Route(f"{PREFIX}/slots", guard(slots)),
        Route(f"{PREFIX}/llm", guard(llm_info)),
        Route(f"{PREFIX}/lora-families", guard(lora_families)),
        Route(f"{PREFIX}/capabilities", guard(capabilities_list)),
        Route(f"{PREFIX}/capabilities/{{id}}", guard(capability_get)),
        Route(f"{PREFIX}/dag/validate", guard(dag_validate), methods=["POST"]),
        Route(f"{PREFIX}/dag/run", guard(dag_run), methods=["POST"]),
        Route(f"{PREFIX}/dag/runs/{{id}}", guard(dag_run_get)),
        Route(f"{PREFIX}/dag/runs/{{id}}/exposable", guard(dag_run_exposable)),
        Route(f"{PREFIX}/dag/runs/{{id}}/save", guard(dag_run_save), methods=["POST"]),
        Route(f"{PREFIX}/dag/runs/{{id}}/revise", guard(dag_run_revise), methods=["POST"]),
        Route(f"{PREFIX}/recipes", guard(recipes_list)),
        Route(f"{PREFIX}/recipes", guard(recipe_save), methods=["POST"]),
        Route(f"{PREFIX}/recipes/{{id}}", guard(recipe_delete), methods=["DELETE"]),
        Route(f"{PREFIX}/recipes/{{id}}/preview", guard(recipe_preview), methods=["POST"]),
        Route(f"{PREFIX}/recipes/{{id}}/run", guard(recipe_run), methods=["POST"]),
        Route(f"{PREFIX}/library/categories", guard(library_categories)),
        Route(f"{PREFIX}/library", guard(library_items)),
        Route(f"{PREFIX}/components/recipe-file", guard(recipe_file_install), methods=["POST"]),
        Route(f"{PREFIX}/upscalers", guard(upscalers)),
        Route(f"{PREFIX}/upscalers/install", guard(upscaler_install), methods=["POST"]),
        Route(f"{PREFIX}/cast", guard(cast_list)),
        Route(f"{PREFIX}/cast/create", guard(cast_create), methods=["POST"]),
        Route(f"{PREFIX}/cast/{{ident}}", guard(cast_delete), methods=["DELETE"]),
        Route(f"{PREFIX}/favorites", guard(favorites_list)),
        Route(f"{PREFIX}/favorites/toggle", guard(favorites_toggle), methods=["POST"]),
        Route(f"{PREFIX}/sessions", guard(sessions_list), methods=["GET"]),
        Route(f"{PREFIX}/sessions", guard(sessions_create), methods=["POST"]),
        Route(f"{PREFIX}/sessions/{{id}}", guard(sessions_get), methods=["GET"]),
        Route(f"{PREFIX}/sessions/{{id}}/delete", guard(sessions_delete), methods=["POST"]),
        Route(f"{PREFIX}/sessions/{{id}}/rename", guard(sessions_rename), methods=["POST"]),
        Route(f"{PREFIX}/sessions/{{id}}/message", guard(sessions_message), methods=["POST"]),
        Route(f"{PREFIX}/sessions/{{id}}/run", guard(sessions_run), methods=["POST"]),
        Route(f"{PREFIX}/search", guard(search_components)),
        Route(f"{PREFIX}/components/install", guard(install_component), methods=["POST"]),
        Route(f"{PREFIX}/benchmarks", guard(benchmarks)),
        Route(f"{PREFIX}/route", guard(route_request), methods=["POST"]),
        Route(f"{PREFIX}/plan", guard(plan_request), methods=["POST"]),
        Route(f"{PREFIX}/models", guard(models)),
        Route(f"{PREFIX}/models/{{key}}", guard(model_detail)),
        Route(f"{PREFIX}/models/{{key}}/install", guard(install_model), methods=["POST"]),
        Route(f"{PREFIX}/loras", guard(loras)),
        Route(f"{PREFIX}/civitai/loras", guard(civitai_loras)),
        Route(f"{PREFIX}/civitai/install", guard(civitai_install), methods=["POST"]),
        Route(f"{PREFIX}/cover/{{key}}", cover),
        Route(f"{PREFIX}/loras/install", guard(install_lora), methods=["POST"]),
        Route(f"{PREFIX}/jobs", guard(list_jobs), methods=["GET"]),
        Route(f"{PREFIX}/jobs", guard(create_job), methods=["POST"]),
        Route(f"{PREFIX}/jobs/{{id}}", guard(get_job)),
        Route(f"{PREFIX}/jobs/{{id}}/events", guard(job_events)),
        Route(f"{PREFIX}/jobs/{{id}}/cancel", guard(cancel_job), methods=["POST"]),
        Route(f"{PREFIX}/queue/clear", guard(clear_queue), methods=["POST"]),
        Route(f"{PREFIX}/uploads/{{ident}}", guard(upload_info)),
        Route(f"{PREFIX}/upload", guard(upload), methods=["POST"]),
        Route(f"{PREFIX}/import", guard(import_result), methods=["POST"]),
        Route(f"{PREFIX}/cinema/validate", guard(cinema_validate), methods=["POST"]),
        Route(f"{PREFIX}/cinema/projects", guard(cinema_projects), methods=["GET", "POST"]),
        Route(f"{PREFIX}/cinema/projects/{{id}}", guard(cinema_project)),
        Route(f"{PREFIX}/cinema/projects/{{id}}/shots", guard(cinema_project_add), methods=["POST"]),
        Route(f"{PREFIX}/cinema/projects/{{id}}/shots/{{shot}}", guard(cinema_project_shot), methods=["POST"]),
        Route(f"{PREFIX}/cinema/projects/{{id}}/order", guard(cinema_project_order), methods=["POST"]),
        Route(f"{PREFIX}/cinema/projects/{{id}}/cut", guard(cinema_project_cut), methods=["POST"]),
        Route(f"{PREFIX}/cinema/projects/{{id}}/export", guard(cinema_project_export), methods=["POST"]),
        Route(f"{PREFIX}/cinema/render", guard(cinema_render), methods=["POST"]),
        Route(f"{PREFIX}/assets", guard(assets_create), methods=["POST"]),
        Route(f"{PREFIX}/assets", guard(assets_list), methods=["GET"]),
        Route(f"{PREFIX}/assets/versions/{{version_id}}", guard(assets_version)),
        Route(f"{PREFIX}/assets/{{asset_id}}/versions", guard(assets_add_version), methods=["POST"]),
        Route(f"{PREFIX}/assets/{{asset_id}}", guard(assets_get)),
        Route(f"{PREFIX}/logs", guard(logs)),
        Route(f"{PREFIX}/files/{{path:path}}", files),
    ]
    portal = Path(portal_dir or Path(__file__).resolve().parent / "portal")
    if portal.is_dir():
        routes.append(Mount("/studio", RevalidatedFiles(directory=portal, html=True), name="studio"))
    app = Starlette(routes=routes, middleware=[Middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"], max_age=600)])
    app.state.manager, app.state.tier = manager, tier
    return app
