"""MOSS-Image app (core ComfyUI nodes): box -> layout rules, working size, mask/picture agreement, the runner up to the point it hands the graph to ComfyUI.
Real-ComfyUI acceptance of the three graphs is in test_comfy_real.py."""
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import cf_apps
import cf_jobs
import cf_moss as moss
import cf_tiers

BOXES = [dict(x=0.1, y=0.1, w=0.5, h=0.3, kind="text", text="OFERTA", desc="letras creme"), dict(x=0.2, y=0.5, w=0.6, h=0.4, kind="obj", desc="um cavaleiro")]


def test_boxes_become_pixel_boxes_with_metadata_in_the_order_drawn():
    state = moss.editor_state(BOXES, 768, 1152)
    assert [s["metadata"]["type"] for s in state] == ["text", "obj"] and state[0]["metadata"]["text"] == "OFERTA" and state[1]["metadata"]["text"] == ""
    assert state[0]["x"] == round(0.1 * 768) and state[0]["width"] == round(0.5 * 768) and state[1]["y"] == round(0.5 * 1152)


@pytest.mark.parametrize("box,words", [(dict(x=0.1, y=0.1, w=0.3, h=0.3, kind="text", text="", desc="x"), "palavras exatas"),
                                       (dict(x=0.1, y=0.1, w=0.3, h=0.3, kind="obj", desc=" "), "Descreva o que deve aparecer"),
                                       (dict(x=0.9, y=0.1, w=0.5, h=0.3, kind="obj", desc="x"), "sai da imagem")])
def test_boxes_without_what_must_be_inside_are_refused_with_the_reason(box, words):
    with pytest.raises(ValueError, match=words):
        moss.editor_state([box], 768, 1152)


def test_generate_graph_follows_the_official_recipe_and_ships_the_boxes_as_a_json_string():
    g = moss.generate_graph("pôster", BOXES, 768, 1152, seed=9)
    ks = g["7"]["inputs"]
    assert (ks["steps"], ks["cfg"], ks["sampler_name"], ks["scheduler"], ks["seed"]) == (25, 2.5, "er_sde", "simple", 9)
    assert g["2"]["inputs"]["type"] == "moss_image" and g["2"]["inputs"]["clip_name"] == "qwen3.5_9b_w4a8_gptq.safetensors"
    assert isinstance(g["11"]["inputs"]["bboxes"], str) and json.loads(g["11"]["inputs"]["bboxes"])[0]["metadata"]["text"] == "OFERTA"  # a plain list would be read as a link
    assert g["10"]["inputs"]["element"] == ["11", 2]


def test_edit_graph_keeps_the_original_outside_the_mask_and_uses_differential_diffusion_not_a_hard_mask():
    g = moss.edit_boxes_graph("a rua com um cartaz", BOXES, (640, 480), "base.png", "mask.png", 1)
    kinds = [n["class_type"] for n in g.values()]
    assert {"SetLatentNoiseMask", "DifferentialDiffusion", "ImageCompositeMasked"} <= set(kinds)
    assert g["26"]["inputs"]["destination"] == ["20", 0] and g["26"]["inputs"]["mask"] == ["22", 0]  # pasted back over the very picture that was encoded
    assert g["7"]["inputs"]["model"] == ["25", 0]


@pytest.mark.parametrize("size", [(640, 480), (4000, 3000), (480, 1200)])
def test_work_size_has_the_pictures_proportions_and_sides_multiple_of_16(size):
    w, h = moss.work_size(size, 1.5)
    assert w % 16 == 0 and h % 16 == 0 and abs((w / h) / (size[0] / size[1]) - 1) < 0.05 and 1.2e6 < w * h < 1.8e6


def test_instruction_graph_comes_from_the_official_template():
    obj = json.loads((Path(__file__).parent / "fixtures" / "objinfo_comfyui_0.44.0.json").read_text(encoding="utf-8"))
    g = moss.instruction_graph(obj, "Change only the coat to black.", "p.png", 5, 28)
    assert next(n for n in g.values() if n["class_type"] == "LoraLoaderModelOnly")["inputs"]["lora_name"] == "moss_image_edit_lora_rank_64_bf16.safetensors"
    assert next(n for n in g.values() if n["class_type"] == "KSampler")["inputs"]["steps"] == 28
    assert any(n["class_type"] == "TextEncodeMOSSImageEdit" and n["inputs"].get("prompt") == "Change only the coat to black." for n in g.values())
    with pytest.raises(ValueError):
        moss.instruction_graph(obj, " ", "p.png")


def test_download_size_by_mode(tmp_path):
    assert 12.9 < moss.download_gb("generate", tmp_path)[0] < 13.2 and moss.download_gb("edit_instruction", tmp_path)[0] > moss.download_gb("generate", tmp_path)[0]


@pytest.fixture()
def fake_run(monkeypatch, tmp_path):
    """Capture what run_moss hands to ComfyUI: the graph and the uploads it prepared. Stops right there (no worker here)."""
    seen = {}

    def run(graph, out_dir, progress, **kwargs):
        seen["graph"], seen["kwargs"] = graph, kwargs
        raise cf_jobs.JobError("parou antes do ComfyUI", "falhou")
    monkeypatch.setattr(cf_apps.workflows, "run", run)
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")

    class Ctx:
        out_dir = tmp_path / "out"
        control = None
        class job: id = "j"
        def progress(self, *a, **k): pass
        def check(self): pass
    Ctx.out_dir.mkdir()
    return seen, Ctx


def test_run_moss_edit_prepares_a_mask_exactly_as_big_as_the_scaled_picture(fake_run, tmp_path):
    seen, Ctx = fake_run
    photo = tmp_path / "p.png"
    Image.new("RGB", (800, 600), (50, 90, 130)).save(photo)
    with pytest.raises(cf_jobs.JobError, match="parou"):
        cf_apps.run_moss(Ctx(), dict(mode="edit_boxes", image=[str(photo)], boxes=BOXES, prompt="a rua com um cartaz novo", megapixels=1.0, feather=8), cf_tiers.detect())
    keep = seen["kwargs"]["prepare"].keywords
    base, mask = Image.open(keep["image"]), Image.open(keep["mask"])
    assert base.size == mask.size and base.size == moss.work_size((800, 600), 1.0)  # the mask cannot disagree with the picture
    assert np.asarray(mask)[int(0.15 * base.height), int(0.3 * base.width)] == 255 and np.asarray(mask)[0, 0] == 0
    assert seen["graph"]["10"]["inputs"]["width"] == base.width


def test_run_moss_refuses_edit_without_a_picture_and_generate_without_boxes(fake_run):
    seen, Ctx = fake_run
    with pytest.raises(cf_jobs.JobError, match="Envie a imagem"):
        cf_apps.run_moss(Ctx(), dict(mode="edit_boxes", boxes=BOXES, prompt="x"), cf_tiers.detect())
    with pytest.raises(cf_jobs.JobError, match="pelo menos uma caixa"):
        cf_apps.run_moss(Ctx(), dict(mode="generate", boxes=[], prompt="x"), cf_tiers.detect())


def test_app_is_registered_with_a_detailed_box_field(monkeypatch):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    fields = {f["id"]: f for f in cf_apps.registry()["moss"].fields(cf_tiers.detect())}
    assert fields["boxes"]["type"] == "boxes" and fields["boxes"]["detail"] is True and {o["value"] for o in fields["mode"]["options"]} == set(moss.MODES)
