"""Observe the application from a separate process while it runs."""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PHASE = "CLONFIELD_PHASE "
READY = "CLONFIELD_READY "


def fields(path):
    try:
        return {key.rstrip(":"): value for key, *values in
                (line.split() for line in path.read_text().splitlines() if line.split())
                if values and (value := values[0]).isdigit()}
    except OSError:
        return {}


def counter_paths(pid):
    root = Path("/sys/fs/cgroup")
    found = {root / "memory.events", root / "memory/memory.oom_control"}
    try:
        for entry in Path(f"/proc/{pid}/cgroup").read_text().splitlines():
            _, controllers, group = entry.split(":", 2)
            if controllers not in ("", "memory") and "memory" not in controllers.split(","):
                continue
            mount = root / "memory" if controllers else root
            name = "memory.oom_control" if controllers else "memory.events"
            directory = mount / group.lstrip("/")
            found.add(directory / name)
            found.update(parent / name for parent in directory.parents if parent.is_relative_to(mount))
    except (OSError, ValueError):
        pass
    return sorted(path for path in found if path.is_file())


def sample(pid, paths, phase):
    cgroups = {}
    for path in paths:
        parent = path.parent
        names = ("current", "max", "peak") if path.name == "memory.events" else (
            "usage_in_bytes", "limit_in_bytes", "max_usage_in_bytes")
        readings = {}
        for name in names:
            try:
                readings[name] = (parent / ("memory." + name)).read_text().strip()
            except OSError:
                pass
        stats = fields(parent / "memory.stat")
        cgroups[str(path)] = {"counters": fields(path), **readings,
                              "anon_bytes": stats.get("anon"), "file_bytes": stats.get("file")}
    return {"time": time.time(), "phase": phase,
            "process_kib": {k: v for k, v in fields(Path(f"/proc/{pid}/status")).items() if k in ("VmRSS", "VmHWM", "RssAnon", "RssFile", "VmSwap")},
            "ram_available_kib": fields(Path("/proc/meminfo")).get("MemAvailable"),
            "cgroups": cgroups}


def gpu_sample():
    if not shutil.which("nvidia-smi"):
        return []
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                                 "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3)
        return [tuple(map(int, row.split(","))) for row in result.stdout.splitlines()] if result.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def classify(code, before, after, cuda_oom=False):
    deltas = {}
    for path, start in before["cgroups"].items():
        end = after["cgroups"].get(path, {}).get("counters", {})
        start = start["counters"]
        if "oom_kill" in start and "oom_kill" in end:
            deltas[path] = int(end["oom_kill"]) - int(start["oom_kill"])
    if code == -signal.SIGKILL:
        outcome = "sigkill_com_oom_no_cgroup" if any(v > 0 for v in deltas.values()) else "sigkill_sem_causa_confirmada"
    elif cuda_oom:
        outcome = "cuda_oom_reportado"
    elif code < 0:
        outcome = "outro_sinal"
    else:
        outcome = "ok" if not code else "erro_com_codigo"
    return outcome, deltas


def supervise(argv, target, startup_timeout=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    paths = counter_paths(os.getpid())
    before = sample(os.getpid(), paths, "antes")
    phase = "inicialização"
    cuda_oom = False
    done = threading.Event()
    ready = threading.Event()
    timed_out = threading.Event()
    write_lock = threading.Lock()
    with target.open("w", encoding="utf-8", buffering=1) as log:
        def record(value):
            with write_lock:
                log.write(json.dumps(value, ensure_ascii=False) + "\n")

        record({"event": "before", **before})
        print("ClonField: abrindo o processo do Studio.", flush=True)
        child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, errors="replace", cwd=ROOT)
        def watch_startup():
            start = time.monotonic()
            while not ready.wait(min(10, max(0, startup_timeout - (time.monotonic() - start)))):
                if done.is_set() or child.poll() is not None:
                    return
                elapsed = time.monotonic() - start
                if elapsed >= startup_timeout:
                    timed_out.set()
                    print(f"ClonField: abertura excedeu {startup_timeout:g} s · etapa: {phase}.", flush=True)
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                    return
                print(f"ClonField: aguardando abertura há {elapsed:.0f} s · etapa: {phase}.", flush=True)

        watchdog = None
        if startup_timeout is not None:
            watchdog = threading.Thread(target=watch_startup, daemon=True)
            watchdog.start()

        def monitor():
            tick = 0
            while not done.is_set():
                snap = sample(child.pid, paths, phase)
                if tick % 5 == 0:
                    snap["gpu_mib_used_total"] = gpu_sample()
                record({"event": "sample", **snap})
                tick += 1
                done.wait(1)

        worker = threading.Thread(target=monitor, daemon=True)
        worker.start()
        try:
            for line in child.stdout:
                if line.startswith(READY):
                    ready.set()
                if line.startswith(PHASE):
                    marker = line.removeprefix(PHASE).strip()
                    if re.fullmatch(r"[a-z_]{1,50}", marker):
                        phase = marker
                        record({"event": "phase", "phase": phase, "time": time.time()})
                        cuda_oom |= phase == "cuda_oom"
                print(line, end="", flush=True)
            code = child.wait()
        except KeyboardInterrupt:
            child.terminate()
            try:
                code = child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                code = child.wait()
        finally:
            done.set()
            ready.set()
            if watchdog is not None:
                watchdog.join()
            worker.join()
            child.stdout.close()
        after = sample(os.getpid(), paths, phase)
        outcome, deltas = classify(code, before, after, cuda_oom)
        if timed_out.is_set():
            outcome = "tempo_de_abertura_excedido"
        record({"event": "exit", "returncode": code, "outcome": outcome, "oom_kill_delta": deltas, **after})
    print(f"Diagnóstico: {outcome} · última etapa: {phase} · {target}", flush=True)
    if timed_out.is_set():
        return 124
    return 128 + abs(code) if code < 0 else code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, default=Path("/content/clonfield_runtime/diagnostico.jsonl"))
    parser.add_argument("--local", action="store_true", help="Abra sem o túnel público do Gradio.")
    args = parser.parse_args()
    app_args = ["--local"] if args.local else []
    timeout = 90
    raise SystemExit(supervise([sys.executable, "-u", str(ROOT / "studio_app.py"), *app_args],
                              args.log, startup_timeout=timeout))


if __name__ == "__main__":
    main()
