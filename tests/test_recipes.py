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


def probe_seconds(path):
    import json
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")
def test_slideshow_recipe_makes_a_real_video(world, tmp_path):
    run = go(world, tmp_path, "apresentacao_de_imagens", dict(images=[ident(1), ident(2), ident(3)], ratio="Quadrado · 1:1", look="Preto e branco", seconds=1, zoom=True))
    assert run["nodes"]["frame"]["items"] == 3 and run["nodes"]["look"]["items"] == 3
    video = run["nodes"]["show"]["outputs"]["video"]["path"]
    assert abs(probe_seconds(video) - 3.0) < 0.4
    assert run["nodes"]["seam"]["outputs"]["report"]["value"]["ratio"] >= 0


def test_best_of_recipe_discards_the_flat_picture_for_real(world, tmp_path):
    flat = ident(99)
    registry, tier, media, base = world
    flat_path = tmp_path / "flat.png"
    Image.new("RGB", (200, 140), (128, 128, 128)).save(flat_path)
    media = {**media, flat: dict(type="image", path=str(flat_path))}
    graph = recipes.graph_for("melhores_do_lote", dict(images=[ident(1), flat, ident(2)], checks=["not_blank"], count=4, look="Frio suave"))
    run = dag.execute(graph, registry, dag.Env(base, tmp_path / "out", tier, media.get), Ctx())
    assert run["nodes"]["keep"]["outputs"]["report"]["value"]["kept"] == 2
    assert run["nodes"]["look"]["items"] == 2
    with pytest.raises(ValueError, match="escolha entre"):
        recipes.graph_for("melhores_do_lote", dict(images=[ident(1)], checks=[], count=1, look="Frio suave"))


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")
def test_storyboard_animatic_recipe_numbers_the_shots_and_cuts_the_video(world, tmp_path):
    shots = [ident(1), ident(2), ident(3), ident(4)]
    run = go(world, tmp_path, "animatic_do_storyboard", dict(images=shots, ratio="Paisagem · 16:9", look="Sem look", seconds=1, zoom=False, fade=True))
    assert "look" not in run["nodes"]  # «Sem look» leaves the grade step out instead of running it at zero
    assert run["nodes"]["frame"]["items"] == 4
    with Image.open(run["nodes"]["sheet"]["outputs"]["image"]["path"]) as sheet:
        assert sheet.width > 300
    assert abs(probe_seconds(run["nodes"]["show"]["outputs"]["video"]["path"]) - 4.0) < 0.5
    graded = go(world, tmp_path, "animatic_do_storyboard", dict(images=shots[:2], ratio="Quadrado · 1:1", look="Preto e branco", seconds=1, zoom=True, fade=False))
    assert graded["nodes"]["look"]["items"] == 2
    labels = recipes.graph_for("animatic_do_storyboard", dict(images=shots, ratio="Paisagem · 16:9", look="Sem look", seconds=1, zoom=True, fade=True))["nodes"][1]["params"]["labels"]
    assert labels == ["Plano 1", "Plano 2", "Plano 3", "Plano 4"]
    with pytest.raises(ValueError):
        recipes.graph_for("animatic_do_storyboard", dict(images=shots[:1], ratio="Paisagem · 16:9", look="Sem look", seconds=1, zoom=True, fade=True))


def test_shots_to_film_recipe_validates_and_never_regenerates(world):
    registry, tier, media, base = world
    graph = recipes.graph_for("planos_em_filme", dict(images=[ident(1), ident(2)], motion="slow push in", ratio="Paisagem · 16:9", seconds=3))
    assert [n["cap"] for n in graph["nodes"]] == ["frame", "app.animate", "video_join", "loop_check"]
    assert not any(n["cap"] == "app.create" for n in graph["nodes"])  # the shots are inputs, not regenerated
    report = dag.validate(graph, registry, tier, media.get)
    assert report["ok"], report["errors"]
    assert recipes.get("planos_em_filme").state == "BLOQUEADO_GPU"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")
def test_boomerang_recipe_loops_each_clip_and_joins(world, tmp_path):
    run = go(world, tmp_path, "boomerang_de_clipes", dict(videos=[ident(10), ident(11)], ratio="Paisagem · 16:9"))
    assert run["nodes"]["boom"]["items"] == 2
    assert abs(probe_seconds(run["nodes"]["join"]["outputs"]["video"]["path"]) - 12.0) < 1.0  # two 3 s clips, each there and back
    single = go(world, tmp_path, "boomerang_de_clipes", dict(videos=[ident(10)], ratio="Paisagem · 16:9"))
    assert "join" not in single["nodes"] and abs(probe_seconds(single["nodes"]["boom"]["outputs"]["video"]["path"]) - 6.0) < 0.6


def test_sweep_recipe_binds_numbers_into_a_number_parameter_for_real(world, tmp_path):
    run = go(world, tmp_path, "varredura_de_intensidade", dict(image=ident(1), look="Cinema quente", start=0, stop=100, count=5))
    assert [a["value"] for a in run["nodes"]["values"]["outputs"]["values"]] == ["0", "25", "50", "75", "100"]
    assert run["nodes"]["graded"]["items"] == 5
    import numpy as np
    images = [Image.open(a["path"]).convert("RGB") for a in run["nodes"]["graded"]["outputs"]["image"]]
    gap = [float(np.abs(np.asarray(images[0], dtype=float) - np.asarray(im, dtype=float)).mean()) for im in images[1:]]
    assert all(g > 0 for g in gap) and gap[-1] > gap[0]  # 0% is the base; a stronger setting moves the picture further: the bound number really reached the step


def test_sweep_step_and_bind_coercion_limits(world, tmp_path):
    registry, tier, media, base = world
    env = dag.Env(base, tmp_path / "out", tier, media.get)
    seeds = {"nodes": [dict(id="s", cap="sweep", params=dict(start=1000, stop=1003, count=4, integer=True))]}
    assert [a["value"] for a in dag.execute(seeds, registry, env, Ctx())["nodes"]["s"]["outputs"]["values"]] == ["1000", "1001", "1002", "1003"]
    with pytest.raises(ValueError, match="se repetiriam"):
        dag.execute({"nodes": [dict(id="s", cap="sweep", params=dict(start=1, stop=2, count=5, integer=True))]}, registry, env, Ctx())
    bad = {"nodes": [dict(id="t", cap="text_list", params=dict(text="abc")), dict(id="g", cap="look", each="strength", inputs={"image": {"media": ident(1)}}, bind={"strength": "t.texts"})]}
    with pytest.raises(ValueError, match="precisa ser número"):
        dag.execute(bad, registry, env, Ctx())


def test_check_and_fix_is_a_real_if_else(world, tmp_path):
    from PIL import ImageFilter
    registry, tier, media, base = world
    soft_path = tmp_path / "soft.png"
    Image.open(media[ident(1)]["path"]).filter(ImageFilter.GaussianBlur(14)).save(soft_path)
    media = {**media, ident(90): dict(type="image", path=str(soft_path))}

    def go_with(image):
        graph = recipes.graph_for("conferir_e_consertar", dict(image=image, checks=["sharp"], ratio=recipes.RATIOS[0], sharpen=100))
        report = dag.validate(graph, registry, tier, media.get)
        assert report["ok"], report["errors"]
        return dag.execute(graph, registry, dag.Env(base, tmp_path / "out", tier, media.get), Ctx())

    sharp = go_with(ident(1))
    assert sharp["nodes"]["gate"]["outputs"]["report"]["value"]["passed"] is True
    assert sharp["nodes"]["keep"]["status"] == "concluído" and sharp["nodes"]["fix"]["status"] == "ignorado" and sharp["nodes"]["reframe"]["status"] == "ignorado"
    assert sharp["nodes"]["final"]["status"] == "concluído"
    soft = go_with(ident(90))
    assert soft["nodes"]["gate"]["outputs"]["report"]["value"]["passed"] is False
    assert soft["nodes"]["keep"]["status"] == "ignorado" and soft["nodes"]["fix"]["status"] == "concluído" and soft["nodes"]["reframe"]["status"] == "concluído"
    assert soft["nodes"]["final"]["status"] == "concluído"
    with Image.open(soft["nodes"]["final"]["outputs"]["image"]["path"]) as out:
        assert out.size == (1080, 1920)  # the fixed branch reached the end


def test_not_inverts_a_condition_and_first_of_needs_one_branch(world, tmp_path):
    registry, tier, media, base = world
    env = dag.Env(base, tmp_path / "out", tier, media.get)
    assert dag.condition_holds({"path": "x", "equals": 1}, {"x": 1}) is True
    assert dag.condition_holds({"path": "x", "equals": 1, "not": True}, {"x": 1}) is False
    assert dag.condition_holds({"path": "x", "gte": 5, "not": True}, {"x": 1}) is True
    both_skipped = {"nodes": [
        dict(id="gate", cap="quality_gate", inputs={"image": {"media": ident(1)}}, params=dict(checks=["not_blank"])),
        dict(id="a", cap="frame", inputs={"image": {"from": "gate.image"}}, when={"from": "gate.report", "path": "passed", "equals": False}),
        dict(id="end", cap="first_of", inputs={"a": {"from": "a.image"}}),
    ]}
    with pytest.raises(ValueError, match="Nenhum dos ramos"):
        dag.execute(both_skipped, registry, env, Ctx())


def test_video_recipes_never_pair_the_fast_mode_with_the_5b_model():
    """Found on the T4: «Planos prontos em filme» asked for fast mode on the default 5B, which only the A14B has, and the job failed."""
    import cf_wan
    for recipe_id, values in (("planos_em_filme", dict(images=[ident(1), ident(2)], motion="x", ratio="Paisagem · 16:9", seconds=3)),
                              ("storyboard_em_filme", dict(shots="a\nb", motion="x", genre="drama", seconds=3)),
                              ("loop_de_imagem", dict(image=ident(1), prompt="x", seconds=3))):
        graph = recipes.graph_for(recipe_id, values)
        for node in graph["nodes"]:
            if node["cap"] in ("app.animate", "app.flf2v"):
                params = node["params"]
                model = params.get("model") or ("a14b-q6" if node["cap"] == "app.flf2v" else cf_wan.DEFAULT_MODEL)
                assert not (params.get("fast") and cf_wan.MODELS[model]["kind"] != "a14b"), (recipe_id, node["id"], model)
