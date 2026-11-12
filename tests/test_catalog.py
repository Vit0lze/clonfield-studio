"""Favourites, LoRA families, upscaler catalogue and model sizes through the real engine app."""
import pytest
import requests
from starlette.testclient import TestClient

import cf_api
import cf_apps
import cf_favorites


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    import cf_factory
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path_factory.mktemp("catalog")
    mp = pytest.MonkeyPatch()
    mp.setenv("CLONFIELD_FAKE_VRAM", "15")
    mp.setenv("CLONFIELD_COMFY_MODELS", str(base / "models"))
    cf_apps.configure(base, base / "outputs")
    client = TestClient(cf_api.build_app(base, base / "outputs", lambda t: t == "pw", "secret"), headers={"Authorization": "Bearer pw"})
    client.base = base
    yield client
    mp.undo()


def test_favourites_toggle_persist_and_validate(api):
    r = api.post("/clonfield/api/favorites/toggle", json={"kind": "model", "id": "flux2", "meta": {"title": "FLUX.2", "evil": "<script>"}})
    assert r.json() == {"favorite": True}
    items = api.get("/clonfield/api/favorites").json()
    entry = next(i for i in items if i["id"] == "flux2")
    assert entry["kind"] == "model" and entry["meta"] == {"title": "FLUX.2"}  # unknown meta keys are dropped
    assert cf_favorites.load(api.base)[0]["id"] == "flux2"  # on disk, so it survives a restart
    assert api.post("/clonfield/api/favorites/toggle", json={"kind": "model", "id": "flux2"}).json() == {"favorite": False}
    assert api.post("/clonfield/api/favorites/toggle", json={"kind": "bogus", "id": "x"}).status_code == 400
    assert api.post("/clonfield/api/favorites/toggle", json={"kind": "app", "id": ""}).status_code == 400


def test_lora_families_cover_every_recipe_family_including_checkpoint_ones(api):
    families = {f["key"]: f for f in api.get("/clonfield/api/lora-families").json()}
    assert {"qwen21", "flux2", "flux3", "krea2", "z-image", "sdxl", "sd15"} <= set(families)
    assert all({"title", "installed", "loras_installed"} <= set(f) for f in families.values())
    assert families["qwen21"]["installed"] is False  # nothing downloaded in the test sandbox


def test_upscaler_catalogue_lists_every_builtin_with_licence_and_install_state(api):
    items = api.get("/clonfield/api/upscalers").json()
    assert len(items) >= 8 and all(i["license"] and i["mb"] and i["installed"] is False for i in items)
    assert api.post("/clonfield/api/upscalers/install", json={"name": "nope"}).status_code == 400


def test_upscale_app_offers_the_new_models_with_a_favourite_kind(api):
    app = next(a for a in api.get("/clonfield/api/apps").json() if a["id"] == "upscale")
    mode = next(f for f in app["fields"] if f["id"] == "mode")
    assert len(mode["options"]) >= 9 and any(o.get("fav_kind") == "upscaler" for o in mode["options"])


def online():
    try:
        return requests.head("https://huggingface.co", timeout=5).status_code < 500
    except requests.RequestException:
        return False


@pytest.mark.skipif(not online(), reason="offline")
def test_models_report_real_download_sizes_from_hugging_face(api):
    models = {m["key"]: m for m in api.get("/clonfield/api/models").json()}
    assert models["flux2"]["download_bytes"] > 10e9 and models["flux2"]["size_known"]
    assert models["flux2"]["files"][0]["size"] > 1e9
