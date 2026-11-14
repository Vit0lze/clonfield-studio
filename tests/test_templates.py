"""Template apps (Wan SCAIL-2, Wan Animate 2) and subgraph flattening, offline: node definitions recorded from a real ComfyUI 0.44.0.
The real-worker acceptance of the converted graphs is in test_comfy_real.py."""
import json
from pathlib import Path

import pytest

import cf_apps
import cf_templates as t
import cf_tiers
import cf_ui2api as u

OBJ = json.loads((Path(__file__).parent / "fixtures" / "objinfo_comfyui_0.44.0.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", list(t.TEMPLATES))
def test_subgraph_templates_flatten_into_plain_graphs_with_the_users_inputs(key):
    spec = t.TEMPLATES[key]
    g = t.build(key, OBJ, video="v.mp4", image="p.png", prompt="a stylish dancer", seed=9)
    assert len(g) > 25 and not any(":" not in k and OBJ[v["class_type"]].get("input") is None for k, v in g.items())
    assert g[spec["video"]]["inputs"]["file"] == "v.mp4" and g[spec["image"]]["inputs"]["image"] == "p.png"
    assert g[spec["seed"][0]]["inputs"][spec["seed"][1]] == 9 and g[spec["prompt"][0]]["inputs"][spec["prompt"][1]] == "a stylish dancer"
    assert any(":" in k for k in g)  # inner nodes carry "outer:inner" ids


@pytest.mark.parametrize("key", list(t.TEMPLATES))
def test_every_weight_the_graph_loads_is_listed_with_a_pinned_revision_and_size(key):
    g = t.build(key, OBJ)
    files = t.files_for(key, g)
    assert files and all(e["revision"] and e["size"] and e["sha256"] for _, e in files)
    assert any(e["size"] > 15e9 for _, e in files)  # the 16.6 GB INT8 model
    total, missing = t.download_gb(key, g, "/nonexistent")
    assert 24 < total < 30 and missing == total


def test_an_unlisted_weight_is_an_error_not_a_guess():
    g = t.build("scail2", OBJ)
    next(n for n in g.values() if n["class_type"] == "UNETLoader")["inputs"]["unet_name"] = "outro_modelo.safetensors"
    with pytest.raises(ValueError, match="não está na lista"):
        t.files_for("scail2", g)


def test_flatten_maps_widget_values_by_the_subgraphs_inputs_even_when_the_outer_node_hides_them():
    """The outer node of the Animate-2 subgraph does not list noise_seed/length as sockets but stores their values: they must reach the inner nodes."""
    g = t.build("animate2", OBJ, seed=-1)
    sampler = next(n for k, n in g.items() if n["class_type"] == "SamplerCustom")
    assert isinstance(sampler["inputs"]["noise_seed"], int) and any(n["class_type"] == "UNETLoader" and n["inputs"]["unet_name"].startswith("wan_animate_2_distill") for n in g.values())


def test_apps_are_gated_by_vram_and_the_agent_needs_confirmation_for_the_swap(monkeypatch):
    import cf_capabilities as caps
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    tier = cf_tiers.detect()
    reg = cf_apps.registry()
    for key in t.TEMPLATES:
        d = reg[key].describe(tier)
        # a 15 GB card is NOT refused: ComfyUI streams the weights to RAM/disk, so it runs slowly; the user is told so up front
        assert not d["blocked"] and d["slow"] and "24" in d["slow_reason"] and "mais lento" in d["slow_reason"]
    assert reg["openjutsu"].describe(tier)["blocked"]  # no offload path for the 96 GB class: still a hard stop
    import cf_dag
    check = cf_dag.validate({"nodes": [{"id": "a", "cap": "app.scail2", "inputs": {}}]}, caps.Registry(reg, tier), tier=tier)
    assert not [e for e in check["errors"] if e["code"] == "resource"]  # missing inputs are reported, the VRAM floor is not
    assert check["resources"].get("slow") == ["a"]
    assert caps.Registry(reg, tier).get("app.scail2").risk == "medium"
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "40")
    d = reg["scail2"].describe(cf_tiers.detect())
    assert not d["blocked"] and not d["slow"]
