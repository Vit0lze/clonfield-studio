"""Component registry, ★ ordering, whole-set presets and the graph overrides they feed. Real files, no network."""
import dataclasses
from pathlib import Path

import pytest

import cf_apps
import cf_model_lab as lab
import cf_registry as reg
import cf_tiers


@pytest.fixture
def tier(monkeypatch):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "16")
    return cf_tiers.detect()


def test_star_is_the_recipe_default_and_comes_first(tmp_path, monkeypatch):
    monkeypatch.setenv("CLONFIELD_COMFY_MODELS", str(tmp_path))
    slots = {s["id"]: s for s in reg.slots("qwen21", tmp_path / "civ")}
    assert list(slots) == ["Difusão", "Encoder", "VAE", "sampler", "scheduler"]
    first = slots["Difusão"]["options"][0]
    assert first["star"] and first["value"] == "" and first["label"].startswith("qwen_image_2.1_int8")
    assert not first["installed"] and "baixa ao usar" in first["hint"]
    target = tmp_path / "diffusion_models"
    target.mkdir()
    (target / "qwen_image_2.1_int8_convrot.safetensors").write_bytes(b"x" * 10)
    again = {s["id"]: s for s in reg.slots("qwen21", tmp_path / "civ")}
    assert again["Difusão"]["options"][0]["installed"]
    assert slots["VAE"]["search"]["sources"] == ["huggingface", "civitai", "local"] and slots["sampler"]["search"] is None


def test_algorithm_slots_put_the_recipe_default_first_and_mark_unqueried_worker(tmp_path):
    slots = {s["id"]: s for s in reg.slots("z-image", tmp_path)}
    assert slots["sampler"]["options"][0]["label"] == "res_multistep" and slots["sampler"]["options"][0]["star"]
    assert sum(o["star"] for o in slots["sampler"]["options"]) == 1


def test_checkpoint_only_models_have_no_star_file_and_offer_search(tmp_path):
    slots = {s["id"]: s for s in reg.slots("sdxl", tmp_path)}
    assert slots["Checkpoint"]["options"] == [] and slots["Checkpoint"]["search"]["family"] == "sdxl"


def test_sets_are_whole_recipes_and_keep_few_step_models_fixed(tier):
    qwen, flux = lab.PRESETS["qwen21"], lab.PRESETS["flux2"]
    steps = {n: reg.set_values(n, qwen, tier)["values"]["steps"] for n in reg.SETS}
    assert steps == {"Rápido": 20, "Moderado": 40, "Qualidade": 50}
    assert {reg.set_values(n, flux, tier)["values"]["steps"] for n in reg.SETS} == {4}
    assert reg.set_values("Rápido", qwen, tier)["values"]["gen_factor"] < 1
    comps = reg.set_values("Moderado", qwen, tier)["components"]
    assert set(comps) == {"Difusão", "Encoder", "VAE"} and all(v.startswith("★") for v in comps.values())
    assert "benchmark" in reg.set_values("Moderado", qwen, tier)["note"]
    with pytest.raises(ValueError):
        reg.set_values("Turbo", qwen, tier)


def test_form_offers_four_sets_including_manual_and_the_set_field_before_steps(tier):
    fields = cf_apps.registry()["create"].describe(tier)["fields"]
    ids = [f["id"] for f in fields]
    assert ids.index("model") < ids.index("set") < ids.index("steps")
    options = next(f for f in fields if f["id"] == "set")["options"]
    assert [o["value"] for o in options] == ["Rápido", "Moderado", "Qualidade", "Manual"]
    assert "by_model" in options[0] and "by_model" not in options[3]


def test_fast_set_generates_smaller_and_upscales_back_to_the_final_size(tier):
    full = cf_apps.resolution_plan("1:1", "standard", tier)
    fast = cf_apps.resolution_plan("1:1", "standard", tier, gen_factor=0.75)
    assert max(fast["native"]) < max(full["native"]) and fast["final"] == full["final"] and fast["scale"] > 1


def test_sampler_override_reaches_the_ksampler_node():
    preset = dataclasses.replace(lab.PRESETS["qwen21"], sampler="dpmpp_2m", scheduler="karras")
    names = {"Difusão": ["a.safetensors"], "Encoder": ["b.safetensors"], "VAE": ["c.safetensors"]}
    graph, _uploads, _seed = lab.make_graph(preset, names, "a red sphere", "", 512, 512, 20, 1, 7, [], 1.0, False)
    sampler = next(n for n in graph.values() if n["class_type"] == "KSampler")["inputs"]
    assert sampler["sampler_name"] == "dpmpp_2m" and sampler["scheduler"] == "karras" and sampler["steps"] == 20
