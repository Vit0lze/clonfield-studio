"""The catalogue contract: every provider emits valid items, sizes and sharing are honest, bad items are refused."""
import pytest
import requests
from starlette.testclient import TestClient

import cf_api
import cf_apps
import cf_contracts as C


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    import cf_factory
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path_factory.mktemp("contracts")
    mp = pytest.MonkeyPatch()
    mp.setenv("CLONFIELD_FAKE_VRAM", "15")
    mp.setenv("CLONFIELD_COMFY_MODELS", str(base / "models"))
    cf_apps.configure(base, base / "outputs")
    client = TestClient(cf_api.build_app(base, base / "outputs", lambda t: t == "pw", "secret"), headers={"Authorization": "Bearer pw"})
    yield client
    mp.undo()


def get(api, **params):
    r = api.get("/clonfield/api/library", params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


@pytest.mark.parametrize("kind", C.CATEGORY_IDS)
@pytest.mark.parametrize("view", ["recommended", "installed"])
def test_every_offline_view_returns_contract_valid_items(api, kind, view):
    items = get(api, kind=kind, view=view)
    for item in items:
        C.check(item)
        assert item["kind"] == kind
        assert item["favorite"]["id"].startswith(item["source"] + ":") or item["favorite"]["kind"] == kind
    ids = [i["favorite"]["id"] for i in items]
    assert len(ids) == len(set(ids)), "one item, one favourite id"


def test_every_kind_has_something_recommended_and_nothing_is_marked_validated_without_proof(api):
    for kind in C.CATEGORY_IDS:
        items = get(api, kind=kind, view="recommended")
        assert items, kind
        assert all(i["status"] != "validado" and not i["compat"]["validated"] for i in items)  # nothing is validated on a GPU yet


def test_recipe_download_size_is_the_sum_of_named_parts_and_shared_files_are_declared(api):
    models = {i["id"]: i for i in get(api, kind="model", view="recommended")}
    z = models["z-image"]
    assert [p["label"] for p in z["size_parts"]] == ["Modelo de difusão", "Encoder de texto", "VAE"]
    assert z["size"] == sum(p["size"] for p in z["size_parts"])
    encoder = z["size_parts"][1]
    assert set(encoder["shared_with"]) == {"FLUX.2 Klein 4B", "Z-Image Turbo"}  # the same 8 GB file serves three recipes
    assert z["size_parts"][0]["size"] < z["size"] / 2  # the model alone is much smaller than the headline number
    flux3 = models["flux3"]
    assert flux3["size"] is None  # gated repository: unknown stays unknown, never a guess
    assert any(a["id"] == "install" and "≥" not in a["label"] or a["id"] == "install" for a in z["actions"])


def test_upscaler_items_carry_licence_and_flag_non_commercial(api):
    items = {i["title"]: i for i in get(api, kind="upscaler", view="recommended")}
    assert len(items) >= 9
    assert "uso não comercial" in items["UltraSharp V2 (140 MB)".split(" (")[0]]["badges"] or any("uso não comercial" in i["badges"] for i in items.values())
    assert all(i["license"] for i in items.values())


def test_unknown_kind_or_view_is_a_clean_400(api):
    assert api.get("/clonfield/api/library", params={"kind": "bogus", "view": "installed"}).status_code == 400
    assert api.get("/clonfield/api/library", params={"kind": "vae", "view": "nope"}).status_code == 400
    assert {c["id"] for c in api.get("/clonfield/api/library/categories").json()} == set(C.CATEGORY_IDS)


def test_contract_refuses_bad_items():
    ok = dict(kind="vae", id="a", title="t", source="civitai", status="descoberto")
    C.item(**ok)
    for bad in (dict(ok, status="pronto"), dict(ok, source="ftp"), dict(ok, kind="x"), dict(ok, size=-1), dict(ok, size="3 GB"),
                dict(ok, status="validado"), dict(ok, actions=[dict(id="install", label="Instalar", enabled=False)])):
        with pytest.raises(C.ContractError):
            C.item(**{k: v for k, v in bad.items()})
    with pytest.raises(C.ContractError):
        C.action("explode", "x")
    with pytest.raises(C.ContractError):
        C.item(**dict(ok, size=10, size_parts=[C.part("a", 3)]))  # headline bigger than the sum of its parts


def online():
    try:
        return requests.head("https://civitai.red", timeout=5).status_code < 500
    except requests.RequestException:
        return False


@pytest.mark.skipif(not online(), reason="offline")
@pytest.mark.parametrize("kind,family,source", [("model", "z-image", "civitai"), ("vae", "qwen21", "civitai"), ("upscaler", "qwen21", "civitai"), ("lora", "qwen21", "civitai"), ("encoder", "qwen21", "huggingface"), ("upscaler", "qwen21", "huggingface")])
def test_live_explore_returns_contract_valid_items_for_every_kind(api, kind, family, source):
    items = get(api, kind=kind, view="explore", family=family, source=source)
    assert items
    for item in items:
        C.check(item)
        assert item["status"] in ("descoberto", "compatível", "instalado")
    if source == "huggingface":
        assert all(i["status"] == "descoberto" for i in items)  # discovery is not compatibility
        assert all(not a["enabled"] for i in items for a in i["actions"] if a["id"] == "install")


@pytest.mark.skipif(not online(), reason="offline")
def test_huggingface_upscaler_search_returns_upscalers_not_qwen_edit_loras(api):
    items = get(api, kind="upscaler", view="explore", family="qwen21", source="huggingface")
    assert len(items) >= 8
    titles = " ".join(i["title"].lower() for i in items)
    assert not any(bad in titles for bad in ("qwen", "flux", "onnx", "gguf", "mlx"))
    assert any(k in titles for k in ("esrgan", "swinir", "upscal", "sr"))
