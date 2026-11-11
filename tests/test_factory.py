"""Content Factory adapter with the real vendored engine (no stubs). The full render test needs node + ffmpeg and takes
minutes: set CLONFIELD_SLOW=1 to run it."""
import copy
import os
import shutil
import subprocess

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("yaml")
import cf_factory as factory  # noqa: E402


@pytest.fixture(scope="module")
def configured(tmp_path_factory):
    base = tmp_path_factory.mktemp("cfbase")
    factory.configure(base)
    return base


def test_formats_and_example_script_load_from_the_vendored_snapshot(configured):
    found = {f["id"]: f for f in factory.formats()}
    assert "what-if" in found and "drawn" in found["what-if"]["modes"]
    script = factory.example_script()
    assert script["render_mode"] == "drawn" and len(script["beats"]) >= 5


def test_create_validates_schema_and_accepts_the_example(configured):
    script = factory.example_script()
    slug = factory.create(copy.deepcopy(script), "Teste do Sol")
    assert slug == "teste-do-sol"
    broken = copy.deepcopy(script)
    del broken["beats"]
    with pytest.raises(ValueError, match="inválido"):
        factory.create(broken)


def test_status_reports_planned_stages_without_running_anything(configured):
    script = factory.example_script()
    slug = factory.create(copy.deepcopy(script), "Status")
    info = factory.status(slug)
    assert info["stages"] == ["tts", "align", "render", "qa"] if script.get("voice") else info["stages"] == ["render", "qa"]
    assert info["video"] is None and info["qa"] is None


@pytest.mark.skipif(not (os.environ.get("CLONFIELD_SLOW") and shutil.which("node") and shutil.which("ffmpeg")),
                    reason="slow: set CLONFIELD_SLOW=1 with node and ffmpeg installed")
def test_real_render_of_a_silent_drawn_episode(configured):
    script = factory.example_script()
    script["voice"] = False
    for beat in script["beats"]:
        beat.pop("vo", None)
    slug = factory.create(script, "Render real")
    lines = []
    result = factory.run(slug, lambda fraction=None, desc=None: lines.append(desc))
    assert result["video"] and result["video"].stat().st_size > 100_000
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_type:format=duration",
                            "-of", "default=nw=1", str(result["video"])], capture_output=True, text=True).stdout
    assert "width=1080" in probe and "height=1920" in probe
    assert result["qa"] is not None and any("render" in (line or "") for line in lines)
