"""The pinned Qwen3.5-9B GGUF files against the real Hugging Face API. Loading the model needs a GPU and is NOT tested here."""
import pytest
import requests

import cf_llama


def online():
    try:
        return requests.head("https://huggingface.co", timeout=5).status_code < 500
    except requests.RequestException:
        return False


@pytest.mark.skipif(not online(), reason="sem rede")
@pytest.mark.parametrize("key", list(cf_llama.MODELS))
def test_pinned_files_match_the_real_hugging_face_listing(key):
    spec = cf_llama.MODELS[key]
    info = requests.get(f"https://huggingface.co/api/models/{spec['repo']}/revision/{spec['revision']}", params={"blobs": "true"}, timeout=20).json()
    file = next(s for s in info["siblings"] if s["rfilename"] == spec["file"])
    assert file["lfs"]["sha256"].startswith(spec["sha256"])
    assert abs(file["size"] / 1e9 - spec["size_gb"]) < 0.05
    assert (info.get("cardData") or {}).get("license") == spec["license"]


def test_server_command_uses_jinja_for_native_tool_calls_and_refuses_without_a_binary(tmp_path, monkeypatch):
    monkeypatch.delenv("CLONFIELD_LLAMA_BIN", raising=False)
    monkeypatch.setattr(cf_llama.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="llama-server"):
        cf_llama.server_command(tmp_path)
    command = cf_llama.server_command(tmp_path, binary="/x/llama-server")
    assert "--jinja" in command and command[command.index("-m") + 1].endswith("Qwen3.5-9B-Q6_K.gguf")


def test_a_corrupt_download_is_refused_and_removed(tmp_path, monkeypatch):
    dest = cf_llama.target(tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"not a model")
    with pytest.raises(ValueError, match="SHA-256"):
        cf_llama.prepare(tmp_path)
    assert not dest.exists()
