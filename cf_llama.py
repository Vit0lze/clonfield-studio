"""Local agent backend: Qwen3.5-9B GGUF served by llama.cpp's `llama-server` (OpenAI-style tool calling).

STATE: CÓDIGO ESCRITO / BLOQUEADO_GPU. This machine has no GPU and 3 GB of RAM, so no Qwen has been run here. What IS checked
here: the pinned files (repo revision, name, size, SHA-256) against the real Hugging Face API (tests/test_llama.py), and the
agent's wire format for tool calls (cf_agent.OpenAICompatProvider). What is NOT: loading the model, tool-calling quality,
latency, VRAM/RAM peak on the T4, and how it coexists with ComfyUI in 15 GB (the plan is to unload one before the other).

Quantisation candidates for the A/B on the T4 (mandate: main models at <= 8 bit; Q6 is the starting point):
  Q6_K  (unsloth, 7.46 GB)  · Q6_K_L (bartowski, 8.45 GB)  · Q8_0 (unsloth, 9.53 GB)
"""

import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

import requests

import cf_download as download

MODELS = {
    "q6_k": dict(repo="unsloth/Qwen3.5-9B-GGUF", revision="3885219b6810b007914f3a7950a8d1b469d598a5", file="Qwen3.5-9B-Q6_K.gguf",
                 sha256="91898433cf5c", size_gb=7.46, license="apache-2.0"),
    "q8_0": dict(repo="unsloth/Qwen3.5-9B-GGUF", revision="3885219b6810b007914f3a7950a8d1b469d598a5", file="Qwen3.5-9B-Q8_0.gguf",
                 sha256="809626574d0c", size_gb=9.53, license="apache-2.0"),
    "q6_k_l": dict(repo="bartowski/Qwen_Qwen3.5-9B-GGUF", revision="182be2fd6c7bc44887d88a91cb03ff009cc9f549", file="Qwen_Qwen3.5-9B-Q6_K_L.gguf",
                   sha256="23a91e941634", size_gb=8.45, license="apache-2.0"),
}
DEFAULT = "q6_k"
PORT = 8080


def target(base, key=DEFAULT):
    return Path(base) / "llm" / MODELS[key]["file"]


def installed(base, key=DEFAULT):
    return target(base, key).is_file()


def prepare(base, key=DEFAULT, progress=None):
    """Download the pinned GGUF (resumable) and refuse a file whose SHA-256 does not start with the pinned prefix."""
    spec = MODELS[key]
    dest = target(base, key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file():
        download.fetch_hf(spec["repo"], spec["file"], dest, revision=spec["revision"], token=os.environ.get("HF_TOKEN") or None, progress=progress)
    import hashlib
    digest = hashlib.sha256()
    with dest.open("rb") as handle:
        while block := handle.read(1 << 24):
            digest.update(block)
    if not digest.hexdigest().startswith(spec["sha256"]):
        dest.unlink(missing_ok=True)
        raise ValueError(f"SHA-256 de {spec['file']} diferente do publicado; o arquivo foi removido.")
    return dest


def server_command(base, key=DEFAULT, binary=None, port=PORT, ctx=16384, gpu_layers=99):
    """The llama-server command line. `--jinja` makes the model's own chat template drive native tool calls."""
    exe = binary or os.environ.get("CLONFIELD_LLAMA_BIN") or shutil.which("llama-server")
    if not exe:
        raise ValueError("llama-server não encontrado. Compile o llama.cpp com CUDA no Colab (ver README do Lote 2) e informe CLONFIELD_LLAMA_BIN.")
    return [exe, "-m", str(target(base, key)), "--port", str(port), "--host", "127.0.0.1", "-c", str(ctx), "-ngl", str(gpu_layers), "--jinja", "-fa", "on"]


def start(base, key=DEFAULT, **kwargs):
    command = server_command(base, key, **kwargs)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = f"http://127.0.0.1:{kwargs.get('port', PORT)}"
    for _ in range(240):
        if process.poll() is not None:
            raise RuntimeError("llama-server encerrou: " + (process.stdout.read() or "")[-400:])
        try:
            if requests.get(url + "/health", timeout=2).status_code == 200:
                os.environ["CLONFIELD_LLAMA_URL"] = url
                return process
        except requests.RequestException:
            pass
        time.sleep(1)
    process.terminate()
    raise RuntimeError("llama-server não respondeu em 4 minutos")


def stop(process):
    """Free the VRAM before ComfyUI needs it (they do not both fit with a 9B model on a 15 GB T4)."""
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
    os.environ.pop("CLONFIELD_LLAMA_URL", None)


COLAB_CELL = """# Colab (T4): build llama.cpp with CUDA once, then let the Studio start it. NOT validated on this machine (no GPU).
!git clone --depth 1 https://github.com/ggml-org/llama.cpp /content/llama.cpp
!cmake -S /content/llama.cpp -B /content/llama.cpp/build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=75 -DLLAMA_CURL=OFF && cmake --build /content/llama.cpp/build --target llama-server -j 4
import os; os.environ['CLONFIELD_LLAMA_BIN'] = '/content/llama.cpp/build/bin/llama-server'
"""
