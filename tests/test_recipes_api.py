"""Recipes through the real Starlette app: catalog, preview, a queue of runs as separate jobs, real uploads, plain-language errors."""
import io

import pytest
from PIL import Image, ImageDraw
from starlette.testclient import TestClient

import cf_api
import cf_apps
from tests.test_agent_api import BASE, wait_job

PNG = None


def png(n):
    out = io.BytesIO()
    image = Image.new("RGB", (160, 120), (20 * n, 40, 60))
    ImageDraw.Draw(image).ellipse((30, 20, 130, 100), fill=(220, 180, 120))
    image.save(out, "PNG")
    return out.getvalue()


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    import cf_factory
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path_factory.mktemp("recapi")
    mp = pytest.MonkeyPatch()
    mp.setenv("CLONFIELD_FAKE_VRAM", "24")
    mp.setenv("CLONFIELD_COMFY_MODELS", str(base / "models"))
    cf_apps.configure(base, base / "outputs")
    client = TestClient(cf_api.build_app(base, base / "outputs", lambda t: t == "pw", "secret"), headers={"Authorization": "Bearer pw"})
    yield client
    mp.undo()


def up(api, n):
    return api.post(f"{BASE}/upload", files={"files": (f"f{n}.png", png(n), "image/png")}).json()[0]["id"]


def test_catalog_lists_cpu_and_gpu_recipes_with_forms(api):
    items = api.get(f"{BASE}/recipes").json()
    ids = {r["id"] for r in items}
    assert {"polir_lote", "looks_lado_a_lado", "cenarios_em_matriz", "storyboard_em_filme"} <= ids
    polish = next(r for r in items if r["id"] == "polir_lote")
    assert polish["lane"] == "cpu" and polish["steps"] == 4 and any(i["id"] == "images" for i in polish["inputs"])
    assert next(r for r in items if r["id"] == "loop_de_imagem")["state"] == "BLOQUEADO_GPU"


def test_preview_names_every_step(api):
    ids = [up(api, n) for n in (1, 2)]
    out = api.post(f"{BASE}/recipes/polir_lote/preview", json=dict(vars=dict(images=ids, ratio="Quadrado · 1:1", look="Frio suave", strength=50))).json()
    assert [s["label"] for s in out["steps"]][0] == "Enquadrar cada imagem"
    assert next(s for s in out["steps"] if s["id"] == "look")["each"] == "image"
    assert out["resources"]["lane"] == "cpu" and out["ok"] is True
    missing = api.post(f"{BASE}/recipes/polir_lote/preview", json=dict(vars={}))
    assert missing.status_code == 200 and missing.json()["ok"] is False and "envie de 1 a 16" in missing.json()["detail"]


def test_batch_becomes_a_queue_of_jobs_and_each_finishes_with_files(api):
    sets = []
    for group in ([1, 2], [3, 4]):
        sets.append(dict(images=[up(api, n) for n in group], ratio="Quadrado · 1:1", look="Cinema quente", strength=70))
    response = api.post(f"{BASE}/recipes/polir_lote/run", json=dict(batch=sets))
    assert response.status_code == 202
    jobs = response.json()["jobs"]
    assert [j["title"] for j in jobs] == ["Polir um lote de imagens · 1/2", "Polir um lote de imagens · 2/2"]
    for job in jobs:
        done = wait_job(api, job["id"], 90)
        assert done["status"] == "concluído", done
        assert len(done["results"]) == 2  # sheet + best


def test_errors_say_what_to_fix(api):
    bad = api.post(f"{BASE}/recipes/polir_lote/run", json=dict(vars=dict(images=[])))
    assert bad.status_code == 400 and "envie de 1 a 16" in bad.json()["detail"]
    ghost = api.post(f"{BASE}/recipes/polir_lote/run", json=dict(vars=dict(images=["f" * 32], ratio="Quadrado · 1:1", look="Frio suave", strength=50)))
    assert ghost.status_code == 400 and "não existe nesta sessão" in ghost.json()["detail"]
    assert api.post(f"{BASE}/recipes/nao-existe/run", json={}).status_code == 404
    many = api.post(f"{BASE}/recipes/looks_lado_a_lado/run", json=dict(batch=[{}] * 13))
    assert many.status_code == 400 and "1 a 12" in many.json()["detail"]
    second = api.post(f"{BASE}/recipes/looks_lado_a_lado/run", json=dict(batch=[dict(image=up(api, 1), strength=50), dict(image="x")]))
    assert second.status_code == 400 and second.json()["detail"].startswith("Execução 2:")
