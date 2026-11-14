"""DAG control flow on real files and real CPU steps: fan-out (`each`), list sources, binds, conditions, per-item cache, limits."""
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

import cf_apps
import cf_capabilities as caps
import cf_dag as dag
import cf_tiers


class Ctx:
    def __init__(self):
        self.control = SimpleNamespace(cancelled=False, prompt_id=None)
        self.notes = []

    def progress(self, fraction=None, desc=None, **_):
        self.notes.append(desc)

    def check(self):
        pass


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    import os
    os.environ["CLONFIELD_FAKE_VRAM"] = "15"
    import cf_factory
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path_factory.mktemp("flow")
    cf_apps.configure(base, base / "outputs")
    tier = cf_tiers.detect()
    registry = caps.Registry(cf_apps.registry(), tier)
    folder = tmp_path_factory.mktemp("media")
    photo = Image.new("RGB", (240, 160), (30, 40, 60))
    d = ImageDraw.Draw(photo)
    d.ellipse((40, 20, 200, 140), fill=(220, 180, 120))
    for x in range(0, 240, 12):
        d.line((x, 0, 240 - x, 160), fill=(255, 255, 255), width=2)
    photo.save(folder / "photo.png")
    Image.new("RGB", (240, 160), (128, 128, 128)).save(folder / "flat.png")
    media = {"photo": dict(type="image", path=str(folder / "photo.png")), "flat": dict(type="image", path=str(folder / "flat.png"))}
    if shutil.which("ffmpeg"):
        for name, color in (("clip-a", "red"), ("clip-b", "blue")):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=160x120:rate=12:duration=3,hue=h={30 if color == 'red' else 200}",
                            "-pix_fmt", "yuv420p", str(folder / f"{name}.mp4")], check=True, timeout=60)
            media[name] = dict(type="video", path=str(folder / f"{name}.mp4"))
    return registry, tier, media, base


def env_for(world, tmp_path):
    registry, tier, media, base = world
    return dag.Env(base, tmp_path / "out", tier, lambda ident: media.get(ident))


def run(world, tmp_path, graph, **kw):
    return dag.execute(graph, world[0], env_for(world, tmp_path), Ctx(), **kw)


def codes(world, graph):
    return {e["code"] for e in dag.validate(graph, world[0], world[1], lambda i: world[2].get(i))["errors"]}


def test_split_each_sheet_pick(world, tmp_path):
    graph = {"nodes": [
        dict(id="src", cap="split_grid", inputs={"image": {"media": "photo"}}, params=dict(columns=3, rows=2)),
        dict(id="warm", cap="look", each="image", inputs={"image": {"from": "src.tiles"}}, params=dict(look="Cinema quente")),
        dict(id="sheet", cap="contact_sheet", inputs={"images": {"from": "warm.image"}}, params=dict(columns=3)),
        dict(id="best", cap="pick_best", inputs={"images": {"from": "warm.image"}}, params=dict(by="contrast")),
    ]}
    result = run(world, tmp_path, graph)
    assert result["nodes"]["warm"]["items"] == 6
    assert len(result["nodes"]["warm"]["outputs"]["image"]) == 6
    sheet = result["nodes"]["sheet"]["outputs"]["image"]
    with Image.open(sheet["path"]) as image:
        assert image.width > 600  # 3 columns of real cells
    ranking = result["nodes"]["best"]["outputs"]["report"]["value"]["ranking"]
    assert len(ranking) == 6 and ranking[0]["score"] >= ranking[-1]["score"]
    assert Path(result["nodes"]["best"]["outputs"]["image"]["path"]).is_file()


def test_per_item_cache_recomputes_only_the_changed_item(world, tmp_path):
    def graph(lines):
        return {"nodes": [dict(id="list", cap="text_list", params=dict(text=lines)),
                          dict(id="cap", cap="caption", each="text", inputs={"image": {"media": "photo"}}, bind={"text": "list.texts"}, params=dict(position="cima"))]}
    first = run(world, tmp_path, graph("um\ndois\ntrês"))
    assert first["nodes"]["cap"]["cached_items"] == 0 and first["nodes"]["cap"]["items"] == 3
    again = run(world, tmp_path, graph("um\ndois\ntrês"))
    assert again["nodes"]["cap"]["status"] == "em cache" and again["nodes"]["cap"]["cached_items"] == 3
    edited = run(world, tmp_path, graph("um\ndois\nquatro"))
    assert edited["nodes"]["cap"]["cached_items"] == 2 and edited["nodes"]["cap"]["status"] == "concluído"
    forced = run(world, tmp_path, graph("um\ndois\nquatro"), force=["cap"])
    assert forced["nodes"]["cap"]["cached_items"] == 0


def test_scenario_matrix_feeds_bound_each(world, tmp_path):
    graph = {"nodes": [
        dict(id="m", cap="scenario_matrix", params=dict(template="{quem} na {onde}", axes=dict(quem=["a menina", "o cão"], onde=["praia", "cidade", "mata"]))),
        dict(id="c", cap="caption", each="text", inputs={"image": {"media": "photo"}}, bind={"text": "m.texts"}),
        dict(id="s", cap="contact_sheet", inputs={"images": {"from": "c.image"}}, params=dict(columns=3)),
    ]}
    result = run(world, tmp_path, graph)
    table = result["nodes"]["m"]["outputs"]["table"]["value"]
    assert len(table) == 6 and table[0]["text"] == "a menina na praia" and table[-1]["text"] == "o cão na mata"
    assert result["nodes"]["c"]["items"] == 6
    assert dag.final_files(result) and all(p.is_file() for p in dag.final_files(result))


def test_bind_path_into_json(world, tmp_path):
    graph = {"nodes": [
        dict(id="m", cap="scenario_matrix", params=dict(template="{x}", axes=dict(x=["alfa"]))),
        dict(id="one", cap="caption", inputs={"image": {"media": "photo"}}, bind={"text": {"from": "m.table", "path": "0.text"}}),
    ]}
    assert run(world, tmp_path, graph)["nodes"]["one"]["status"] == "concluído"


def test_when_skips_branch_and_descendants(world, tmp_path):
    graph = {"nodes": [
        dict(id="gate", cap="quality_gate", inputs={"image": {"media": "flat"}}, params=dict(checks=["not_blank"])),
        dict(id="grade", cap="look", inputs={"image": {"from": "gate.image"}}, when={"from": "gate.report", "path": "passed", "equals": True}),
        dict(id="frame", cap="frame", inputs={"image": {"from": "grade.image"}}),
        dict(id="always", cap="caption", inputs={"image": {"media": "photo"}}, params=dict(text="sempre")),
    ]}
    result = run(world, tmp_path, graph)
    assert result["nodes"]["gate"]["outputs"]["report"]["value"]["passed"] is False
    assert result["nodes"]["grade"]["status"] == "ignorado" and "condição" in result["nodes"]["grade"]["reason"]
    assert result["nodes"]["frame"]["status"] == "ignorado"
    assert result["nodes"]["always"]["status"] == "concluído"
    assert set(result["skipped"]) == {"grade", "frame"}
    assert list(result["final"]) == ["always"]  # the skipped sink produced nothing and is not reported as a result

    sharp = {"nodes": [dict(id="gate", cap="quality_gate", inputs={"image": {"media": "photo"}}, params=dict(checks=["not_blank"])),
                       dict(id="grade", cap="look", inputs={"image": {"from": "gate.image"}}, when={"from": "gate.report", "path": "passed", "equals": True})]}
    assert run(world, tmp_path, sharp)["nodes"]["grade"]["status"] == "concluído"


def test_validation_explains_control_flow_mistakes(world):
    one_to_one = {"nodes": [dict(id="s", cap="split_grid", inputs={"image": {"media": "photo"}}),
                            dict(id="l", cap="look", inputs={"image": {"from": "s.tiles"}})]}
    assert "list_to_single" in codes(world, one_to_one)
    assert "bad_each" in codes(world, {"nodes": [dict(id="l", cap="look", each="nope", inputs={"image": {"media": "photo"}})]})
    assert "bind_conflict" in codes(world, {"nodes": [dict(id="t", cap="text_list", params=dict(text="a")),
                                                      dict(id="c", cap="caption", inputs={"image": {"media": "photo"}}, params=dict(text="x"), bind={"text": "t.texts"})]})
    assert "list_to_single" in codes(world, {"nodes": [dict(id="t", cap="text_list", params=dict(text="a")),
                                                       dict(id="c", cap="caption", inputs={"image": {"media": "photo"}}, bind={"text": "t.texts"})]})
    assert "bad_bind" in codes(world, {"nodes": [dict(id="s", cap="split_grid", inputs={"image": {"media": "photo"}}),
                                                 dict(id="c", cap="caption", each="text", inputs={"image": {"media": "photo"}}, bind={"text": "s.tiles"})]})
    assert "bad_when" in codes(world, {"nodes": [dict(id="l", cap="look", inputs={"image": {"media": "photo"}}, when={"equals": 1})]})
    assert "cycle" in codes(world, {"nodes": [dict(id="a", cap="caption", inputs={"image": {"media": "photo"}}, bind={"text": "b.texts"}, params={}),
                                              dict(id="b", cap="text_list", params=dict(text="x"), when={"from": "a.image", "equals": 1})]})


def test_limits_are_refused_with_a_reason(world, tmp_path):
    big = {"nodes": [dict(id="m", cap="scenario_matrix", params=dict(template="{a}{b}", axes=dict(a=list("abcdefg"), b=list("12345"))))]}
    with pytest.raises(ValueError, match="35 combinações"):
        run(world, tmp_path, big)
    with pytest.raises(ValueError, match="{eixo}"):
        run(world, tmp_path, {"nodes": [dict(id="m", cap="scenario_matrix", params=dict(template="sem eixo", axes={}))]})
    with pytest.raises(ValueError, match="limite"):
        run(world, tmp_path, {"nodes": [dict(id="t", cap="text_list", params=dict(text=";".join(f"x{i}" for i in range(33))))]})


def test_direction_and_cast_steps(world, tmp_path):
    import cf_cast
    base = world[3]
    photo = Image.new("RGB", (64, 64), (200, 90, 60))
    path = tmp_path / "ref.png"
    photo.save(path)
    item = cf_cast.add(base, "Mira", "jovem de jaqueta vermelha", str(path))
    try:
        _cast_scene(world, tmp_path)
    finally:
        cf_cast.remove(base, item["id"])


def _cast_scene(world, tmp_path):
    graph = {"nodes": [
        dict(id="t", cap="text_list", params=dict(text="@Mira corre na chuva")),
        dict(id="cast", cap="cast_expand", each="prompt", bind={"prompt": "t.texts"}, params=dict(ref_slots=1)),
        dict(id="dir", cap="direction", each="text", inputs={"text": {"from": "cast.text"}}, params=dict(dir_genre="noir")),
    ]}
    result = run(world, tmp_path, graph)
    final = result["nodes"]["dir"]["outputs"]["text"]
    assert len(final) == 1 and "jovem de jaqueta vermelha" in final[0]["value"] and "noir" in final[0]["value"].lower()
    info = result["nodes"]["cast"]["outputs"]["info"][0]["value"]
    assert info["used"] == ["Mira"] and len(info["refs"]) == 1


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")
def test_video_frames_join_and_loop_check(world, tmp_path):
    graph = {"nodes": [
        dict(id="f", cap="video_frames", inputs={"video": {"media": "clip-a"}}, params=dict(every_s=1, max=5)),
        dict(id="cap", cap="caption", each="image", inputs={"image": {"from": "f.frames"}}, params=dict(text="quadro")),
        dict(id="sheet", cap="contact_sheet", inputs={"images": {"from": "cap.image"}}, params=dict(columns=3)),
        dict(id="join", cap="video_join", inputs={"videos": [{"media": "clip-a"}, {"media": "clip-b"}]}, params=dict(ratio="Quadrado · 1:1", mute=True)),
        dict(id="seam", cap="loop_check", inputs={"video": {"from": "join.video"}}),
    ]}
    result = run(world, tmp_path, graph)
    assert result["nodes"]["f"]["outputs"]["frames"].__len__() == 3  # 3 s clip, one frame per second
    assert Path(result["nodes"]["join"]["outputs"]["video"]["path"]).stat().st_size > 1000
    report = result["nodes"]["seam"]["outputs"]["report"]["value"]
    assert report["frames"] >= 3 and "passed" in report and "ratio" in report
