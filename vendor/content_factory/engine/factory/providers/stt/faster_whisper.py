"""faster-whisper with word timestamps on CPU (int8). Added by ClonField (not upstream)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

RATE = 16000


@cache
def _model(name: str):
    from faster_whisper import WhisperModel
    return WhisperModel(name, device="cpu", compute_type="int8")


def load_audio(wav: Path):
    """The narration as mono float32 at 16 kHz. faster-whisper's own file decoder goes through PyAV with `metadata_errors=`, which the PyAV
    that Colab ships does not accept ("open() got an unexpected keyword argument 'metadata_errors'"); handing it the samples skips PyAV."""
    import numpy as np
    try:
        import soundfile
        data, rate = soundfile.read(str(wav), dtype="float32", always_2d=True)
    except ImportError:
        import wave
        with wave.open(str(wav), "rb") as handle:
            if handle.getsampwidth() != 2:
                raise ValueError("Sem soundfile, só entendo WAV de 16 bits.")
            rate, channels = handle.getframerate(), handle.getnchannels()
            data = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype("float32").reshape(-1, channels) / 32768.0
    mono = data.mean(axis=1).astype("float32")
    if rate != RATE:
        try:
            from math import gcd
            from scipy.signal import resample_poly
            divisor = gcd(RATE, int(rate))
            mono = resample_poly(mono, RATE // divisor, int(rate) // divisor).astype("float32")
        except ImportError:
            count = max(1, round(len(mono) * RATE / rate))
            mono = np.interp(np.linspace(0, len(mono) - 1, count), np.arange(len(mono)), mono).astype("float32")
    return mono


def words(wav: Path, language: str, model: str) -> list[dict]:
    segments, _info = _model(model).transcribe(load_audio(wav), language=language, word_timestamps=True,
                                               condition_on_previous_text=False)
    return [{"word": w.word, "start": float(w.start), "end": float(w.end)} for seg in segments for w in (seg.words or [])]
