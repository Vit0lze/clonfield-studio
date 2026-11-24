"""V9-P1-ASSET-001 demonstration against a RUNNING engine (cf_engine.py), real CPU jobs, no GPU.
Usage: CF_URL=http://127.0.0.1:7861 CF_TOKEN=<session password> python tests/demo/asset_graph_demo.py
Prints one line per proof. Exits non-zero on the first broken invariant."""
import hashlib
import io
import os
import sys
import time

import requests
from PIL import Image, ImageDraw

URL = os.environ.get("CF_URL", "http://127.0.0.1:7861") + "/clonfield/api"
S = requests.Session()
S.trust_env = False
S.headers["Authorization"] = "Bearer " + os.environ["CF_TOKEN"]


def png(color):
    out = io.BytesIO()
    image = Image.new("RGB", (320, 240), color)
    ImageDraw.Draw(image).ellipse((60, 40, 260, 200), fill=(color[2], color[0], color[1]))
    image.save(out, "PNG")
    return out.getvalue()


def call(method, path, **kw):
    r = S.request(method, URL + path, timeout=60, **kw)
    if r.status_code >= 400:
        sys.exit(f"FALHA {method} {path}: {r.status_code} {r.text[:300]}")
    return r.json()


def wait(job_id):
    for _ in range(300):
        job = call("GET", f"/jobs/{job_id}")
        if job["status"] in ("concluído", "falhou", "cancelado"):
            return job
        time.sleep(0.5)
    sys.exit("FALHA: job não terminou")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check(ok, text):
    print(("OK   " if ok else "FALHA ") + text)
    if not ok:
        sys.exit(1)


up = call("POST", "/upload", files={"files": ("retrato.png", png((200, 60, 60)), "image/png")})[0]
base_job = wait(call("POST", "/jobs", json={"app": "upscale", "params": {"image": [up["id"]], "mode": "Lanczos (rápido, sem IA)", "scale": 2}})["id"])
check(base_job["status"] == "concluído", f"job real de origem (upscale Lanczos) {base_job['id']}")
result = base_job["results"][0]
original_bytes = S.get(URL.rsplit("/clonfield/api", 1)[0] + result["url"]).content

made = call("POST", "/assets", json={"from": {"result": result["path"]}, "title": "Retrato demo"})
asset, v1 = made["asset"], made["version"]
check(v1["schema"] == "AssetRef.v1" and v1["sha256"] == sha(original_bytes), f"publicado {asset['asset_id']} {v1['version_id']} sha={v1['sha256'][:12]} = sha do resultado")
check(v1["producer"]["kind"] == "job" and v1["producer"]["job_id"] == base_job["id"], f"procedência: producer.job_id={v1['producer']['job_id']} app={v1['producer']['app']}")

uploads_before = len(call("GET", "/jobs"))  # noqa: F841 (jobs list only for context)
a = wait(call("POST", "/jobs", json={"app": "look", "params": {"image": [{"id": v1["version_id"]}], "look": "Preto e branco", "strength": 100}})["id"])
b = wait(call("POST", "/jobs", json={"app": "frame", "params": {"image": [{"id": v1["version_id"]}]}})["id"])
check(a["status"] == "concluído" and a["asset_versions"] == {v1["version_id"]: v1["version_id"]}, f"consumidor 1 «{a['app']}» usou {v1['version_id']} ({a['id']})")
check(b["status"] == "concluído" and b["asset_versions"] == {v1["version_id"]: v1["version_id"]}, f"consumidor 2 «{b['app']}» usou {v1['version_id']} ({b['id']}) — {b.get('message') or ''}")
check(call("GET", f"/assets/versions/{v1['version_id']}")["verified"], "v1 continua conferindo com o SHA-256 depois dos dois usos")

up2 = call("POST", "/upload", files={"files": ("retrato-v2.png", png((60, 160, 60)), "image/png")})[0]
v2 = call("POST", f"/assets/{asset['asset_id']}/versions", json={"from": {"upload": up2["id"]}, "note": "cor nova"})["version"]
detail = call("GET", f"/assets/{asset['asset_id']}")
check(detail["current"] == v2["version_id"] and [v["number"] for v in detail["versions"]] == [1, 2], f"v2 {v2['version_id']} é a atual; v1 continua listada")
check(v2["parents"][0] == {"asset_id": asset["asset_id"], "version_id": v1["version_id"], "role": "previous"}, "v2.parents aponta v1 (role previous)")

other = call("POST", "/upload", files={"files": ("cenario.png", png((40, 40, 160)), "image/png")})[0]


def graph(media):
    return {"nodes": [
        {"id": "a_look", "cap": "look", "inputs": {"image": {"media": media}}, "params": {"look": "Preto e branco", "strength": 100}},
        {"id": "a_up", "cap": "upscale", "inputs": {"image": {"from": "a_look.image"}}, "params": {"scale": 2}},
        {"id": "b_look", "cap": "look", "inputs": {"image": {"media": other["id"]}}, "params": {"look": "Preto e branco", "strength": 100}},
        {"id": "b_up", "cap": "upscale", "inputs": {"image": {"from": "b_look.image"}}, "params": {"scale": 2}}]}


def run(media):
    job = wait(call("POST", "/dag/run", json={"graph": graph(media)})["id"])
    return call("GET", f"/dag/runs/{job['run']}")


r1, r2, r3 = run(v1["version_id"]), run(v2["version_id"]), run(v1["version_id"])
print(f"     DAG v1: recomputados={sorted(r1['recomputed'])} cache={sorted(r1['cached'])}")
print(f"     DAG v2: recomputados={sorted(r2['recomputed'])} cache={sorted(r2['cached'])}")
print(f"     DAG v1 de novo: recomputados={sorted(r3['recomputed'])} cache={sorted(r3['cached'])}")
check(set(r2["recomputed"]) == {"a_look", "a_up"} and set(r2["cached"]) >= {"b_look", "b_up"}, "trocar v1→v2 refez só o ramo que lê o ativo")
check(r3["recomputed"] == [], "voltar para v1 (versão anterior, ainda selecionável): tudo do cache")
check(call("GET", f"/assets/versions/{v1['version_id']}")["sha256"] == v1["sha256"], "hash de v1 inalterado no fim")
print(f"ASSET {asset['asset_id']} V1 {v1['version_id']} V2 {v2['version_id']}")
