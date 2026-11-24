"""Cinema alfa (cf_cinema.py): real FFmpeg on small real clips, the real Asset Graph store, the vendored Content Factory stage cache,
and the real Starlette engine app on the CPU lane. No stubs: every clip, stem and film below is encoded and probed for real."""
import hashlib
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import cf_api
import cf_apps
import cf_asset_graph as ag
import cf_cinema

BASE = "/clonfield/api"
ROOT = Path(__file__).resolve().parents[1]


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def probe(path):
    return json.loads(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                                      "format=duration:stream=codec_type,nb_read_frames,width,height,r_frame_rate:stream_tags=handler_name:stream_disposition=default",
                                      "-of", "json", str(path)], capture_output=True, check=True, text=True).stdout)


@pytest.fixture()
def world(tmp_path):
    media = tmp_path / "outputs"
    media.mkdir()
    ff("-f", "lavfi", "-i", "testsrc2=s=200x120:r=16:d=1.5", "-pix_fmt", "yuv420p", media / "a.mp4")
    ff("-f", "lavfi", "-i", "mandelbrot=s=120x200:r=24", "-t", "1", "-pix_fmt", "yuv420p", media / "b.mp4")
    ff("-f", "lavfi", "-i", "testsrc=s=200x120:r=24:d=1", "-vf", "hue=h=90", "-pix_fmt", "yuv420p", media / "b2.mp4")
    ff("-f", "lavfi", "-i", "sine=f=440:d=1.2:r=44100", "-af", "volume=0.5", media / "voice.wav")
    ff("-f", "lavfi", "-i", "sine=f=110:d=3:r=48000", "-af", "volume=0.3", media / "music.wav")
    ff("-f", "lavfi", "-i", "anoisesrc=c=pink:d=4:a=0.3:r=48000", media / "sea.wav")
    roots = [media]
    pub = lambda name, kind: ag.publish(tmp_path, media / name, roots, kind=kind, title=name)
    a, b, voice, music, sea = pub("a.mp4", "video"), pub("b.mp4", "video"), pub("voice.wav", "audio"), pub("music.wav", "audio"), pub("sea.wav", "audio")
    b2 = ag.add_version(tmp_path, b["asset"]["asset_id"], media / "b2.mp4", roots)
    ids = dict(a=a["version"]["version_id"], b=b["version"]["version_id"], b2=b2["version"]["version_id"], b_asset=b["asset"]["asset_id"],
               voice=voice["version"]["version_id"], music=music["version"]["version_id"], sea=sea["version"]["version_id"])
    return tmp_path, ids


def timeline(ids, second="b"):
    return {
        "schema": "Timeline.v1", "name": "teste", "fps": 12, "size": [320, 180],
        "video": [dict(id="s1", src={"color": "black"}, dur=0.5),
                  dict(id="s2", src=ids["a"], dur=2.0, speed=0.5, look="dusk", fade_in=0.3),
                  dict(id="s3", src=ids[second], dur=1.5, pingpong=True, crop=[0, 0.1, 1, 0.5], look="memory"),
                  dict(id="s4", src=ids["a"], dur=1.0, loop=True, push=0.1, fade_out=0.5)],
        "audio": {"voice": [dict(src=ids["voice"], at=1.0)],
                  "music": [dict(src=ids["music"], at=0.0, dur=3.0, fade_out=1.0)],
                  "sfx": [dict(src=ids["sea"], at=0.0, dur=5.0, loop=True)]},
    }


def test_the_timeline_must_pin_asset_versions(world):
    base, ids = world
    t = timeline(ids)
    t["video"][1]["src"] = ids["b_asset"]  # "the current version" would change under the cut
    with pytest.raises(ValueError, match="fixe a versão"):
        cf_cinema.validate(t, base)
    t = timeline(ids)
    t["video"][1]["src"] = "v_" + "0" * 16
    with pytest.raises(ValueError, match="não encontrada"):
        cf_cinema.validate(t, base)
    t = timeline(ids)
    t["audio"]["voice"][0]["src"] = ids["a"]  # a video in the voice track
    with pytest.raises(ValueError, match="não serve"):
        cf_cinema.validate(t, base)
    t = timeline(ids)
    t["video"][0]["id"] = "s2"
    with pytest.raises(ValueError, match="único"):
        cf_cinema.validate(t, base)
    with pytest.raises(ValueError, match="schema"):
        cf_cinema.validate({**timeline(ids), "schema": "x"}, base)


def test_render_gives_exact_frames_four_titled_audio_streams_and_separate_stems(world):
    base, ids = world
    out = base / "cut"
    record = cf_cinema.render(timeline(ids), base, out)
    film = out / "teste.mp4"
    info = probe(film)
    video = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    assert (video["width"], video["height"], video["r_frame_rate"]) == (320, 180, "12/1")
    assert int(video["nb_read_frames"]) == 60 == record["frames"]  # 0.5 + 2 + 1.5 + 1 s at 12 fps
    assert abs(float(info["format"]["duration"]) - 5.0) < 0.05
    assert [s["tags"]["handler_name"] for s in audio] == ["mix", "voz", "musica", "efeitos"]
    assert [s["disposition"]["default"] for s in audio] == [1, 0, 0, 0]
    for name in ("teste-voz.wav", "teste-musica.wav", "teste-efeitos.wav"):
        assert abs(float(probe(out / name)["format"]["duration"]) - 5.0) < 0.01
    # the voice stem is silent before its clip starts at 1.0 s and carries the tone after it
    quiet = subprocess.run(["ffmpeg", "-nostats", "-i", str(out / "teste-voz.wav"), "-af", "atrim=0:0.9,astats=measure_perchannel=none", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
    loud = subprocess.run(["ffmpeg", "-nostats", "-i", str(out / "teste-voz.wav"), "-af", "atrim=1.1:2.1,astats=measure_perchannel=none", "-f", "null", "-"],
                          capture_output=True, text=True).stderr
    assert "RMS level dB: -inf" in quiet and "RMS level dB: -inf" not in loud
    assert all(p is not None and p < 0 for p in record["stem_peaks_db"].values())
    assert -18 < record["film"]["loudness"]["I"] < -14 and record["film"]["loudness"]["true_peak"] < 0
    assert set(record["rendered"]) == {"video:s1", "video:s2", "video:s3", "video:s4", "picture", "stem:voice", "stem:music", "stem:sfx", "mix"}


def test_swapping_one_take_rerenders_only_that_shot_and_the_old_version_stays(world):
    base, ids = world
    first = cf_cinema.render(timeline(ids, "b"), base, base / "cut1")
    second = cf_cinema.render(timeline(ids, "b2"), base, base / "cut2")
    assert second["rendered"] == ["video:s3", "picture"]  # the stems and the mix do not depend on the picture
    before = {s["shot"]: s["sha256"] for s in first["segments"]}
    after = {s["shot"]: s["sha256"] for s in second["segments"]}
    assert [s for s in before if before[s] != after[s]] == ["s3"]
    assert ag.verify(base, ids["b"]) and ag.resolve(base, ids["b"]).is_file()  # v1 still there and selectable
    third = cf_cinema.render(timeline(ids, "b"), base, base / "cut3")  # back to v1: even the v1 join is still in the cache
    assert third["rendered"] == [] and third["film"]["sha256"] == first["film"]["sha256"]
    renamed = timeline(ids, "b")
    renamed["video"][2]["note"] = "só uma anotação"
    assert cf_cinema.render(renamed, base, base / "cut4")["rendered"] == []


def test_a_cancelled_render_resumes_from_the_finished_shots(world):
    base, ids = world

    class StopAfter:
        def __init__(self):
            self.cancelled = False

    control = StopAfter()
    seen = []

    def progress(value, desc=""):
        seen.append(desc)
        if desc == "Plano s3":  # s1 and s2 are done and stamped; stop before s3 is rendered
            control.cancelled = True

    with pytest.raises(cf_cinema.Cancelled):
        cf_cinema.render(timeline(ids), base, base / "cut", progress=progress, control=control)
    segments = base / "cinema" / "cache" / "segments"
    assert len(list(segments.glob("*.key"))) == 2 and not list(segments.glob("*.part"))
    record = cf_cinema.render(timeline(ids), base, base / "cut")
    assert record["reused"][:2] == ["video:s1", "video:s2"] and "video:s3" in record["rendered"]


def test_a_killed_render_leaves_no_stale_stamp_and_resumes(world, tmp_path):
    """A crash, not a cancel: SIGKILL the renderer while it encodes. A half-written segment is a .part without a stamp, so the next
    run cannot mistake it for a finished one."""
    base, ids = world
    t = timeline(ids)
    t["video"][1]["dur"] = 20.0  # long enough to be killed mid-encode
    path = tmp_path / "t.json"
    path.write_text(json.dumps(t))
    proc = subprocess.Popen([sys.executable, str(ROOT / "cf_cinema.py"), str(base), str(path), str(base / "cut")], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    segments = base / "cinema" / "cache" / "segments"
    deadline = time.monotonic() + 60
    # kill while s2 (20 s, slow) is being encoded: s1 is already stamped and a .part exists
    while time.monotonic() < deadline and not (segments.exists() and list(segments.glob("*.key")) and list(segments.glob("*.part"))):
        time.sleep(0.02)
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    subprocess.run(["pkill", "-KILL", "-f", str(base / "cinema")], check=False)  # the orphaned ffmpeg child of this test only
    stamps = {p.name[:-4] for p in segments.glob("*.key")}
    assert all((segments / s).is_file() for s in stamps)
    assert not any(p.name.replace(".part", "") in stamps for p in segments.glob("*.part"))
    record = cf_cinema.render(t, base, base / "cut")
    assert "video:s1" in record["reused"] and "video:s2" in record["rendered"]
    assert int(probe(base / "cut" / "teste.mp4")["streams"][0]["nb_read_frames"]) == record["frames"]


@pytest.fixture()
def api(world):
    base, ids = world
    mp = pytest.MonkeyPatch()
    mp.setenv("CLONFIELD_FAKE_VRAM", "15")
    mp.setenv("CLONFIELD_COMFY_MODELS", str(base / "models"))
    import cf_factory
    mp.setitem(cf_factory._state, "data", None)  # each test gets its own data folder; the Content Factory guard is per process
    cf_apps.configure(base, base / "outputs")
    client = TestClient(cf_api.build_app(base, base / "outputs", lambda t: t == "pw", "secret"), headers={"Authorization": "Bearer pw"})
    client.base = base
    yield client, ids
    mp.undo()


def test_the_api_renders_a_timeline_as_a_cpu_job_with_its_provenance(api):
    client, ids = api
    bad = timeline(ids)
    bad["video"][1]["src"] = ids["b_asset"]
    assert client.post(f"{BASE}/cinema/validate", json={"timeline": bad}).status_code == 400
    assert client.post(f"{BASE}/cinema/render", json={"timeline": bad}).status_code == 400
    ok = client.post(f"{BASE}/cinema/validate", json={"timeline": timeline(ids)}).json()
    assert ok["ok"] and ok["duration_s"] == 5.0 and ok["shots"] == 4
    job = client.post(f"{BASE}/cinema/render", json={"timeline": timeline(ids)})
    assert job.status_code == 202, job.text
    for _ in range(400):
        done = client.get(f"{BASE}/jobs/{job.json()['id']}").json()
        if done["status"] in ("concluído", "falhou", "cancelado"):
            break
        time.sleep(0.3)
    assert done["status"] == "concluído", done.get("message")
    names = sorted(Path(r["path"]).name for r in done["results"])
    assert names == ["teste-efeitos.wav", "teste-musica.wav", "teste-voz.wav", "teste.mp4", "teste.render.json", "teste.timeline.json"]
    assert set(done["asset_versions"]) == {ids["a"], ids["b"], ids["voice"], ids["music"], ids["sea"]}
    film = next(r for r in done["results"] if r["path"].endswith(".mp4"))
    assert client.get(film["url"]).status_code == 200


def wait(client, job_id):
    for _ in range(600):
        done = client.get(f"{BASE}/jobs/{job_id}").json()
        if done["status"] in ("concluído", "falhou", "cancelado"):
            return done
        time.sleep(0.3)
    raise AssertionError("job não terminou")


def project_body(ids):
    t = timeline(ids)
    t["audio"]["voice"][0]["note"] = "uma fala"
    sea = dict(label="O mar toma conta", music=[dict(src=ids["music"], at=0.0, dur=2.0, fade_out=0.5)],
               sfx=[dict(src=ids["sea"], at=0.0, dur=5.0, loop=True, gain_db=-2)], mix={"music": -3})
    music = dict(label="Música até o fim", music=[dict(src=ids["music"], at=0.0, dur=5.0, loop=True)],
                 sfx=[dict(src=ids["sea"], at=0.0, dur=5.0, loop=True, gain_db=-12)], mix={"music": -3})
    return dict(title="Teste A/B", timeline={**t, "audio": {"voice": t["audio"]["voice"]}}, cuts={"mar": sea, "musica": music}, cut="mar")


def test_a_saved_project_opens_swaps_a_take_and_exports_two_cuts_with_the_same_picture(api):
    client, ids = api
    made = client.post(f"{BASE}/cinema/projects", json=project_body(ids))
    assert made.status_code == 201, made.text
    project = made.json()
    pid = project["id"]
    assert [p["id"] for p in client.get(f"{BASE}/cinema/projects").json()] == [pid]
    opened = client.get(f"{BASE}/cinema/projects/{pid}").json()
    assert [s["id"] for s in opened["shots"]] == ["s1", "s2", "s3", "s4"] and opened["duration_s"] == 5.0
    s3 = opened["shots"][2]
    assert [v["number"] for v in s3["versions"]] == [1, 2] and s3["version"]["number"] == 1 and s3["start"] == 2.5
    assert opened["cuts_view"]["mar"]["lanes"]["voice"][0]["note"] == "uma fala"
    # a take of ANOTHER asset is not a take of this shot
    assert client.post(f"{BASE}/cinema/projects/{pid}/shots/s3", json={"version": ids["a"]}).status_code == 400

    first = wait(client, client.post(f"{BASE}/cinema/projects/{pid}/export", json={"cuts": ["mar", "musica"]}).json()["id"])
    assert first["status"] == "concluído", first.get("message")
    renders = {Path(r["path"]).name: client.get(r["url"]).json() for r in first["results"] if r["path"].endswith(".render.json")}
    sea, music = renders["teste-a-b-mar.render.json"], renders["teste-a-b-musica.render.json"]
    assert "video:s3" in sea["rendered"] and all(not s.startswith("video") and s != "picture" for s in music["rendered"])
    ab = client.get(next(r["url"] for r in first["results"] if r["path"].endswith(".ab.json"))).json()
    assert ab["picture_identical"] and ab["loudness_spread_lu"] <= 0.5, ab  # EBU R128 tolerance for "same level": ±0.5 LU
    assert client.get(f"{BASE}/cinema/projects/{pid}").json()["last_export"] == first["id"]

    swapped = client.post(f"{BASE}/cinema/projects/{pid}/shots/s3", json={"version": ids["b2"]})
    assert swapped.status_code == 200 and swapped.json()["shots"][2]["version"]["number"] == 2
    assert swapped.json()["history"][-1] == {**swapped.json()["history"][-1], "shot": "s3", "numbers": [1, 2]}
    assert client.post(f"{BASE}/cinema/projects/{pid}/cut", json={"cut": "musica"}).json()["cut"] == "musica"
    second = wait(client, client.post(f"{BASE}/cinema/projects/{pid}/export", json={"cuts": ["mar", "musica"]}).json()["id"])
    renders = {Path(r["path"]).name: client.get(r["url"]).json() for r in second["results"] if r["path"].endswith(".render.json")}
    assert renders["teste-a-b-mar.render.json"]["rendered"] == ["video:s3", "picture"]
    assert renders["teste-a-b-musica.render.json"]["rendered"] == []  # the B cut reuses the new picture and its own sound
    # each export keeps its own files: the first A/B pair is still the v1 picture, the second is v2
    first_files = {Path(r["path"]).name: r["path"] for r in first["results"]}
    second_files = {Path(r["path"]).name: r["path"] for r in second["results"]}
    assert first_files["teste-a-b-mar.mp4"] != second_files["teste-a-b-mar.mp4"]
    old = client.get(next(r["url"] for r in first["results"] if r["path"].endswith("mar.render.json"))).json()
    assert "video:s3" in old["rendered"] and len(old["rendered"]) > 2


def test_a_film_starts_empty_and_reaches_a_first_cut_through_the_api(api):
    """The second-film path: empty project, three Library assets, reorder, one duration, reopen, export."""
    client, ids = api
    made = client.post(f"{BASE}/cinema/projects", json={"title": "Segundo filme"})
    assert made.status_code == 201, made.text
    pid = made.json()["id"]
    assert made.json()["shots"] == [] and made.json()["revision"] == 1
    assert client.post(f"{BASE}/cinema/projects/{pid}/export", json={}).status_code == 400  # nothing to export yet
    assert client.post(f"{BASE}/cinema/projects/{pid}/shots", json={"asset": ids["voice"]}).status_code == 400  # audio is not a shot
    for ident in (ids["a"], ids["b_asset"], ids["b2"]):  # a version, an asset (pinned to its current version), a version
        assert client.post(f"{BASE}/cinema/projects/{pid}/shots", json={"asset": ident}).status_code == 200
    project = client.get(f"{BASE}/cinema/projects/{pid}").json()
    assert [s["id"] for s in project["shots"]] == ["s01", "s02", "s03"]
    assert project["shots"][1]["src"] == ids["b2"]  # a_ was pinned to the version that was current (v2)
    order = client.post(f"{BASE}/cinema/projects/{pid}/order", json={"order": ["s03", "s01", "s02"]})
    assert [s["id"] for s in order.json()["shots"]] == ["s03", "s01", "s02"]
    assert client.post(f"{BASE}/cinema/projects/{pid}/order", json={"order": ["s01", "s02"]}).status_code == 400
    longer = client.post(f"{BASE}/cinema/projects/{pid}/shots/s01", json={"dur": 2.5})
    assert longer.status_code == 200 and next(s for s in longer.json()["shots"] if s["id"] == "s01")["loop"] is True  # 1.5 s take, 2.5 s shot
    assert client.post(f"{BASE}/cinema/projects/{pid}/shots/s01", json={"dur": 0.1}).status_code == 400
    reopened = client.get(f"{BASE}/cinema/projects/{pid}").json()
    assert [s["id"] for s in reopened["shots"]] == ["s03", "s01", "s02"] and reopened["revision"] == 1 + 3 + 1 + 1
    assert [h["revision"] for h in reopened["history"]] == [1, 2, 3, 4, 5, 6]
    job = wait(client, client.post(f"{BASE}/cinema/projects/{pid}/export", json={}).json()["id"])
    assert job["status"] == "concluído", job.get("message")
    film = next(r for r in job["results"] if r["path"].endswith(".mp4"))
    frames = int(probe(Path(cf_api_base(client)) / "outputs" / film["path"])["streams"][0]["nb_read_frames"])
    assert frames == round((1.0 + 2.5 + 1.0) * 24)  # s03 (b2, 1 s) + s01 2.5 s + s02 (b2, 1 s) at the default 24 fps
    done = client.get(f"{BASE}/cinema/projects/{pid}").json()
    assert done["last_good"] == job["id"] and done["exports"][-1]["status"] == "concluído" and done["exports"][-1]["revision"] == 6
    assert done["exports"][-1]["signatures"]["principal"] == done["cuts_view"]["principal"]["signature"]


def cf_api_base(client):
    return client.base


def test_a_failed_export_keeps_the_last_finished_pair_and_says_the_timeline_moved_on(api):
    client, ids = api
    pid = client.post(f"{BASE}/cinema/projects", json=project_body(ids)).json()["id"]
    good = wait(client, client.post(f"{BASE}/cinema/projects/{pid}/export", json={"cuts": ["mar", "musica"]}).json()["id"])
    assert good["status"] == "concluído"
    edited = client.post(f"{BASE}/cinema/projects/{pid}/shots/s2", json={"dur": 2.5}).json()  # needs a new s2 segment
    assert edited["exports"][-1]["signatures"]["mar"] != edited["cuts_view"]["mar"]["signature"]  # the pair now shows an older timeline
    blob = ag.resolve(client.base, ids["a"])
    blob.chmod(0o000)  # the take cannot be read: the export has to fail
    try:
        bad = wait(client, client.post(f"{BASE}/cinema/projects/{pid}/export", json={"cuts": ["mar", "musica"]}).json()["id"])
    finally:
        blob.chmod(0o444)
    assert bad["status"] == "falhou" and "ffmpeg" in bad["message"]
    project = client.get(f"{BASE}/cinema/projects/{pid}").json()
    assert project["last_export"] == bad["id"] and project["last_good"] == good["id"]
    assert [e["status"] for e in project["exports"]] == ["concluído", "falhou"]
    assert all(client.get(r["url"]).status_code == 200 for r in good["results"] if r["path"].endswith(".mp4"))  # still playable
