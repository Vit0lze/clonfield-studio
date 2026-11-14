"""Image-to-3D from the vendored official template, offline (recorded node definitions of a real ComfyUI 0.44.0) and the converter's rules.
The real-ComfyUI acceptance of the converted graphs is in test_comfy_real.py."""
import json
from pathlib import Path

import pytest

import cf_3d
import cf_ui2api as u

OBJ = json.loads((Path(__file__).parent / "fixtures" / "objinfo_comfyui_0.44.0.json").read_text(encoding="utf-8"))


def test_both_engines_convert_and_only_their_own_weights_are_required():
    pix, tre = cf_3d.build(OBJ, "pixal3d", 1), cf_3d.build(OBJ, "trellis2", 1)
    names = lambda g: {f[0] for f in cf_3d.files_for(g)}
    assert "pixal3d_int8_convrot.safetensors" in names(pix) and "trellis_2_int8_convrot.safetensors" not in names(pix) and "moge_2_vitl_normal_fp16.safetensors" in names(pix)
    assert "trellis_2_int8_convrot.safetensors" in names(tre) and "pixal3d_int8_convrot.safetensors" not in names(tre) and "moge_2_vitl_normal_fp16.safetensors" not in names(tre)
    assert not any(n["class_type"] == "ComfySwitchNode" and isinstance(n["inputs"].get("switch"), list) and n["inputs"]["switch"][0] == "316" for n in pix.values())  # the engine switch is folded away


def test_overrides_reach_the_graph_and_the_output_is_one_glb_save_node():
    g = cf_3d.build(OBJ, "pixal3d", seed=10, texture=4096, faces=300_000, image="foto.png")
    assert g["122"]["inputs"]["image"] == "foto.png" and g["288"]["inputs"]["value"] == 4096 and g["186"]["inputs"]["target_face_count"] == 300_000
    assert [g[k]["inputs"]["seed"] for k in ("3", "18", "12", "23")] == [10, 11, 12, 13]
    outputs = [k for k, v in g.items() if OBJ[v["class_type"]].get("output_node")]
    assert "322" in outputs and g["322"]["class_type"] == "Save3DAdvanced"


def test_the_graph_is_pruned_to_what_the_glb_needs():
    g = cf_3d.build(OBJ, "trellis2", 1)
    template_nodes = [n for n in cf_3d.template()["nodes"] if n["type"] not in u.VIRTUAL]
    assert 40 < len(g) < len(template_nodes)  # preview-only branches and the unused engine are not queued


@pytest.mark.parametrize("kwargs,words", [(dict(engine="x"), "Pixal3D"), (dict(texture=999), "textura"), (dict(faces=10), "faces"), (dict(seed=-4), "seed")])
def test_bad_options_are_refused(kwargs, words):
    with pytest.raises(ValueError, match=words):
        cf_3d.build(OBJ, **{"engine": "pixal3d", **kwargs})


def test_download_size_is_known_before_downloading(tmp_path):
    total, missing = cf_3d.download_gb(cf_3d.build(OBJ, "pixal3d", 1), tmp_path)
    assert 9 < total < 11 and missing == total
    assert cf_3d.download_gb(cf_3d.build(OBJ, "trellis2", 1), tmp_path)[0] < total


def test_converter_handles_dynamic_combos_colors_and_seed_controls():
    wf = {"nodes": [{"id": 1, "type": "KSampler", "widgets_values": [7, "randomize", 12, 3, "euler", "simple", 1], "inputs": []},
                    {"id": 2, "type": "RemeshMesh", "widgets_values": [768, "solid", 20, False, 1, 0, False, 20, 0.01, 20000000], "inputs": []},
                    {"id": 3, "type": "ImageCropToMask", "widgets_values": [512, 512, 1.1, 0, "#ff0000"], "inputs": []}], "links": []}
    g = u.convert(wf, OBJ, outputs=[1, 2, 3])
    assert g["1"]["inputs"]["seed"] == 7 and g["1"]["inputs"]["steps"] == 12 and g["1"]["inputs"]["sampler_name"] == "euler"   # the "randomize" control value is skipped
    assert g["2"]["inputs"]["sign_mode"] == "solid" and g["2"]["inputs"]["sign_mode.fill"] == 20 and g["2"]["inputs"]["band"] == 1  # nested dynamic-combo input
    assert g["3"]["inputs"]["background"] == "#ff0000"


def test_converter_refuses_unknown_nodes_that_are_needed_instead_of_queueing_half_a_graph():
    with pytest.raises(u.ConversionError, match="não existe"):
        u.convert({"nodes": [{"id": 1, "type": "NoSuchNode", "widgets_values": []}], "links": []}, OBJ, outputs=[1])
    ignored = u.convert({"nodes": [{"id": 1, "type": "NoSuchNode", "widgets_values": []}, {"id": 2, "type": "PrimitiveInt", "widgets_values": [3, "fixed"], "inputs": []}], "links": []}, OBJ, outputs=[2])
    assert list(ignored) == ["2"]  # an unknown node nobody needs (e.g. a preview-only branch) does not block the conversion


def test_converter_folds_a_known_switch_and_drops_the_unused_branch():
    wf = {"nodes": [{"id": 1, "type": "PrimitiveBoolean", "widgets_values": [True], "inputs": []},
                    {"id": 2, "type": "PrimitiveInt", "widgets_values": [111, "fixed"], "inputs": []},
                    {"id": 3, "type": "PrimitiveInt", "widgets_values": [222, "fixed"], "inputs": []},
                    {"id": 4, "type": "ComfySwitchNode", "widgets_values": [], "inputs": [{"name": "switch", "link": 10}, {"name": "on_false", "link": 11}, {"name": "on_true", "link": 12}]},
                    {"id": 5, "type": "KSampler", "widgets_values": [1, "fixed", 5, 1, "euler", "simple", 1], "inputs": [{"name": "model", "link": 13}]}],
          "links": [[10, 1, 0, 4, 0, "BOOLEAN"], [11, 2, 0, 4, 1, "INT"], [12, 3, 0, 4, 2, "INT"], [13, 4, 0, 5, 0, "MODEL"]]}
    g = u.convert(wf, OBJ, outputs=[5])
    assert g["5"]["inputs"]["model"] == ["3", 0] and "2" not in g and "4" not in g  # the true branch was chosen; the false one and the switch are gone
