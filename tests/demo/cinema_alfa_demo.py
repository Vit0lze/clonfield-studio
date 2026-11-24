"""Cinema alfa, end to end on CPU: «A última luz», 60 s.

1. publish  — the real Studio takes (Wan 2.2 5B / A14B outputs downloaded from the Colab T4 validation runs, tests/gpu/out*),
              the Kokoro narration (tests/demo/cinema_voice.py) and the FFmpeg-synthesized music/effects
              (tests/demo/cinema_sound.py) become AssetRef.v1 versions; take «Lembrança» gets a second version (v2).
2. cut      — render the timeline in a child process and KILL it (SIGKILL) once 3 segments are stamped: a crash, not a cancel.
3. resume   — render again: the finished segments are reused, the rest is rendered.
4. swap     — shot s04 moves from «Lembrança» v1 to v2 and re-renders; every other segment keeps its bytes.

Usage: python tests/demo/cinema_alfa_demo.py <work_dir>   (expects <work_dir>/voice and <work_dir>/sound)"""
import json
import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import cf_asset_graph  # noqa: E402

WORK = Path(sys.argv[1]).resolve()
BASE = WORK / "data"
GPU = ROOT / "tests" / "gpu"
ROOTS = [GPU, WORK]
PY = sys.executable

# take -> (file, title, what the Studio run was)
TAKES = {
    "farol_pier": ("out3/agent_chain/00-result.mp4", "Farol no píer ao pôr do sol", "agente local → Wan 2.2 5B (T4)"),
    "farol_feixe": ("a14b-q4-loop.mp4", "Farol, feixe girando (loop)", "Wan 2.2 A14B Q4 · primeiro/último quadro iguais (T4)"),
    "farol_azul": ("out14/recipe_loop/00-video.mp4", "Farol no azul, luz acendendo (loop)", "receita Loop → Wan 2.2 A14B (T4)"),
    "poste": ("out-agent/agent_job/00-result.mp4", "Poste acendendo ao entardecer", "agente local → Wan 2.2 5B (T4)"),
    "maos": ("out-cmp/5b-q6/00-81bea9ba2eb44114.mp4", "Jaqueta verde, mãos", "Wan 2.2 5B Q6 (T4)"),
    "lembranca_v1": ("out-cmp3/5b-q6-vertical/00-aeee381d504f8e0b.mp4", "Lembrança (retrato)", "Wan 2.2 5B Q6 vertical (T4)"),
    "lembranca_v2": ("out-cmp5/a14b-q4-fast/00-fc03abfba03b420d.mp4", None, "Wan 2.2 A14B Q4 LightX2V 4 passos (T4)"),
}
SOUNDS = {
    "v1": ("voice/v1.wav", "Voz 1"), "v2": ("voice/v2.wav", "Voz 2"), "v3": ("voice/v3.wav", "Voz 3"),
    "v4": ("voice/v4.wav", "Voz 4"), "v5": ("voice/v5.wav", "Voz 5"),
    "music": ("sound/music-pad.wav", "Música · pad em ré menor (sintetizada)"), "sea": ("sound/sea.wav", "Mar (sintetizado)"),
    "foghorn": ("sound/foghorn.wav", "Buzina de nevoeiro (sintetizada)"), "lamp": ("sound/lamp.wav", "Relé e zumbido do poste (sintetizado)"),
}


def publish():
    ids, assets = {}, {}
    for name, (rel, title, how) in TAKES.items():
        source = GPU / rel
        if name == "lembranca_v2":
            done = cf_asset_graph.add_version(BASE, assets["lembranca_v1"], source, ROOTS, producer=dict(kind="import", note=how),
                                              metadata=dict(note="segunda tomada: " + how))
        else:
            done = cf_asset_graph.publish(BASE, source, ROOTS, kind="video", title=title, producer=dict(kind="import", note=how),
                                          metadata=dict(title=title, note=how))
            assets[name] = done["asset"]["asset_id"]
        ids[name] = done["version"]["version_id"]
    for name, (rel, title) in SOUNDS.items():
        note = "Kokoro-82M int8 pt-BR (pf_dora) pelo provider do Studio" if name.startswith("v") else "FFmpeg, sintetizado"
        done = cf_asset_graph.publish(BASE, WORK / rel, ROOTS, kind="audio", title=title, producer=dict(kind="import", note=note),
                                      metadata=dict(title=title, note=note))
        ids[name] = done["version"]["version_id"]
    return ids, assets


def timeline(ids, memory):
    """The cut. Times in seconds. The film: a daughter remembers the lighthouse her father lit; the town now lights itself."""
    shots = [
        dict(id="s01", src={"color": "black"}, dur=3.0, note="escuro: só o mar"),
        dict(id="s02", src=ids["farol_pier"], dur=6.0, speed=0.5, look="dusk", push=0.04, fade_in=1.5),
        dict(id="s03", src=ids["farol_feixe"], dur=7.0, loop=True, look="dusk"),
        dict(id="s04", src=memory, dur=5.0, speed=0.6, pingpong=True, crop=[0, 0.02, 1, 0.3245], look="memory", fade_in=0.4,
             note="lembrança: rosto"),
        dict(id="s05", src=ids["maos"], dur=4.0, speed=0.5, look="memory", crop=[0.1, 0.25, 0.8, 0.75]),
        dict(id="s06", src=ids["poste"], dur=6.0, speed=0.5, look="dusk"),
        dict(id="s07", src=ids["farol_azul"], dur=12.0, loop=True, push=0.10, note="seguro: sem música, sem voz"),
        dict(id="s08", src=ids["farol_feixe"], dur=9.0, loop=True, look="dusk", fade_out=3.0),
        dict(id="s09", src={"color": "black"}, dur=8.0, note="escuro: a buzina"),
    ]
    return {
        "schema": "Timeline.v1", "name": "a-ultima-luz", "title": "A última luz", "fps": 24, "size": [1280, 720], "video": shots,
        "audio": {
            "voice": [dict(src=ids["v1"], at=4.0), dict(src=ids["v2"], at=10.0), dict(src=ids["v3"], at=17.0),
                      dict(src=ids["v4"], at=26.5), dict(src=ids["v5"], at=45.5)],
            "music": [dict(src=ids["music"], at=3.0, dur=29.0, gain_db=6, fade_in=3.0, fade_out=6.0)],
            # the sea stays under the music; when the music leaves (32 s) the sea comes forward and fills the held shot
            "sfx": [dict(src=ids["sea"], at=0.0, dur=33.0, gain_db=-13, fade_in=2.5, fade_out=3.0),
                    dict(src=ids["sea"], at=30.0, **{"in": 30.0}, dur=30.0, gain_db=-4, fade_in=3.0, fade_out=6.0),
                    dict(src=ids["lamp"], at=25.4, dur=5.0, gain_db=-6),
                    dict(src=ids["foghorn"], at=53.5, dur=6.0, gain_db=-9)],
        },
        "mix": {"voice": 0, "music": -3, "sfx": -3, "duck": True},
    }


def render(path, out, kill_after=None):
    """Render in a child process; with kill_after, SIGKILL it once that many segment stamps exist (a crash mid-render)."""
    segs = BASE / "cinema" / "cache" / "segments"
    before = set(segs.glob("*.key")) if segs.exists() else set()
    started = time.monotonic()
    proc = subprocess.Popen([PY, str(ROOT / "cf_cinema.py"), str(BASE), str(path), str(out)], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if kill_after:
        while proc.poll() is None and len(set(segs.glob("*.key")) - before) < kill_after:
            time.sleep(0.1)
        proc.send_signal(signal.SIGKILL)
        proc.wait()
        parts = sorted(p.name for p in segs.glob("*.part"))
        return dict(killed=True, new_stamps=len(set(segs.glob("*.key")) - before), left_parts=parts,
                    seconds=round(time.monotonic() - started, 1))
    log = proc.communicate()[0]
    if proc.returncode:
        raise SystemExit(log)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    record = json.loads((out / "render.json").read_text())
    return dict(rendered=record["rendered"], reused=record["reused"], seconds=record["seconds"],
                children_peak_rss_mb=round(usage.ru_maxrss / 1024), film_sha256=record["film"]["sha256"],
                segments={s["shot"]: s["sha256"][:16] for s in record["segments"]})


def main():
    stage = os.environ.get("STAGE", "all")
    ids_file = WORK / "ids.json"
    if stage in ("all", "publish"):
        ids, assets = publish()
        ids_file.write_text(json.dumps(dict(ids=ids, assets=assets), indent=1))
    saved = json.loads(ids_file.read_text())
    ids = saved["ids"]
    report = dict(ids=ids)
    first = timeline(ids, ids["lembranca_v1"])
    second = timeline(ids, ids["lembranca_v2"])
    (WORK / "timeline-v1.json").write_text(json.dumps(first, ensure_ascii=False, indent=1))
    (WORK / "timeline-v2.json").write_text(json.dumps(second, ensure_ascii=False, indent=1))
    if stage in ("all", "render"):
        report["1_cut_killed"] = render(WORK / "timeline-v1.json", WORK / "cut1", kill_after=3)
        report["2_resume"] = render(WORK / "timeline-v1.json", WORK / "cut1")
        report["3_swap_s04_to_v2"] = render(WORK / "timeline-v2.json", WORK / "cut2")
        a, b = report["2_resume"]["segments"], report["3_swap_s04_to_v2"]["segments"]
        report["same_bytes"] = [s for s in a if a[s] == b[s]]
        report["changed"] = [s for s in a if a[s] != b[s]]
        report["v1_still_selectable"] = cf_asset_graph.verify(BASE, ids["lembranca_v1"])
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
