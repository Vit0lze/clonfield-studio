"""Cinema alfa: an editable timeline (Timeline.v1) of pinned asset versions, rendered on CPU with FFmpeg.

- Every clip is an AssetRef version (`v_<16hex>`, cf_asset_graph): the timeline pins exactly which take it uses; `a_` ids are refused.
- Each shot renders to its own normalized segment (same size, fps, codec, exact frame count). A segment is cached by the
  Content Factory stage cache (vendor/content_factory core/cache.py: digest / fresh / mark, MIT, commit 0ea76329): its key is
  the digest of the render version, the output settings, the shot's own fields and the blob's sha256. A shot whose key did not
  change is reused, so swapping one take re-renders one segment; the others keep their bytes.
- Segments are written to `.part`, moved into place and only then stamped (`mark`), so an interrupted render never leaves a
  stale stamp on a half-written file: the next run reuses every finished segment and redoes the rest.
- The picture is joined with the concat demuxer (stream copy, no re-encode). Voice, music and effects are rendered as three
  separate stems (WAV, exact length), mixed with the music ducked under the voice, and muxed as four audio streams:
  mix (default), voz, musica, efeitos.

Nothing here uses the GPU. Remotion is not used (licence decision pending); OpenTimelineIO export is a later step."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

import cf_asset_graph

SCHEMA = "Timeline.v1"
RENDER_VERSION = "cinema-seg-1"
AUDIO_VERSION = "cinema-audio-2"  # float stems + two-pass loudness on the mix
LOUDNESS = dict(I=-16.0, TP=-1.5, LRA=11.0)  # web/phone delivery; EBU R128 broadcast would be I=-23  # bump when the segment encoder changes: every key changes with it
TRACKS = ("voice", "music", "sfx")
STREAM_TITLES = {"mix": "mix", "voice": "voz", "music": "musica", "sfx": "efeitos"}
LOOKS = {
    "none": "",
    # a remembered picture: colour pulled down, a little warmth, soft vignette, fine grain
    "memory": "eq=saturation=0.45:contrast=0.95:brightness=0.01,colorbalance=rs=0.04:bs=-0.03,vignette=PI/5,noise=alls=7:allf=t",
    # dusk grade shared by the sea shots so three different generations read as one place
    "dusk": "eq=saturation=0.9:contrast=1.04,colorbalance=rm=0.02:bm=0.03",
}
_ROOT = Path(__file__).resolve().parent / "vendor" / "content_factory" / "engine"


def _cache():
    """digest / fresh / mark from the vendored Content Factory (no copy of the code)."""
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from factory.core import cache
    return cache


class Cancelled(RuntimeError):
    pass


# ------------------------------------------------------------------ timeline


def validate(timeline, base):
    """Refuse anything the renderer would have to guess. Returns the resolved sources: {version_id: (path, AssetRef)}."""
    if not isinstance(timeline, dict) or timeline.get("schema") != SCHEMA:
        raise ValueError(f"A timeline precisa de \"schema\": \"{SCHEMA}\".")
    fps = timeline.get("fps", 24)
    width, height = timeline.get("size", [1280, 720])
    if not (isinstance(fps, int) and 12 <= fps <= 60) or width % 2 or height % 2 or not (160 <= width <= 3840 and 160 <= height <= 3840):
        raise ValueError("fps inteiro de 12 a 60 e tamanho par entre 160 e 3840.")
    shots = timeline.get("video")
    if not isinstance(shots, list) or not shots:
        raise ValueError("A timeline precisa de pelo menos um plano em \"video\".")
    ids, sources = set(), {}

    def need(src, kind, where):
        if isinstance(src, dict) and kind == "video" and set(src) == {"color"}:
            return
        if not isinstance(src, str) or not cf_asset_graph.VERSION_ID.fullmatch(src):
            raise ValueError(f"{where}: fixe a versão do ativo (\"v_…\"); \"{src}\" não é uma versão.")
        path = cf_asset_graph.resolve(base, src)
        if path is None:
            raise ValueError(f"{where}: versão {src} não encontrada.")
        ref = cf_asset_graph.get_version(base, src)
        if ref["kind"] not in ((kind,) if kind == "audio" else ("video", "image", "character")):
            raise ValueError(f"{where}: {src} é {ref['kind']}, não serve aqui.")
        sources[src] = (path, ref)

    for shot in shots:
        sid = shot.get("id")
        if not isinstance(sid, str) or not sid or sid in ids:
            raise ValueError("Cada plano precisa de um \"id\" único.")
        ids.add(sid)
        if not (isinstance(shot.get("dur"), (int, float)) and 0.25 <= shot["dur"] <= 120):
            raise ValueError(f"Plano {sid}: \"dur\" de 0,25 a 120 s.")
        if shot.get("look", "none") not in LOOKS:
            raise ValueError(f"Plano {sid}: look desconhecido ({', '.join(LOOKS)}).")
        if not 0.1 <= float(shot.get("speed", 1)) <= 4:
            raise ValueError(f"Plano {sid}: \"speed\" de 0,1 a 4.")
        need(shot.get("src"), "video", f"Plano {sid}")
    audio = timeline.get("audio", {})
    if set(audio) - set(TRACKS):
        raise ValueError(f"Trilhas de áudio: {', '.join(TRACKS)}.")
    total = duration(timeline)
    for track in TRACKS:
        for i, clip in enumerate(audio.get(track, [])):
            need(clip.get("src"), "audio", f"Trilha {track} #{i + 1}")
            if not 0 <= float(clip.get("at", 0)) < total:
                raise ValueError(f"Trilha {track} #{i + 1}: \"at\" fora do filme (0 a {total:g} s).")
    return sources


def duration(timeline):
    fps = timeline.get("fps", 24)
    return sum(frames(shot["dur"], fps) for shot in timeline["video"]) / fps


def frames(seconds, fps):
    return max(1, round(float(seconds) * fps))


def _settings(timeline):
    return dict(fps=timeline.get("fps", 24), size=list(timeline.get("size", [1280, 720])), version=RENDER_VERSION)


def shot_key(timeline, shot, sources):
    cache = _cache()
    spec = {k: v for k, v in shot.items() if k not in ("id", "note")}  # renaming or annotating a shot does not re-render it
    src = shot["src"]
    blob = sources[src][1]["sha256"] if isinstance(src, str) else src
    return cache.digest(_settings(timeline), spec, blob)


# ------------------------------------------------------------------ ffmpeg


def _run(args, control=None, timeout=1800):
    """ffmpeg with a cancel check every 0.2 s (kills the child on cancel)."""
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-y", *map(str, args)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    start = time.monotonic()
    while True:
        try:
            _, err = proc.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if (control is not None and control.cancelled) or time.monotonic() - start > timeout:
                proc.kill()
                proc.communicate()
                raise Cancelled("Montagem cancelada.") if control is not None and control.cancelled else TimeoutError("ffmpeg passou do tempo.")
    if proc.returncode:
        raise ValueError("ffmpeg falhou: " + err.decode(errors="replace")[-400:])


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels:stream_tags=handler_name",
                          "-of", "json", str(path)], capture_output=True, check=True, text=True).stdout
    return json.loads(out)


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _segment_args(timeline, shot, sources, target):
    fps = timeline.get("fps", 24)
    width, height = timeline.get("size", [1280, 720])
    count = frames(shot["dur"], fps)
    src = shot["src"]
    if isinstance(src, dict):
        inputs = ["-f", "lavfi", "-i", f"color=c={src['color']}:s={width}x{height}:r={fps}"]
        chain = "[0:v]setsar=1"
    else:
        path, ref = sources[src]
        still = ref["kind"] in ("image", "character")
        inputs = (["-loop", "1", "-framerate", str(fps)] if still else ["-stream_loop", "-1"] if shot.get("loop") else [])
        inputs += ["-ss", f"{float(shot.get('in', 0)):.3f}"] if shot.get("in") and not still else []
        inputs += ["-i", str(path)]
        parts = []
        if shot.get("pingpong") and not still:
            parts.append("split[f][b];[b]reverse[r];[f][r]concat=n=2:v=1:a=0")
        speed = float(shot.get("speed", 1))
        if speed != 1:
            parts.append(f"setpts={1 / speed:.6f}*PTS")
        # 'framerate' blends neighbouring frames when slowing a 16/24 fps take, which reads smoother than duplicated frames
        parts.append(f"framerate=fps={fps}" if speed < 1 else f"fps={fps}")
        x, y, w, h = shot.get("crop", [0, 0, 1, 1])  # fractions of the source frame: where the camera looks
        parts.append(f"crop=trunc(iw*{w}/2)*2:trunc(ih*{h}/2)*2:trunc(iw*{x}):trunc(ih*{y})")
        parts.append(f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height}")
        zoom = float(shot.get("push", 0))  # slow push-in, as a fraction of the frame over the whole shot
        if zoom:
            parts.append(f"scale={width * 2}:{height * 2}:flags=lanczos,zoompan=z='1+{zoom:.4f}*on/{count}':d=1:"
                         f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}")
        chain = "[0:v]" + ",".join(parts) + ",setsar=1"
    look = LOOKS[shot.get("look", "none")]
    if look:
        chain += "," + look
    seconds = count / fps
    if shot.get("fade_in"):
        chain += f",fade=t=in:st=0:d={float(shot['fade_in']):.3f}"
    if shot.get("fade_out"):
        chain += f",fade=t=out:st={seconds - float(shot['fade_out']):.3f}:d={float(shot['fade_out']):.3f}"
    chain += f",tpad=stop_mode=clone:stop_duration={seconds:.3f},format=yuv420p[v]"
    return [*inputs, "-filter_complex", chain, "-map", "[v]", "-frames:v", count, "-r", fps, "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-g", fps, "-threads", "2",
            "-video_track_timescale", fps * 1000, "-movflags", "+faststart", "-f", "mp4", target]


def _stem_args(timeline, track, sources, total, target):
    clips = timeline.get("audio", {}).get(track, [])
    if not clips:
        return ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{total:.3f}", "-c:a", "pcm_f32le", "-f", "wav", target]
    args, chains, tags = [], [], []
    for i, clip in enumerate(clips):
        path, _ = sources[clip["src"]]
        args += (["-stream_loop", "-1"] if clip.get("loop") else []) + ["-i", str(path)]
        start = float(clip.get("in", 0))
        chain = f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=start={start:.3f}"
        if clip.get("dur"):
            chain += f":duration={float(clip['dur']):.3f}"
        chain += ",asetpts=PTS-STARTPTS"
        if clip.get("gain_db"):
            chain += f",volume={float(clip['gain_db']):.2f}dB"
        if clip.get("fade_in"):
            chain += f",afade=t=in:st=0:d={float(clip['fade_in']):.3f}"
        if clip.get("fade_out") and clip.get("dur"):
            chain += f",afade=t=out:st={float(clip['dur']) - float(clip['fade_out']):.3f}:d={float(clip['fade_out']):.3f}"
        delay = round(float(clip.get("at", 0)) * 1000)
        chain += f",adelay={delay}|{delay}[a{i}]"
        chains.append(chain)
        tags.append(f"[a{i}]")
    chains.append(f"{''.join(tags)}amix=inputs={len(clips)}:normalize=0:dropout_transition=0,apad,atrim=duration={total:.6f}[out]")
    # 32-bit float: a stem that goes over full scale keeps its shape (and its measured peak says so) instead of clipping
    return [*args, "-filter_complex", ";".join(chains), "-map", "[out]", "-c:a", "pcm_f32le", "-ar", 48000, "-f", "wav", target]


def _mix_args(timeline, stems, target):
    mix = {"voice": 0.0, "music": -12.0, "sfx": -4.0, "duck": True, **timeline.get("mix", {})}
    v, m, s = stems["voice"], stems["music"], stems["sfx"]
    graph = [f"[0:a]volume={mix['voice']}dB,asplit=2[v][key]", f"[1:a]volume={mix['music']}dB[m0]", f"[2:a]volume={mix['sfx']}dB[s]"]
    if mix["duck"]:  # the music steps back while someone speaks
        graph.append("[m0][key]sidechaincompress=threshold=0.03:ratio=6:attack=80:release=900[m]")
    else:
        graph.append("[key]anullsink;[m0]anull[m]")
    graph.append("[v][m][s]amix=inputs=3:normalize=0:dropout_transition=0[out]")
    return ["-i", v, "-i", m, "-i", s, "-filter_complex", ";".join(graph), "-map", "[out]", "-c:a", "pcm_f32le", "-ar", 48000, "-f", "wav", target]


def _loudness(path):
    """First loudnorm pass: the measured values the second (linear) pass needs."""
    done = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-af",
                           "loudnorm=I={I}:TP={TP}:LRA={LRA}:print_format=json".format(**LOUDNESS), "-f", "null", "-"],
                          capture_output=True, text=True, check=True).stderr
    return json.loads(done[done.rindex("{"):done.rindex("}") + 1])


def _master_args(premix, target):
    m = _loudness(premix)
    try:
        silent = float(m["input_i"]) < -70  # no sound at all (a film that has no tracks yet): nothing to normalize
    except ValueError:  # "-inf"
        silent = True
    if silent:
        return ["-i", premix, "-c:a", "pcm_s16le", "-ar", 48000, "-f", "wav", target]
    norm = ("loudnorm=I={I}:TP={TP}:LRA={LRA}".format(**LOUDNESS) +
            f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
            f":offset={m['target_offset']}:linear=true")
    return ["-i", premix, "-af", f"{norm},aresample=48000", "-c:a", "pcm_s16le", "-ar", 48000, "-f", "wav", target]


def peak_db(path):
    out = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-af", "astats=measure_overall=Peak_level:measure_perchannel=none",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    line = [x for x in out.splitlines() if "Peak level dB" in x]
    return _finite(float(line[-1].rsplit(":", 1)[1])) if line else None


def integrated_lufs(path, stream="0:a:0"):
    out = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-map", stream, "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    summary = out[out.rfind("Summary:"):]
    get = lambda label: _finite(float(summary.split(label + ":", 1)[1].split()[0]))
    return dict(I=get("I"), true_peak=get("Peak"))


def _finite(value):
    """Silence measures as -inf, which JSON (and the browser) cannot read: None instead."""
    import math
    return value if value is not None and math.isfinite(value) else None


# ------------------------------------------------------------------ render


def _step(out, key, build, control, report, name):
    """One cached step: reuse when the Content Factory stamp matches, else render to .part, move, stamp."""
    cache = _cache()
    if cache.fresh(out, key):
        report.append(dict(step=name, key=key, status="reused", file=out.name))
        return False
    if control is not None and control.cancelled:
        raise Cancelled("Montagem cancelada.")
    stamp = out.with_name(out.name + ".key")
    stamp.unlink(missing_ok=True)  # a stamp must never outlive the bytes it describes
    part = out.with_name(out.name + ".part")
    started = time.monotonic()
    _run(build(part), control)
    os.replace(part, out)
    cache.mark(out, key)
    report.append(dict(step=name, key=key, status="rendered", file=out.name, seconds=round(time.monotonic() - started, 2)))
    return True


def render(timeline, base, out_dir, progress=None, control=None):
    """Render the timeline. Cache lives in <base>/cinema/cache (shared by every timeline); the film, the stems and
    the record (<name>.render.json) go to out_dir. Returns the record."""
    say = progress or (lambda *a, **k: None)
    sources = validate(timeline, base)
    cache = _cache()
    folder = Path(base) / "cinema" / "cache"
    (folder / "segments").mkdir(parents=True, exist_ok=True)
    (folder / "stems").mkdir(parents=True, exist_ok=True)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fps = timeline.get("fps", 24)
    total = duration(timeline)
    report, segments, started = [], [], time.monotonic()

    for i, shot in enumerate(timeline["video"]):
        key = shot_key(timeline, shot, sources)
        out = folder / "segments" / f"{key}.mp4"
        say(0.05 + 0.6 * i / len(timeline["video"]), desc=f"Plano {shot['id']}")
        _step(out, key, lambda part, s=shot: _segment_args(timeline, s, sources, part), control, report, f"video:{shot['id']}")
        segments.append(dict(shot=shot["id"], src=shot["src"] if isinstance(shot["src"], str) else shot["src"], key=key,
                             frames=frames(shot["dur"], fps), sha256=_sha256(out), path=str(out)))

    picture_key = cache.digest(_settings(timeline), [s["key"] for s in segments])
    picture = folder / f"picture-{picture_key}.mp4"
    listing = folder / f"picture-{picture_key}.txt"

    def join(part):
        listing.write_text("".join(f"file '{Path(s['path']).as_posix()}'\n" for s in segments), encoding="utf-8")
        return ["-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", "-movflags", "+faststart", "-f", "mp4", part]

    say(0.7, desc="Juntando os planos (cópia, sem recodificar)")
    _step(picture, picture_key, join, control, report, "picture")
    listing.unlink(missing_ok=True)

    stems = {}
    for track in TRACKS:
        clips = timeline.get("audio", {}).get(track, [])
        key = cache.digest(_settings(timeline), AUDIO_VERSION, total, [{**{k: v for k, v in c.items() if k != "note"}, "sha256": sources[c["src"]][1]["sha256"]} for c in clips])  # a note (the spoken line) does not re-render
        stems[track] = folder / "stems" / f"{track}-{key}.wav"
        say(0.75, desc=f"Trilha {STREAM_TITLES[track]}")
        _step(stems[track], key, lambda part, t=track: _stem_args(timeline, t, sources, total, part), control, report, f"stem:{track}")
    mix_key = cache.digest(_settings(timeline), AUDIO_VERSION, LOUDNESS, timeline.get("mix", {}), [stems[t].name for t in TRACKS])
    mixed = folder / "stems" / f"mix-{mix_key}.wav"
    say(0.85, desc="Mixando (música abaixa sob a voz) e acertando o volume")

    def master(part):
        premix = part.with_name(part.name + ".pre.wav")
        _run(_mix_args(timeline, stems, premix), control)
        return _master_args(premix, part)  # the pre-mix is removed after the step

    _step(mixed, mix_key, master, control, report, "mix")
    mixed.with_name(mixed.name + ".part.pre.wav").unlink(missing_ok=True)

    name = timeline.get("name") or "curta"
    film = out_dir / f"{name}.mp4"
    say(0.92, desc="Gravando o filme com as quatro trilhas")
    args = ["-i", picture, "-i", mixed, *sum((["-i", stems[t]] for t in TRACKS), []), "-map", "0:v"]
    for i in range(4):
        args += ["-map", f"{i + 1}:a"]
    args += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", 48000]
    for i, label in enumerate(["mix", *TRACKS]):
        # MP4 keeps a track's name in handler_name (a plain "title" is dropped by the muxer); players list it by that name
        args += [f"-metadata:s:a:{i}", f"handler_name={STREAM_TITLES[label]}", f"-metadata:s:a:{i}", "language=por",
                 f"-disposition:a:{i}", "default" if i == 0 else "0"]
    args += ["-metadata", f"title={timeline.get('title', name)}", "-movflags", "+faststart", "-f", "mp4"]
    part = film.with_name(film.name + ".part")
    _run([*args, part], control)
    os.replace(part, film)
    exported = []
    for track in TRACKS:
        copy = out_dir / f"{name}-{STREAM_TITLES[track]}.wav"
        copy.write_bytes(stems[track].read_bytes())
        exported.append(copy)
    record = dict(schema="CinemaRender.v1", timeline=timeline, duration_s=round(total, 3), frames=sum(s["frames"] for s in segments),
                  segments=[{k: v for k, v in s.items() if k != "path"} for s in segments], steps=report,
                  rendered=[r["step"] for r in report if r["status"] == "rendered"], reused=[r["step"] for r in report if r["status"] == "reused"],
                  film=dict(file=film.name, sha256=_sha256(film), probe=_probe(film), loudness=integrated_lufs(film)), stems=[p.name for p in exported],
                  stem_peaks_db={t: peak_db(stems[t]) for t in TRACKS},
                  seconds=round(time.monotonic() - started, 2))
    (out_dir / f"{name}.timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{name}.render.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    say(1.0, desc=f"{len(record['rendered'])} passo(s) refeito(s), {len(record['reused'])} reaproveitado(s)")
    return record


def result_files(record, out_dir):
    out_dir = Path(out_dir)
    name = Path(record["film"]["file"]).stem
    return [out_dir / record["film"]["file"], *(out_dir / s for s in record["stems"]), out_dir / f"{name}.timeline.json", out_dir / f"{name}.render.json"]


# ------------------------------------------------------------------ projects (what the Studio screen opens and edits)
# CinemaProject.v1: one picture + voice (`timeline.video`, `timeline.audio.voice`) and named cuts that differ ONLY in music,
# effects and mix. A/B cuts therefore share every video segment and the joined picture by construction.

PROJECT_ID = re.compile(r"p_[0-9a-f]{12}")
CUT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
_projects_lock = threading.Lock()
SHOT_DUR = (0.5, 60.0)  # what the screen lets a shot last


def projects_dir(base):
    return Path(base) / "cinema" / "projects"


def blank_timeline(fps=24, size=(1280, 720)):
    return {"schema": SCHEMA, "fps": fps, "size": list(size), "video": [], "audio": {"voice": []}}


def compose(project, cut_id):
    """The full Timeline.v1 of one cut: the project's picture and voice + that cut's music, effects and mix."""
    cut = project["cuts"].get(cut_id)
    if cut is None:
        raise ValueError(f"Corte «{cut_id}» não existe neste projeto.")
    timeline = json.loads(json.dumps(project["timeline"]))
    timeline["audio"] = {"voice": timeline.get("audio", {}).get("voice", []), "music": cut.get("music", []), "sfx": cut.get("sfx", [])}
    timeline["mix"] = cut.get("mix", timeline.get("mix", {}))
    timeline["name"] = f"{project['slug']}-{cut_id}"
    timeline["title"] = f"{project['title']} · {cut.get('label', cut_id)}"
    return timeline


def signature(project, cut_id):
    """What the render of one cut depends on (notes, names and titles left out). Equal signature = the export shows this timeline."""
    import hashlib
    timeline = compose(project, cut_id)
    for key in ("name", "title"):
        timeline.pop(key, None)
    strip = lambda items: [{k: v for k, v in i.items() if k != "note"} for i in items]
    timeline["video"] = strip(timeline["video"])
    timeline["audio"] = {k: strip(v) for k, v in timeline["audio"].items()}
    return hashlib.sha256(json.dumps(timeline, sort_keys=True).encode()).hexdigest()[:16]


def _check(project, base):
    if not project.get("cuts"):
        raise ValueError("O projeto precisa de pelo menos um corte.")
    for cut_id in project["cuts"]:
        if not CUT_ID.fullmatch(cut_id):
            raise ValueError(f"Nome de corte inválido: «{cut_id}» (minúsculas, números e hífen).")
        if project["timeline"]["video"]:  # an empty project is allowed; it only cannot be exported
            validate(compose(project, cut_id), base)
    if project.get("cut") not in project["cuts"]:
        project["cut"] = next(iter(project["cuts"]))


def _write_project(base, project):
    folder = projects_dir(base)
    folder.mkdir(parents=True, exist_ok=True)
    project["updated"] = int(time.time())
    path = folder / f"{project['id']}.json"
    part = path.with_suffix(".json.part")
    part.write_text(json.dumps(project, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(part, path)
    return project


def create_project(base, title, timeline=None, cuts=None, cut=None):
    """A new project. Without a timeline it starts empty (no shots) with one silent cut, «Corte 1»."""
    import secrets
    title = str(title or "").strip()[:80] or "Sem título"
    slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()).strip("-")[:40] or "curta"
    project = dict(schema="CinemaProject.v1", id="p_" + secrets.token_hex(6), title=title, slug=slug,
                   timeline=timeline or blank_timeline(), cuts=cuts or {"principal": dict(label="Corte 1", music=[], sfx=[], mix={})},
                   cut=cut, revision=1, history=[dict(at=int(time.time()), revision=1, what="projeto criado")], exports=[],
                   last_export=None, last_good=None, created=int(time.time()))
    if not isinstance(project["timeline"].get("video"), list):
        raise ValueError("A timeline precisa de uma lista \"video\".")
    _check(project, base)
    with _projects_lock:
        return _write_project(base, project)


def load_project(base, project_id):
    if not isinstance(project_id, str) or not PROJECT_ID.fullmatch(project_id):
        raise KeyError(project_id)
    path = projects_dir(base) / f"{project_id}.json"
    if not path.is_file():
        raise KeyError(project_id)
    project = json.loads(path.read_text(encoding="utf-8"))
    project.setdefault("revision", 1)  # projects saved before revisions existed
    project.setdefault("exports", [])
    project.setdefault("last_good", None)
    return project


def list_projects(base):
    out = []
    for path in sorted(projects_dir(base).glob("p_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        p = json.loads(path.read_text(encoding="utf-8"))
        out.append(dict(id=p["id"], title=p["title"], shots=len(p["timeline"]["video"]), cuts=list(p["cuts"]),
                        duration_s=round(duration(p["timeline"]), 3) if p["timeline"]["video"] else 0, updated=p.get("updated"),
                        revision=p.get("revision", 1)))
    return out


def _edit(base, project_id, change):
    """Apply one change to the timeline: `change(project)` returns what to log; the project gets a new revision."""
    with _projects_lock:
        project = load_project(base, project_id)
        what = change(project)
        if what is None:  # nothing changed: same revision
            return project
        _check(project, base)
        project["revision"] += 1
        project["history"] = [*project.get("history", []), dict(at=int(time.time()), revision=project["revision"], **what)][-80:]
        return _write_project(base, project)


def _shot(project, shot_id):
    shot = next((s for s in project["timeline"]["video"] if s["id"] == shot_id), None)
    if shot is None:
        raise ValueError(f"Plano {shot_id} não existe.")
    return shot


def set_shot_version(base, project_id, shot_id, version_id):
    """Swap the take of one shot for another VERSION OF THE SAME ASSET (the gesture is «trocar a tomada», not «trocar o plano»)."""
    def change(project):
        shot = _shot(project, shot_id)
        if not isinstance(shot["src"], str):
            raise ValueError(f"Plano {shot_id} não tem tomada para trocar.")
        if not isinstance(version_id, str) or not cf_asset_graph.VERSION_ID.fullmatch(version_id):
            raise ValueError("Escolha uma versão (v_…).")
        old, new = cf_asset_graph.get_version(base, shot["src"]), cf_asset_graph.get_version(base, version_id)
        if old["asset_id"] != new["asset_id"]:
            raise ValueError("Essa versão é de outro ativo; aqui só se troca a tomada do mesmo plano.")
        if shot["src"] == version_id:
            return None
        shot["src"] = version_id
        return dict(what=f"{shot_id}: tomada v{old['number']} → v{new['number']}", shot=shot_id, before=old["version_id"], after=version_id,
                    numbers=[old["number"], new["number"]])
    return _edit(base, project_id, change)


def add_shot(base, project_id, ident, dur=None):
    """Append a shot made from a Library asset. An `a_` id is pinned to that asset's current version right here."""
    found = cf_asset_graph.resolve_ref(base, ident)
    if found is None:
        raise ValueError("Ativo ou versão não encontrado.")
    version = found[1]
    if version["kind"] not in ("video", "image", "character"):
        raise ValueError("Só imagem ou vídeo viram plano.")
    asset = cf_asset_graph.get(base, version["asset_id"])
    natural = (version.get("media") or {}).get("duration_s")
    seconds = float(dur) if dur is not None else (round(min(max(float(natural), SHOT_DUR[0]), 8.0), 2) if version["kind"] == "video" and natural else 3.0)

    def change(project):
        if not SHOT_DUR[0] <= seconds <= SHOT_DUR[1]:
            raise ValueError(f"Duração de {SHOT_DUR[0]:g} a {SHOT_DUR[1]:g} s.")
        taken = {s["id"] for s in project["timeline"]["video"]}
        n = 1
        while f"s{n:02d}" in taken:
            n += 1
        shot = dict(id=f"s{n:02d}", src=version["version_id"], dur=seconds, note=asset.get("title"))
        if version["kind"] == "video" and natural and seconds > float(natural):
            shot["loop"] = True  # longer than the take: loop it instead of freezing the last frame
        project["timeline"]["video"].append(shot)
        return dict(what=f"{shot['id']}: adicionado «{asset.get('title')}» v{version['number']}", shot=shot["id"], after=version["version_id"])
    return _edit(base, project_id, change)


def remove_shot(base, project_id, shot_id):
    def change(project):
        shot = _shot(project, shot_id)
        project["timeline"]["video"].remove(shot)
        return dict(what=f"{shot_id}: removido", shot=shot_id, before=shot["src"] if isinstance(shot["src"], str) else None)
    return _edit(base, project_id, change)


def set_shot_duration(base, project_id, shot_id, dur):
    def change(project):
        shot = _shot(project, shot_id)
        try:
            seconds = round(float(dur), 2)
        except (TypeError, ValueError):
            raise ValueError("Duração inválida.") from None
        if not SHOT_DUR[0] <= seconds <= SHOT_DUR[1]:
            raise ValueError(f"Duração de {SHOT_DUR[0]:g} a {SHOT_DUR[1]:g} s.")
        if shot["dur"] == seconds:
            return None
        before = shot["dur"]
        shot["dur"] = seconds
        if isinstance(shot["src"], str):
            ref = cf_asset_graph.get_version(base, shot["src"])
            natural = (ref.get("media") or {}).get("duration_s")
            if ref["kind"] == "video" and natural and not shot.get("speed") and not shot.get("pingpong"):
                shot["loop"] = seconds > float(natural) + 0.05
        return dict(what=f"{shot_id}: {before:g} s → {seconds:g} s", shot=shot_id)
    return _edit(base, project_id, change)


def reorder(base, project_id, order):
    def change(project):
        shots = {s["id"]: s for s in project["timeline"]["video"]}
        if not isinstance(order, list) or sorted(order) != sorted(shots):
            raise ValueError("A nova ordem precisa ter exatamente os mesmos planos.")
        if order == [s["id"] for s in project["timeline"]["video"]]:
            return None
        project["timeline"]["video"] = [shots[i] for i in order]
        return dict(what="ordem: " + " ".join(order))
    return _edit(base, project_id, change)


def set_cut(base, project_id, cut_id):
    """Which cut is the chosen one. Not a timeline change: no new revision."""
    with _projects_lock:
        project = load_project(base, project_id)
        if cut_id not in project["cuts"]:
            raise ValueError(f"Corte «{cut_id}» não existe.")
        project["cut"] = cut_id
        return _write_project(base, project)


def begin_export(base, project_id, job_id, cut_ids):
    """Record an export attempt with the revision and the signature of each cut it renders."""
    with _projects_lock:
        project = load_project(base, project_id)
        entry = dict(job_id=job_id, status="na fila", at=int(time.time()), revision=project["revision"], cuts=cut_ids,
                     signatures={c: signature(project, c) for c in cut_ids}, versions={s["id"]: s["src"] for s in project["timeline"]["video"]
                                                                                    if isinstance(s["src"], str)})
        project["exports"] = [*project["exports"], entry][-20:]
        project["last_export"] = job_id
        return _write_project(base, project)


def finish_export(base, project_id, job_id, status, summary=None, message=None):
    """Close an export entry. Only a finished one becomes `last_good`: a failed export never hides the last pair that worked."""
    with _projects_lock:
        project = load_project(base, project_id)
        entry = next((e for e in project["exports"] if e["job_id"] == job_id), None)
        if entry is None:
            return project
        entry.update(status=status, finished=int(time.time()), summary=summary, message=message)
        if status == "concluído":
            project["last_good"] = job_id
        return _write_project(base, project)


def _video_md5(path):
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v", "-c", "copy", "-f", "md5", "-"], capture_output=True, text=True, check=True)
    return out.stdout.strip().removeprefix("MD5=")


def export_project(base, project, cut_ids, out_dir, progress=None, control=None):
    """Render the chosen cuts one after the other. With two or more, also an A/B record: is the picture byte-identical
    (same joined picture, same video stream MD5) and is every cut at the same reference loudness?"""
    say = progress or (lambda *a, **k: None)
    records = []
    for i, cut_id in enumerate(cut_ids):
        span = (i / len(cut_ids), (i + 1) / len(cut_ids))
        step = lambda value=None, desc="", **k: say(span[0] + (span[1] - span[0]) * float(value or 0), desc=f"{project['cuts'][cut_id].get('label', cut_id)} · {desc}")
        records.append(render(compose(project, cut_id), base, out_dir, step, control))
    files = [f for r in records for f in result_files(r, out_dir)]
    if len(records) > 1:
        pictures = {r["timeline"]["name"]: next(s["key"] for s in r["steps"] if s["step"] == "picture") for r in records}
        streams = {r["timeline"]["name"]: _video_md5(Path(out_dir) / r["film"]["file"]) for r in records}
        loud = {r["timeline"]["name"]: r["film"]["loudness"] for r in records}
        ab = dict(schema="CinemaAB.v1", cuts=cut_ids, picture_key=pictures, video_md5=streams,
                  picture_identical=len(set(pictures.values())) == 1 and len(set(streams.values())) == 1,
                  loudness=loud, target=LOUDNESS, loudness_spread_lu=round(max(v["I"] for v in loud.values()) - min(v["I"] for v in loud.values()), 2))
        path = Path(out_dir) / f"{project['slug']}.ab.json"
        path.write_text(json.dumps(ab, ensure_ascii=False, indent=2), encoding="utf-8")
        files.append(path)
    return records, files


if __name__ == "__main__":  # python cf_cinema.py <base> <timeline.json> <out_dir>
    base, path, out = sys.argv[1:4]
    done = render(json.loads(Path(path).read_text(encoding="utf-8")), base, out,
                  progress=lambda value, desc="": print(f"{value:4.0%} {desc}", flush=True))
    print(json.dumps(dict(rendered=done["rendered"], reused=done["reused"], seconds=done["seconds"], film=done["film"]["sha256"]), indent=1))
