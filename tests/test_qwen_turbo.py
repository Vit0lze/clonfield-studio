"""Qwen Image 2.1 Turbo: the official ComfyUI template's recipe (Turbo INT8 weights, 8-step ManualSigmas schedule, euler, CFGGuider)."""

import pytest
import requests

import cf_apps
import cf_model_lab as lab

TURBO_FILE = "diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors"


def build(refs=0, steps=40):
    preset = lab.PRESETS["qwen21-turbo"]
    names, _sources = lab.names_and_sources(preset, {}, False)
    graph, uploads, _seed = lab.make_graph(preset, names, "um farol ao entardecer", "", 1024, 768, steps, preset.cfg, 5, ["a.png", "b.png"][:refs], 1.0, False)
    return graph, uploads


def of(graph, kind):
    return [n["inputs"] for n in graph.values() if n["class_type"] == kind]


def test_turbo_uses_its_own_weights_and_the_fixed_eight_step_schedule():
    graph, _ = build(steps=40)  # the form's step count is ignored: the schedule is part of the model
    assert of(graph, "UNETLoader")[0]["unet_name"] == "qwen_image_2.1_turbo_int8_convrot.safetensors"
    assert of(graph, "CLIPLoader")[0]["clip_name"] == "qwen3vl_8b_int8_convrot.safetensors"
    sigmas = of(graph, "ManualSigmas")[0]["sigmas"]
    values = [float(v) for v in sigmas.split(",")]
    assert len(values) == 9 and values[0] == 1.0 and values[-1] == 0.0 and values == sorted(values, reverse=True)
    assert of(graph, "KSamplerSelect")[0]["sampler_name"] == "euler" and of(graph, "CFGGuider")[0]["cfg"] == 8.0
    assert of(graph, "SamplerCustomAdvanced") and not of(graph, "KSampler") and not of(graph, "Flux2Scheduler")


def test_turbo_edits_follow_the_first_reference_like_the_base_model():
    graph, uploads = build(refs=2)
    assert len(uploads) == 2 and of(graph, "ImageScale") and of(graph, "TextEncodeQwenImage21")[0]["images.image_2"]
    sampler = of(graph, "SamplerCustomAdvanced")[0]
    assert sampler["latent_image"][1] == 2  # the latent comes out of the Qwen encode node, as in the base recipe


def test_base_model_recipe_is_untouched_and_turbo_is_offered_with_the_same_loras():
    base = lab.PRESETS["qwen21"]
    assert not base.sigmas and base.steps == 40 and base.cfg == 1
    assert "qwen21-turbo" in cf_apps.IMAGE_MODELS and cf_apps.LORA_FAMILIES["qwen21-turbo"] == ["qwen21", "qwen21-turbo"]
    import cf_loras
    assert cf_loras.norm("qwen21-turbo") == "qwen21"


def test_pinned_turbo_file_matches_the_real_hugging_face_listing():
    repo, path = lab.PRESETS["qwen21-turbo"].files["Difusão"]
    try:
        tree = requests.get(f"https://huggingface.co/api/models/{repo}/tree/{lab.REVISIONS[repo]}/diffusion_models", timeout=20).json()
    except requests.RequestException as exc:
        pytest.skip(f"sem rede: {exc}")
    entry = next(e for e in tree if e["path"] == path)
    assert path == TURBO_FILE and entry["size"] == 7_256_787_829 and entry["lfs"]["oid"].startswith("8144a0182964")
