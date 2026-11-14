"""The V8.5 native steps run for real on the CPU: list slicing/merging/filtering, text templates, slideshow, boomerang, blend."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import cf_dag as dag
from test_dag_flow import Ctx, codes, env_for, run  # noqa: F401  (shared fixtures)
from test_dag_flow import world as _world  # noqa: F401

world = _world

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


def test_take_merge_and_text_template(world, tmp_path):
    graph = {"nodes": [
        dict(id="grid", cap="split_grid", inputs={"image": {"media": "photo"}}, params=dict(columns=3, rows=3)),
        dict(id="some", cap="take_images", inputs={"images": {"from": "grid.tiles"}}, params=dict(count=4, every=2, skip=1)),
        dict(id="last", cap="take_images", inputs={"images": {"from": "grid.tiles"}}, params=dict(count=2, reverse=True)),
        dict(id="both", cap="merge_images", inputs={"a": {"from": "some.images"}, "b": {"from": "last.images"}}),
        dict(id="sheet", cap="contact_sheet", inputs={"images": {"from": "both.images"}}, params=dict(columns=3)),
        dict(id="names", cap="text_list", params=dict(text="praia\nmata")),
        dict(id="styled", cap="text_template", each="text", inputs={"text": {"from": "names.texts"}}, params=dict(template="{text}, luz de fim de tarde")),
        dict(id="joined", cap="text_join", inputs={"texts": {"from": "styled.text"}}, params=dict(separator="linha")),
    ]}
    result = run(world, tmp_path, graph)
    assert len(result["nodes"]["some"]["outputs"]["images"]) == 4  # tiles 2,4,6,8 (skip 1, every 2)
    assert len(result["nodes"]["both"]["outputs"]["images"]) == 6
    assert result["nodes"]["styled"]["items"] == 2
    assert result["nodes"]["joined"]["outputs"]["text"]["value"] == "praia, luz de fim de tarde\nmata, luz de fim de tarde"
    with Image.open(result["nodes"]["sheet"]["outputs"]["image"]["path"]) as sheet:
        assert sheet.width > 300


def test_text_template_needs_the_placeholder(world, tmp_path):
    graph = {"nodes": [dict(id="t", cap="text_template", params=dict(template="sem marcador", text="x"))]}
    with pytest.raises(ValueError, match=r"\{text\}"):
        run(world, tmp_path, graph)


def test_keep_passing_drops_the_flat_ones_and_fails_when_none_pass(world, tmp_path):
    graph = {"nodes": [
        dict(id="a", cap="look", inputs={"image": {"media": "photo"}}, params=dict(look="Contraste limpo")),
        dict(id="b", cap="look", inputs={"image": {"media": "flat"}}, params=dict(look="Contraste limpo")),
        dict(id="all", cap="merge_images", inputs={"a": {"from": "a.image"}, "b": {"from": "b.image"}}),
        dict(id="keep", cap="keep_passing", inputs={"images": {"from": "all.images"}}, params=dict(checks=["not_blank"])),
    ]}
    result = run(world, tmp_path, graph)
    report = result["nodes"]["keep"]["outputs"]["report"]["value"]
    assert report["total"] == 2 and report["kept"] == 1 and [r["passed"] for r in report["rows"]] == [True, False]
    assert len(result["nodes"]["keep"]["outputs"]["images"]) == 1
    only_flat = {"nodes": [dict(id="b", cap="look", inputs={"image": {"media": "flat"}}), dict(id="keep", cap="keep_passing", inputs={"images": {"from": "b.image"}}, params=dict(checks=["not_blank"]))]}
    with pytest.raises(ValueError, match="Nenhuma"):
        run(world, tmp_path, only_flat)


def test_blend_mixes_two_real_images(world, tmp_path):
    graph = {"nodes": [dict(id="mix", cap="blend", inputs={"a": {"media": "photo"}, "b": {"media": "flat"}}, params=dict(mix=100))]}
    path = run(world, tmp_path, graph)["nodes"]["mix"]["outputs"]["image"]["path"]
    with Image.open(path) as image:
        assert image.convert("RGB").getpixel((5, 5)) == (128, 128, 128)  # 100% of the flat grey


@needs_ffmpeg
def test_slideshow_makes_a_video_of_the_right_length(world, tmp_path):
    graph = {"nodes": [
        dict(id="grid", cap="split_grid", inputs={"image": {"media": "photo"}}, params=dict(columns=3, rows=1)),
        dict(id="show", cap="slideshow", inputs={"images": {"from": "grid.tiles"}}, params=dict(seconds=1, ratio="Quadrado · 1:1", zoom=True, fade=True)),
    ]}
    result = run(world, tmp_path, graph)
    path = result["nodes"]["show"]["outputs"]["video"]["path"]
    assert abs(probe(path) - 3.0) < 0.4


@needs_ffmpeg
def test_boomerang_doubles_and_speed_halves(world, tmp_path):
    graph = {"nodes": [
        dict(id="boom", cap="video_fx", inputs={"video": {"media": "clip-a"}}, params=dict(op="boomerang")),
        dict(id="fast", cap="video_fx", inputs={"video": {"media": "clip-a"}}, params=dict(op="speed", factor=2)),
        dict(id="seam", cap="loop_check", inputs={"video": {"from": "boom.video"}}),
    ]}
    result = run(world, tmp_path, graph)
    assert abs(probe(result["nodes"]["boom"]["outputs"]["video"]["path"]) - 6.0) < 0.5
    assert abs(probe(result["nodes"]["fast"]["outputs"]["video"]["path"]) - 1.5) < 0.4
    assert result["nodes"]["seam"]["outputs"]["report"]["value"]["passed"] is True  # forward + reverse meets itself at both ends
