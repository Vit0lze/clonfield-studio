"""Asset Graph (AssetRef.v1, docs/V9_ASSET_GRAPH_CONTRACT.md): real files (PIL), the real storage module and the real Starlette engine app
with real CPU jobs (Lanczos upscale, look) and the real DAG executor. The only spy is a pass-through wrapper on an app runner that records the
path it was handed and then calls the real runner."""
import hashlib
import io
import os
import stat
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from starlette.testclient import TestClient

import cf_api
import cf_apps
import cf_asset_graph as ag

BASE = "/clonfield/api"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def png_bytes(color=(30, 40, 60), size=(160, 120)):
    out = io.BytesIO()
    image = Image.new("RGB", size, color)
    ImageDraw.Draw(image).ellipse((30, 20, 130, 100), fill=(color[2], color[0], color[1]))
    image.save(out, "PNG")
    return out.getvalue()


@pytest.fixture()
def store(tmp_path):
    out = tmp_path / "outputs"
    out.mkdir()
    (tmp_path / "uploads").mkdir()
    return dict(base=tmp_path, out=out, roots=[out, tmp_path / "uploads", tmp_path / "cast"])


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    base = tmp_path_factory.mktemp("assetapi")
    mp = pytest.MonkeyPatch()
    mp.setenv("CLONFIELD_FAKE_VRAM", "15")
    mp.setenv("CLONFIELD_COMFY_MODELS", str(base / "models"))
    cf_apps.configure(base, base / "outputs")
    client = TestClient(cf_api.build_app(base, base / "outputs", lambda t: t == "pw", "secret"), headers={"Authorization": "Bearer pw"})
    client.base = base
    yield client
    mp.undo()


def upload(api, data=None, name="foto.png"):
    return api.post(f"{BASE}/upload", files={"files": (name, data or png_bytes(), "image/png")}).json()[0]


def wait_job(api, job_id, seconds=60):
    for _ in range(int(seconds / 0.3)):
        job = api.get(f"{BASE}/jobs/{job_id}").json()
        if job["status"] in ("concluído", "falhou", "cancelado"):
            return job
        time.sleep(0.3)
    raise AssertionError("job não terminou")


def real_result(api):
    """A real finished job (Lanczos upscale of an upload) -> its first result dict."""
    up = upload(api, png_bytes((200, 50, 50)))
    job = wait_job(api, api.post(f"{BASE}/jobs", json={"app": "upscale", "params": {"image": [up["id"]], "mode": "Lanczos (rápido, sem IA)", "scale": 2}}).json()["id"])
    assert job["status"] == "concluído", job
    return job["results"][0]


class Spy:
    """Pass-through: remembers the files each real runner of `app_id` was handed, then calls the real runner."""
    def __init__(self, app_id):
        self.app, self.seen = cf_apps.registry()[app_id], []
        self.real = self.app.runner

    def __enter__(self):
        self.app.runner = lambda ctx, p, tier: (self.seen.append(list(p["image"])), self.real(ctx, p, tier))[1]
        return self

    def __exit__(self, *exc):
        self.app.runner = self.real


# ---- storage module

def test_publish_makes_a_read_only_blob_and_leaves_the_source_untouched(store):
    source = store["out"] / "resultado.png"
    source.write_bytes(png_bytes())
    before = sha(source)
    done = ag.publish(store["base"], source, store["roots"], title="Capa")
    version = done["version"]
    blob = ag.resolve(store["base"], version["version_id"])
    assert blob.parent == store["base"] / "assets" / "blobs" and blob.name == f"{before}.png"
    assert stat.S_IMODE(blob.stat().st_mode) == 0o444
    assert version["sha256"] == before == sha(blob) and ag.verify(store["base"], version["version_id"])
    assert sha(source) == before and source.exists()  # the origin is only read
    assert version["schema"] == "AssetRef.v1" and version["number"] == 1 and version["kind"] == "image"
    assert version["media"]["width"] == 160 and version["media"]["height"] == 120 and version["media"]["duration_s"] is None
    assert version["asset_id"].startswith("a_") and len(version["version_id"]) == 18
    assert done["asset"]["current"] == version["version_id"] and done["deduplicated"] is False


def test_verify_detects_a_changed_blob(store):
    source = store["out"] / "x.png"
    source.write_bytes(png_bytes())
    version = ag.publish(store["base"], source, store["roots"])["version"]
    blob = ag.resolve(store["base"], version["version_id"])
    os.chmod(blob, 0o644)
    blob.write_bytes(b"adulterado")
    assert ag.verify(store["base"], version["version_id"]) is False


def test_new_version_never_replaces_the_previous_one(store):
    first, second = store["out"] / "a.png", store["out"] / "b.png"
    first.write_bytes(png_bytes((10, 20, 30)))
    second.write_bytes(png_bytes((90, 80, 70)))
    one = ag.publish(store["base"], first, store["roots"], title="Rosto")
    two = ag.add_version(store["base"], one["asset"]["asset_id"], second, store["roots"], metadata=dict(note="retoque"))
    asset_id = one["asset"]["asset_id"]
    assert two["version"]["number"] == 2 and not two["deduplicated"]
    assert ag.get(store["base"], asset_id)["current"] == two["version"]["version_id"]
    assert [v["number"] for v in ag.versions(store["base"], asset_id)] == [1, 2]
    v1 = ag.resolve(store["base"], one["version"]["version_id"])
    assert sha(v1) == sha(first) and ag.verify(store["base"], one["version"]["version_id"])
    assert ag.resolve(store["base"], asset_id) == ag.resolve(store["base"], two["version"]["version_id"])  # a_ = current now
    assert two["version"]["parents"] == [dict(asset_id=asset_id, version_id=one["version"]["version_id"], role="previous")]
    assert two["version"]["metadata"]["note"] == "retoque"
    # the same bytes as the current version add nothing
    again = ag.add_version(store["base"], asset_id, second, store["roots"])
    assert again["deduplicated"] and len(ag.get(store["base"], asset_id)["versions"]) == 2


def test_publishing_the_same_file_twice_is_idempotent(store):
    source = store["out"] / "d.png"
    source.write_bytes(png_bytes())
    copy = store["out"] / "copia.png"
    copy.write_bytes(source.read_bytes())
    one = ag.publish(store["base"], source, store["roots"])
    two = ag.publish(store["base"], copy, store["roots"])
    assert two["deduplicated"] and two["version"]["version_id"] == one["version"]["version_id"]
    assert len(ag.list_assets(store["base"])) == 1 and len(list((store["base"] / "assets" / "blobs").iterdir())) == 1


def test_input_validation(store, tmp_path_factory):
    outside = tmp_path_factory.mktemp("fora") / "intruso.png"
    outside.write_bytes(png_bytes())
    with pytest.raises(ValueError, match="pastas"):
        ag.publish(store["base"], outside, store["roots"])
    odd = store["out"] / "nota.txt"
    odd.write_text("oi")
    with pytest.raises(ValueError, match="Formato"):
        ag.publish(store["base"], odd, store["roots"])
    empty = store["out"] / "vazio.png"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="vazio"):
        ag.publish(store["base"], empty, store["roots"])
    with pytest.raises(ag.NotFound):
        ag.add_version(store["base"], "a_" + "0" * 16, empty, store["roots"])
    assert ag.resolve(store["base"], "v_" + "0" * 16) is None and ag.resolve(store["base"], "../etc") is None


# ---- API

def test_api_rejects_foreign_sources_and_unknown_ids(api, tmp_path_factory):
    assert api.post(f"{BASE}/assets", json={"from": {"result": "../../etc/passwd"}}).status_code == 400
    assert api.post(f"{BASE}/assets", json={"from": {"result": "nao-existe.png"}}).status_code == 400
    assert api.post(f"{BASE}/assets", json={"from": {"upload": "0" * 32}}).status_code == 400
    assert api.post(f"{BASE}/assets", json={"from": {"path": "/etc/passwd"}}).status_code == 400
    assert api.post(f"{BASE}/assets", json={"from": {"cast": "nope"}}).status_code == 404
    assert api.get(f"{BASE}/assets/a_{'0' * 16}").status_code == 404
    assert api.get(f"{BASE}/assets/versions/v_{'0' * 16}").status_code == 404
    assert api.post(f"{BASE}/assets/a_{'0' * 16}/versions", json={"from": {"upload": upload(api)["id"]}}).status_code == 404
    assert api.get(f"{BASE}/assets").status_code == 200
    assert TestClient(api.app).post(f"{BASE}/assets", json={}).status_code == 401


def test_one_version_feeds_two_apps_without_copies(api):
    result = real_result(api)
    made = api.post(f"{BASE}/assets", json={"from": {"result": result["path"]}, "title": "Base"})
    assert made.status_code == 201, made.text
    body = made.json()
    version_id = body["version"]["version_id"]
    assert body["version"]["producer"]["kind"] == "job" and body["version"]["producer"]["app"] == "upscale"
    assert body["version"]["recipe"]["params"]["scale"] == 2
    blob = ag.resolve(api.base, version_id)
    assert api.get(body["url"]).content == blob.read_bytes()  # the signed url serves the blob
    uploads = api.base / "uploads"
    before = sorted(p.name for p in uploads.iterdir())
    with Spy("upscale") as up_spy, Spy("look") as look_spy:
        first = wait_job(api, api.post(f"{BASE}/jobs", json={"app": "upscale", "params": {"image": [{"id": version_id}], "mode": "Lanczos (rápido, sem IA)", "scale": 2}}).json()["id"])
        second = wait_job(api, api.post(f"{BASE}/jobs", json={"app": "look", "params": {"image": [version_id], "look": "Preto e branco", "strength": 100}}).json()["id"])
    assert first["status"] == "concluído" and second["status"] == "concluído", (first, second)
    assert sorted(p.name for p in uploads.iterdir()) == before  # no new folder in uploads/
    for spy in (up_spy, look_spy):
        (handed,) = spy.seen[0]
        assert Path(handed) == blob and os.path.samefile(handed, blob) and sha(handed) == body["version"]["sha256"]
    assert first["asset_versions"] == {version_id: version_id}
    assert second["asset_versions"] == {version_id: version_id}
    check = api.get(f"{BASE}/assets/versions/{version_id}").json()
    assert check["verified"] is True and check["sha256"] == body["version"]["sha256"]
    # same file again -> the same asset (idempotent), no new blob
    again = api.post(f"{BASE}/assets", json={"from": {"result": result["path"]}}).json()
    assert again["deduplicated"] and again["version"]["version_id"] == version_id


def test_asset_id_resolves_to_current_and_records_which_version(api):
    first = api.post(f"{BASE}/assets", json={"from": {"upload": upload(api, png_bytes((1, 2, 3)))["id"]}, "title": "Atual"}).json()
    asset_id = first["asset"]["asset_id"]
    second = api.post(f"{BASE}/assets/{asset_id}/versions", json={"from": {"upload": upload(api, png_bytes((9, 8, 7)))["id"]}, "note": "v2"})
    assert second.status_code == 201 and second.json()["version"]["number"] == 2
    detail = api.get(f"{BASE}/assets/{asset_id}").json()
    assert [v["number"] for v in detail["versions"]] == [1, 2] and detail["current"] == second.json()["version"]["version_id"]
    assert all(api.get(v["url"]).status_code == 200 for v in detail["versions"])  # v1 still downloadable
    job = wait_job(api, api.post(f"{BASE}/jobs", json={"app": "look", "params": {"image": [asset_id], "look": "Preto e branco", "strength": 100}}).json()["id"])
    assert job["status"] == "concluído"
    assert job["asset_versions"] == {asset_id: second.json()["version"]["version_id"]}
    listing = {a["asset_id"]: a for a in api.get(f"{BASE}/assets").json()}
    assert listing[asset_id]["current_version"]["number"] == 2 and listing[asset_id]["url"]


def test_get_uploads_hydrates_an_asset_version(api):
    made = api.post(f"{BASE}/assets", json={"from": {"upload": upload(api, png_bytes((5, 5, 5)))["id"]}, "title": "Hidratar"}).json()
    version_id = made["version"]["version_id"]
    info = api.get(f"{BASE}/uploads/{version_id}")
    assert info.status_code == 200
    data = info.json()
    assert data["id"] == version_id and data["name"] == "Hidratar" and data["kind"] == "image" and data["url"]
    assert api.get(data["url"]).status_code == 200
    assert api.get(f"{BASE}/uploads/v_{'1' * 16}").status_code == 404
    assert api.get(f"{BASE}/uploads/{upload(api)['id']}").status_code == 200  # plain uploads still hydrate


def test_dag_partial_cache_only_recomputes_the_branch_that_changed(api):
    a1 = api.post(f"{BASE}/assets", json={"from": {"upload": upload(api, png_bytes((120, 30, 30)))["id"]}, "title": "Ramo A"}).json()
    asset_id = a1["asset"]["asset_id"]
    v1 = a1["version"]["version_id"]
    v2 = api.post(f"{BASE}/assets/{asset_id}/versions", json={"from": {"upload": upload(api, png_bytes((30, 120, 30)))["id"]}}).json()["version"]["version_id"]
    other = upload(api, png_bytes((30, 30, 120)))["id"]

    def graph(a_media):
        return {"nodes": [
            {"id": "a_look", "cap": "look", "inputs": {"image": {"media": a_media}}, "params": {"look": "Preto e branco", "strength": 100}},
            {"id": "a_up", "cap": "upscale", "inputs": {"image": {"from": "a_look.image"}}, "params": {"scale": 2}},
            {"id": "b_look", "cap": "look", "inputs": {"image": {"media": other}}, "params": {"look": "Preto e branco", "strength": 100}},
            {"id": "b_up", "cap": "upscale", "inputs": {"image": {"from": "b_look.image"}}, "params": {"scale": 2}}]}

    def run(a_media):
        started = api.post(f"{BASE}/dag/run", json={"graph": graph(a_media)})
        assert started.status_code == 202, started.text
        job = wait_job(api, started.json()["id"])
        assert job["status"] == "concluído", job
        return api.get(f"{BASE}/dag/runs/{job['run']}").json()  # the provenance record: which nodes recomputed, which came from the cache

    first = run(v1)
    assert set(first["recomputed"]) == {"a_look", "a_up", "b_look", "b_up"} and first["cached"] == []
    second = run(v2)  # branch A now reads version 2
    assert set(second["recomputed"]) == {"a_look", "a_up"} and set(second["cached"]) == {"b_look", "b_up"}
    third = run(v1)  # back to version 1: everything is already in the cache
    assert third["recomputed"] == [] and set(third["cached"]) == {"a_look", "a_up", "b_look", "b_up"}
    assert api.post(f"{BASE}/dag/validate", json={"graph": graph("v_" + "0" * 16)}).json()["errors"][0]["code"] == "unresolved_media"


def test_cast_character_is_published_as_a_character_asset(api):
    picture = upload(api, png_bytes((200, 120, 80)))
    member = api.post(f"{BASE}/cast/create", json={"name": "Marina", "description": "ruiva, jaqueta jeans", "upload": picture["id"]}).json()
    made = api.post(f"{BASE}/assets", json={"from": {"cast": member["id"]}})
    assert made.status_code == 201, made.text
    body = made.json()
    version = body["version"]
    assert version["kind"] == "character" and version["metadata"]["name"] == "Marina" and version["metadata"]["description"] == "ruiva, jaqueta jeans"
    assert version["producer"]["kind"] == "cast" and body["asset"]["title"] == "Marina" and version["media"]["width"] > 0
    assert api.get(body["url"]).headers["content-type"] == "image/png"
    assert api.post(f"{BASE}/assets", json={"from": {"cast": member["id"]}}).json()["deduplicated"] is True
    job = wait_job(api, api.post(f"{BASE}/jobs", json={"app": "look", "params": {"image": [version["version_id"]], "look": "Preto e branco", "strength": 100}}).json()["id"])
    assert job["status"] == "concluído"  # a character version feeds an image app
    bare = api.post(f"{BASE}/cast/create", json={"name": "SemFoto", "description": "x"}).json()
    assert api.post(f"{BASE}/assets", json={"from": {"cast": bare["id"]}}).status_code == 400
