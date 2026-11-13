"""Face swap with the REAL FaceFusion 3.9.2 on CPU. The command builder and every option are checked against the program's own --help; one real
image swap runs when FaceFusion is installed (CLONFIELD_FACEFUSION_DIR or ~/.cache/clonfield-facefusion) and proves the face region, and only it, changed.
Not covered (no way to test here): video, GPU providers, the other swapper models, two different people."""
import os
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import cf_apps
import cf_faceswap as ff
import cf_jobs
import cf_tiers

ROOT = Path(os.environ.get("CLONFIELD_FACEFUSION_DIR") or Path.home() / ".cache" / "clonfield-facefusion")
needs_ff = pytest.mark.skipif(not ff.installed(ROOT), reason="FaceFusion não instalado (rode prepare_facefusion.py)")


def help_text():
    out = subprocess.run([str(ff.python_of(ROOT)), str(ROOT / "src" / "facefusion.py"), "headless-run", "--help"], capture_output=True, text=True, timeout=120, cwd=str(ROOT / "src")).stdout
    return re.sub(r"\s+", " ", out)


@needs_ff
def test_every_choice_we_offer_exists_in_the_real_programs_help():
    text = help_text()
    for flag, choices in (("face-swapper-model", ff.SWAPPERS), ("face-enhancer-model", ff.ENHANCERS), ("face-selector-mode", ff.SELECTOR_MODES)):
        listed = set(re.search(rf"--{flag} \{{([^}}]*)\}}", text).group(1).split(","))
        assert set(choices) <= listed, (flag, set(choices) - listed)
    assert set(ff.ORDERS) <= set(re.search(r"--face-selector-order \{([^}]*)\}", text).group(1).split(","))
    for flag in ("--processors", "--face-swapper-pixel-boost", "--execution-providers", "--temp-path", "--jobs-path", "--source-paths", "--target-path", "--output-path"):
        assert flag in text


def test_command_is_built_from_validated_options(tmp_path):
    args = ff.command(tmp_path, ["a.png", "b.png"], "t.mp4", "o.mp4", swapper="hyperswap_1c_256", enhancer="gfpgan_1.4", mode="many", providers=("cpu",))
    assert args[2] == "headless-run" and args[args.index("--processors") + 1:args.index("--processors") + 3] == ["face_swapper", "face_enhancer"]
    assert "a.png" in args and "b.png" in args and args[args.index("--face-swapper-model") + 1] == "hyperswap_1c_256" and "gfpgan_1.4" in args
    for bad in (dict(swapper="x"), dict(enhancer="x"), dict(mode="x"), dict(order="x"), dict(pixel_boost="1x1"), dict(providers=("quantum",))):
        with pytest.raises(ValueError):
            ff.command(tmp_path, ["a.png"], "t.png", "o.png", **bad)
    with pytest.raises(ValueError, match="origem"):
        ff.command(tmp_path, [], "t.png", "o.png")


def test_target_kind_and_missing_install_are_reported_with_a_reason(tmp_path):
    assert ff.kind_of("a.MP4") == "video" and ff.kind_of("a.jpg") == "image"
    with pytest.raises(ValueError, match="imagem"):
        ff.kind_of("a.pdf")
    with pytest.raises(ValueError, match="não está instalado"):
        ff.run(tmp_path / "nada", ["a.png"], "t.png", tmp_path / "o.png")


def test_app_refuses_without_the_consent_confirmation_and_is_registered_as_medium_risk(monkeypatch, tmp_path):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    tier = cf_tiers.detect()
    app = cf_apps.registry()["faceswap"]
    fields = {f["id"]: f for f in app.fields(tier)}
    assert fields["consent"]["required"] is True and fields["consent"]["default"] is False

    class Ctx:
        out_dir = tmp_path
        def progress(self, *a, **k): pass
        def check(self): pass
    with pytest.raises(cf_jobs.JobError, match="autorizaram"):
        cf_apps.run_faceswap(Ctx(), dict(source=["a.png"], target=["t.png"], consent=False), tier)
    import cf_capabilities as caps
    assert caps.Registry(cf_apps.registry(), tier).get("app.faceswap").risk == "medium"


@needs_ff
def test_real_image_swap_changes_only_the_face_region(tmp_path):
    skimage = pytest.importorskip("skimage")
    from skimage import data
    source = tmp_path / "source.png"
    target = tmp_path / "target.png"
    Image.fromarray(data.astronaut()).save(source)  # public-domain NASA portrait bundled with scikit-image
    Image.fromarray(data.astronaut()).save(target)
    out = ff.run(ROOT, [str(source)], str(target), tmp_path / "out.png", swapper="inswapper_128", mode="one", providers=("cpu",))
    a, b = np.asarray(Image.open(target).convert("RGB")).astype(int), np.asarray(Image.open(out).convert("RGB")).astype(int)
    assert a.shape == b.shape
    changed = np.abs(a - b).sum(2) > 0
    ys, xs = np.nonzero(changed)
    assert len(ys) > 5000, "a troca não mudou o rosto"
    assert xs.min() > 100 and xs.max() < 350 and ys.min() > 10 and ys.max() < 220  # only around the face (the astronaut's head), the rest is untouched
    assert not changed[300:, :].any() and not changed[:, :100].any()
    blank = tmp_path / "blank.png"
    Image.new("RGB", (256, 256), (30, 30, 30)).save(blank)
    with pytest.raises(ValueError, match="Nenhum rosto foi trocado"):  # a target with no face: FaceFusion copies silently, the Studio says so
        ff.run(ROOT, [str(source)], str(blank), tmp_path / "out2.png")
    with pytest.raises(ValueError, match="foto de origem"):  # a source with no face
        ff.run(ROOT, [str(blank)], str(target), tmp_path / "out3.png")
