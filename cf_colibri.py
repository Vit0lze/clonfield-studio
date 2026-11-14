"""colibri (github.com/JustVugg/colibri, Apache-2.0) as the Studio's local LLM and local System One.

colibri is a C inference engine that keeps the always-needed part of a big mixture-of-experts model in RAM and streams the rest from disk
(hot experts on the GPU when there is one). That is how a 35B model with 3B active parameters can serve the chat on a Colab T4 that
could not hold it in VRAM. It speaks the OpenAI and Anthropic APIs and `POST /v1/systemone`, which has the request and reply of
TypeSafe's Jev: the router's typed decisions then run on the same local model, with no outside service.

Files are pinned: the engine by release tag AND commit, each model by repository revision, size and SHA-256 (read from the Hugging Face API).
GGUFs are read in place by `coli import` (a ~7 MB model directory next to the file); nothing is converted or quantised again.

STATE (honest):
  * VERIFIED on this CPU-only box: the engine builds from the pinned commit; a real LFM3-VL-2B Q4_K_M GGUF (SHA-256 checked) is imported and
    served; chat text, a native tool call and /v1/systemone work through cf_llm / cf_agent / cf_router (tests/test_colibri.py, live).
  * FOUND: LFM3's sliding-window KV ring aborts the engine when System One scores the Studio's ~50 options (`the KV ring no longer holds the
    window`); Q36_KV_RING=0 (every layer linear) avoids it, so start() sets it. Reported upstream-style in the notes below, not patched.
  * NOT VERIFIED (BLOQUEADO_GPU / no RAM here): the abliterated Qwen3.6-35B-A3B, its refusal behaviour, tool-call quality, routing accuracy
    (the 2B stand-in routes badly: it is a wire-format check, not a quality claim), speed on a T4 and how it shares RAM with ComfyUI.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

import cf_download as download

REPO_URL = "https://github.com/JustVugg/colibri"
TAG = "v2.1.0"
COMMIT = "704a3f68184b78367a04cb5526e428dc2f90f05b"
PORT = 8000

_QWEN = "mradermacher/Huihui-Qwen3.6-35B-A3B-abliterated-GGUF"
_QWEN_REV = "0693fc2b47f66380f4b568b01e05195d22edd3a2"
MODELS = {
    # The default for the Colab: Huihui's abliterated (refusal-removed) Qwen3.6-35B-A3B, Apache-2.0, on colibri's qwen36 engine.
    "qwen36_35b_q4_k_m": dict(repo=_QWEN, revision=_QWEN_REV, file="Huihui-Qwen3.6-35B-A3B-abliterated.Q4_K_M.gguf", size=21166758784,
                              sha256="fbaa4eb3e2365abffd495c5efa7df88c2b2a5088ba32cd2895973d130991e92b", license="apache-2.0", abliterated=True, ram_gb=10),
    "qwen36_35b_q6_k": dict(repo=_QWEN, revision=_QWEN_REV, file="Huihui-Qwen3.6-35B-A3B-abliterated.Q6_K.gguf", size=28514153344,
                            sha256="420f7a99363f9ac98b532aef0897096b0a68704180a6b8b680ee121bb76720ee", license="apache-2.0", abliterated=True, ram_gb=12),
    # A small real model used ONLY to exercise the protocol on a CPU box (not abliterated, 2B: not for chatting or routing quality).
    "protocol_test_lfm3_2b": dict(repo="LiquidAI/LFM3-VL-2B-GGUF", revision="1add221a5ea6c047fcf1eaaf2d247939d7cf8849", file="LFM3-VL-2B-Q4_K_M.gguf", size=1099627808,
                                  sha256="56dac2e192ff0d9ab8507f4f1aeb4aed0463449bbbefaac79497f041c95f21eb", license="LFM Open License v1.0", abliterated=False, ram_gb=2),
}
DEFAULT = "qwen36_35b_q4_k_m"


def sha256_of(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1 << 24):
            digest.update(block)
    return digest.hexdigest()


def src_dir(base):
    return Path(base) / "colibri" / "src"


def gguf_path(base, key=DEFAULT):
    return Path(base) / "llm" / "colibri" / MODELS[key]["file"]


def model_dir(base, key=DEFAULT):
    return gguf_path(base, key).with_suffix(".colibri")


def run(command, cwd, env=None, timeout=1800):
    done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    if done.returncode:
        raise RuntimeError(f"{' '.join(map(str, command))} falhou: {(done.stdout + done.stderr)[-500:]}")
    return done.stdout


def install_engine(base, cuda=None):
    """Clone the pinned release, check the commit, build the Qwen3.6 engine (it also runs the LFM3 and Qwen3-Coder GGUFs).
    `cuda`: None builds for CUDA when nvcc exists, else CPU. Returns the engine path."""
    src = src_dir(base)
    if not (src / ".git").is_dir():
        src.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--depth", "1", "--branch", TAG, REPO_URL, str(src)], src.parent, timeout=600)
    head = run(["git", "rev-parse", "HEAD"], src).strip()
    if head != COMMIT:
        raise ValueError(f"O colibri clonado está em {head[:10]}, não no commit fixado {COMMIT[:10]}; apague {src} e tente de novo.")
    cuda = shutil.which("nvcc") is not None if cuda is None else cuda
    engine = src / "c" / "qwen36"
    if not engine.is_file():
        run(["make", "-j", str(os.cpu_count() or 2), "qwen36"] + (["CUDA=1"] if cuda else []), src / "c")
    return engine


def prepare(base, key=DEFAULT, progress=None):
    """Download the pinned GGUF (resumable), check its SHA-256, and `coli import` it. Returns the model directory."""
    spec = MODELS[key]
    gguf = gguf_path(base, key)
    gguf.parent.mkdir(parents=True, exist_ok=True)
    if not gguf.is_file():
        download.fetch_hf(spec["repo"], spec["file"], gguf, revision=spec["revision"], token=os.environ.get("HF_TOKEN") or None, progress=progress)
    if sha256_of(gguf) != spec["sha256"]:
        gguf.unlink(missing_ok=True)
        raise ValueError(f"SHA-256 de {spec['file']} diferente do publicado; o arquivo foi removido.")
    folder = model_dir(base, key)
    if not (folder / "config.json").is_file():
        run([sys.executable, str(src_dir(base) / "c" / "coli"), "import", str(gguf)], src_dir(base) / "c", timeout=900)
    return folder


def server_command(base, key=DEFAULT, port=PORT):
    return [sys.executable, str(src_dir(base) / "c" / "coli"), "serve", "--host", "127.0.0.1", "--port", str(port), "--model", str(model_dir(base, key))]


def start(base, key=DEFAULT, wait=600, port=PORT):
    """Start `coli serve` and point the Studio at it (CLONFIELD_COLIBRI_URL + CLONFIELD_LLM_BACKEND=colibri)."""
    command = server_command(base, key, port)
    env = dict(os.environ, Q36_KV_RING="0")  # LFM3's sliding-window ring aborts the engine under System One; every layer linear avoids it
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, cwd=src_dir(base) / "c")
    url = f"http://127.0.0.1:{port}"
    for _ in range(wait):
        if process.poll() is not None:
            raise RuntimeError("coli serve encerrou; rode o comando à mão para ver o erro: " + " ".join(command))
        try:
            if requests.get(url + "/health", timeout=2).json().get("status") == "ok":
                os.environ["CLONFIELD_COLIBRI_URL"] = url
                os.environ["CLONFIELD_LLM_BACKEND"] = "colibri"
                return process
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1)
    process.terminate()
    raise RuntimeError(f"coli serve não respondeu em {wait} s")


def stop(process):
    """Free RAM/VRAM before ComfyUI needs it."""
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
    for name in ("CLONFIELD_COLIBRI_URL", "CLONFIELD_LLM_BACKEND"):
        os.environ.pop(name, None)


COLAB_CELL = """# Colab (T4): chat, agente e roteador tipado pelo colibri, 100% local. Baixa ~21 GB (modelo) uma vez. NÃO validado nesta máquina (sem GPU/RAM).
import cf_colibri
base = '/content/ClonField_Lab'
cf_colibri.install_engine(base)
cf_colibri.prepare(base, 'qwen36_35b_q4_k_m')
colibri = cf_colibri.start(base, 'qwen36_35b_q4_k_m')
"""
