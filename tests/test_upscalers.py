"""Upscaler catalogue: every entry is well-formed, and the small ones are downloaded, SHA-checked and run for real on CPU."""
import pytest
import requests
from PIL import Image

import cf_upscale as up

torch = pytest.importorskip("torch")
pytest.importorskip("spandrel")


def test_catalogue_entries_are_complete_and_pinned_when_hosted_on_hugging_face():
    assert len(up.MODELS) >= 8
    for name, spec in up.MODELS.items():
        assert {"file", "url", "sha256", "license", "use"} <= set(spec), name
        assert spec["url"].startswith("https://") and spec["file"]
        if "huggingface.co" in spec["url"]:
            assert spec["sha256"] and len(spec["sha256"]) == 64 and "/resolve/main/" not in spec["url"], name  # pinned revision


def online():
    try:
        return requests.head("https://huggingface.co", timeout=5).status_code < 500
    except requests.RequestException:
        return False


@pytest.mark.skipif(not online(), reason="offline")
@pytest.mark.parametrize("name,scale", [("OmniSR x2 (ultraleve)", 2), ("OmniSR x4 (ultraleve)", 4), ("Real-ESRGAN geral v3 (leve)", 4)])
def test_small_upscalers_download_verify_and_upscale_a_real_image_on_cpu(tmp_path, name, scale):
    image = Image.effect_noise((48, 32), 40).convert("RGB")
    out = up.process(image, name, scale, 64, 8, "cpu", 0, tmp_path)
    assert out.size == (48 * scale, 32 * scale)
    weight = tmp_path / "upscalers" / up.MODELS[name]["file"]
    assert weight.is_file()
    if up.MODELS[name]["sha256"]:
        assert up.sha256_of(weight) == up.MODELS[name]["sha256"]


def test_a_corrupted_download_is_refused_and_deleted(tmp_path, monkeypatch):
    spec = up.MODELS["OmniSR x2 (ultraleve)"]
    target = tmp_path / "upscalers" / spec["file"]

    def fake_fetch(url, dest, progress=None, label=None, **kw):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"not a model")

    monkeypatch.setattr(up.download, "fetch", fake_fetch)
    with pytest.raises(ValueError, match="SHA-256"):
        up.load("OmniSR x2 (ultraleve)", tmp_path)
    assert not target.exists()
