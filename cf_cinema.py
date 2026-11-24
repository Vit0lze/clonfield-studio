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
import subprocess
import sys
import time
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
    norm = ("loudnorm=I={I}:TP={TP}:LRA={LRA}".format(**LOUDNESS) +
            f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
            f":offset={m['target_offset']}:linear=true")
    return ["-i", premix, "-af", f"{norm},aresample=48000", "-c:a", "pcm_s16le", "-ar", 48000, "-f", "wav", target]


def peak_db(path):
    out = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-af", "astats=measure_overall=Peak_level:measure_perchannel=none",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    line = [x for x in out.splitlines() if "Peak level dB" in x]
    return float(line[-1].rsplit(":", 1)[1]) if line else None


def integrated_lufs(path, stream="0:a:0"):
    out = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-map", stream, "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    summary = out[out.rfind("Summary:"):]
    get = lambda label: float(summary.split(label + ":", 1)[1].split()[0])
    return dict(I=get("I"), true_peak=get("Peak"))


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
    the record (render.json) go to out_dir. Returns the record."""
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
        key = cache.digest(_settings(timeline), AUDIO_VERSION, total, [{**c, "sha256": sources[c["src"]][1]["sha256"]} for c in clips])
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
    (out_dir / "render.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    say(1.0, desc=f"{len(record['rendered'])} passo(s) refeito(s), {len(record['reused'])} reaproveitado(s)")
    return record


def result_files(record, out_dir):
    out_dir = Path(out_dir)
    name = Path(record["film"]["file"]).stem
    return [out_dir / record["film"]["file"], *(out_dir / s for s in record["stems"]), out_dir / f"{name}.timeline.json", out_dir / "render.json"]


if __name__ == "__main__":  # python cf_cinema.py <base> <timeline.json> <out_dir>
    base, path, out = sys.argv[1:4]
    done = render(json.loads(Path(path).read_text(encoding="utf-8")), base, out,
                  progress=lambda value, desc="": print(f"{value:4.0%} {desc}", flush=True))
    print(json.dumps(dict(rendered=done["rendered"], reused=done["reused"], seconds=done["seconds"], film=done["film"]["sha256"]), indent=1))
