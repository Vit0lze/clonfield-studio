"""Wan 2.2 video on GGUF: pinned weights vs the real Hugging Face API, graphs vs the real ComfyUI v0.44.0 / ComfyUI-GGUF source (node and input
names), controls (seconds, FPS, size) and guard rails. NOTHING here generates a video: that needs a GPU (BLOQUEADO_GPU)."""
import ast
import os

import pytest
import requests

import cf_apps
import cf_tiers
import cf_wan as wan

COMFY_TAG = "v0.44.0"
RAW = "https://raw.githubusercontent.com/{repo}/{rev}/{path}"
SOURCES = {  # node class -> file in the ComfyUI repo at COMFY_TAG
    "nodes.py": ["CLIPLoader", "VAELoader", "UNETLoader", "CLIPTextEncode", "KSampler", "KSamplerAdvanced", "VAEDecode", "LoadImage"],
    "comfy_extras/nodes_model_advanced.py": ["ModelSamplingSD3"],
    "comfy_extras/nodes_wan.py": ["WanImageToVideo", "Wan22ImageToVideoLatent"],
    "comfy_extras/nodes_hunyuan.py": ["EmptyHunyuanLatentVideo"],
    "comfy_extras/nodes_video.py": ["CreateVideo", "SaveVideo"],
}


def online():
    try:
        return requests.head("https://huggingface.co", timeout=5).status_code < 500
    except requests.RequestException:
        return False


needs_net = pytest.mark.skipif(not online(), reason="sem rede")


def node_inputs(source, class_name):
    """Input names of a ComfyUI node from its source: INPUT_TYPES keys (v1) or every `.Input("name")` of define_schema (v3)."""
    tree = ast.parse(source)
    cls = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name), None)
    if cls is None:
        return None
    names = set()
    for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
        for node in ast.walk(fn):
            if isinstance(node, ast.Dict) and fn.name == "INPUT_TYPES":
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value in ("required", "optional") and isinstance(value, ast.Dict):
                        names |= {k.value for k in value.keys if isinstance(k, ast.Constant)}
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Input" and node.args and isinstance(node.args[0], ast.Constant):
                names.add(node.args[0].value)
    return names


@pytest.fixture(scope="module")
def sources(tmp_path_factory):
    found = {}
    for path, classes in SOURCES.items():
        text = requests.get(RAW.format(repo="comfyanonymous/ComfyUI", rev=COMFY_TAG, path=path), timeout=30)
        text.raise_for_status()
        for name in classes:
            found[name] = node_inputs(text.text, name)
    gguf = requests.get(RAW.format(repo="city96/ComfyUI-GGUF", rev=wan.GGUF_PACK[1], path="nodes.py"), timeout=30)
    gguf.raise_for_status()
    found["UnetLoaderGGUF"] = node_inputs(gguf.text, "UnetLoaderGGUF")
    return found


@needs_net
@pytest.mark.parametrize("model", list(wan.MODELS))
@pytest.mark.parametrize("mode", [wan.TEXT_MODE, wan.IMAGE_MODE])
def test_graph_uses_only_real_node_and_input_names(sources, model, mode):
    image = "x.png" if mode == wan.IMAGE_MODE else None
    graph = wan.make_graph(model, mode, image, "uma raposa corre na neve", "", "Horizontal · 832 × 480", 3, 16, 20, 3.5, 7)
    for node_id, node in graph.items():
        known = sources.get(node["class_type"])
        assert known, f"{node['class_type']} não existe no ComfyUI {COMFY_TAG} / ComfyUI-GGUF fixado"
        given = {k for k in node["inputs"] if "." not in k}  # dotted keys are the nested widgets of a combo (format.codec)
        assert given <= known, f"{node['class_type']}: entradas inexistentes {sorted(given - known)}"
    # the links must point at nodes that exist
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in graph


@needs_net
def test_pinned_weights_match_the_real_hugging_face_listing():
    seen = set()
    for key in wan.MODELS:
        for mode in (wan.TEXT_MODE, wan.IMAGE_MODE):
            for folder, repo, filename, revision, size, sha in wan.files_for(key, mode):
                if (repo, filename) in seen:
                    continue
                seen.add((repo, filename))
                info = requests.get(f"https://huggingface.co/api/models/{repo}/revision/{revision}", params={"blobs": "true"}, timeout=30).json()
                file = next(s for s in info["siblings"] if s["rfilename"] == filename)
                assert file["lfs"]["sha256"].startswith(sha), filename
                assert abs(file["size"] - size) <= max(8_000_000, size // 50), (filename, file["size"], size)


@needs_net
def test_gguf_pack_commit_exists_on_github():
    repo, commit = wan.GGUF_PACK
    response = requests.get(f"https://api.github.com/repos/{repo.removeprefix('https://github.com/')}/commits/{commit}", timeout=20)
    assert response.status_code == 200 and response.json()["sha"] == commit


@pytest.mark.parametrize("seconds,fps,expected", [(5, 16, 81), (3, 24, 73), (1, 8, 9), (10, 30, 301), (2.5, 16, 41)])
def test_seconds_and_fps_become_a_valid_4n_plus_1_length(seconds, fps, expected):
    frames = wan.frames_for(seconds, fps)
    assert frames == expected and (frames - 1) % 4 == 0


def test_a14b_is_two_samplers_over_two_weight_files_and_5b_is_one():
    a14b = wan.make_graph("a14b-q6", wan.TEXT_MODE, None, "p", "", "Horizontal · 832 × 480", 5, 16, 20, 3.5, 1)
    assert {n["inputs"]["unet_name"] for n in a14b.values() if n["class_type"] == "UnetLoaderGGUF"} == {"Wan2.2-T2V-A14B-HighNoise-Q6_K.gguf", "Wan2.2-T2V-A14B-LowNoise-Q6_K.gguf"}
    first, second = a14b["3"]["inputs"], a14b["4"]["inputs"]
    assert (first["start_at_step"], first["end_at_step"], first["return_with_leftover_noise"], first["add_noise"]) == (0, 10, "enable", "enable")
    assert (second["start_at_step"], second["add_noise"]) == (10, "disable") and a14b["8"]["inputs"]["samples"] == ["4", 0]
    five = wan.make_graph("5b-q6", wan.TEXT_MODE, None, "p", "", "Horizontal · 832 × 480", 5, 24, 20, 5, 1)
    assert [n["class_type"] for n in five.values()].count("KSampler") == 1 and five["37"]["class_type"] == "UnetLoaderGGUF"
    assert wan.make_graph("5b-fp16", wan.TEXT_MODE, None, "p", "", "Horizontal · 832 × 480", 5, 24, 20, 5, 1)["37"]["class_type"] == "UNETLoader"  # the original weights keep the core loader


def test_image_to_video_feeds_the_photo_and_uses_the_i2v_weights():
    g = wan.make_graph("a14b-q6", wan.IMAGE_MODE, "foto.png", "p", "", "Horizontal · 832 × 480", 5, 16, 20, 3.5, 1)
    assert g["55"]["class_type"] == "WanImageToVideo" and g["55"]["inputs"]["start_image"] == ["56", 0]
    assert g["37"]["inputs"]["unet_name"].startswith("Wan2.2-I2V-A14B-HighNoise")
    assert g["3"]["inputs"]["positive"] == ["55", 0] and g["3"]["inputs"]["latent_image"] == ["55", 2]
    with pytest.raises(ValueError, match="foto"):
        wan.make_graph("a14b-q6", wan.IMAGE_MODE, None, "p", "", "Horizontal · 832 × 480", 5, 16, 20, 3.5, 1)


def test_fps_and_length_reach_the_graph():
    g = wan.make_graph("5b-q6", wan.TEXT_MODE, None, "p", "", "Horizontal · 832 × 480", 3, 12, 20, 5, 1)
    assert g["57"]["inputs"]["fps"] == 12 and g["55"]["inputs"]["length"] == wan.frames_for(3, 12)


@pytest.mark.parametrize("kwargs,message", [
    (dict(size="Personalizado", width=830, height=480), "múltiplos"),                     # not a multiple of 16
    (dict(size="Personalizado", width=1920, height=1920), "limite"),                      # over the pixel budget
    (dict(seconds=0.2), "segundos"), (dict(seconds=60), "segundos"), (dict(fps=2), "quadros por segundo"),
    (dict(steps=3), "passos"), (dict(cfg=0), "CFG"), (dict(seed=-5), "seed"),
])
def test_bad_controls_are_refused_with_the_reason(kwargs, message):
    base = dict(model_key="5b-q6", mode=wan.TEXT_MODE, image=None, prompt="p", negative="", size="Horizontal · 832 × 480", seconds=3, fps=24, steps=20, cfg=5, seed=1, vram_gb=15)
    base.update(kwargs)
    with pytest.raises(ValueError, match=message):
        wan.make_graph(**base)


def test_5b_needs_multiples_of_32_and_a14b_of_16():
    ok = dict(mode=wan.TEXT_MODE, image=None, prompt="p", negative="", size="Personalizado", seconds=3, fps=16, steps=20, cfg=5, seed=1, vram_gb=24)
    wan.make_graph("a14b-q6", width=848, height=480, **ok)  # 848 = 53*16
    with pytest.raises(ValueError, match="32"):
        wan.make_graph("5b-q6", width=848, height=480, **ok)


def test_download_size_is_known_before_anything_downloads(tmp_path):
    total, missing = wan.download_gb("a14b-q6", wan.TEXT_MODE, tmp_path)
    assert 30 < total < 33 and missing == total  # two 12 GB files + text encoder + VAE
    assert wan.download_gb("5b-q6", wan.IMAGE_MODE, tmp_path)[0] < 14
    (tmp_path / "vae").mkdir()
    (tmp_path / "vae" / "wan2.2_vae.safetensors").write_bytes(b"x")
    assert wan.download_gb("5b-q6", wan.IMAGE_MODE, tmp_path)[1] < wan.download_gb("5b-q6", wan.IMAGE_MODE, tmp_path)[0]


def test_video_apps_expose_model_seconds_fps_size_and_variations():
    os.environ["CLONFIELD_FAKE_VRAM"] = "15"
    tier = cf_tiers.detect()
    for app_id, mode in (("text2video", wan.TEXT_MODE), ("animate", wan.IMAGE_MODE)):
        fields = {f["id"]: f for f in cf_apps.registry()[app_id].fields(tier)}
        assert fields["mode"]["default"] == mode
        assert {"model", "size", "seconds", "fps", "width", "height", "steps", "cfg", "seed", "variations"} <= set(fields)
        assert {o["value"] for o in fields["model"]["options"]} == set(wan.MODELS) | {"ltxv-2b"}
        assert "Personalizado" in {o["value"] for o in fields["size"]["options"]}
        assert fields["seconds"]["max"] == wan.SECONDS[1] and ("image" in fields) == (mode == wan.IMAGE_MODE)
