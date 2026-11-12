"""Universal component search: local files are real; Hugging Face and Civitai tests hit the public APIs (skipped offline)."""
import pytest
import requests

import cf_search as search


def online(url):
    try:
        return requests.get(url, timeout=5).status_code < 500
    except requests.RequestException:
        return False


def test_local_search_lists_real_files_of_the_slot_folder_and_filters_by_name(tmp_path, monkeypatch):
    monkeypatch.setenv("CLONFIELD_COMFY_MODELS", str(tmp_path))
    (tmp_path / "vae").mkdir()
    (tmp_path / "vae" / "flux2-vae.safetensors").write_bytes(b"x" * 2048)
    (tmp_path / "vae" / "other.safetensors").write_bytes(b"y")
    (tmp_path / "vae" / "notes.txt").write_text("ignored")
    items, nxt = search.search("VAE", "flux2", "local", "flux", tmp_path / "civ")
    assert nxt is None and [i["title"] for i in items] == ["flux2-vae.safetensors"]
    assert items[0]["status"] == "instalado" and items[0]["source"] == "local"


def test_rejects_unknown_family_and_source(tmp_path):
    with pytest.raises(ValueError):
        search.search("VAE", "nope", "local", "", tmp_path)
    with pytest.raises(ValueError):
        search.search("VAE", "flux2", "ftp", "", tmp_path)


@pytest.mark.skipif(not online("https://huggingface.co/api/models?limit=1"), reason="offline")
def test_huggingface_search_marks_results_as_discovered_not_validated(tmp_path):
    items, _ = search.search("Encoder", "qwen21", "huggingface", "qwen3", tmp_path)
    assert items and all(i["source"] == "huggingface" for i in items)
    assert all(i["status"] in ("descoberto", "padrão da receita") and i["install"] is None for i in items)
    assert all("validar" in i["compatible"] for i in items)


@pytest.mark.skipif(not online("https://civitai.red/api/v1/models?limit=1"), reason="offline")
def test_civitai_search_by_role_only_returns_base_compatible_files_with_install_data(tmp_path):
    items, _ = search.search("VAE", "sdxl", "civitai", "", tmp_path)
    assert items and all(i["status"] in ("compatível", "instalado") for i in items)
    first = items[0]
    assert set(first["install"]) == {"model", "version", "file", "expect"} and "SDXL" in first["compatible"].upper()
    # the item carries the identity of its file, and the install request carries what the user was shown
    assert first["variant"]["file_id"] == first["install"]["file"] and first["install"]["expect"]["name"] == first["variant"]["file_name"]
