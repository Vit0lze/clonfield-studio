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
    # The engine reads its paths once per process; another test module may have configured it first, so reuse that folder.
    if factory._state["data"] is None:
        factory.configure(tmp_path_factory.mktemp("cfbase"))
    return factory.data().parent


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
                    reason="slow (minutes, ~3 GB RAM, downloads Kokoro 120 MB + Whisper base): set CLONFIELD_SLOW=1")
def test_real_narrated_render_of_a_drawn_episode(configured):
    pytest.importorskip("kokoro_onnx")
    pytest.importorskip("faster_whisper")
    script = factory.example_script()
    script["voice"] = True
    slug = factory.create(script, "Render real")
    lines = []
    result = factory.run(slug, lambda fraction=None, desc=None: lines.append(desc))
    assert result["video"] and result["video"].stat().st_size > 100_000
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_type", "-of", "default=nw=1",
                            str(result["video"])], capture_output=True, text=True).stdout
    assert "width=1080" in probe and "height=1920" in probe and "codec_type=audio" in probe
    assert result["qa"]["ok"] is True  # no 'no-audio' error: the narration made it into the file


def test_the_stt_provider_hands_faster_whisper_samples_instead_of_a_file_so_pyav_is_never_called(tmp_path, monkeypatch):
    """Colab's PyAV rejects `metadata_errors=`, which faster-whisper passes when it decodes a file path itself."""
    import sys, types, wave
    from pathlib import Path
    import numpy as np
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "content_factory" / "engine"))
    from factory.providers.stt import faster_whisper as stt
    wav = tmp_path / "vo.wav"
    tone = (np.sin(np.linspace(0, 440 * 2 * np.pi, 24000)) * 12000).astype("<i2")  # 1 s at 24 kHz, like Kokoro's output
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(24000); handle.writeframes(tone.tobytes())
    seen = {}

    class Word:
        word, start, end = " oi", 0.0, 0.4

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            seen["audio"], seen["kwargs"] = audio, kwargs
            return [types.SimpleNamespace(words=[Word()])], None

    monkeypatch.setitem(sys.modules, "soundfile", None)  # force the stdlib reader as well
    monkeypatch.setattr(stt, "_model", lambda name: FakeModel())
    result = stt.words(wav, "pt", "tiny")
    assert isinstance(seen["audio"], np.ndarray) and seen["audio"].dtype == np.float32
    assert abs(len(seen["audio"]) - 16000) <= 2 and float(np.abs(seen["audio"]).max()) > 0.2
    assert result == [{"word": " oi", "start": 0.0, "end": 0.4}] and seen["kwargs"]["word_timestamps"] is True
