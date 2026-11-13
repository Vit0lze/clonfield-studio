"""Outpaint / Restore / Outfit swap: the CPU parts (canvas, stitch, prompts, parameters, graph) with real images, the LoRA catalog against the
real Hugging Face API, and the router/capability wiring. Running the LoRAs needs the T4 and is NOT tested here (BLOQUEADO_GPU)."""
import numpy as np
import pytest
import requests
from PIL import Image

import cf_apps
import cf_capabilities as caps
import cf_dag as dag
import cf_edits as edits
import cf_loras
import cf_model_lab as lab
import cf_router
import cf_tiers


def photo(size=(640, 480)):
    rng = np.random.default_rng(7)
    return Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8), "RGB")


def test_plan_gives_32_multiple_canvas_under_2mp_and_keeps_unasked_sides_flush():
    plan = edits.outpaint_plan((640, 480), right=256)
    w, h = plan["canvas"]
    assert w % 32 == 0 and h % 32 == 0 and w * h <= 2_000_000
    x0, y0, x1, y1 = plan["box"]
    assert x0 == 0 and y0 == 0 and y1 == h and x1 < w  # only the right grew: left, top and bottom stay flush


def test_a_big_source_is_scaled_down_so_the_canvas_fits_two_megapixels():
    plan = edits.outpaint_plan((3000, 2000), left=512, right=512)
    assert plan["scale"] < 1 and plan["canvas"][0] * plan["canvas"][1] <= 2_000_000 and plan["canvas"][0] <= 2048


@pytest.mark.parametrize("kwargs", [dict(), dict(left=-5), dict(left=4000, right=4000, top=4000, bottom=4000)])
def test_impossible_expansions_are_refused_with_a_reason(kwargs):
    with pytest.raises(ValueError):
        edits.outpaint_plan((640, 480), **kwargs)


def test_canvas_is_flat_gray_outside_and_the_source_inside():
    source = photo()
    plan = edits.outpaint_plan(source.size, left=128, bottom=64)
    canvas, mask = edits.pad_canvas(source, plan)
    x0, y0, x1, y1 = plan["box"]
    arr, m = np.asarray(canvas), np.asarray(mask)
    assert (arr[:, :x0] == 128).all()  # the left strip is exactly #808080
    assert (m[y0:y1, x0:x1] == 255).all() and m.sum() == 255 * (x1 - x0) * (y1 - y0)
    scaled = np.asarray(source.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS))
    assert (arr[y0:y1, x0:x1] == scaled).all()


def test_stitch_without_feather_restores_the_source_byte_for_byte_even_from_a_garbage_generation():
    source = photo()
    plan = edits.outpaint_plan(source.size, left=96, top=64, right=96, bottom=64)
    garbage = Image.fromarray(np.random.default_rng(1).integers(0, 255, (plan["canvas"][1], plan["canvas"][0], 3), dtype=np.uint8), "RGB")
    out = edits.stitch(source, garbage, plan, feather=0)
    x0, y0, x1, y1 = plan["box"]
    want = np.asarray(source.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS))
    assert (np.asarray(out)[y0:y1, x0:x1] == want).all()
    assert (np.asarray(out)[:y0] == np.asarray(garbage)[:y0]).all()  # outside the box the generation is untouched


def test_stitch_with_feather_keeps_the_core_exact_and_fades_only_the_seam():
    source = photo()
    plan = edits.outpaint_plan(source.size, right=128, left=128)
    generated = Image.new("RGB", plan["canvas"], (255, 0, 0))
    out = np.asarray(edits.stitch(source, generated, plan, feather=4))
    x0, y0, x1, y1 = plan["box"]
    want = np.asarray(source.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS))
    assert (out[y0 + 4:y1 - 4, x0 + 4:x1 - 4] == want[4:-4, 4:-4]).all()
    assert (out[:, :x0] == (255, 0, 0)).all()


def test_stitch_resizes_a_generation_of_another_size():
    source = photo((320, 240))
    plan = edits.outpaint_plan(source.size, right=64)
    out = edits.stitch(source, Image.new("RGB", (plan["canvas"][0] // 2, plan["canvas"][1] // 2), (9, 9, 9)), plan, 0)
    assert out.size == tuple(plan["canvas"])


def test_prompts_follow_the_authors_wording():
    assert edits.outpaint_prompt().startswith("Outpaint the image: replace the solid gray areas with a seamless continuation of the scene")
    assert edits.outpaint_prompt("a beach at dusk").endswith("Scene: a beach at dusk")
    assert "remove blur, noise and compression artifacts" in edits.restore_prompt(next(iter(edits.RESTORE_PROMPTS)))
    assert edits.restore_strength(True) == 0.5 and edits.restore_strength(False) == 1.0
    assert edits.outfit_prompt("black leather jacket") == "Dress the person in image 1 in the black leather jacket shown in image 2. Keep their face, hair, hands, pose and the background exactly the same."
    with pytest.raises(ValueError):
        edits.outfit_prompt("  ")
    with pytest.raises(ValueError):
        edits.restore_prompt("qualquer")


def test_restore_resize_goes_to_about_two_megapixels_in_multiples_of_32():
    for size in ((300, 200), (4000, 3000), (800, 1200)):
        out = edits.restore_resize(photo(size))
        assert out.width % 32 == 0 and out.height % 32 == 0 and out.width * out.height <= 2_000_000 and out.width * out.height > 1_300_000


def test_the_three_loras_are_in_the_catalog_for_qwen21_and_match_the_real_hugging_face_repos():
    by_file = {i["file"]: i for i in cf_loras.CATALOGO}
    for key, file in edits.LORAS.items():
        entry = by_file[file]
        assert cf_loras.family(entry["repo"], entry["file"]) == ["qwen21"], key
        try:
            info = requests.get(f"https://huggingface.co/api/models/{entry['repo']}/revision/{entry['revision']}", params={"blobs": "true"}, timeout=20).json()
        except requests.RequestException:
            pytest.skip("sem rede")
        sibling = next(s for s in info["siblings"] if s["rfilename"] == file)
        assert 150e6 < sibling["size"] < 170e6, key


def graph_for(params, files, size):
    preset = lab.PRESETS["qwen21"]
    names, _sources = lab.names_and_sources(preset, {}, False)
    names["LoRA"] = [item["name"] for item in params["loras"]]
    weights = [(float(i["strength"]), float(i["clip"])) for i in params["loras"]]
    import dataclasses
    preset = dataclasses.replace(preset, sampler=params.get("sampler") or preset.sampler, scheduler=params.get("scheduler") or preset.scheduler)
    graph, uploads, used = lab.make_graph(preset, names, params["prompt"], "", size[0], size[1], int(params.get("steps") or preset.steps), float(params.get("cfg") or preset.cfg), 7,
                                          files, 1.0, False, weights)
    return graph, uploads


def test_outpaint_parameters_build_the_authors_graph():
    params = cf_apps.edit_params({"seed": 7}, edits.outpaint_prompt("x"), "outpaint", 1.0, 25, 1, "euler", "simple")
    graph, uploads = graph_for(params, ["canvas.png"], (1024, 768))
    loras = [n for n in graph.values() if n["class_type"] == "LoraLoader"]
    assert len(loras) == 1 and loras[0]["inputs"]["lora_name"] == edits.LORAS["outpaint"] and loras[0]["inputs"]["strength_model"] == 1.0
    sampler = next(n for n in graph.values() if n["class_type"] in ("KSampler", "KSamplerAdvanced"))["inputs"]
    assert (sampler["steps"], sampler["cfg"], sampler["sampler_name"], sampler["scheduler"]) == (25, 1.0, "euler", "simple")
    assert len(uploads) == 1  # the canvas is the only reference
    assert not any(n["class_type"] == "SetLatentNoiseMask" for n in graph.values())  # the author says: do not pin the known area


def test_restore_and_outfit_use_their_lora_and_the_right_number_of_images():
    restore = cf_apps.edit_params({}, edits.restore_prompt(next(iter(edits.RESTORE_PROMPTS))), "restore", edits.restore_strength(True))
    graph, uploads = graph_for(restore, ["a.png"], (1024, 768))
    lora = next(n for n in graph.values() if n["class_type"] == "LoraLoader")["inputs"]
    assert lora["lora_name"] == edits.LORAS["restore"] and lora["strength_model"] == 0.5 and len(uploads) == 1
    outfit = cf_apps.edit_params({}, edits.outfit_prompt("red coat"), "outfit", 1.0)
    graph, uploads = graph_for(outfit, ["person.png", "coat.png"], (1024, 768))
    assert next(n for n in graph.values() if n["class_type"] == "LoraLoader")["inputs"]["lora_name"] == edits.LORAS["outfit"] and len(uploads) == 2


def test_apps_are_registered_with_their_forms_and_the_router_knows_them(monkeypatch):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    tier = cf_tiers.detect()
    registry = cf_apps.registry()
    fields = {f["id"] for f in registry["outpaint"].fields(tier)}
    assert {"image", "left", "top", "right", "bottom", "scene", "variations", "feather", "seed"} <= fields
    assert {"person", "outfit_image", "outfit"} <= {f["id"] for f in registry["outfit"].fields(tier)}
    assert {"kind", "blurry"} <= {f["id"] for f in registry["restore"].fields(tier)}
    for text, app in (("quero expandir a foto para os lados", "outpaint"), ("restaurar essa foto antiga com riscos e poeira", "restore"), ("trocar a roupa dela por um vestido", "outfit")):
        probs = cf_router.local_provider(text, {"image"})
        assert max(probs, key=probs.get) == app, (text, max(probs, key=probs.get))


def test_pad_then_stitch_through_the_dag_returns_the_source_in_the_kept_area(tmp_path):
    import cf_factory
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path
    cf_apps.configure(base, base / "outputs")
    tier = cf_tiers.detect()
    registry = caps.Registry(cf_apps.registry(), tier)
    source = photo((320, 240))
    path = tmp_path / "s.png"
    source.save(path)
    env = dag.Env(base, tmp_path / "out", tier, lambda i: dict(type="image", path=str(path)) if i == "m" else None)

    class Ctx:
        control = None
        def progress(self, *a, **k): pass
        def check(self): pass
    graph = {"nodes": [{"id": "pad", "cap": "outpaint_pad", "inputs": {"image": {"media": "m"}}, "params": {"right": 128, "left": 128}},
                       {"id": "fix", "cap": "outpaint_stitch", "inputs": {"original": {"media": "m"}, "generated": {"from": "pad.image"}, "plan": {"from": "pad.plan"}}, "params": {"feather": 0}}]}
    run = dag.execute(graph, registry, env, Ctx())
    plan = run["nodes"]["pad"]["outputs"]["plan"]["value"]
    out = np.asarray(Image.open(run["nodes"]["fix"]["outputs"]["image"]["path"]))
    x0, y0, x1, y1 = plan["box"]
    assert (out[y0:y1, x0:x1] == np.asarray(source.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS))).all()
    assert Image.open(run["nodes"]["pad"]["outputs"]["mask"]["path"]).mode == "L"
