"""LTX-Video 2B from the official templates: controls, frame maths, pinned weights vs the Hugging Face API, wiring into the video apps.
The real-worker acceptance is in test_comfy_real.py."""
import json
from pathlib import Path

import pytest
import requests

import cf_apps
import cf_jobs
import cf_ltxv as ltxv
import cf_tiers
import cf_wan as wan

OBJ = json.loads((Path(__file__).parent / "fixtures" / "objinfo_comfyui_0.44.0.json").read_text(encoding="utf-8"))
LONG = "A red fox moving gracefully through a snowy forest at dawn, its russet coat vivid against the white landscape, steam rising from its breath in the crisp air."


@pytest.mark.parametrize("seconds,fps,expected", [(4, 24, 97), (1, 8, 9), (5, 25, 129), (2.5, 24, 57)])
def test_ltx_needs_8n_plus_1_frames(seconds, fps, expected):
    assert ltxv.frames_for(seconds, fps) == expected and (expected - 1) % 8 == 0


def test_text_and_image_graphs_carry_the_controls():
    t = ltxv.build(OBJ, "text", LONG, seconds=4, fps=24, width=768, height=512, steps=25, cfg=3.5, seed=11)
    assert t["70"]["inputs"] == dict(width=768, height=512, length=97, batch_size=1) and t["72"]["inputs"]["noise_seed"] == 11 and t["72"]["inputs"]["cfg"] == 3.5
    assert t["71"]["inputs"]["steps"] == 25 and t["44"]["inputs"]["ckpt_name"] == "ltx-video-2b-v0.9.5.safetensors" and t["38"]["inputs"]["clip_name"] == "t5xxl_fp8_e4m3fn_scaled.safetensors"
    assert t["38"]["inputs"]["type"] == "ltxv" and t["78"]["inputs"]["fps"] == 24.0 and t["69"]["inputs"]["frame_rate"] == 24.0
    i = ltxv.build(OBJ, "image", LONG, seconds=2, fps=24, image="foto.png")
    assert i["78"]["inputs"]["image"] == "foto.png" and i["77"]["inputs"]["length"] == ltxv.frames_for(2, 24) and i["77"]["inputs"]["image"] == ["78", 0]


@pytest.mark.parametrize("kwargs,words", [(dict(prompt="curto"), "longo"), (dict(seconds=0.1), "segundos"), (dict(seconds=99), "segundos"), (dict(fps=2), "quadros por segundo"),
                                          (dict(width=770), "múltiplos de 32"), (dict(steps=2), "passos"), (dict(seed=-3), "seed"), (dict(mode="x"), "texto em vídeo")])
def test_bad_controls_are_refused_with_the_reason(kwargs, words):
    base = dict(mode="text", prompt=LONG, seconds=4, fps=24, width=768, height=512, steps=30, cfg=3.0, seed=1)
    base.update(kwargs)
    with pytest.raises(ValueError, match=words):
        ltxv.build(OBJ, **base)


def test_pinned_weights_match_the_real_hugging_face_listing():
    for folder, repo, name, revision, size, sha in ltxv.files():
        try:
            info = requests.get(f"https://huggingface.co/api/models/{repo}/revision/{revision}", params={"blobs": "true"}, timeout=30).json()
        except requests.RequestException:
            pytest.skip("sem rede")
        file = next(s for s in info["siblings"] if s["rfilename"] == name)
        assert file["lfs"]["sha256"].startswith(sha) and file["size"] == size, name


def test_download_size_is_known_before_downloading(tmp_path):
    total, missing = ltxv.download_gb(tmp_path)
    assert 11 < total < 12 and missing == total


def test_the_video_apps_offer_ltx_and_dispatch_to_it(monkeypatch, tmp_path):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    for app_id in ("text2video", "animate"):
        fields = {f["id"]: f for f in cf_apps.registry()[app_id].fields(cf_tiers.detect())}
        assert "ltxv-2b" in {o["value"] for o in fields["model"]["options"]}

    class Ctx:
        out_dir = tmp_path
        control = None
        def progress(self, *a, **k): pass
        def check(self): pass
    # run_ltxv asks the worker for /object_info first: with no worker the job fails with a reason (not a crash), proving the dispatch reached run_ltxv
    monkeypatch.setattr(cf_apps.workflows, "SERVER", "http://127.0.0.1:9")
    with pytest.raises(cf_jobs.JobError):
        cf_apps.run_wan(Ctx(), dict(mode=wan.TEXT_MODE, model="ltxv-2b", prompt=LONG), cf_tiers.detect())
