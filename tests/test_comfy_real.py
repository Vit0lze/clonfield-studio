"""Graphs the Studio builds, checked by a REAL ComfyUI 0.44.0 running on CPU (POST /prompt validation: node names, input names, types, ranges, combo values,
links) and, for the MOSS layout, one node chain EXECUTED for real. Nothing here loads a model or makes an image/video/audio/3D file: that needs the T4.

The scratch ComfyUI lives in ~/.cache/clonfield-comfyui (src + venv + ComfyUI-GGUF at the pinned commit). Point CLONFIELD_COMFY_CPU_URL at a server that is
already running, or let the fixture start `start.sh`. Without that install the tests skip (the AST/fixture tests elsewhere still run)."""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest
import requests

import cf_3d
import cf_audio
import cf_comfy_check as check
import cf_moss
import cf_wan

HOME = Path(os.environ.get("CLONFIELD_COMFY_CPU_HOME") or Path.home() / ".cache" / "clonfield-comfyui")
URL = os.environ.get("CLONFIELD_COMFY_CPU_URL", "http://127.0.0.1:8199")
IMAGE = Path(__file__).parent / "e2e" / "fixtures" / "portrait.png"
VIDEO = Path(__file__).parent / "e2e" / "fixtures" / "clip.mp4"


def up(url):
    try:
        return requests.get(f"{url}/system_stats", timeout=2).status_code == 200
    except requests.RequestException:
        return False


@pytest.fixture(scope="module")
def comfy():
    process = None
    url = URL
    if not up(url):
        if not (HOME / "start.sh").is_file():
            pytest.skip("ComfyUI de teste em CPU não instalado (~/.cache/clonfield-comfyui)")
        url = "http://127.0.0.1:8299"
        process = subprocess.Popen([str(HOME / "start.sh"), "8299"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(120):
            if up(url):
                break
            time.sleep(1)
        else:
            process.terminate()
            pytest.skip("o ComfyUI de teste não subiu")
    info = requests.get(f"{url}/object_info", timeout=60).json()
    yield dict(url=url, info=info, models=HOME / "src" / "models", inputs=HOME / "src" / "input")
    if process:
        process.terminate()


def ok(comfy, graph):
    return check.validate(graph, comfy["url"], str(comfy["models"]), str(comfy["inputs"]), str(IMAGE), str(VIDEO))


def explain(errors):
    return [(e["node"], e.get("class_type"), e["type"], str(e["details"])[:120]) for e in errors]


def test_the_real_comfyui_rejects_a_wrong_graph_so_the_check_means_something(comfy):
    good = cf_audio.make_graph("small_sfx", "rain", 5, 1)
    assert ok(comfy, good) == []
    bad = json.loads(json.dumps(good))
    bad["3"]["inputs"]["seed_typo"] = bad["3"]["inputs"].pop("seed")
    bad["11"]["inputs"]["seconds"] = 99999.0
    types = {e["type"] for e in ok(comfy, bad)}
    assert types & {"required_input_missing", "value_bigger_than_max"}, types


@pytest.mark.parametrize("model", list(cf_wan.MODELS))
@pytest.mark.parametrize("mode", [cf_wan.TEXT_MODE, cf_wan.IMAGE_MODE])
def test_wan_graphs_are_accepted(comfy, model, mode):
    graph = cf_wan.make_graph(model, mode, "x.png" if mode == cf_wan.IMAGE_MODE else None, "uma raposa corre na neve", "", "Horizontal · 832 × 480", 3, 16, 20, 3.5, 7, vram_gb=24)
    assert ok(comfy, graph) == []


@pytest.mark.parametrize("mode", [cf_wan.TEXT_MODE, cf_wan.IMAGE_MODE])
def test_wan_fast_lightx2v_graphs_are_accepted(comfy, mode):
    graph = cf_wan.make_graph("a14b-q6", mode, "x.png" if mode == cf_wan.IMAGE_MODE else None, "uma raposa corre na neve", "", "Horizontal · 832 × 480", 3, 16, 20, 3.5, 7, vram_gb=24, fast=True)
    assert ok(comfy, graph) == []


@pytest.mark.parametrize("fast", [False, True])
def test_wan_first_last_frame_graphs_are_accepted(comfy, fast):
    graph = cf_wan.make_graph("a14b-q6", cf_wan.FLF_MODE, "x.png", "um gato vira um leão", "", "Horizontal · 832 × 480", 3, 16, 20, 3.5, 7, vram_gb=24, fast=fast, end_image="y.png")
    assert graph["55"]["class_type"] == "WanFirstLastFrameToVideo"
    assert ok(comfy, graph) == []


@pytest.mark.parametrize("model", list(cf_audio.MODELS))
@pytest.mark.parametrize("fmt", list(cf_audio.FORMATS))
def test_audio_graphs_are_accepted(comfy, model, fmt):
    assert ok(comfy, cf_audio.make_graph(model, "rain on a tin roof", 10, 3, fmt)) == []


@pytest.mark.parametrize("engine", list(cf_3d.ENGINES))
def test_the_official_3d_template_converts_and_the_real_comfyui_accepts_it(comfy, engine):
    graph = cf_3d.build(comfy["info"], engine, seed=5, texture=2048, faces=500_000)
    errors = ok(comfy, graph)
    assert errors == [], explain(errors)
    names = {f[0] for f in cf_3d.files_for(graph)}
    assert ("pixal3d_int8_convrot.safetensors" in names) == (engine == "pixal3d") and ("trellis_2_int8_convrot.safetensors" in names) == (engine == "trellis2")


BOXES = [dict(x=0.1, y=0.1, w=0.5, h=0.3, kind="text", text="OFERTA", desc="letras creme grandes"), dict(x=0.2, y=0.5, w=0.6, h=0.4, kind="obj", desc="um cavaleiro de armadura")]


def test_moss_graphs_are_accepted(comfy):
    for graph in (cf_moss.generate_graph("pôster de fantasia", BOXES, 768, 1152, 3), cf_moss.edit_boxes_graph("a rua com um cartaz novo", BOXES, cf_moss.work_size((640, 480)), "x.png", "m.png", 3),
                  cf_moss.instruction_graph(comfy["info"], "Change only the jacket to black wool. Keep everything else.", "x.png", 3)):
        errors = ok(comfy, graph)
        assert errors == [], explain(errors)


def test_the_boxes_really_become_the_moss_layout_prompt_in_the_real_comfyui(comfy):
    """EXECUTES CreateBoundingBoxes -> MOSSImageLayoutPrompt for real (no model involved) and reads the prompt the MOSS encoder would get."""
    graph = cf_moss.generate_graph("frame", BOXES, 768, 1152, 3)
    run = {"11": graph["11"], "12": graph["10"], "13": {"class_type": "PreviewAny", "inputs": {"source": ["12", 0]}}}
    run["12"] = json.loads(json.dumps(run["12"]))
    response = requests.post(f"{comfy['url']}/prompt", json={"prompt": run}, timeout=30).json()
    assert not response.get("node_errors"), response
    for _ in range(40):
        history = requests.get(f"{comfy['url']}/history/{response['prompt_id']}", timeout=10).json()
        if history:
            break
        time.sleep(0.5)
    out = history[response["prompt_id"]]
    assert out["status"]["status_str"] == "success"
    layout = json.loads(out["outputs"]["13"]["text"][0])
    assert layout["summary"]["caption"] == "frame" and layout["bbox_format"] == "yxyx"
    text, obj = layout["items"]
    assert text["label"] == "text" and text["text"] == "OFERTA" and text["caption"] == "letras creme grandes"
    assert obj["label"] == "object" and obj["caption"] == "um cavaleiro de armadura"
    # box 1: x .1-.6 of 768 -> -307..77, y .1-.4 of 1152 -> -461..-115 (origin at the canvas centre)
    assert text["bbox"] == [-461, -308, -115, 77]


def test_every_image_recipe_with_loras_and_references_is_accepted(comfy):
    """The recipes the Studio shipped before (Qwen, FLUX.2/3, Krea, Z-Image), with 0-2 reference images and a LoRA: the real worker validates them all."""
    import cf_model_lab as lab
    long_caption = "A detailed photograph of a calm lake at dawn with mist over the water, pine trees on the shore, soft golden light and a small wooden boat in the foreground. " * 3
    checked = 0
    for key, preset in lab.PRESETS.items():
        if key in ("sdxl", "sd15"):  # checkpoint recipes need a Civitai checkpoint choice, not a fixed file
            continue
        names, _ = lab.names_and_sources(preset, {}, False)
        for refs in range(0, min(preset.refs, 2) + 1):
            for lora in (False, True):
                cfg = max(1.0, preset.cfg)
                n = dict(names, **({"LoRA": ["demo_lora.safetensors"]} if lora else {}))
                graph, uploads, _used = lab.make_graph(preset, n, long_caption, "blur" if cfg > 1 else "", 1024, 768, preset.steps, cfg, 5, ["a.png", "b.png"][:refs], 1.0, False, [(1.0, 1.0)] if lora else [])
                for node_id in uploads:
                    graph[node_id]["inputs"]["image"] = "portrait.png"
                errors = ok(comfy, graph)
                assert errors == [], (key, refs, lora, explain(errors))
                checked += 1
    assert checked >= 20


@pytest.mark.parametrize("key", ["scail2", "animate2"])
def test_character_replacement_templates_convert_with_subgraphs_and_are_accepted(comfy, key):
    """Official Wan SCAIL-2 / Wan Animate 2 templates (subgraphs flattened by cf_ui2api): the real worker validates the 47-82 node graphs."""
    import cf_templates
    graph = cf_templates.build(key, comfy["info"], prompt="a stylish dancer", seed=4)
    assert len(graph) > 25
    errors = ok(comfy, graph)
    assert errors == [], explain(errors)
    names = {n for n, _ in cf_templates.files_for(key, graph)}
    assert any(n.endswith("int8_convrot.safetensors") for n in names)


def test_the_official_stable_audio_template_with_its_reprompt_subgraph_converts_too(comfy):
    """A second subgraph template (Stable Audio 3 + Qwen re-prompt): converted mechanically and accepted."""
    import cf_ui2api
    wf = requests.get("https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/audio_stable_audio_3_medium.json", timeout=30).json()
    graph = cf_ui2api.convert(wf, comfy["info"])
    assert len(graph) > 15
    errors = ok(comfy, graph)
    assert errors == [], explain(errors)


@pytest.mark.parametrize("mode", ["text", "image"])
def test_ltx_video_graphs_are_accepted(comfy, mode):
    import cf_ltxv
    graph = cf_ltxv.build(comfy["info"], mode, "A red fox moving gracefully through a snowy forest at dawn, its russet coat vivid against the white landscape.", seconds=4, fps=24)
    errors = ok(comfy, graph)
    assert errors == [], explain(errors)


def test_agent_system_info_and_free_memory_against_the_real_worker(comfy, monkeypatch, tmp_path):
    """The agent's two memory tools talk to a real ComfyUI: /system_stats for the numbers, /free to unload."""
    import types
    import cf_agent
    import cf_workflows
    monkeypatch.setattr(cf_workflows, "SERVER", comfy["url"])
    box = cf_agent.Toolbox(None, types.SimpleNamespace(tier=types.SimpleNamespace(gpu="CPU de teste", vram_gb=0.0, label="Leve"), base=tmp_path), None)
    info = box.system_info()
    assert info["worker"] and info["worker"]["ram_total_gb"] > 0 and info["worker"]["ram_free_gb"] > 0 and info["disk_free_gb"] > 0
    assert box.free_memory()["ok"] is True


def test_a14b_stage_graphs_are_accepted_and_a_latent_survives_the_save_upload_load_roundtrip(comfy, tmp_path, monkeypatch):
    """The A14B runs one expert per prompt. REAL ComfyUI: both stage graphs validate, and a latent saved by stage 1 is downloaded by the Studio's own
    executor, uploaded back and loaded by LoadLatent in a second prompt. (No model is loaded here: the latent is an empty tiny one.)"""
    import cf_seedvr2
    import cf_workflows as workflows
    graph = cf_wan.make_graph("a14b-q4", cf_wan.FLF_MODE, "x.png", "uma raposa", "", "Horizontal · 832 × 480", 3, 16, 20, 3.5, 7, None, None, 15, fast=True, end_image="x.png")
    one, two = cf_wan.split_a14b(graph, "estagio1.latent")
    assert {"37", "60", "48", "3", "70"} <= set(one) and not ({"47", "61", "49", "4", "8", "58"} & set(one))
    assert {"47", "61", "49", "4", "8", "58", "71"} <= set(two) and not ({"37", "60", "48", "3"} & set(two))
    assert ok(comfy, one) == []
    sample = comfy["inputs"] / "estagio1.latent"
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_bytes(b"placeholder")  # only so the combo of LoadLatent has a value while the graph is validated
    try:
        assert ok(comfy, two) == [], explain(ok(comfy, two))
    finally:
        sample.unlink(missing_ok=True)
    monkeypatch.setattr(workflows, "SERVER", comfy["url"])
    monkeypatch.setattr(cf_seedvr2, "SERVER", comfy["url"])
    save = {"1": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {"width": 64, "height": 64, "length": 5, "batch_size": 1}},
            "2": {"class_type": "SaveLatent", "inputs": {"samples": ["1", 0], "filename_prefix": "ClonField/teste-estagio"}}}
    first = workflows.run(save, tmp_path, lambda *a, **k: None, title="latente 1", family="teste")
    assert first["status"] == "concluído", first
    latents = [tmp_path / first["id"] / name for name in first["results"] if name.endswith(".latent")]
    assert len(latents) == 1 and latents[0].stat().st_size > 0
    load = {"1": {"class_type": "LoadLatent", "inputs": {"latent": latents[0].name}},
            "2": {"class_type": "SaveLatent", "inputs": {"samples": ["1", 0], "filename_prefix": "ClonField/teste-estagio-2"}}}
    second = workflows.run(load, tmp_path, lambda *a, **k: None, title="latente 2", family="teste", files=[latents[0]])
    assert second["status"] == "concluído", second
    again = [tmp_path / second["id"] / name for name in second["results"] if name.endswith(".latent")]
    assert len(again) == 1

    def tensor_bytes(path):  # a .latent is a safetensors file; SaveLatent also embeds the prompt as metadata, so file sizes differ: compare the tensor itself
        raw = path.read_bytes()
        size = int.from_bytes(raw[:8], "little")
        entry = json.loads(raw[8:8 + size])["latent_tensor"]
        start, end = entry["data_offsets"]
        return entry["shape"], raw[8 + size + start:8 + size + end]
    shape_a, data_a = tensor_bytes(latents[0])
    shape_b, data_b = tensor_bytes(again[0])
    assert shape_a == shape_b == [1, 16, 2, 8, 8] and data_a == data_b and len(data_a) > 0
