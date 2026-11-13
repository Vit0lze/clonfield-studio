"""The local LLM stack, checked against the real sources: Hugging Face (model files) and GitHub (llama.cpp release digests). Loading the
9B needs a GPU and is NOT tested here; the tool-calling wire format is tested against a real small Qwen in test_agent.py."""
import io
import tarfile

import pytest
import requests

import cf_llama


def online(url="https://huggingface.co"):
    try:
        return requests.head(url, timeout=5).status_code < 500
    except requests.RequestException:
        return False


def test_default_is_an_abliterated_build_and_nothing_sends_data_out():
    spec = cf_llama.MODELS[cf_llama.DEFAULT]
    assert spec["abliterated"] is True and "abliterated" in spec["file"].lower()
    assert [k for k, v in cf_llama.MODELS.items() if not v["abliterated"]] == ["protocol_test_0.8b"]  # the only non-abliterated entry is the CPU protocol stand-in


@pytest.mark.skipif(not online(), reason="sem rede")
@pytest.mark.parametrize("key", list(cf_llama.MODELS))
def test_pinned_model_files_match_the_real_hugging_face_listing(key):
    spec = cf_llama.MODELS[key]
    info = requests.get(f"https://huggingface.co/api/models/{spec['repo']}/revision/{spec['revision']}", params={"blobs": "true"}, timeout=20).json()
    file = next(s for s in info["siblings"] if s["rfilename"] == spec["file"])
    assert file["lfs"]["sha256"] == spec["sha256"] and file["size"] == spec["size"]
    assert (info.get("cardData") or {}).get("license") == spec["license"]


@pytest.mark.skipif(not online("https://api.github.com"), reason="sem rede")
def test_pinned_llama_cpp_assets_match_the_real_github_digests():
    release = requests.get(f"https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{cf_llama.TAG}", timeout=20).json()
    assets = {a["name"]: a for a in release["assets"]}
    for key, spec in cf_llama.BINARIES.items():
        asset = assets[spec["file"]]
        assert asset["digest"] == "sha256:" + spec["sha256"] and asset["size"] == spec["size"], key


def test_server_command_uses_jinja_for_native_tool_calls_and_refuses_without_a_binary(tmp_path, monkeypatch):
    monkeypatch.delenv("CLONFIELD_LLAMA_BIN", raising=False)
    monkeypatch.setattr(cf_llama.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="llama-server"):
        cf_llama.server_command(tmp_path)
    command = cf_llama.server_command(tmp_path, binary="/x/llama-server")
    assert "--jinja" in command and command[command.index("-m") + 1].endswith("abliterated.Q6_K.gguf") and "127.0.0.1" in command


def test_a_corrupt_download_is_refused_and_removed(tmp_path):
    dest = cf_llama.target(tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"not a model")
    with pytest.raises(ValueError, match="SHA-256"):
        cf_llama.prepare(tmp_path)
    assert not dest.exists()


def test_archive_with_a_path_escape_is_refused(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"hi"))
    with pytest.raises(ValueError, match="suspeito"):
        cf_llama.safe_extract(bad, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()
