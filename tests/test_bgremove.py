"""Remover fundo with the REAL U^2-Net ONNX models on the CPU (downloaded once into the test cache, SHA-256 checked); skipped without network and onnxruntime."""

import hashlib
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

import cf_apps
import cf_bgremove as bg
import cf_jobs
import cf_tiers

pytest.importorskip("onnxruntime")
CACHE = Path(os.environ.get("CLONFIELD_BG_CACHE", Path.home() / ".cache" / "clonfield-bg-test"))


@pytest.fixture(scope="module")
def models():
    try:
        return {key: bg.ensure(CACHE, key) for key in bg.MODELS}
    except Exception as exc:  # no network, no space: a skip with the reason, never a silent pass
        pytest.skip(f"modelos de recorte indisponíveis: {exc}")


def subject(size=(320, 320)):
    """A bright, high-contrast subject on a dark gradient background."""
    image = Image.new("RGB", size, (20, 30, 50))
    draw = ImageDraw.Draw(image)
    for y in range(size[1]):
        draw.line([(0, y), (size[0], y)], fill=(20 + y // 8, 30 + y // 10, 50 + y // 6))
    draw.ellipse((size[0] * .3, size[1] * .15, size[0] * .7, size[1] * .55), fill=(235, 190, 150))  # a head
    draw.rounded_rectangle((size[0] * .2, size[1] * .5, size[0] * .8, size[1] * .98), 30, fill=(200, 40, 40))  # a torso
    return image


def test_pins_match_the_hugging_face_listing():
    import requests
    for key, spec in bg.MODELS.items():
        try:
            tree = requests.get(f"https://huggingface.co/api/models/{spec['repo']}/tree/{spec['revision']}/onnx", timeout=20).json()
        except requests.RequestException as exc:
            pytest.skip(f"sem rede: {exc}")
        entry = next(e for e in tree if e["path"] == spec["file"])
        assert (entry["size"], entry["lfs"]["oid"]) == (spec["size"], spec["sha256"]), key


def test_a_file_that_does_not_match_the_pin_is_removed_and_refused(tmp_path):
    path = bg.model_path(tmp_path, "u2netp")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * bg.MODELS["u2netp"]["size"])  # right size, wrong content
    with pytest.raises(ValueError, match="não confere"):
        bg.ensure(tmp_path, "u2netp")
    assert not path.exists()
    with pytest.raises(ValueError, match="lista"):
        bg.ensure(tmp_path, "outro")


@pytest.mark.parametrize("key", list(bg.MODELS))
def test_the_subject_stays_and_the_background_goes(models, key):
    out = bg.remove(subject(), models[key])
    alpha = np.asarray(out.getchannel("A")) / 255
    assert out.mode == "RGBA" and out.size == (320, 320)
    assert alpha[100, 160] > 0.9 and alpha[260, 160] > 0.9  # the head and the torso are kept
    assert max(alpha[3, 3], alpha[3, -4], alpha[160, 3], alpha[160, -4]) < 0.2  # the corners are background


def test_flat_background_crop_and_hard_edge(models):
    path = models["u2net"]
    photo = subject()
    flat = bg.remove(photo, path, background=(0, 177, 64))
    assert flat.mode == "RGB" and flat.getpixel((3, 3)) == (0, 177, 64) and flat.getpixel((160, 100)) != (0, 177, 64)
    cropped = bg.remove(photo, path, crop=True)
    assert cropped.width < 320 and cropped.height <= 320 and cropped.width > 120  # trimmed around the subject, with a margin
    hard = np.asarray(bg.remove(photo, path, cutoff=100).getchannel("A"))
    assert set(np.unique(hard)) <= {0, 255}


def test_exif_rotation_is_respected(models, tmp_path):
    image = subject((320, 480))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees on display
    image.save(tmp_path / "r.jpg", exif=exif)
    out = bg.remove(Image.open(tmp_path / "r.jpg"), models["u2netp"])
    assert out.size == (480, 320)


def test_the_app_writes_a_transparent_png_and_refuses_a_bad_background(models, tmp_path, monkeypatch):
    import cf_factory
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path
    cf_apps.configure(base, base / "outputs")
    for key, path in models.items():  # reuse the cached models instead of downloading again into the app's folder
        target = bg.model_path(base, key)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(path)
    source = tmp_path / "s.png"
    subject().save(source)

    class Ctx:
        out_dir = tmp_path / "o"
        class job: id = "j"
        def progress(self, *a, **k): pass
        def check(self): pass
    Ctx.out_dir.mkdir()
    out = cf_apps.run_removebg(Ctx(), dict(image=[str(source)], model="u2netp"), cf_tiers.detect())
    assert Image.open(out[0]).mode == "RGBA" and out[0].name.startswith("sem-fundo")
    green = cf_apps.run_removebg(Ctx(), dict(image=[str(source)], model="u2netp", background="Verde (chroma)", crop=True), cf_tiers.detect())
    assert Image.open(green[0]).mode == "RGB"
    with pytest.raises(cf_jobs.JobError, match="fundo"):
        cf_apps.run_removebg(Ctx(), dict(image=[str(source)], background="Arco-íris"), cf_tiers.detect())
    app = cf_apps.registry()["removebg"].describe(cf_tiers.detect())
    assert app["lane"] == "cpu" and not app["blocked"] and app["group"] == "Melhorar"
