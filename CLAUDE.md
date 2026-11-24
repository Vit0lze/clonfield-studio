# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

ClonField Studio: a "Higgsfield-like" studio (image, edit, video, audio, flows, a local agent) that runs on a Colab GPU. A ComfyUI worker does the generation, a Starlette API (`cf_api.py`) orchestrates it, and a no-build ES-module SPA (`portal/`) is the UI. The user-facing text, docs and most comments are in Portuguese.

## Commands

All Python is `~/.cache/clonfield-venv/bin/python` (create it with the `pip install` line in `docs/HANDOFF.md`, "Como retomar").

```bash
python cf_engine.py --port 7861                  # the API alone, no Gradio (local dev; password from CLONFIELD_PASSWORD)
python -m pytest tests/test_dag.py -q            # one file
python -m pytest tests/test_wan.py::test_name -q # one test
PATH=~/.nvm/versions/node/v24.15.0/bin:$PATH CF_PY=$PY tests/e2e/run.sh [spec]   # Playwright (Node 24, CommonJS specs) against a real engine on a fresh data dir
python tests/gpu/validate_remote.py --list       # remote validation of a running Colab Studio (see below)
```

- **Do not run the whole suite, nor two pytest processes at once, on the 3.7 GB dev machine**: it killed the machine three times (exit 137). Run single files, one at a time, or verify on the Colab. Full run, when memory allows: `pytest tests -q --ignore=tests/test_comfy_real.py --ignore=tests/test_faceswap.py --ignore=tests/test_live.py --ignore=tests/test_resilience_live.py`.
- `tests/test_comfy_real.py` needs a CPU ComfyUI 0.44 at `~/.cache/clonfield-comfyui` (or `CLONFIELD_COMFY_CPU_URL`) and skips without it; it validates graphs against the real node registry and runs tiny real node chains. It never loads a model.
- Tests do not use stubs (a standing rule): real files, real ffmpeg, a real engine, real ComfyUI where it applies. A scripted model or a fake HTTP server is allowed only when it is labelled as such in the test and the real path is covered elsewhere.
- `CLONFIELD_FAKE_VRAM=15` makes `cf_tiers` report a 15 GB card (tests use it to get the "leve" tier).
- Frontend has no build step. Cache-busting is a `?v=N` on the module imports in `portal/index.html`; bump it when a portal file changes.

### Remote validation (Colab T4)
`tests/gpu/validate_remote.py` reads `api=` (public gradio.live link) and `bearer=` (the session password printed by notebook cell 8) from `../.env` (the parent of this repo; never committed, never print it). It exchanges the password for a token with `POST /clonfield/connect`, submits real jobs, downloads every result and checks the files (image not flat, video via ffprobe plus motion, audio duration). The link and password change every time cell 8 starts the Studio. Results go to `tests/gpu/out*/` (git-ignored); `docs/VALIDACAO_GPU.md` and `docs/CHANGELOG_V8_VALIDACAO_GPU.md` hold what was measured.

## Architecture

**Request path.** `portal/` (SPA) -> in Colab the Gradio app (`studio_app.py`) mounts `cf_portal.PortalAPI`, which authenticates and forwards to `cf_api.py` (Starlette, prefix `/clonfield/api`) -> `cf_jobs.Manager` (one serial GPU lane + a small CPU pool, persisted snapshots) -> app runners in `cf_apps.py` -> `cf_workflows.py` (submits a ComfyUI graph over HTTP/WebSocket, follows the queue, downloads the outputs) -> the ComfyUI worker on `:8188`. `cf_engine.py` serves the same API without Gradio.

**Three layers of "what can run".**
1. `cf_apps.py`: `registry()` of `App` objects (form `fields`, a `runner`, a lane). Hidden fields exist and runners read them (`p["mode"]`); `POST /jobs` fills omitted fields from the form defaults.
2. `cf_capabilities.py`: a typed registry generated from the apps plus native steps (CPU list/text/media steps), actions and engines. Each capability has typed ports and params (`required`, `options`, ranges).
3. `cf_dag.py`: executes a graph of capability nodes (`inputs` from media or `node.port`, `params`, and `each` / `bind` / `when` for fan-out, bound params and conditions) with a content-hash cache, partial re-run, cancel/resume and provenance. `validate()` runs before anything executes and refuses unknown params, type mismatches and empty required params.
   `cf_recipes.py` (built-in flows) and `cf_myflows.py` (user-saved flows) are graph builders on top of this; `cf_steps.py` holds the CPU steps.

**Local agent.** `cf_agent.py` is a tool-calling loop (`list_capabilities`, `inspect_capability`, `compose_chain`, `validate_graph`, `execute_graph`, ...) over the DAG; the model is a local llama.cpp server (`cf_llama.py` installs and starts it, `cf_llm.py` talks to it; Qwen3.5-9B abliterated Q6_K). Chat and agent are 100% local by design (no Google/Gemma API); the adult filter is on by default. The reply to a chat message is produced asynchronously (`pending: true` until done), so clients poll `/sessions/{id}`. `cf_router.py` is only a keyword heuristic.

**Cinema.** `cf_cinema.py` renders a `Timeline.v1` (pinned `v_` asset versions, `docs/V9_CINEMA_ALFA.md`) on CPU with FFmpeg: one cached segment per shot (Content Factory `digest`/`fresh`/`mark`), concat without re-encode, three float stems (voice/music/sfx), ducked mix at -16 LUFS, MP4 with four named audio streams. Swapping a take re-renders that shot only. API: `POST /cinema/validate`, `POST /cinema/render` (CPU lane); saved projects (`CinemaProject.v1`, cuts that differ only in music/sfx/mix) under `/cinema/projects…`, edited in the portal at `#/cinema` (`docs/V9_CINEMA_TELA.md`). Each export gets its own `outputs/cinema_<job>` folder. A cut's mix stores only what differs from `cf_cinema.MIX_DEFAULT` (`mix_stored`), so an old `mix: {}` keeps its cache key and signature; the screen shows the defaults.

**Video.** `cf_wan.py` holds the Wan 2.2 catalogue (`MODELS`: 5B Q6/Q8/FP16, A14B Q6_K/Q4_K_S/Q3_K_S, each file pinned by repo revision, size and SHA-256 prefix) and `make_graph`. "Entre dois quadros" (first/last frame, also the seamless loop) exists only on the A14B; the LightX2V "fast" mode (4 steps) also only on the A14B.

## Memory rules that shape the code (12.7 GB RAM + 15 GB VRAM on the Colab T4)

These were measured, not assumed; each one cost a crashed worker or session.
- **One resident text model and one running GPU job must not coexist.** llama-server starts with `--sleep-idle-seconds` (`CLONFIELD_LLM_SLEEP`, default 30). `cf_jobs.Manager` sets `gpu_active` and calls `before_gpu` (`cf_llm.release_gpu`) so a GPU job waits for the model to be asleep; while it runs `cf_llm.ensure_gpu_free()` refuses text requests, and right before a sleeping model wakes ComfyUI is asked to `/free` its models. The agent turn ends with a fixed answer once its tool starts a GPU job.
- **ComfyUI gives back only part of its RAM** after `/free` (one 5B job leaves it at 6-9 GB; `/free` took it 8.1 -> 3.8 GB once, not enough for the A14B; a new process starts at ~1.3 GB). `cf_worker.py` captures the worker's argv/cwd/env from `/proc` (memory only) and restarts or revives it; `cf_workflows.run` restarts it before a GPU job when it holds more than `CLONFIELD_WORKER_RESTART_GB` (default 7). It only ever touches the process listening on ComfyUI's port. **One owner at a time:** every path that talks to the worker for a job (`cf_workflows.run`, `cf_seedvr2.run`, the A14B's two stages) and every restart holds `cf_worker.hold()` (reentrant lock), so the classic Gradio mode, the GPU lane and a restart never overlap; a failed restart raises `cf_worker.WorkerUnavailable` instead of going on. `cf_jobs`: a runner returns files inside the output folder, or `cf_jobs.Effect(note)` for a side effect (installs); anything else is "falhou", never an empty "concluído".
- **The A14B runs one expert per prompt**: `cf_wan.split_a14b` -> stage 1 ends in `SaveLatent`, the worker restarts, stage 2 starts from `LoadLatent` (`.latent` travels through the executor like media). `cf_apps.run_a14b_staged` drives it. The Q6_K pair (12 GB each) is refused below 24 GB of RAM (`cf_wan.memory_problem`); the default for the FLF app is `a14b-q4`.
- The workflow "family" passed to `workflows.run` is `wan:<model>`, so switching models frees ComfyUI first.
- `/system` reports `ram_free_gb` and `worker_rss_gb`; read them between jobs when debugging a worker that dies.

## Conventions and constraints

- Honest status vocabulary in docs and reports: NAO INICIADO / CODIGO ESCRITO / TESTADO CPU / TESTADO API REAL / TESTADO GPU / INTEGRADO E VALIDADO / BLOQUEADO_GPU. Never present an unmeasured number as a benchmark.
- FaceFusion / face swap must never be installed or run on Colab (keep `PREPARE_FACEFUSION = False` in the notebook; the Colab FAQ forbids deepfakes). Do not edit `ClonField_Colab.ipynb` unless asked.
- HF and Civitai tokens exist only as environment variables; never write them to files or logs.
- `llama-server` b12360 prints nothing about its backend in the log: check CUDA with `llama-server --list-devices` (it needs the sibling `cudart-*` folder and `/usr/lib64-nvidia` on `LD_LIBRARY_PATH`).
- `git push` only when the user explicitly asks for it.
- Other environment variables: `CLONFIELD_DIR` (data folder), `CLONFIELD_COMFY_MODELS`, `CLONFIELD_LLAMA_URL`, `CLONFIELD_LLM_BACKEND`, `CLONFIELD_COMFY_EXTRA` (extra ComfyUI flags).

More context: `docs/HANDOFF.md` (state per cycle), `docs/CONTRATOS.md`, `docs/BACKLOG_CAPACIDADES_APPS.md`, `README.md`.
