"""Narration for the Cinema alfa short through the Studio's own CPU voice path: the vendored Content Factory provider
providers/tts/kokoro_onnx.py (Kokoro-82M int8, Apache-2.0 weights, SHA-256 pinned downloads), pt-BR. One WAV per line.
Usage: python tests/demo/cinema_voice.py <out_dir> [voice]"""
import json
import os
import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import cf_factory  # noqa: E402

LINES = {
    "v1": "Meu pai acendia o farol todo fim de tarde.",
    "v2": "Ele dizia que a luz não era para quem chega. Era para quem ainda está no mar.",
    "v3": "Eu achava que era só uma lâmpada, girando.",
    "v4": "Hoje a cidade acende sozinha. Ninguém mais sobe a escada.",
    "v5": "Mas toda tarde, eu ainda olho para o mar.",
}

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
cf_factory.configure(os.environ.get("CLONFIELD_DIR", str(out.parent)))
from factory.providers.tts import kokoro_onnx  # noqa: E402

voice = dict(speaker=sys.argv[2] if len(sys.argv) > 2 else "pf_dora", language="pt", speed=0.92)
t0 = time.monotonic()
say = kokoro_onnx.load(voice)
log = dict(voice=voice, load_s=round(time.monotonic() - t0, 1), lines={})
for name, text in LINES.items():
    t = time.monotonic()
    say(text, out / f"{name}.wav")
    log["lines"][name] = dict(text=text, seconds=round(time.monotonic() - t, 1))
log["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
print(json.dumps(log, ensure_ascii=False, indent=1))
