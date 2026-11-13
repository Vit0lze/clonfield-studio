"""Runs the 30 tasks against the REAL Gemma 4 API agent (real tools, real DAG jobs on CPU) and, for the routing subset, against the
previous path (live Jev plan). Writes results.json and docs/AGENT_EVAL.md.

  python tests/agent_eval/run_eval.py [--only id,id] [--workers 3]

Honest scope: tasks are written by the agent's author; one run per task (temperature 0.2); the Gemma API is flaky, so an API
failure is reported as `api_error` and is NOT counted as a model failure. The Qwen3.5-9B GGUF provider is not evaluated here
(no GPU on this machine)."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("CLONFIELD_FAKE_VRAM", "15")

from PIL import Image, ImageDraw  # noqa: E402

import cf_agent as agent  # noqa: E402
import cf_apps  # noqa: E402
import cf_capabilities as caps  # noqa: E402
import cf_dag as dag  # noqa: E402
import cf_jobs  # noqa: E402
import cf_router  # noqa: E402
import cf_tiers  # noqa: E402
from tasks import TASKS  # noqa: E402

CAP_APP = {"upscale": "upscale", "look": "look", "frame": "frame", "still": "still", "compare": "compare"}


def make_world(kind, base):
    folder = Path(tempfile.mkdtemp(prefix="cf-eval-", dir=base))
    media = {}
    if kind in ("media", "video_only"):
        if kind == "media":
            image = Image.new("RGB", (160, 120), (30, 40, 60))
            ImageDraw.Draw(image).ellipse((30, 20, 130, 100), fill=(220, 180, 120))
            image.save(folder / "foto.png")
            media["m-foto"] = dict(type="image", path=str(folder / "foto.png"), name="foto.png")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=128x128:rate=8", "-pix_fmt", "yuv420p", str(folder / "clipe.mp4")], check=True)
        media["m-clipe"] = dict(type="video", path=str(folder / "clipe.mp4"), name="clipe.mp4")
    tier = cf_tiers.detect()
    registry = caps.Registry(cf_apps.registry(), tier)
    env = dag.Env(base, folder / "out", tier, lambda ident: media.get(ident))
    manager = cf_jobs.Manager(env.out_dir, cpu_workers=1)
    attached = []
    host = agent.LocalHost(registry, env, manager, lambda: [dict(id=k, name=v["name"], kind=v["type"], origin="upload") for k, v in media.items()],
                           on_result=lambda files, job: attached.extend(str(f) for f in files), wait=120)
    world = type("World", (), {})()
    world.registry, world.env, world.manager, world.host, world.attached, world.media, world.tier = registry, env, manager, host, attached, media, tier
    return world


def run_one(task):
    tid, request, kind, expected, check, category = task
    world = make_world(kind, BASE)
    jobs_before = len(world.manager.jobs)
    started = time.monotonic()
    record = dict(id=tid, category=category, request=request, expected=expected)
    try:
        out = None
        for attempt in range(3):
            try:
                out = agent.run_agent(agent.GeminiProvider(), agent.Toolbox(world.registry, world.env, world.host), request, max_steps=12)
                break
            except agent.AgentError as exc:
                record["api_error"] = str(exc)[:140]
                time.sleep(5)
        if out is None:
            record.update(status="api_error")
            return record
        record.pop("api_error", None)
        invalid = sum(1 for t in out["trace"] if t["tool"] in ("validate_graph", "execute_graph", "estimate_resources") and not t["ok"])
        from tasks import caps_run
        ran = caps_run(out)
        passed = bool(check(world, out, jobs_before))
        tools = [t["tool"] for t in out["trace"]]
        record.update(status="pass" if passed else "fail", steps=out["steps"], stop=out["stop"], seconds=round(time.monotonic() - started, 1), invalid_calls=invalid,
                      tools=tools, caps_run=ran, final=(out["final"] or "")[:300], model=out.get("model"),
                      right_caps=(sorted(set(expected)) == sorted(set(ran))) if expected else None,
                      jobs=len(world.manager.jobs) - jobs_before,
                      improper_job=(category in ("recusar", "perguntar", "seguranca") and len(world.manager.jobs) > jobs_before))
    except Exception as exc:  # a harness bug must not hide as a model result
        record.update(status="harness_error", error=f"{type(exc).__name__}: {exc}"[:200])
    return record


def jev_routing(task):
    tid, request, kind, expected, _check, category = task
    apps = [CAP_APP[c] for c in (expected or []) if c in CAP_APP]
    if not expected or len(apps) != len(set(expected) & set(CAP_APP)) or set(expected) - set(CAP_APP):
        return None
    kinds = {"image"} if kind == "media" else {"video"} if kind == "video_only" else set()
    if kind == "media" and "still" in apps:
        kinds = {"image", "video"}
    registry = cf_apps.registry()
    try:
        plan = cf_router.plan(request, kinds, registry, cf_tiers.detect())
    except Exception as exc:
        return dict(id=tid, status="api_error", error=str(exc)[:120])
    got = [s["app"] for s in plan["steps"] if s.get("app")]
    return dict(id=tid, status="pass" if set(apps) <= set(got) else "fail", planned=got, expected_apps=sorted(set(apps)), repeated_steps_possible=False)


def summarize(results, jev):
    scored = [r for r in results if r["status"] in ("pass", "fail")]
    by_cat = {}
    for r in scored:
        c = by_cat.setdefault(r["category"], dict(n=0, passed=0))
        c["n"] += 1
        c["passed"] += r["status"] == "pass"
    return dict(tasks=len(results), scored=len(scored), passed=sum(r["status"] == "pass" for r in scored), api_errors=sum(r["status"] == "api_error" for r in results),
                harness_errors=sum(r["status"] == "harness_error" for r in results), by_category=by_cat,
                mean_steps=round(sum(r["steps"] for r in scored) / max(1, len(scored)), 1), mean_seconds=round(sum(r["seconds"] for r in scored) / max(1, len(scored)), 1),
                invalid_call_rate=round(sum(r["invalid_calls"] for r in scored) / max(1, sum(r["steps"] for r in scored)), 3),
                improper_jobs=sum(bool(r.get("improper_job")) for r in scored),
                right_caps=sum(1 for r in scored if r.get("right_caps")), with_expected=sum(1 for r in scored if r.get("right_caps") is not None),
                jev_scored=len([j for j in jev if j and j["status"] in ("pass", "fail")]), jev_passed=len([j for j in jev if j and j["status"] == "pass"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--no-jev", action="store_true")
    args = parser.parse_args()
    BASE = Path(tempfile.mkdtemp(prefix="cf-eval-base-"))
    cf_apps.configure(BASE, BASE / "outputs")
    chosen = [t for t in TASKS if not args.only or t[0] in args.only.split(",")]
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(run_one, chosen))
    jev = [] if args.no_jev else [jev_routing(t) for t in chosen]
    summary = summarize(results, jev)
    out = Path(__file__).parent / "results.json"
    out.write_text(json.dumps(dict(summary=summary, results=results, jev=jev, date=time.strftime("%Y-%m-%d %H:%M")), ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
