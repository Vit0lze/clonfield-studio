"""Live Civitai (civitai.red) browsing and a real LoRA download. Needs CIVITAI_TOKEN; skipped without it."""
import os

import pytest

import cf_apps
import cf_civitai
import cf_loras
import cf_model_lab as lab

pytestmark = pytest.mark.skipif(not os.environ.get("CIVITAI_TOKEN"), reason="needs a real CIVITAI_TOKEN")


def test_browse_returns_cards_with_covers_and_adult_models():
    cards, cursor = cf_civitai.browse_loras(lab.PRESETS["qwen21"], sort="downloads")
    assert len(cards) >= 10 and cursor
    assert all(c["files"] and c["title"] and c["covers"] is not None for c in cards)
    assert any(c["adult"] for c in cards), "civitai.red should list adult models"
    data, media_type = cf_civitai.read_catalog_cover(cards[0]["cover_id"])
    assert len(data) > 2000 and media_type.startswith(("image/", "video/"))


def test_install_small_lora_verifies_sha_and_registers_card(tmp_path):
    cards, _ = cf_civitai.browse_loras(lab.PRESETS["qwen21"], sort="downloads")
    small = min((c for c in cards if c["files"][0]["size_mb"] > 0), key=lambda c: c["files"][0]["size_mb"])
    cf_apps.ENV.update(base=tmp_path, out=tmp_path / "out", civitai=tmp_path / "civitai")
    entry, record = cf_civitai.entry_for(lab.PRESETS["qwen21"], small["model"], small["version"], small["files"][0]["file"])
    source = cf_civitai.install(entry, cf_apps.ENV["civitai"])
    version = next(v for v in record["modelVersions"] if v["id"] == entry["version"])
    card = cf_civitai.model_card(record, version, [entry], lab.PRESETS["qwen21"])
    target = cf_loras.link_civitai(tmp_path, entry, source, ["qwen21"], card["covers"], card["page"])
    assert target.is_file() and target.stat().st_size == source.stat().st_size
    local = [i for i in cf_loras.local(tmp_path) if i["name"] == target.name][0]
    assert local["label"] == small["title"] and local["families"] == ["qwen21"] and local["covers"]
