"""See-through integration. Package test uses real PIL/psd-tools files; the live test needs ComfyUI on :8188 with the
pinned ComfyUI-See-through pack (prepare_seethrough.py). Weights are never downloaded: auto_download is switched off."""
import io
import json
import zipfile
from functools import partial

import pytest
import requests
from PIL import Image

import cf_seethrough as st


def png(size, color):
    buffer = io.BytesIO()
    Image.new("RGBA", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def test_profiles_build_valid_graphs_and_reject_bad_input():
    nf4 = st.build_graph("T4 · NF4 (leve)", 7, 30, "a.png")
    assert nf4["2"]["inputs"]["quant_mode"] == "nf4" and nf4["3"]["inputs"]["quant_mode"] == "nf4"
    full = st.build_graph("BF16 completo", 7, 30, "a.png", resolution=1280)
    assert full["2"]["inputs"]["quant_mode"] == "none" and not full["2"]["inputs"]["group_offload"]
    for bad in (dict(profile="x", seed=1, steps=30), dict(profile=st.DEFAULT_PROFILE, seed=-1, steps=30),
                dict(profile=st.DEFAULT_PROFILE, seed=1, steps=0)):
        with pytest.raises(ValueError):
            st.build_graph(bad["profile"], bad["seed"], bad["steps"], "a.png")
    with pytest.raises(ValueError):
        st.build_graph(st.DEFAULT_PROFILE, 1, 30, "a.png", resolution=1000)


def test_package_psd_zip_and_preview_keep_layer_order_and_pixels(tmp_path):
    pytest.importorskip("psd_tools")
    from psd_tools import PSDImage
    info = {"width": 64, "height": 48, "layers": []}
    layers = [dict(name="back_hair", left=0, top=0, png=png((64, 48), (0, 0, 255, 255)), depth_png=None, depth_median=0.9),
              dict(name="face", left=16, top=8, png=png((32, 32), (255, 0, 0, 255)), depth_png=png((32, 32), (9, 9, 9, 255)), depth_median=0.2)]
    out = st.write_package(info, layers, tmp_path)
    names = {p.name for p in out}
    assert names == {"camadas_previa.png", "camadas.psd", "camadas.zip"}
    psd = PSDImage.open(tmp_path / "camadas.psd")
    assert [l.name for l in psd] == ["back_hair", "face"]
    assert psd.size == (64, 48)
    composite = Image.open(tmp_path / "camadas_previa.png")
    assert composite.getpixel((20, 20)) == (255, 0, 0, 255) and composite.getpixel((2, 2)) == (0, 0, 255, 255)
    with zipfile.ZipFile(tmp_path / "camadas.zip") as bundle:
        assert {"layers.json", "layers/face.png", "depth/face.png"} <= set(bundle.namelist())


def server_up():
    try:
        return "SeeThrough_SavePSD" in requests.get(st.SERVER + "/object_info/SeeThrough_SavePSD", timeout=3).json()
    except (requests.RequestException, ValueError):
        return False


@pytest.mark.skipif(not server_up(), reason="ComfyUI with See-through pack not running on :8188")
@pytest.mark.parametrize("profile", list(st.PROFILES))
def test_live_comfyui_accepts_graph_then_refuses_to_download(tmp_path, profile):
    import cf_workflows as workflows
    image = tmp_path / "in.png"
    Image.new("RGB", (256, 256), "white").save(image)
    graph = st.build_graph(profile, 3, 4, "x.png")
    for node in ("2", "3"):
        graph[node]["inputs"]["auto_download"] = False  # never pull 10 GB in a test
    job = workflows.run(graph, tmp_path, lambda *a, **k: None, prepare=partial(st.prepare, image=image),
                        title="see-through", family="seethrough", stall=120)
    # Accepted by ComfyUI input validation (types, combos, links); fails only at weight loading.
    assert job["status"] == "falhou", job
    assert "local" in job["message"].lower() or "not found" in job["message"].lower() or "SeeThrough" in job["message"], job["message"]
