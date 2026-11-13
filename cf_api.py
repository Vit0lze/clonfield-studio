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
import cf_contracts
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


def build_app(base, out_dir, verify, secret, portal_dir=None):
    base, out_dir = Path(base), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    uploads = base / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    cf_apps.configure(base, out_dir)
    cf_civitai.set_cover_cache(base / "cache" / "covers")
    manager = cf_jobs.Manager(out_dir)
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
        except (RuntimeError, requests.RequestException, KeyError, TypeError) as exc:
            return JSONResponse({"detail": f"Planejamento indisponível (Jev): {str(exc)[:160]}"}, 503)
        return JSONResponse(result)

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
        """Runs in a thread: Gemma takes ~20-40 s, so the plan is already on screen while it writes."""
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
                        m["text"], m["error"] = f"Não consegui falar com o Gemma agora ({error}). O plano acima continua valendo.", True
                elif plan_id and m["id"] == plan_id and out and out.get("prompt") and m["plan"].get("prompt") == m["plan"].get("text") and not any(x["role"] == "job" for x in session["messages"]):
                    m["plan"]["prompt"] = out["prompt"]  # only fills the box if the user has not rewritten it and nothing has run yet
        cf_chat.update(base, session_id, apply)

    # ---- capabilities, DAG, agent
    def capability_registry():
        return cf_capabilities.Registry(cf_apps.registry(), tier)

    def dag_env(resolver):
        return cf_dag.Env(base, out_dir, tier, resolver)

    def upload_media(ident):
        """An uploaded file as a DAG artifact source. Only ids that are real upload folders resolve."""
        if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{32}", ident):
            return None
        folder = uploads / ident
        found = next(iter(folder.iterdir()), None) if folder.is_dir() else None
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

        def runner(ctx):
            return cf_dag.final_files(cf_dag.execute(graph, registry, env, ctx, force=force))

        job = manager.submit("dag", title, {}, report["resources"]["lane"], runner)
        return JSONResponse(public_job(job), 202)

    async def dag_run_get(request):
        try:
            return JSONResponse(cf_dag.load_run(dag_env(upload_media), request.path_params["id"]))
        except (OSError, ValueError):
            return JSONResponse({"detail": "Execução não encontrada."}, 404)

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
        return JSONResponse(dict(available=cf_llm.available(), model=cf_llm.models()[0], keys=cf_env.status(), agent=cf_env.flag("agent"), jev=cf_env.flag("jev")))

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
            conversation = False
            try:
                if not cf_env.flag("jev"):
                    raise RuntimeError("")  # JEV is an optional router behind CLONFIELD_JEV; without it the local heuristic suggests one step
                plan = await run_in_threadpool(cf_router.plan, text, cf_chat.kinds(session), registry, tier)
                note = ""
                conversation = bool(plan.get("conversation"))
            except (RuntimeError, requests.RequestException, KeyError, TypeError, ValueError) as exc:
                routed = await run_in_threadpool(cf_router.route, text, cf_chat.kinds(session), registry, tier, None, cf_router.local_provider)
                best = next((c for c in routed["candidates"] if c["router"]["available"]), None)
                plan = dict(provider="local", steps=[dict(app=best["app"], title=best["title"], probability=best["probability"])] if best else [], complete=bool(best))
                note = f"O Jev não respondeu ({str(exc)[:80]}); usei a heurística local, que só sugere um passo." if str(exc) else "Sem agente neste ambiente: a heurística local sugere um passo."
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
                plan_id = cf_chat.add_message(session, "assistant", plan=dict(provider=plan.get("provider", "jev"), steps=steps, text=text, prompt=text, note=note))["id"]
            reply = cf_chat.add_message(session, "assistant", text="", pending=cf_llm.available(), kind="text")
            if not cf_llm.available():
                reply["text"] = ("" if steps else "Entendi, mas o assistente de conversa (Gemma) não está configurado neste ambiente, então só consigo sugerir passos quando o pedido for uma tarefa.")
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
        if app.min_vram and tier.vram_gb < app.min_vram:
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
    def resolve_files(app, params):
        schema = {f["id"]: f for f in app.fields(tier)}
        resolved = dict(params)
        for field_id, field in schema.items():
            if field["type"] not in FILE_FIELDS:
                continue
            ids = params.get(field_id) or []
            ids = [ids] if isinstance(ids, str) else ids
            paths = []
            for ident in ids:
                ident = str(ident.get("id") if isinstance(ident, dict) else ident)
                if not re.fullmatch(r"[0-9a-f]{32}", ident):
                    raise ValueError("Arquivo enviado inválido.")
                folder = uploads / ident
                found = next(iter(folder.iterdir()), None) if folder.is_dir() else None
                if found is None:
                    raise ValueError("Um arquivo enviado expirou. Envie novamente.")
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
        if app.min_vram and tier.vram_gb < app.min_vram:
            return JSONResponse({"detail": app.describe(tier)["blocked_reason"]}, 409)
        params = body.get("params") or {}
        resolved = resolve_files(app, params)
        for field in app.fields(tier):
            if field.get("required") and not str(resolved.get(field["id"], "")).strip():
                raise ValueError(f"Preencha: {field['label']}.")
        title = app.title
        prompt = str(params.get("prompt", "")).strip()
        if prompt:
            title += " · " + (prompt[:48] + "…" if len(prompt) > 48 else prompt)
        lane = "gpu" if (app.lane == "gpu" or (app.id == "upscale" and not str(resolved.get("mode", "")).startswith("Lanczos"))) else "cpu"
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
        folder = uploads / ident
        found = next(iter(folder.iterdir()), None) if re.fullmatch(r"[0-9a-f]{32}", ident) and folder.is_dir() else None
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
            if target.is_file() and (target.is_relative_to(out_dir.resolve()) or target.is_relative_to(uploads.resolve())):
                return FileResponse(target, headers={"Cache-Control": "private, max-age=3600",
                                                    "X-Content-Type-Options": "nosniff"})
        return JSONResponse({"detail": "Arquivo não encontrado."}, 404)

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
        Route(f"{PREFIX}/library/categories", guard(library_categories)),
        Route(f"{PREFIX}/library", guard(library_items)),
        Route(f"{PREFIX}/components/recipe-file", guard(recipe_file_install), methods=["POST"]),
        Route(f"{PREFIX}/upscalers", guard(upscalers)),
        Route(f"{PREFIX}/upscalers/install", guard(upscaler_install), methods=["POST"]),
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
