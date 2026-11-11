"""Kokoro-82M through kokoro-onnx (CPU, int8): the narration backend for Linux/Colab where MLX does not exist.
Added by ClonField (not upstream). Models: thewh1teagle/kokoro-onnx release model-files-v1.0, SHA-256 verified."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

LANGUAGES = {"en", "es", "fr", "it", "pt", "ja", "zh", "hi"}
BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = {
    "kokoro-v1.0.int8.onnx": "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
LANG_CODES = {"en": "en-us", "es": "es", "fr": "fr-fr", "it": "it", "pt": "pt-br", "ja": "ja", "zh": "cmn", "hi": "hi"}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def models_dir() -> Path:
    from factory.core.paths import MODELS
    return MODELS / "kokoro"


def ensure_models() -> Path:
    folder = models_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for name, digest in FILES.items():
        target = folder / name
        if target.exists() and _sha(target) == digest:
            continue
        part = target.with_suffix(target.suffix + ".part")
        urllib.request.urlretrieve(BASE + name, part)
        if _sha(part) != digest:
            part.unlink()
            raise SystemExit(f"kokoro: checksum of {name} did not match; download refused")
        part.replace(target)
    return folder


def load(voice: dict):
    import numpy as np
    import soundfile as sf
    from kokoro_onnx import Kokoro

    folder = ensure_models()
    engine = Kokoro(str(folder / "kokoro-v1.0.int8.onnx"), str(folder / "voices-v1.0.bin"))
    lang = LANG_CODES.get(voice.get("language", "en"), "en-us")

    def say(text: str, out: Path) -> None:
        samples, rate = engine.create(text, voice=voice["speaker"], speed=float(voice.get("speed", 1.0)), lang=lang)
        sf.write(str(out), np.asarray(samples, dtype="float32"), rate)

    return say
