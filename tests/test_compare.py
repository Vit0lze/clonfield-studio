"""Comparar modelos: the pure parts (validation, timing record, sheet) with real images, and the orchestration with the generation call replaced
by a function that writes a real PNG (the models themselves need a GPU: BLOQUEADO_GPU)."""

import json
import time

import numpy as np
import pytest
from PIL import Image

import cf_apps
import cf_compare as compare
import cf_jobs
import cf_model_lab as lab
import cf_tiers


def png(path, size=(640, 480), color=(90, 120, 200)):
    Image.new("RGB", size, color).save(path)
    return str(path)


def test_pick_models_keeps_order_and_refuses_what_compares_nothing():
    valid = ["a", "b", "c"]
    assert compare.pick_models("b", "a", "none", valid=valid) == ["b", "a"]
    assert compare.pick_models("a", "b", "c", valid=valid) == ["a", "b", "c"]
    with pytest.raises(ValueError, match="diferentes"):
        compare.pick_models("a", "a", valid=valid)
    with pytest.raises(ValueError, match="2 a 3"):
        compare.pick_models("a", "none", "", valid=valid)
    with pytest.raises(ValueError, match="desconhecido"):
        compare.pick_models("a", "zzz", valid=valid)


def test_distilled_recipes_count_their_schedule_not_the_form_steps():
    assert compare.steps_of(lab.PRESETS["qwen21-turbo"], 40) == 8  # nine sigmas = eight steps
    assert compare.steps_of(lab.PRESETS["qwen21"]) == 40 and compare.steps_of(lab.PRESETS["qwen21"], 25) == 25
    assert compare.steps_of(lab.PRESETS["flux2"]) == 4


def test_timing_uses_the_warm_run_when_there_is_one_and_says_which():
    warm = compare.measure(130.0, 100.0, 40)
    assert warm["seconds_per_step"] == 2.5 and warm["basis"] == "quente" and warm["cold_seconds"] == 130.0 and warm["warm_seconds"] == 100.0
    cold_only = compare.measure(130.0, None, 40)
    assert cold_only["seconds_per_step"] == 3.25 and cold_only["warm_seconds"] is None and "frio" in cold_only["basis"]


def items_for(tmp_path):
    return [dict(model="qwen21", title="Qwen Image 2.1", seed=1, cfg=1.0, size=(768, 768), vram_gb=14.2, timing=compare.measure(130, 100, 40), image=png(tmp_path / "a.png", (768, 768), (200, 60, 60))),
            dict(model="qwen21-turbo", title="Qwen Image 2.1 Turbo", seed=2, cfg=8.0, size=(768, 768), vram_gb=None, timing=compare.measure(40, 20, 8), image=png(tmp_path / "b.png", (1024, 576), (60, 200, 90)))]


def test_sheet_puts_each_picture_at_one_height_with_its_numbers_underneath(tmp_path):
    items = items_for(tmp_path)
    image = compare.sheet(items, "um farol ao entardecer " * 30)  # a prompt far wider than the sheet must not break it
    assert image.height == 44 + compare.CELL_HEIGHT + compare.CAPTION_LINES * 26 + 2 * compare.GAP
    assert image.width == 512 + round(1024 * 512 / 576) + 3 * compare.GAP
    pixels = np.asarray(image)
    assert pixels[44 + 100, compare.GAP + 50].tolist() == [200, 60, 60]  # picture 1 where it should be
    caption = pixels[44 + compare.CELL_HEIGHT + 4: 44 + compare.CELL_HEIGHT + 80, compare.GAP: compare.GAP + 512]
    assert len({tuple(p) for p in caption.reshape(-1, 3)}) > 3  # text was drawn, not an empty bar
    text = "\n".join(compare.caption(items[0]))
    assert "2.5 s/passo" in text and "40 passos" in text and "14.2 GB VRAM" in text and "768×768" in text
    assert "VRAM" not in "\n".join(compare.caption(items[1]))  # unknown VRAM is not invented


def test_faster_and_summary_line():
    items = [dict(title="A", timing=compare.measure(130, 100, 40)), dict(title="B", timing=compare.measure(40, 20, 8))]
    assert compare.faster(items) == ("B", 5.0)
    assert compare.summary_line(items) == "A: 2.5 s/passo · B: 2.5 s/passo"


def test_history_keeps_the_last_twenty(tmp_path):
    path = tmp_path / "h.json"
    for n in range(25):
        compare.append_history(path, {"n": n})
    assert [e["n"] for e in json.loads(path.read_text())] == list(range(5, 25))


# ---------------------------------------------------------------- the app
@pytest.fixture()
def world(tmp_path, monkeypatch):
    import cf_factory
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    tmp_path = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path  # the vendored engine binds its folder once per process
    cf_apps.configure(tmp_path, tmp_path / "outputs")
    (tmp_path / "compare_models.json").unlink(missing_ok=True)
    calls = []

    def fake(ctx, preset, p, files, width, height, count, progress_total=None):
        calls.append(dict(model=preset.key, seed=p["seed"], free=p.get("free_vram"), size=(width, height)))
        time.sleep(0.25)  # a real clock reading, so the rounded timings are non-zero
        return [png(ctx.out_dir / f"{preset.key}-{len(calls)}.png", (width, height))]
    monkeypatch.setattr(cf_apps, "run_graph_images", fake)
    monkeypatch.setattr(cf_apps, "vram_used_gb", lambda: 9.5)

    class Job:
        message = ""
        def update(self, **kw): self.message = kw.get("message", self.message)

    class Ctx:
        out_dir = tmp_path / "cmp-out"
        job = Job()
        def progress(self, *a, **k): pass
        def check(self): pass
    Ctx.out_dir.mkdir(exist_ok=True)
    return calls, Ctx, tmp_path


def test_app_runs_each_model_cold_then_warm_and_returns_the_sheet_first(world):
    calls, Ctx, tmp_path = world
    ctx = Ctx()
    out = cf_apps.run_compare_models(ctx, dict(prompt="um farol", model_a="qwen21", model_b="qwen21-turbo", model_c="none", side=768, seed=10), cf_tiers.detect())
    assert [c["model"] for c in calls] == ["qwen21", "qwen21", "qwen21-turbo", "qwen21-turbo"]  # cold + warm, one model after the other
    assert [c["free"] for c in calls] == [False, True, False, True]  # weights are released after each model's last run
    assert calls[0]["seed"] == 10 and calls[2]["seed"] == 11 and calls[1]["seed"] != calls[0]["seed"]  # a fresh seed for the warm run
    assert len(out) == 3 and out[0].name.startswith("comparacao") and Image.open(out[0]).height > 512
    assert "s/passo" in ctx.job.message and "mais rápido" in ctx.job.message
    history = json.loads((tmp_path / "compare_models.json").read_text())
    assert [m["model"] for m in history[-1]["models"]] == ["qwen21", "qwen21-turbo"] and history[-1]["models"][0]["vram_gb"] == 9.5 and history[-1]["models"][1]["steps"] == 8


def test_app_without_warm_runs_once_and_refuses_bad_choices(world):
    calls, Ctx, _ = world
    cf_apps.run_compare_models(Ctx(), dict(prompt="x", model_a="flux2", model_b="z-image-turbo", model_c="krea2-turbo", warm=False, side=512), cf_tiers.detect())
    assert [c["model"] for c in calls] == ["flux2", "z-image-turbo", "krea2-turbo"] and all(c["free"] for c in calls)
    with pytest.raises(cf_jobs.JobError, match="diferentes"):
        cf_apps.run_compare_models(Ctx(), dict(prompt="x", model_a="flux2", model_b="flux2"), cf_tiers.detect())
    with pytest.raises(cf_jobs.JobError, match="pedido"):
        cf_apps.run_compare_models(Ctx(), dict(prompt=" ", model_a="flux2", model_b="flux3"), cf_tiers.detect())


def test_app_is_registered_with_the_three_model_slots(monkeypatch):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    app = cf_apps.registry()["compare_models"]
    fields = {f["id"]: f for f in app.fields(cf_tiers.detect())}
    assert set(fields) >= {"prompt", "model_a", "model_b", "model_c", "side", "warm"} and fields["model_c"]["default"] == "none"
    assert {o["value"] for o in fields["model_a"]["options"]} == set(cf_apps.IMAGE_MODELS) and not app.describe(cf_tiers.detect())["blocked"]
