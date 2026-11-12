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
    assert list(slots) == ["Difusão", "Encoder", "VAE", "Upscaler", "sampler", "scheduler"]
    assert slots["Upscaler"]["options"] == [] and slots["Upscaler"]["search"]["role"] == "Upscaler"  # still searchable when empty
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


def test_sets_pick_a_different_whole_pipeline_each(monkeypatch):
    for vram, expected in ((15, ("z-image-turbo", "z-image", "qwen21")), (24, ("z-image-turbo", "krea2-turbo", "qwen21"))):
        monkeypatch.setenv("CLONFIELD_FAKE_VRAM", str(vram))
        t = cf_tiers.detect()
        options = {o["value"]: o for o in reg.describe_sets(t, cf_apps.MODEL_INFO, cf_apps.IMAGE_MODELS)}
        models = tuple(options[n]["recipe"]["model"] for n in reg.SETS)
        assert models == expected and len(set(models)) == 3
        assert "recipe" not in options["Manual"]
    r = options["Qualidade"]["recipe"]
    assert r["steps"] == 50 and set(r["components"]) == {"Difusão", "Encoder", "VAE"} and "benchmark" in r["note"]
    assert options["Rápido"]["recipe"]["gen_factor"] < 1 and options["Rápido"]["recipe"]["steps"] == 8  # distilled keeps its steps


def test_heavy_models_say_so_and_flux3_is_never_picked_silently(monkeypatch):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    t = cf_tiers.detect()
    options = {o["value"]: o for o in reg.describe_sets(t, cf_apps.MODEL_INFO, cf_apps.IMAGE_MODELS)}
    assert "Pesado" in options["Qualidade"]["recipe"]["warning"] and options["Rápido"]["recipe"]["warning"] == ""
    assert all(o.get("recipe", {}).get("model") != "flux3" for o in options.values())


def test_sets_for_apps_that_need_references_only_use_models_that_take_them(monkeypatch):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    t = cf_tiers.detect()
    options = reg.describe_sets(t, cf_apps.MODEL_INFO, cf_apps.IMAGE_MODELS, needs_refs=True)
    for o in options:
        if "recipe" in o:
            assert lab.PRESETS[o["recipe"]["model"]].refs >= 1


def test_form_has_sections_set_before_model_and_variations_1_to_4(tier):
    fields = cf_apps.registry()["create"].describe(tier)["fields"]
    ids = [f["id"] for f in fields]
    assert ids.index("set") < ids.index("model") < ids.index("steps")
    assert [o["value"] for o in next(f for f in fields if f["id"] == "set")["options"]] == ["Rápido", "Moderado", "Qualidade", "Manual"]
    var = next(f for f in fields if f["id"] == "variations")
    assert var["type"] == "seg" and [o["value"] for o in var["options"]] == [1, 2, 3, 4]  # never limited by the card
    assert {f.get("section") for f in fields if f["id"] in ("prompt", "set", "aspect", "loras")} == {"Pedido", "Modelo", "Formato", "Estilo"}
    cfg = next(f for f in fields if f["id"] == "cfg")
    assert cfg["step"] == 0.1 and cfg["decimals"] == 1


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
