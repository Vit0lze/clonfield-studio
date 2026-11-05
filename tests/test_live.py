"""Live tests: a real engine (cf_engine.py) in front of a real ComfyUI. No stubs.

Run with the engine on :7861 and ComfyUI on :8188:
  CLONFIELD_API=http://127.0.0.1:7861 CLONFIELD_PASSWORD=... pytest tests/test_live.py -v
"""

import io
import json
import os
import time

import pytest
import requests
from PIL import Image

API = os.environ.get("CLONFIELD_API", "http://127.0.0.1:7861") + "/clonfield/api"
AUTH = {"Authorization": "Bearer " + os.environ.get("CLONFIELD_PASSWORD", "testpw-local")}


def call(method, path, **kw):
    kw.setdefault("headers", AUTH)
    kw.setdefault("timeout", 30)
    return requests.request(method, API + path, **kw)


def upload(name, image):
    buf = io.BytesIO()
    image.save(buf, "PNG")
    r = call("POST", "/upload", files={"files": (name, buf.getvalue(), "image/png")})
    assert r.ok, r.text
    return r.json()[0]


def wait(job_id, timeout=120):
    """Follow the SSE stream like the web app does, returning every snapshot."""
    seen = []
    with requests.get(f"{API}/jobs/{job_id}/events", headers=AUTH, stream=True, timeout=timeout) as r:
        for line in r.iter_lines():
            if line.startswith(b"data: "):
                seen.append(json.loads(line[6:]))
                if seen[-1]["status"] in ("concluído", "falhou", "cancelado", "travado"):
                    break
    return seen


def submit(app, params):
    r = call("POST", "/jobs", json={"app": app, "params": params})
    assert r.status_code == 202, r.text
    return r.json()


def slow_graph(name, hops=40, side=4096):
    graph = {"1": {"class_type": "LoadImage", "inputs": {"image": name}}}
    last = "1"
    for i in range(hops):
        key = str(i + 2)
        graph[key] = {"class_type": "ImageScale", "inputs": {
            "image": [last, 0], "upscale_method": "lanczos", "width": side - (i % 2) * 64, "height": side, "crop": "center"}}
        last = key
    graph["save"] = {"class_type": "SaveImage", "inputs": {"images": [last, 0], "filename_prefix": "ClonField/test"}}
    return graph


def test_auth_required():
    assert requests.get(API + "/apps").status_code == 401
    assert requests.get(API + "/apps", headers={"Authorization": "Bearer errada"}).status_code == 401


def test_apps_follow_tier():
    apps = call("GET", "/apps").json()
    tier = call("GET", "/system").json()["tier"]
    assert {a["id"] for a in apps} >= {"create", "animate", "upscale", "workflow"}
    openjutsu = next(a for a in apps if a["id"] == "openjutsu")
    assert openjutsu["blocked"] == (tier["vram_gb"] < 90)
    create = next(a for a in apps if a["id"] == "create")
    qualities = next(f for f in create["fields"] if f["id"] == "quality")
    assert any(o["hint"].startswith(str(tier["default_side"])) for o in qualities["options"])


def test_cpu_apps_end_to_end():
    src = upload("foto.png", Image.effect_noise((640, 480), 60).convert("RGB"))
    done = wait(submit("upscale", {"image": [src["id"]], "mode": "Lanczos (rápido, sem IA)", "scale": 2})["id"])
    assert done[-1]["status"] == "concluído", done[-1]
    result = done[-1]["results"][0]
    data = requests.get(API.replace("/clonfield/api", "") + result["url"]).content
    assert Image.open(io.BytesIO(data)).size == (1280, 960)
    look = wait(submit("look", {"image": [src["id"]], "look": "Cinema quente", "strength": 80})["id"])
    assert look[-1]["status"] == "concluído", look[-1]
    frame = wait(submit("frame", {"image": [src["id"]], "ratio": "Quadrado · 1:1", "fit": "Preencher"})["id"])
    assert frame[-1]["status"] == "concluído", frame[-1]
    b = upload("depois.png", Image.effect_noise((640, 480), 20).convert("RGB"))
    cmp_ = wait(submit("compare", {"before": [src["id"]], "after": [b["id"]]})["id"])
    assert cmp_[-1]["status"] == "concluído", cmp_[-1]


def test_missing_required_is_a_clear_error():
    r = call("POST", "/jobs", json={"app": "create", "params": {"model": "flux2"}})
    assert r.status_code == 400 and "Preencha" in r.json()["detail"]
    r = call("POST", "/jobs", json={"app": "edit", "params": {"prompt": "x", "model": "flux2"}})
    assert r.status_code == 400 and "ao menos" in r.json()["detail"]


def test_signed_links_expire_and_reject_tampering():
    src = upload("a.png", Image.new("RGB", (8, 8), "red"))
    url = API.replace("/clonfield/api", "") + src["url"]
    assert requests.get(url).status_code == 200
    assert requests.get(url[:-2] + "00").status_code == 403
    assert requests.get(url.split("?")[0]).status_code == 403


def test_real_comfyui_workflow_streams_progress():
    img = upload("entrada.png", Image.effect_noise((512, 512), 80).convert("RGB"))
    graph = {"1": {"class_type": "LoadImage", "inputs": {"image": "entrada.png"}},
             "2": {"class_type": "ImageScale", "inputs": {"image": ["1", 0], "upscale_method": "lanczos", "width": 1024, "height": 1024, "crop": "center"}},
             "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "ClonField/test"}}}
    gf = call("POST", "/upload", files={"files": ("g.json", json.dumps(graph).encode(), "application/json")}).json()[0]
    snaps = wait(submit("workflow", {"graph": [gf["id"]], "media": [img["id"]]})["id"])
    assert snaps[-1]["status"] == "concluído", snaps[-1]
    assert snaps[-1]["results"][0]["kind"] == "image"
    assert any("ComfyUI" in s["desc"] for s in snaps)


def test_cancel_running_comfyui_job_frees_the_worker():
    img = upload("grande.png", Image.effect_noise((2048, 2048), 80).convert("RGB"))
    gf = call("POST", "/upload", files={"files": ("g2.json", json.dumps(slow_graph("grande.png")).encode(), "application/json")}).json()[0]
    job = submit("workflow", {"graph": [gf["id"]], "media": [img["id"]]})
    for _ in range(60):
        state = call("GET", f"/jobs/{job['id']}").json()
        if "ComfyUI" in state["desc"] and state["status"] == "executando":
            break
        time.sleep(0.5)
    time.sleep(2)
    assert call("POST", f"/jobs/{job['id']}/cancel").json()["cancelled"]
    final = wait(job["id"], 60)[-1]
    assert final["status"] == "cancelado", final
    # ComfyUI only honours an interrupt between nodes, so give the current node time to finish.
    for _ in range(60):
        worker = call("GET", "/system").json()["worker"]
        if worker["running"] == 0 and worker["pending"] == 0:
            break
        time.sleep(1)
    assert worker["running"] == 0 and worker["pending"] == 0, worker


def test_gpu_lane_queues_and_reports_position():
    img = upload("fila.png", Image.effect_noise((1024, 1024), 80).convert("RGB"))
    gf = call("POST", "/upload", files={"files": ("g3.json", json.dumps(slow_graph("fila.png", hops=12, side=2048)).encode(), "application/json")}).json()[0]
    first = submit("workflow", {"graph": [gf["id"]], "media": [img["id"]]})
    second = submit("workflow", {"graph": [gf["id"]], "media": [img["id"]]})
    assert call("GET", f"/jobs/{second['id']}").json()["position"] == 1
    assert call("POST", f"/jobs/{second['id']}/cancel").json()["cancelled"]
    assert call("GET", f"/jobs/{second['id']}").json()["status"] == "cancelado"
    call("POST", f"/jobs/{first['id']}/cancel")
    wait(first["id"], 60)


def test_install_catalog_lora_from_huggingface_matches_published_sha():
    """Real download through the API job + SSE. Needs HF_TOKEN in the engine's environment."""
    import hashlib
    name, sha = "bfs_body_swap_v1.0_qwen_2.1.safetensors", "7dc0a53aba4dbc70c204f498936a619d226559da11011f748c389189af46b664"
    loras = call("GET", "/loras?family=qwen21").json()
    entry = next(item for item in loras if item["name"] == name)
    assert entry["source"] == "catálogo"
    job = call("POST", "/loras/install", json={"name": name}).json()
    snaps = wait(job["id"], timeout=600)
    assert snaps[-1]["status"] == "concluído", snaps[-1]
    assert any("Baixando" in s["desc"] and "/s" in s["desc"] for s in snaps) or entry["installed"]
    path = os.path.join(os.environ["CLONFIELD_DIR"], "loras", name)
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    assert digest == sha
    assert next(i for i in call("GET", "/loras?family=qwen21").json() if i["name"] == name)["installed"]
