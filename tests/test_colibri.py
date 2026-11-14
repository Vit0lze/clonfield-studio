"""colibri (github.com/JustVugg/colibri) as a local LLM backend for the chat and the agent.

Backend selection is checked without a server. The live tests talk to a REAL `coli serve` (set CLONFIELD_COLIBRI_URL; `CLONFIELD_COLIBRI_E2E=1` builds the pinned engine and serves a real
LFM3-VL-2B Q4_K_M GGUF on CPU in the install test below). No stubs: a skipped test means no server.
A 2B model proves the wire formats and the tool-call path, not the quality of the 9B-class models the Colab would serve.
"""

import os
import socket
from pathlib import Path

import pytest
import requests

import cf_agent as agent
import cf_colibri
import cf_llm

URL = os.environ.get("CLONFIELD_COLIBRI_URL", "")


def reachable():
    try:
        return bool(URL) and requests.get(URL + "/health", timeout=2).status_code == 200
    except requests.RequestException:
        return False


LIVE = pytest.mark.skipif(not reachable(), reason="sem servidor colibri (defina CLONFIELD_COLIBRI_URL)")


@pytest.fixture(autouse=True)
def fresh_cache():
    cf_llm._health.update(at=0.0, pick=None, key=None)
    yield
    cf_llm._health.update(at=0.0, pick=None, key=None)


def test_colibri_is_never_guessed_from_a_port(monkeypatch):
    monkeypatch.delenv("CLONFIELD_COLIBRI_URL", raising=False)
    monkeypatch.delenv("CLONFIELD_LLM_BACKEND", raising=False)
    assert [name for name, _ in cf_llm.candidates()] == ["llama"]  # a stranger on :8000 must not pass for a model


def test_backend_order_and_forcing(monkeypatch):
    monkeypatch.setenv("CLONFIELD_COLIBRI_URL", "http://127.0.0.1:9/")
    monkeypatch.setenv("CLONFIELD_LLAMA_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("CLONFIELD_LLM_BACKEND", raising=False)
    assert cf_llm.candidates() == [("llama", "http://127.0.0.1:9"), ("colibri", "http://127.0.0.1:9")]
    monkeypatch.setenv("CLONFIELD_LLM_BACKEND", "colibri")
    assert cf_llm.candidates() == [("colibri", "http://127.0.0.1:9")]
    assert cf_llm.backend() == "colibri" and not cf_llm.available() and agent.choose_provider() is None
    monkeypatch.setenv("CLONFIELD_LLM_BACKEND", "llama")
    assert [n for n, _ in cf_llm.candidates()] == ["llama"]


@pytest.fixture
def colibri(monkeypatch):
    monkeypatch.setenv("CLONFIELD_LLM_BACKEND", "colibri")
    monkeypatch.setenv("CLONFIELD_COLIBRI_URL", URL)
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    return URL


@LIVE
def test_live_chat_text_comes_from_the_colibri_model(colibri):
    assert cf_llm.backend() == "colibri" and cf_llm.available() and cf_llm.models()[0].endswith("colibri")
    text = cf_llm.generate("Responda em português, em uma frase curta.", "O que é um estúdio de imagens?", timeout=120)
    assert len(text) > 10 and "<think>" not in text


@LIVE
def test_live_agent_provider_is_colibri_and_parses_a_tool_call(colibri):
    provider = agent.choose_provider()
    assert provider is not None and provider.name == "colibri" and provider.model.endswith("colibri")
    tools = [dict(name="list_capabilities", description="Lista capacidades do Studio", parameters={"type": "object", "properties": {"query": {"type": "string", "description": "palavras-chave"}}})]
    replies = [provider.step("Você opera um estúdio de mídia. Chame ferramentas.", [dict(role="user", text="Quais capacidades servem para ampliar imagem? Use a ferramenta.")], tools) for _ in range(3)]
    called = [r for r in replies if r["calls"]]
    assert called, f"nenhuma das 3 respostas trouxe chamada de ferramenta estruturada: {replies}"
    assert called[0]["calls"][0]["name"] == "list_capabilities" and isinstance(called[0]["calls"][0]["args"], dict)


# ---------------------------------------------------------------- the install path (pins, build, import, serve)
def test_pins_match_hugging_face():
    """Every pinned file against the REAL Hugging Face API: size and SHA-256 of the revision we download."""
    for key, spec in cf_colibri.MODELS.items():
        try:
            tree = requests.get(f"https://huggingface.co/api/models/{spec['repo']}/tree/{spec['revision']}", timeout=20)
        except requests.RequestException as exc:
            pytest.skip(f"sem rede para o Hugging Face: {exc}")
        assert tree.ok, (key, tree.status_code)
        entry = next(e for e in tree.json() if e["path"] == spec["file"])
        assert (entry["size"], entry["lfs"]["oid"]) == (spec["size"], spec["sha256"]), key
    assert [k for k, v in cf_colibri.MODELS.items() if not v["abliterated"]] == ["protocol_test_lfm3_2b"]  # the only non-abliterated entry is the CPU protocol stand-in
    assert cf_colibri.DEFAULT in cf_colibri.MODELS and cf_colibri.MODELS[cf_colibri.DEFAULT]["abliterated"]


def test_engine_commit_is_pinned_and_a_different_checkout_is_refused(tmp_path, monkeypatch):
    src = cf_colibri.src_dir(tmp_path)
    src.mkdir(parents=True)
    cf_colibri.run(["git", "init", "-q"], src)
    cf_colibri.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"], src)
    with pytest.raises(ValueError, match="commit fixado"):
        cf_colibri.install_engine(tmp_path, cuda=False)


E2E = pytest.mark.skipif(not os.environ.get("CLONFIELD_COLIBRI_E2E"), reason="CLONFIELD_COLIBRI_E2E=1 (clona e compila o colibri, ~1 min; reaproveita CLONFIELD_COLIBRI_GGUF se definido)")


@E2E
def test_install_engine_import_model_and_serve_for_real(tmp_path):
    key = "protocol_test_lfm3_2b"
    cached = os.environ.get("CLONFIELD_COLIBRI_GGUF")  # an already downloaded copy; prepare() still checks its SHA-256
    if cached:
        target = cf_colibri.gguf_path(tmp_path, key)
        target.parent.mkdir(parents=True)
        target.symlink_to(Path(cached).resolve())
    engine = cf_colibri.install_engine(tmp_path, cuda=False)
    assert engine.is_file()
    folder = cf_colibri.prepare(tmp_path, key)
    assert (folder / "config.json").is_file()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = cf_colibri.start(tmp_path, key, port=port, wait=240)
    try:
        assert os.environ["CLONFIELD_LLM_BACKEND"] == "colibri" and os.environ["CLONFIELD_COLIBRI_URL"].endswith(str(port))
        cf_llm._health.update(at=0.0, pick=None, key=None)
        assert cf_llm.backend() == "colibri" and cf_llm.available()
        assert len(cf_llm.generate("Responda em uma frase.", "Diga olá.", timeout=120)) > 1
    finally:
        cf_colibri.stop(process)
    assert "CLONFIELD_COLIBRI_URL" not in os.environ
