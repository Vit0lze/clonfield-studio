"""One source of truth for LoRAs: every file the worker can see, classified against the model the user is on."""
import json

import numpy as np
import pytest
from safetensors.numpy import save_file
from starlette.testclient import TestClient

import cf_api
import cf_apps
import cf_loras


def lora_file(path, metadata=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    save_file({"lora_down.weight": np.zeros((2, 4), dtype=np.float32), "lora_up.weight": np.zeros((4, 2), dtype=np.float32)}, str(path), metadata=metadata)
    return path


@pytest.fixture()
def world(tmp_path, monkeypatch):
    import shutil
    import cf_factory
    # Content Factory binds one data dir per process: reuse it when another test file already configured it, and start clean.
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path / "data"
    comfy = tmp_path / "comfy"
    shutil.rmtree(base / "loras", ignore_errors=True)
    monkeypatch.setenv("CLONFIELD_COMFY_MODELS", str(comfy))
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    # 1. Civitai download for Qwen 2.1 (sidecar declares the family)
    lora_file(base / "loras" / "pixel_style__cv11.safetensors")
    (base / "loras" / "pixel_style__cv11.json").write_text(json.dumps({"title": "Pixel style", "families": ["qwen21"], "model": 1, "version": 11}))
    # 2. a loose file dropped straight into ComfyUI/models/loras, no sidecar, name gives a hint
    lora_file(comfy / "loras" / "my_flux2_portrait.safetensors")
    # 3. loose file, no hint at all
    lora_file(comfy / "loras" / "mystery.safetensors")
    # 4. loose file whose safetensors header names the base model
    lora_file(comfy / "loras" / "from_header.safetensors", {"modelspec.architecture": "stable-diffusion-xl-v1-base/lora"})
    yield base, comfy
    shutil.rmtree(base / "loras", ignore_errors=True)


def by_name(result):
    return {i["name"]: i for i in result["items"]}


def test_available_sees_both_folders_and_classifies_for_the_current_family(world):
    base, comfy = world
    result = cf_loras.available(base, comfy, "qwen21")
    items = by_name(result)
    assert items["pixel_style__cv11.safetensors"]["compat"] == "confirmada"
    assert items["my_flux2_portrait.safetensors"]["compat"] == "incompatível"  # name says FLUX.2, we are on Qwen
    assert "flux2" in items["my_flux2_portrait.safetensors"]["compat_reason"].lower() or "FLUX" in items["my_flux2_portrait.safetensors"]["compat_reason"]
    assert items["mystery.safetensors"]["compat"] == "desconhecida"
    assert items["from_header.safetensors"]["compat"] == "incompatível"  # header says SDXL
    assert all(i["installed"] for n, i in items.items() if n in {"pixel_style__cv11.safetensors", "mystery.safetensors"})


def test_empty_family_is_never_confirmed(world):
    base, comfy = world
    for family in ("qwen21", "flux2", "flux3", "krea2", "z-image"):
        for item in cf_loras.available(base, comfy, family)["items"]:
            if not item["families"]:
                assert item["compat"] != "confirmada", (family, item["name"])


def test_name_hint_is_only_probable_when_it_matches(world):
    base, comfy = world
    items = by_name(cf_loras.available(base, comfy, "flux2"))
    assert items["my_flux2_portrait.safetensors"]["compat"] == "provável"
    assert items["pixel_style__cv11.safetensors"]["compat"] == "incompatível"
    assert items["from_header.safetensors"]["compat"] == "incompatível"


def test_counts_explain_what_is_installed_for_other_families(world):
    base, comfy = world
    counts = cf_loras.available(base, comfy, "flux3")["counts"]
    assert counts["installed_total"] == 4
    assert counts["installed_for_family"] == 0  # none declared/probable for FLUX.3
    assert counts["installed_other"] == 3  # Qwen (declared), FLUX.2 (name hint), SDXL (header) are all for other families
    assert counts["by_family"]["qwen21"] == 1 and counts["by_family"]["flux2"] == 1 and counts["by_family"]["sdxl"] == 1
    assert counts["unknown"] == 1


def test_catalog_entries_are_listed_not_installed(world):
    base, comfy = world
    items = cf_loras.available(base, comfy, "qwen21")["items"]
    catalog = [i for i in items if i["source"] == "catálogo"]
    assert catalog and not any(i["installed"] for i in catalog)
    assert all(i["compat"] in {"confirmada", "incompatível"} for i in catalog)


def test_loose_comfy_lora_can_be_used_by_a_job(world):
    base, comfy = world
    assert cf_loras.ensure(base, "mystery.safetensors").parent == comfy / "loras"


@pytest.fixture()
def client(world, monkeypatch):
    base, comfy = world
    cf_apps.configure(base, base / "outputs")
    return TestClient(cf_api.build_app(base, base / "outputs", lambda t: t == "pw", "secret"), headers={"Authorization": "Bearer pw"})


def test_endpoint_returns_every_lora_with_compat_and_counts(client):
    body = client.get("/clonfield/api/loras?family=flux3").json()
    assert {"items", "counts", "family"} <= set(body)
    names = {i["name"] for i in body["items"]}
    assert {"pixel_style__cv11.safetensors", "my_flux2_portrait.safetensors", "mystery.safetensors"} <= names  # nothing hidden by filtering
    assert body["counts"]["installed_for_family"] == 0 and body["counts"]["installed_total"] == 4
    assert client.get("/clonfield/api/loras?family=nonsense").status_code == 400
