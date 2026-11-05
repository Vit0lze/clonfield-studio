"""Watchdog behaviour against a real ComfyUI (CPU). Needs CLONFIELD_COMFY_DIR (checkout) and CLONFIELD_COMFY_PY."""

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

import pytest
import requests
from PIL import Image

import cf_workflows as workflows

COMFY = Path(os.environ.get("CLONFIELD_COMFY_DIR", ""))
PY = os.environ.get("CLONFIELD_COMFY_PY", "")
pytestmark = pytest.mark.skipif(not COMFY.is_dir(), reason="CLONFIELD_COMFY_DIR ausente")


def graph(hops, side, image="r.png"):
    g = {"1": {"class_type": "LoadImage", "inputs": {"image": image}}}
    last = "1"
    for i in range(hops):
        key = str(i + 2)
        g[key] = {"class_type": "ImageScale", "inputs": {"image": [last, 0], "upscale_method": "lanczos",
                                                         "width": side - (i % 2) * 32, "height": side, "crop": "center"}}
        last = key
    g["save"] = {"class_type": "SaveImage", "inputs": {"images": [last, 0], "filename_prefix": "ClonField/r"}}
    return g


def stage(tmp_path, name="r.png", size=2048):
    path = tmp_path / name
    Image.effect_noise((size, size), 70).convert("RGB").save(path)
    return path


def run(tmp_path, g, **kw):
    media = [stage(tmp_path)]
    return workflows.run(g, tmp_path, lambda *a, **k: None, files=media, **kw)


def wait_idle(timeout=90):
    for _ in range(timeout):
        try:
            q = requests.get(f"{workflows.SERVER}/queue", timeout=3).json()
            if not q["queue_running"] and not q["queue_pending"]:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise AssertionError("ComfyUI não ficou ocioso")


def restart_comfy():
    subprocess.run(["pkill", "-f", "[m]ain.py --cpu --listen"], check=False)
    time.sleep(2)
    log = open(os.environ["CLONFIELD_COMFY_LOG"], "w")
    subprocess.Popen([PY, "main.py", "--cpu", "--listen", "127.0.0.1", "--port", "8188"], cwd=COMFY,
                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(90):
        try:
            requests.get(f"{workflows.SERVER}/system_stats", timeout=2)
            return
        except requests.RequestException:
            time.sleep(1)
    raise AssertionError("ComfyUI não voltou")


def test_stall_watchdog_interrupts_a_silent_node(tmp_path):
    wait_idle()
    started = time.monotonic()
    job = run(tmp_path, graph(1, 7000), stall=3, control=workflows.Control())
    assert job["status"] == "travado", job
    assert "Sem progresso" in job["message"]
    assert time.monotonic() - started < 60
    wait_idle()


def test_job_removed_behind_our_back_is_reported_as_lost(tmp_path):
    wait_idle()
    blocker = threading.Thread(target=lambda: run(tmp_path, graph(30, 3000), control=workflows.Control()))
    blocker.start()
    time.sleep(2)

    def delete_pending():
        for _ in range(60):
            q = requests.get(f"{workflows.SERVER}/queue").json()
            if q["queue_pending"]:
                requests.post(f"{workflows.SERVER}/queue", json={"delete": [q["queue_pending"][0][1]]})
                return
            time.sleep(0.3)
    threading.Thread(target=delete_pending).start()
    job = run(tmp_path, graph(1, 256), control=workflows.Control())
    assert job["status"] == "falhou" and "perdeu" in job["message"], job
    workflows.interrupt()
    blocker.join(120)
    wait_idle()


def test_dead_worker_is_reported_with_log_tail(tmp_path):
    wait_idle()
    killer = threading.Timer(3, lambda: subprocess.run(["pkill", "-f", "[m]ain.py --cpu --listen"]))
    killer.start()
    started = time.monotonic()
    job = run(tmp_path, graph(40, 3000), control=workflows.Control())
    try:
        assert job["status"] == "falhou", job
        assert "parou de responder" in job["message"]
        assert time.monotonic() - started < 90
    finally:
        restart_comfy()
