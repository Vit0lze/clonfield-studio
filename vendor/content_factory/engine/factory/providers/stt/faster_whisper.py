"""faster-whisper with word timestamps on CPU (int8). Added by ClonField (not upstream)."""

from __future__ import annotations

from functools import cache
from pathlib import Path


@cache
def _model(name: str):
    from faster_whisper import WhisperModel
    return WhisperModel(name, device="cpu", compute_type="int8")


def words(wav: Path, language: str, model: str) -> list[dict]:
    segments, _info = _model(model).transcribe(str(wav), language=language, word_timestamps=True,
                                               condition_on_previous_text=False)
    return [{"word": w.word, "start": float(w.start), "end": float(w.end)} for seg in segments for w in (seg.words or [])]
