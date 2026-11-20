"""The local LLM stack, checked against the real sources: Hugging Face (model files) and GitHub (llama.cpp release digests). Loading the
9B needs a GPU and is NOT tested here; the tool-calling wire format is tested against a real small Qwen in test_agent.py."""
import io
import tarfile

import os

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


def test_server_command_finds_the_unpacked_binary_without_the_return_value(tmp_path, monkeypatch):
    """The Colab cell calls install_binary() and drops its result; start() must still find the binary (this failed on the T4)."""
    monkeypatch.delenv("CLONFIELD_LLAMA_BIN", raising=False)
    monkeypatch.setattr(cf_llama.shutil, "which", lambda name: None)
    exe = tmp_path / "llama" / cf_llama.TAG / "build" / "bin" / "llama-server"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    assert cf_llama.server_command(tmp_path)[0] == str(exe)


def test_free_port_skips_a_port_that_is_taken_like_colabs_8080():
    import socket
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        busy = taken.getsockname()[1]
        chosen = cf_llama.free_port(busy)
        assert chosen != busy and chosen > 0
        with socket.socket() as probe:  # the chosen port really is bindable
            probe.bind(("127.0.0.1", chosen))
    assert cf_llama.free_port(chosen) == chosen  # a free preferred port is kept


def test_start_launches_on_a_free_port_and_publishes_that_url(tmp_path, monkeypatch):
    """A real child process answers /health on the port start() chose while the preferred one is taken (no model needed)."""
    import socket, stat, sys
    server = tmp_path / "llama" / cf_llama.TAG / "llama-server"
    server.parent.mkdir(parents=True)
    server.write_text(f"#!{sys.executable}\nimport sys, http.server\nprint('ggml_cuda_init: found 1 CUDA devices', flush=True)\nport = int(sys.argv[sys.argv.index('--port') + 1])\n"
                      "class H(http.server.BaseHTTPRequestHandler):\n    def do_GET(self):\n        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n"
                      "    def log_message(self, *a): pass\nhttp.server.HTTPServer(('127.0.0.1', port), H).serve_forever()\n")
    server.chmod(server.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CLONFIELD_LLAMA_BIN", str(server))
    monkeypatch.delenv("CLONFIELD_LLAMA_URL", raising=False)
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        busy = taken.getsockname()[1]
        process = cf_llama.start(tmp_path, wait=20, port=busy)
        try:
            url = os.environ["CLONFIELD_LLAMA_URL"]
            assert url != f"http://127.0.0.1:{busy}" and url.startswith("http://127.0.0.1:")
        finally:
            cf_llama.stop(process)


def _fake_server(tmp_path, monkeypatch, banner, filler=200000):
    import stat, sys
    server = tmp_path / "llama" / cf_llama.TAG / "llama-server"
    server.parent.mkdir(parents=True)
    body = "import sys, http.server\n" + (f"print({banner!r}, flush=True)\n" if banner else "") + f"print('x' * {filler}, flush=True)\n"  # 200 KB of log: a PIPE nobody reads would block here
    body += "port = int(sys.argv[sys.argv.index('--port') + 1])\nclass H(http.server.BaseHTTPRequestHandler):\n    def do_GET(self):\n        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n    def log_message(self, *a): pass\nhttp.server.HTTPServer(('127.0.0.1', port), H).serve_forever()\n"
    server.write_text(f"#!{sys.executable}\n" + body)
    server.chmod(server.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CLONFIELD_LLAMA_BIN", str(server))
    monkeypatch.delenv("CLONFIELD_LLAMA_URL", raising=False)
    return server


def test_a_server_that_came_up_without_cuda_is_refused_not_left_crawling_on_the_cpu(tmp_path, monkeypatch):
    _fake_server(tmp_path, monkeypatch, "load_backend: failed to load libggml-cuda.so")
    with pytest.raises(RuntimeError, match="SEM o backend CUDA"):
        cf_llama.start(tmp_path, wait=20)
    assert "failed to load" in (tmp_path / "logs" / "llama-server.log").read_text()


def test_a_chatty_server_does_not_block_on_its_log_and_the_cuda_line_is_accepted(tmp_path, monkeypatch):
    _fake_server(tmp_path, monkeypatch, "ggml_cuda_init: found 1 CUDA devices")
    process = cf_llama.start(tmp_path, wait=20)
    try:
        assert requests.get(os.environ["CLONFIELD_LLAMA_URL"] + "/health", timeout=5).status_code == 200
    finally:
        cf_llama.stop(process)


def test_the_cuda_runtime_folder_next_to_the_binary_is_on_the_library_path(tmp_path):
    """The real layout of the b12360 release: llama-server in llama-<tag>/, libcudart/libcublas in a SIBLING cudart-... folder."""
    binary = tmp_path / "llama" / cf_llama.TAG / "llama-b12360" / "llama-server"
    runtime = tmp_path / "llama" / cf_llama.TAG / "cudart-llama-b12360-bin-ubuntu-cuda-12.8-x64"
    binary.parent.mkdir(parents=True)
    runtime.mkdir(parents=True)
    (binary.parent / "libggml-cuda.so").write_text("")
    (runtime / "libcudart.so.12").write_text("")
    dirs = cf_llama.library_dirs(tmp_path, binary)
    assert dirs[0] == str(binary.parent) and str(runtime) in dirs


def test_the_cuda_banner_is_found_even_when_a_verbose_load_pushes_it_far_from_the_log_tail(tmp_path, monkeypatch):
    _fake_server(tmp_path, monkeypatch, "ggml_cuda_init: found 1 CUDA devices", filler=1500000)
    process = cf_llama.start(tmp_path, wait=30)
    cf_llama.stop(process)


def test_the_refusal_names_the_backend_lines_of_the_log(tmp_path, monkeypatch):
    _fake_server(tmp_path, monkeypatch, "load_backend: failed to load libggml-cuda.so", filler=1500000)
    with pytest.raises(RuntimeError, match="failed to load libggml-cuda.so"):
        cf_llama.start(tmp_path, wait=30)
