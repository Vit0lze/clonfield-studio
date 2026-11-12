"""Cover/image stability: stable signed URLs, ETag, a persistent cover cache, remembered failures."""
import hashlib
import io
import json

import pytest
import requests
from PIL import Image
from starlette.testclient import TestClient

import cf_api
import cf_apps
import cf_civitai


def png_bytes():
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(out, "PNG")
    return out.getvalue()


@pytest.fixture()
def client(tmp_path):
    import cf_factory
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path
    return TestClient(cf_api.build_app(base, base / "outputs", lambda t: t == "pw", "secret"), headers={"Authorization": "Bearer pw"}), base


def test_signed_urls_are_stable_within_a_window(client):
    api, _ = client
    up = api.post("/clonfield/api/upload", files={"files": ("a.png", png_bytes(), "image/png")}).json()[0]
    first = api.get(f"/clonfield/api/uploads/{up['id']}").json()["url"]
    import time
    time.sleep(1.2)  # the old signer put time.time() in the URL, so a second later it differed
    second = api.get(f"/clonfield/api/uploads/{up['id']}").json()["url"]
    assert first == second
    assert api.get(first.replace("/clonfield/api", "/clonfield/api", 1)).status_code == 200  # and it still validates


def register(client_base):
    covers = [{"url": "https://image.civitai.com/x/y/original=true/a.png", "type": "image"}]
    return cf_civitai.register_cover(1, 11, covers)


def test_cover_downloaded_once_then_served_from_disk_even_after_restart(client, monkeypatch):
    api, base = client
    key = register(base)
    calls = []
    monkeypatch.setattr(cf_civitai, "fetch_cover_bytes", lambda session, url: (calls.append(url), (png_bytes(), "image/png"))[1])  # isolates the cache layer from the CDN
    url = api.app.state if False else None
    first = cf_civitai.read_catalog_cover(key)
    second = cf_civitai.read_catalog_cover(key)
    assert first == second and len(calls) == 1
    # "restart": in-memory registry and failure memory are gone, the disk cache is not
    with cf_civitai._cover_lock:
        cf_civitai._cover_sources.clear()
    third = cf_civitai.read_catalog_cover(key)
    assert third == first and len(calls) == 1
    assert (base / "cache" / "covers" / f"{key}.bin").is_file()


def test_registry_is_restored_after_restart_so_the_cover_does_not_404(client, monkeypatch):
    api, base = client
    key = register(base)
    with cf_civitai._cover_lock:
        cf_civitai._cover_sources.clear()
    monkeypatch.setattr(cf_civitai, "fetch_cover_bytes", lambda session, url: (png_bytes(), "image/png"))
    data, kind = cf_civitai.read_catalog_cover(key)
    assert kind == "image/png" and data.startswith(b"\x89PNG")


def test_a_403_is_remembered_instead_of_retried_on_every_repaint(client, monkeypatch):
    api, base = client
    covers = [{"url": "https://image.civitai.com/x/y/original=true/forbidden.png", "type": "image"}]
    key = cf_civitai.register_cover(2, 22, covers)
    calls = []

    def deny(session, url):
        calls.append(url)
        response = requests.Response(); response.status_code = 403
        raise requests.HTTPError("403", response=response)
    monkeypatch.setattr(cf_civitai, "fetch_cover_bytes", deny)
    monkeypatch.setattr(cf_civitai, "version_covers", lambda v: [])
    monkeypatch.setattr(cf_civitai, "gallery_covers", lambda m, v: [])
    for _ in range(3):
        with pytest.raises(OSError, match="403"):
            cf_civitai.read_catalog_cover(key)
    assert len(calls) == 1


def test_cover_endpoint_sends_etag_and_answers_304(client, monkeypatch):
    api, base = client
    key = register(base)
    monkeypatch.setattr(cf_civitai, "fetch_cover_bytes", lambda session, url: (png_bytes(), "image/png"))
    import cf_api as mod  # signed cover url through the real library path
    url = f"/clonfield/api/cover/{key}"
    # sign it the way the app does: ask the app for a LoRA card that carries the cover
    from pathlib import Path
    loras = Path(base) / "loras"
    loras.mkdir(parents=True, exist_ok=True)
    import numpy as np
    from safetensors.numpy import save_file
    save_file({"a": np.zeros((1,), dtype=np.float32)}, str(loras / "covered__cv11.safetensors"))
    (loras / "covered__cv11.json").write_text(json.dumps({"title": "Covered", "families": ["qwen21"], "model": 1, "version": 11,
                                                          "covers": [{"url": "https://image.civitai.com/x/y/original=true/a.png", "type": "image"}]}))
    try:
        item = next(i for i in api.get("/clonfield/api/loras?family=qwen21").json()["items"] if i["name"] == "covered__cv11.safetensors")
        signed = item["cover"]
        a = api.get(signed)
        assert a.status_code == 200 and a.headers["etag"] and "max-age=86400" in a.headers["cache-control"]
        b = api.get(signed, headers={"If-None-Match": a.headers["etag"]})
        assert b.status_code == 304 and b.content == b""
        # the same card asked twice carries the same url
        again = next(i for i in api.get("/clonfield/api/loras?family=qwen21").json()["items"] if i["name"] == "covered__cv11.safetensors")["cover"]
        assert again == signed
    finally:
        (loras / "covered__cv11.safetensors").unlink(missing_ok=True); (loras / "covered__cv11.json").unlink(missing_ok=True)
