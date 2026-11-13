"""Stable Audio 3 graph: node/input names against the REAL ComfyUI v0.44.0 source, pinned files against the Hugging Face API, controls and the local
re-prompt. No audio is generated here (needs more RAM or a GPU): BLOQUEADO."""
import os

import pytest
import requests

import cf_apps
import cf_audio as audio
import cf_tiers
from test_wan import COMFY_TAG, RAW, node_inputs, online

needs_net = pytest.mark.skipif(not online(), reason="sem rede")
SOURCES = {"nodes.py": ["CheckpointLoaderSimple", "CLIPLoader", "CLIPTextEncode", "KSampler"], "comfy_extras/nodes_audio.py": ["EmptyLatentAudio", "VAEDecodeAudio", "SaveAudioAdvanced"]}


@needs_net
@pytest.mark.parametrize("fmt", list(audio.FORMATS))
def test_graph_uses_only_real_node_and_input_names(fmt):
    known = {}
    for path, classes in SOURCES.items():
        text = requests.get(RAW.format(repo="comfyanonymous/ComfyUI", rev=COMFY_TAG, path=path), timeout=30)
        text.raise_for_status()
        for name in classes:
            known[name] = node_inputs(text.text, name)
    graph = audio.make_graph("small_sfx", "rain on a tin roof", 12, 5, fmt)
    for node in graph.values():
        assert known.get(node["class_type"]), node["class_type"]
        given = {k for k in node["inputs"] if "." not in k}
        assert given <= known[node["class_type"]], (node["class_type"], given - known[node["class_type"]])
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in graph
    sd = requests.get(RAW.format(repo="comfyanonymous/ComfyUI", rev=COMFY_TAG, path="comfy/sd.py"), timeout=30).text
    assert "STABLE_AUDIO" in sd  # the CLIPLoader type we pass exists at the pinned ComfyUI


@needs_net
def test_pinned_files_match_the_real_hugging_face_listing():
    info = requests.get(f"https://huggingface.co/api/models/{audio.REPO}/revision/{audio.REVISION}", params={"blobs": "true"}, timeout=30).json()
    for key in audio.MODELS:
        for folder, filename, size, sha in audio.files_for(key):
            file = next(s for s in info["siblings"] if s["rfilename"] == filename)
            assert file["lfs"]["sha256"].startswith(sha) and abs(file["size"] - size) <= max(8_000_000, size // 50), filename


def test_the_graph_follows_the_official_template_settings():
    g = audio.make_graph("small_music", "lofi beat", 30, 1, "mp3")
    ks = g["3"]["inputs"]
    assert (ks["steps"], ks["cfg"], ks["sampler_name"], ks["scheduler"]) == (8, 1.0, "lcm", "simple")
    assert g["26"]["inputs"]["type"] == "stable_audio" and g["11"]["inputs"]["seconds"] == 30.0
    assert g["57"]["inputs"]["format"] == "mp3" and g["57"]["inputs"]["format.quality"] == "V0"
    assert "format.quality" not in audio.make_graph("small_sfx", "x", 5, 1, "flac")["57"]["inputs"]


@pytest.mark.parametrize("kwargs,words", [(dict(prompt=" "), "Descreva"), (dict(seconds=0), "segundos"), (dict(seconds=500), "segundos"), (dict(model_key="x"), "modelo"),
                                          (dict(fmt="wav"), "mp3"), (dict(steps=0), "passos"), (dict(seed=-9), "seed")])
def test_bad_controls_are_refused(kwargs, words):
    base = dict(model_key="small_sfx", prompt="p", seconds=10, seed=1, fmt="mp3", steps=8)
    base.update(kwargs)
    with pytest.raises(ValueError, match=words):
        audio.make_graph(**base)


def test_small_models_stop_at_120_seconds_and_medium_goes_further():
    with pytest.raises(ValueError):
        audio.make_graph("small_sfx", "x", 121, 1)
    audio.make_graph("medium", "x", 300, 1)


def test_reprompt_uses_the_local_model_and_falls_back_to_the_original_idea():
    seen = {}

    def fake_llm(system, user):
        seen.update(system=system, user=user)
        return '  "Heavy rain on a corrugated tin roof, close microphone, steady drumming."  '
    text, used = audio.reprompt("chuva no telhado", "SFX", fake_llm)
    assert used and text.startswith("Heavy rain") and "sound effect" in seen["system"] and "chuva no telhado" in seen["user"]
    assert "Do not filter" in seen["system"]  # no topic filtering, as the user asked

    def broken(system, user):
        raise RuntimeError("servidor desligado")
    assert audio.reprompt("chuva", "SFX", broken) == ("chuva", False)
    with pytest.raises(ValueError):
        audio.reprompt("x", "Nada", fake_llm)


def test_audio_app_is_registered_with_its_controls(monkeypatch):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    fields = {f["id"]: f for f in cf_apps.registry()["audio"].fields(cf_tiers.detect())}
    assert {"prompt", "model", "seconds", "reprompt", "category", "variations", "format", "steps", "seed"} <= set(fields)
    assert {o["value"] for o in fields["model"]["options"]} == set(audio.MODELS)
