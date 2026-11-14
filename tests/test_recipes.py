"""Recipes: forms resolve with plain-language errors, every graph validates against the real registry, CPU recipes run for real."""
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

import cf_apps
import cf_capabilities as caps
import cf_dag as dag
import cf_recipes as recipes
import cf_tiers


class Ctx:
    def __init__(self):
        self.control = SimpleNamespace(cancelled=False, prompt_id=None)

    def progress(self, *a, **k):
        pass

    def check(self):
        pass


def ident(n):
    return f"{n:032x}"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    import os
    os.environ["CLONFIELD_FAKE_VRAM"] = "24"
    import cf_factory
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path_factory.mktemp("rec")
    cf_apps.configure(base, base / "outputs")
    tier = cf_tiers.detect()
    registry = caps.Registry(cf_apps.registry(), tier)
    folder = tmp_path_factory.mktemp("rm")
    media = {}
    for n in range(1, 5):
        image = Image.new("RGB", (200, 140), (20 * n, 60, 90))
        d = ImageDraw.Draw(image)
        d.ellipse((40, 20, 160, 120), fill=(230, 190, 120))
        d.rectangle((90, 50, 110, 90), fill=(30 * n, 30, 30))
        image.save(folder / f"i{n}.png")
        media[ident(n)] = dict(type="image", path=str(folder / f"i{n}.png"))
    if shutil.which("ffmpeg"):
        for n in (10, 11):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=160x120:rate=12:duration=3,hue=h={n * 9}", "-pix_fmt", "yuv420p", str(folder / f"v{n}.mp4")], check=True, timeout=60)
            media[ident(n)] = dict(type="video", path=str(folder / f"v{n}.mp4"))
    return registry, tier, media, base


def go(world, tmp_path, rid, raw):
    registry, tier, media, base = world
    graph = recipes.graph_for(rid, raw)
    report = dag.validate(graph, registry, tier, media.get)
    assert report["ok"], report["errors"]
    return dag.execute(graph, registry, dag.Env(base, tmp_path / "out", tier, media.get), Ctx())


def test_every_recipe_graph_validates_against_the_real_registry(world):
    registry, tier, media, _ = world
    for rid, recipe in recipes.RECIPES.items():
        raw = {}
        for spec in recipe.inputs:
            if spec["kind"] in ("image", "video"):
                raw[spec["id"]] = ident(1 if spec["kind"] == "image" else 10)
            elif spec["kind"] in ("images", "videos"):
                raw[spec["id"]] = [ident(1), ident(2)] if spec["kind"] == "images" else [ident(10), ident(11)]
        graph = recipes.graph_for(rid, raw)
        report = dag.validate(graph, registry, tier, media.get)
        assert report["ok"], (rid, report["errors"])
        assert all(n.get("label") for n in graph["nodes"]), rid  # every step has a name the screen can show
    assert recipes.catalog() and {r["lane"] for r in recipes.catalog()} == {"cpu", "gpu"}


def test_form_errors_are_in_plain_language():
    with pytest.raises(ValueError, match="envie de 1 a 16"):
        recipes.resolve(recipes.get("polir_lote"), {"images": []})
    with pytest.raises(ValueError, match="escolha uma das opções"):
        recipes.resolve(recipes.get("polir_lote"), {"images": [ident(1)], "look": "inexistente"})
    with pytest.raises(ValueError, match="envie uma imagem"):
        recipes.resolve(recipes.get("looks_lado_a_lado"), {"image": "../etc/passwd"})
    with pytest.raises(ValueError, match="use de 2 a 6 linhas"):
        recipes.resolve(recipes.get("storyboard_em_filme"), {"shots": "só um plano"})
    with pytest.raises(KeyError):
        recipes.get("nao-existe")


def test_polish_batch_runs_per_item_and_caches_per_item(world, tmp_path):
    raw = dict(images=[ident(1), ident(2), ident(3)], ratio="Quadrado · 1:1", look="Frio suave", strength=60)
    first = go(world, tmp_path, "polir_lote", raw)
    assert first["nodes"]["frame"]["items"] == 3 and first["nodes"]["look"]["items"] == 3
    with Image.open(first["nodes"]["frame"]["outputs"]["image"][0]["path"]) as img:
        assert img.size == (1080, 1080)
    again = go(world, tmp_path, "polir_lote", raw)
    assert set(again["cached"]) == {"frame", "look", "sheet", "best"}
    swapped = go(world, tmp_path, "polir_lote", {**raw, "images": [ident(1), ident(2), ident(4)]})
    assert swapped["nodes"]["frame"]["cached_items"] == 2 and swapped["nodes"]["look"]["cached_items"] == 2
    assert len(dag.final_files(first)) == 2  # the sheet and the best picture


def test_looks_side_by_side_binds_each_look(world, tmp_path):
    result = go(world, tmp_path, "looks_lado_a_lado", dict(image=ident(1), strength=90))
    assert result["nodes"]["graded"]["items"] == 4
    assert result["nodes"]["graded"]["params"] == dict(strength=90)
    hashes = {o["sha256"] for o in result["nodes"]["graded"]["outputs"]["image"]}
    assert len(hashes) == 4  # four looks, four different pictures


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")
def test_video_recipes(world, tmp_path):
    frames = go(world, tmp_path, "folha_de_quadros", dict(video=ident(10), every_s=1, max=8))
    assert len(frames["nodes"]["frames"]["outputs"]["frames"]) == 3
    seq = go(world, tmp_path, "clipes_em_sequencia", dict(videos=[ident(10), ident(11)], ratio="Quadrado · 1:1", mute=True))
    assert Path(seq["nodes"]["join"]["outputs"]["video"]["path"]).stat().st_size > 1000
    assert "ratio" in seq["nodes"]["seam"]["outputs"]["report"]["value"]


def test_cutouts_use_the_real_u2net_on_cpu(world, tmp_path):
    import cf_bgremove
    try:
        cf_bgremove.ensure(world[3], "u2netp")
    except Exception as exc:  # no network on this box: say so instead of faking a result
        pytest.skip(f"modelo U²-Net indisponível: {exc}")
    result = go(world, tmp_path, "recortes_em_lote", dict(images=[ident(1), ident(2)], background="Transparente"))
    assert result["nodes"]["cut"]["items"] == 2
    with Image.open(result["nodes"]["cut"]["outputs"]["result"][0]["path"]) as cut:
        assert cut.mode == "RGBA" and cut.getchannel("A").getextrema()[0] < 255
