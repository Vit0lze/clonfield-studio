"""Resolution scale: quality names the FINAL file; generation stays inside the tier limit and upscaling closes the gap."""
import pytest
from PIL import Image

import cf_apps
import cf_tiers


def tier(monkeypatch, vram):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", str(vram))
    return cf_tiers.detect()


def test_plan_reaches_exact_final_long_side_with_the_aspect_kept(monkeypatch):
    t = tier(monkeypatch, 16)
    ultra = cf_apps.resolution_plan("9:16", "ultra", t)
    assert max(ultra["final"]) == 4096 and ultra["scale"] > 1 and max(ultra["native"]) == t.max_side
    assert abs(ultra["final"][0] / ultra["final"][1] - ultra["native"][0] / ultra["native"][1]) < 0.01
    assert "ampliação" in ultra["text"] and "saída" in ultra["text"]
    very = cf_apps.resolution_plan("1:1", "veryhigh", t)
    assert very["final"] == (2048, 2048)
    plain = cf_apps.resolution_plan("16:9", "standard", t)
    assert plain["scale"] == 1 and plain["native"] == plain["final"]


def test_old_quality_names_still_resolve_and_new_ones_are_offered(monkeypatch):
    t = tier(monkeypatch, 16)
    assert cf_apps.dimensions("1:1", "high", t) == cf_apps.dimensions("1:1", "ultra", t)  # generated size, not final
    values = [o["value"] for o in cf_apps.quality_options(t)]
    assert values == ["draft", "standard", "high", "veryhigh", "ultra"]
    field = next(f for f in cf_apps.registry()["create"].describe(t)["fields"] if f["id"] == "quality")
    assert field["label"] == "Resolução final"


class Ctx:
    class job_(dict):
        pass
    job = job_()

    def progress(self, *a, **k): pass
    def check(self): pass


def test_reach_final_size_writes_the_exact_final_size_with_lanczos(monkeypatch, tmp_path):
    t = tier(monkeypatch, 16)
    plan = cf_apps.resolution_plan("1:1", "veryhigh", t)
    native = tmp_path / "n.png"
    Image.new("RGB", plan["native"], (200, 30, 30)).save(native)
    ctx = Ctx()
    ctx.job = Ctx.job_()
    out = cf_apps.reach_final_size(ctx, [native], plan, "Clássico (Lanczos)")
    with Image.open(out[0]) as image:
        assert image.size == (2048, 2048)
    assert "ampliação" in ctx.job["message"]
    assert cf_apps.reach_final_size(ctx, [native], cf_apps.resolution_plan("1:1", "standard", t), None) == [native]
