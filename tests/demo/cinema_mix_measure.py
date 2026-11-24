"""Measure what a cut's mix does to each sound, before loudness (the second loudnorm pass is linear: it moves every sound by
the same gain, so the differences below are what the delivered film has).

python tests/demo/cinema_mix_measure.py <base> <project_id> <cut> [<cut> ...] [--relay 9.25] [--json out.json]

For each cut it renders, with the engine's own builders, every sound alone (voice, music, each effect clip), applies the cut's
mix (track gains, and the music ducked by the voice with the cut's sidechain settings) and reports:
- the music level (RMS, dBFS) in windows before, under and after the spoken line: how far it steps back and when it returns;
- the relay window: the effect that starts at --relay against everything else playing then (broadband and 1-6 kHz)."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import cf_cinema  # noqa: E402

RATE = 48000


def decode(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def stem(timeline, track, clips, sources, total, out):
    one = dict(timeline, audio={track: clips})
    cf_cinema._run(cf_cinema._stem_args(one, track, sources, total, out))
    return out


def ducked_music(voice, music, mix, out):
    graph = [f"[0:a]volume={mix['voice']}dB[key]", f"[1:a]volume={mix['music']}dB[m0]"]
    if mix["duck"]:
        graph.append(f"[m0][key]sidechaincompress=threshold={mix['duck_threshold']:g}:ratio={mix['duck_ratio']:g}"
                     f":attack={mix['duck_attack']:g}:release={mix['duck_release']:g}[m]")
    else:
        graph.append("[key]anullsink;[m0]anull[m]")
    cf_cinema._run(["-i", voice, "-i", music, "-filter_complex", ";".join(graph), "-map", "[m]", "-c:a", "pcm_f32le", "-ar", RATE, "-f", "wav", out])
    return out


def rms_db(x):
    value = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    return round(20 * np.log10(value), 1) if value > 1e-9 else None


def band(x, low=1000, high=6000):
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / RATE)
    spectrum[(freqs < low) | (freqs > high)] = 0
    return np.fft.irfft(spectrum, len(x))


def window(x, a, b):
    return x[int(a * RATE):int(b * RATE)]


def measure(base, project, cut_id, relay_at):
    timeline = cf_cinema.compose(project, cut_id)
    sources = cf_cinema.validate(timeline, base)
    total = cf_cinema.duration(timeline)
    mix = cf_cinema.mix_values(timeline.get("mix"))
    voice_clips = timeline["audio"].get("voice", [])
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        voice = stem(timeline, "voice", voice_clips, sources, total, tmp / "voice.wav")
        music = stem(timeline, "music", timeline["audio"].get("music", []), sources, total, tmp / "music.wav")
        sounds = {"voz": decode(voice) * 10 ** (mix["voice"] / 20), "música": decode(ducked_music(voice, music, mix, tmp / "ducked.wav"))}
        undocked = decode(music) * 10 ** (mix["music"] / 20)
        for i, clip in enumerate(timeline["audio"].get("sfx", [])):
            name = "relé" if abs(float(clip.get("at", 0)) - relay_at) < 0.05 else f"efeito {i + 1}"
            sounds[name] = decode(stem(timeline, "sfx", [clip], sources, total, tmp / f"sfx{i}.wav")) * 10 ** (mix["sfx"] / 20)
    n = min(len(s) for s in sounds.values())
    sounds = {k: v[:n] for k, v in sounds.items()}
    line = voice_clips[0] if voice_clips else None
    report = dict(cut=cut_id, label=project["cuts"][cut_id].get("label"), mix=mix)
    if line:
        start = float(line["at"])
        speech = np.abs(window(sounds["voz"], start, total)) > 0.01
        end = start + (np.nonzero(speech)[0][-1] / RATE if speech.any() else 0)
        report["fala"] = [round(start, 2), round(end, 2)]
        m = sounds["música"]
        report["música_dbfs"] = {
            "antes da fala (4,5-6,0 s)": rms_db(window(m, 4.5, 6.0)),
            "sob a fala": rms_db(window(m, start + 0.5, end - 0.2)),
            "sem recuo, sob a fala": rms_db(window(undocked, start + 0.5, end - 0.2)),
            "0,5 s depois da fala": rms_db(window(m, end, end + 0.5)),
        }
        steps = [(round(t, 2), rms_db(window(m, t, t + 0.25))) for t in np.arange(start - 1.0, min(end + 2.0, total - 0.25), 0.25)]
        report["música_envelope"] = steps
        before, under = report["música_dbfs"]["antes da fala (4,5-6,0 s)"], report["música_dbfs"]["sob a fala"]
        if before is not None and under is not None:
            report["recuo_db"] = round(before - under, 1)
    if "relé" in sounds:
        a, b = relay_at, relay_at + 0.5
        relay = window(sounds["relé"], a, b)
        others = sum(window(v, a, b) for k, v in sounds.items() if k != "relé")
        report["relé"] = {
            "relé dBFS": rms_db(relay), "resto dBFS": rms_db(others),
            "relé sobre o resto (dB)": None if rms_db(others) is None else round(rms_db(relay) - rms_db(others), 1),
            "1-6 kHz: relé sobre o resto (dB)": round(rms_db(band(relay)) - rms_db(band(others)), 1),
            "música na janela dBFS": rms_db(window(sounds["música"], a, b)),
            "mar na janela dBFS": next((rms_db(window(v, a, b)) for k, v in sounds.items() if k.startswith("efeito")), None),
        }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base", type=Path)
    parser.add_argument("project")
    parser.add_argument("cuts", nargs="+")
    parser.add_argument("--relay", type=float, default=9.25)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    project = cf_cinema.load_project(args.base, args.project)
    reports = [measure(args.base, project, cut, args.relay) for cut in args.cuts]
    for r in reports:
        print(json.dumps({k: v for k, v in r.items() if k != "música_envelope"}, ensure_ascii=False))
        print("  envelope:", " ".join(f"{t:g}:{v}" for t, v in r.get("música_envelope", [])))
    if args.json:
        args.json.write_text(json.dumps(reports, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
