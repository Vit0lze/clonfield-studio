"""Quality gate, refine loop and router with real PIL images and the real app registry (no network)."""
import numpy as np
import pytest
from PIL import Image, ImageFilter

import cf_apps
import cf_refine as rf
import cf_router
import cf_tiers


def textured(path, seed, blur=0.0, size=(256, 256)):
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (size[1] // 8, size[0] // 8, 3), dtype=np.uint8)
    image = Image.fromarray(base).resize(size, Image.NEAREST)
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    image.save(path)
    return path


def test_gate_separates_sharp_blank_and_blown_images(tmp_path):
    sharp = textured(tmp_path / "s.png", 1)
    soft = textured(tmp_path / "b.png", 1, blur=6)
    Image.new("RGB", (64, 64), "white").save(tmp_path / "w.png")
    names = ["not_blank", "sharp", "exposure"]
    assert not rf.failures(rf.judge(sharp, {}, names))
    assert [v.line for v in rf.failures(rf.judge(soft, {}, names))] == ["sharp"]
    assert {v.line for v in rf.failures(rf.judge(tmp_path / "w.png", {}, names))} == {"not_blank", "sharp", "exposure"}


def test_free_text_rubric_lines_are_never_scored(tmp_path):
    verdicts = rf.judge(textured(tmp_path / "s.png", 2), {}, ["sharp"], manual=["logo no canto superior esquerdo"])
    assert verdicts[-1].status == rf.SKIPPED and not rf.failures(verdicts)


def test_loop_fixes_blur_with_cheap_finish_pass_from_baseline(tmp_path):
    calls = []

    def generate(params):
        calls.append(params["seed"])
        return textured(tmp_path / f"g{params['seed']}.png", 5, blur=1.6)

    report = rf.refine(generate, {"seed": 10}, {"sharp_floor": 120.0}, ["sharp"], tmp_path / "w")
    assert calls == [10]  # the fix was a deterministic finish pass, no regeneration spent
    assert report["passed"] and report["best"]["how"].startswith("finish") and report["stop"] == "passou"
    assert report["best"]["path"].parent == tmp_path / "w"


def test_loop_regenerates_with_only_the_seed_changed_then_stops_at_cap(tmp_path):
    seeds = []

    def generate(params):
        seeds.append(params["seed"])
        return textured(tmp_path / f"g{len(seeds)}.png", 9, blur=8)  # always too soft

    report = rf.refine(generate, {"seed": 1, "prompt": "x"}, {"sharp_floor": 1e6}, ["sharp"], tmp_path / "w", max_rounds=3)
    assert seeds == [1, 3]  # round 1 = unsharp finish, round 2 = regenerate (seed+2), round 3 = ladder exhausted
    assert not report["passed"] and "troque modelo" in report["stop"]
    assert len(report["attempts"]) == 3


def test_loop_keeps_best_attempt_when_nothing_passes(tmp_path):
    def generate(params):
        return textured(tmp_path / "g.png", 3, blur=9)

    report = rf.refine(generate, {"seed": 0}, {"sharp_floor": 1e6, "clip_limit": 1.0}, ["sharp", "exposure"], tmp_path / "w", max_rounds=1)
    assert report["best"]["round"] == 0 and report["stop"] == "limite de rodadas"


def test_router_uses_media_as_hard_evidence_and_does_not_renormalise(monkeypatch):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "16")
    tier = cf_tiers.detect()
    assert tier.vram_gb >= 8
    registry = cf_apps.registry()
    text = cf_router.route("anime em camadas para psd", {"image"}, registry, tier, provider=cf_router.local_provider)
    assert text["choice"] == "seethrough"
    assert abs(sum(c["probability"] for c in text["candidates"]) - 1) < 1e-3
    no_media = cf_router.route("anime em camadas para psd", set(), registry, tier, provider=cf_router.local_provider)
    see = next(c for c in no_media["candidates"] if c["app"] == "seethrough")
    assert not see["router"]["available"] and "image" in see["router"]["reasons"][0]
    assert no_media["choice"] != "seethrough"
    video = cf_router.route("cortar um trecho", {"video"}, registry, tier, provider=cf_router.local_provider)
    assert video["choice"] == "clip"
    with pytest.raises(ValueError):
        cf_router.route("", set(), registry, tier, provider=cf_router.local_provider)


def test_router_marks_gpu_apps_unavailable_without_vram(monkeypatch):
    monkeypatch.delenv("CLONFIELD_FAKE_VRAM", raising=False)
    tier = cf_tiers.detect()
    if tier.vram_gb >= 8:
        pytest.skip("this machine has a GPU")
    result = cf_router.route("anime em camadas para psd", {"image"}, cf_apps.registry(), tier, provider=cf_router.local_provider)
    see = next(c for c in result["candidates"] if c["app"] == "seethrough")
    assert not see["router"]["available"] and "VRAM" in see["router"]["reasons"][0]
    assert result["choice"] != "seethrough" and see["probability"] > 0.2  # probability kept, not re-normalised


def test_refine_outputs_keeps_baseline_and_only_regenerates_when_needed(tmp_path, monkeypatch):
    class Job(dict):
        pass

    class Ctx:
        out_dir = tmp_path
        job = Job()
        def progress(*a, **k): pass

    ctx = Ctx()
    good = textured(tmp_path / "good.png", 4)
    generated = []
    monkeypatch.setattr(cf_apps, "run_graph_images", lambda *a, **k: generated.append(1) or [good])
    out = cf_apps.refine_outputs(ctx, None, {"seed": 5}, [], 256, 256, [good])
    assert out == [good] and generated == []  # passing baseline: zero extra GPU runs
    assert "passou" in ctx.job["message"]
    soft = textured(tmp_path / "soft.png", 4, blur=12)
    out = cf_apps.refine_outputs(ctx, None, {"seed": 5}, [], 256, 256, [soft])
    assert generated == [1] and out[0] == good  # unsharp could not fix it, one regeneration found a sharp image


def test_benchmark_is_a_system_job_not_a_creative_app():
    registry = cf_apps.registry()
    assert "speedtest" not in registry and registry["benchmark"].hidden and registry["benchmark"].group == "Sistema"
    visible = [a.id for a in registry.values() if not a.hidden]
    assert "benchmark" not in visible and "create" in visible


def test_router_is_local_and_never_calls_an_outside_service(monkeypatch):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "16")
    registry, tier = cf_apps.registry(), cf_tiers.detect()
    result = cf_router.route("cortar um trecho", {"video"}, registry, tier)
    assert result["provider"] == "local" and result["fallback"] is None and result["choice"] == "clip"
    assert not hasattr(cf_router, "jev_provider") and not hasattr(cf_router, "JEV_ENDPOINT")


def test_plan_suggests_one_available_step_and_treats_plain_talk_as_conversation(monkeypatch):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "16")
    registry, tier = cf_apps.registry(), cf_tiers.detect()
    talk = cf_router.plan("oi, tudo bem?", set(), registry, tier)
    assert talk["conversation"] and talk["steps"] == []
    job = cf_router.plan("ampliar esta foto", {"image"}, registry, tier)
    assert not job["conversation"] and len(job["steps"]) == 1 and job["steps"][0]["app"] in registry
    assert cf_router.CAPABILITIES[job["steps"][0]["app"]][0] <= {"image"}  # never a step whose media is missing
    with pytest.raises(ValueError):
        cf_router.plan("  ", set(), registry, tier)

