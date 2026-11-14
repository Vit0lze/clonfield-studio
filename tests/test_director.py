"""Direção de cinema: the vocabulary, the compile rules, and the wiring into the image and video apps (generation itself needs a GPU)."""

import pytest

import cf_apps
import cf_director as d
import cf_jobs
import cf_tiers


def test_vocabulary_is_well_formed():
    assert set(d.ORDER) == set(d.AXES)
    for axis, (label, options) in d.AXES.items():
        ids = [o[0] for o in options]
        assert label and len(ids) == len(set(ids)) and d.AUTO not in ids, axis
        assert all(text.strip() and text.isascii() for _, _, text in options)  # the model gets English; the labels are Portuguese
    for genre, sets in d.GENRE_DEFAULTS.items():
        assert genre in [o[0] for o in d.AXES["genre"][1]]
        for axis, option in sets.items():
            assert axis != "genre" and option in [o[0] for o in d.AXES[axis][1]], (genre, axis, option)
    assert set(d.GENRE_DEFAULTS) == {o[0] for o in d.AXES["genre"][1]}  # every genre has defaults


def test_all_auto_leaves_the_prompt_exactly_as_written():
    assert d.apply("uma raposa na neve", {}) == "uma raposa na neve"
    assert d.apply("  texto sem ponto  ", {"dir_genre": "auto", "dir_light": "auto"}) == "  texto sem ponto  "


def test_genre_fills_the_unset_axes_and_an_explicit_pick_wins():
    picks = d.picks_from({"dir_genre": "noir"})
    assert d.effective(picks) == dict(genre="noir", light="chiaroscuro", film="bw", look="noir", grade="mono")
    over = d.effective(d.picks_from({"dir_genre": "noir", "dir_light": "neon", "dir_grade": "teal"}))
    assert over["light"] == "neon" and over["grade"] == "teal" and over["film"] == "bw"
    text = d.apply("um detetive na chuva", {"dir_genre": "noir", "dir_light": "neon"})
    assert text.startswith("um detetive na chuva. film noir") and "saturated neon light" in text and "chiaroscuro" not in text


def test_phrases_join_in_the_fixed_order_with_full_stops():
    text = d.apply("Cena.", {"dir_framing": "close", "dir_camera": "tele", "dir_grade": "mono"})
    assert text == "Cena. close-up on the face. 135mm telephoto lens, compressed background, creamy falloff. monochrome grade."
    assert d.compile_prompt(["a", "b?", "", None, " c! "]) == "a. b? c!"


def test_an_unknown_option_is_refused_with_the_axis_named():
    with pytest.raises(ValueError, match="Luz"):
        d.picks_from({"dir_light": "disco"})


# ---------------------------------------------------------------- the apps
def fields(app_id, monkeypatch):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    return {f["id"]: f for f in cf_apps.registry()[app_id].fields(cf_tiers.detect())}


def test_create_and_the_video_apps_offer_the_direction_with_only_the_genre_up_front(monkeypatch):
    for app_id in ("create", "text2video", "animate"):
        got = fields(app_id, monkeypatch)
        assert got["dir_genre"]["default"] == "auto" and not got["dir_genre"]["advanced"], app_id
        assert all(got[d.field_id(a)]["advanced"] for a in d.ORDER if a != "genre") and len(got[d.field_id("light")]["options"]) == len(d.AXES["light"][1]) + 1
    assert "dir_genre" not in fields("edit", monkeypatch) and "dir_genre" not in fields("character_sheet", monkeypatch)


class Ctx:
    control = None
    class job: id = "j"
    def progress(self, *a, **k): pass
    def check(self): pass


def test_video_job_sends_the_compiled_prompt_to_the_text_encoder(monkeypatch, tmp_path):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    seen = {}

    def run(graph, out_dir, progress, **kwargs):
        seen["graph"] = graph
        raise cf_jobs.JobError("parou antes do ComfyUI", "falhou")
    monkeypatch.setattr(cf_apps.workflows, "run", run)
    ctx = Ctx()
    ctx.out_dir = tmp_path
    base = dict(mode="Texto em vídeo", model="5b-q6", size="Horizontal · 512 × 288 (rápido)", seconds=2, steps=20, seed=3, negative="blur")
    with pytest.raises(cf_jobs.JobError, match="parou"):
        cf_apps.run_wan(ctx, dict(base, prompt="uma raposa corre na neve", dir_genre="epic", dir_framing="wide"), cf_tiers.detect())
    positive = seen["graph"]["6"]["inputs"]["text"]
    assert positive.startswith("uma raposa corre na neve. sweeping epic") and "wide establishing shot" in positive and "anamorphic 40mm" in positive
    with pytest.raises(cf_jobs.JobError, match="parou"):
        cf_apps.run_wan(ctx, dict(base, prompt="uma raposa corre na neve"), cf_tiers.detect())
    assert seen["graph"]["6"]["inputs"]["text"] == "uma raposa corre na neve"  # nothing added without a direction
    with pytest.raises(cf_jobs.JobError, match="Luz"):
        cf_apps.run_wan(ctx, dict(base, prompt="x", dir_light="disco"), cf_tiers.detect())


def test_image_job_compiles_the_direction_before_building_the_graph(monkeypatch, tmp_path):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    seen = {}

    def fake(ctx, preset, p, files, width, height, count, progress_total=None):
        seen.update(prompt=p["prompt"], model=preset.key)
        return []
    monkeypatch.setattr(cf_apps, "run_graph_images", fake)
    monkeypatch.setattr(cf_apps, "reach_final_size", lambda ctx, outputs, plan, method: outputs)
    monkeypatch.setattr(cf_apps, "post_upscale", lambda ctx, outputs, choice: outputs)
    ctx = Ctx()
    ctx.out_dir = tmp_path
    cf_apps.run_image(ctx, dict(model="flux2", prompt="retrato de uma mulher", dir_genre="drama", dir_light="golden", refs=[]), cf_tiers.detect())
    assert seen["prompt"].startswith("retrato de uma mulher. intimate character drama") and "golden-hour sun" in seen["prompt"] and "overcast" not in seen["prompt"]
