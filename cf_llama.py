"""Local chat/agent LLM: an ABLITERATED Qwen3.5-9B GGUF served by llama.cpp's `llama-server` (OpenAI-style tool calling).

Why abliterated: the official Qwen3.5-9B refuses some prompts. The default here is huihui-ai's abliterated build (refusal direction
removed), quantised by mradermacher, Apache-2.0. Abliteration is a crude edit: it removes refusals but can also dent instruction
following and tool calling. That trade-off is NOT measured here.

STATE (honest):
  * VERIFIED on this machine: pinned files (revision, size, SHA-256) against the real Hugging Face API; llama.cpp release assets
    against the real GitHub digests; the llama-server tool-calling protocol against a REAL Qwen3.5-0.8B on CPU (a stand-in model
    for the wire format only, not abliterated, not the 9B).
  * NOT VERIFIED (BLOQUEADO_GPU): loading the 9B, its refusal behaviour, tool-call quality, latency, VRAM/RAM peak on the T4, and how
    it shares 15 GB with ComfyUI (the plan is to stop one before starting the other: see stop()).

Quantisation candidates for the A/B on the T4 (mandate: main models <= 8 bit, Q6 first): Q6_K 7.36 GB · Q8_0 9.53 GB · Q4_K_M 5.63 GB.
"""

import hashlib
import os
import re
import shutil
import socket
import subprocess
import tarfile
import time
from pathlib import Path

import requests

import cf_download as download

REPO = "mradermacher/Huihui-Qwen3.5-9B-abliterated-GGUF"
REVISION = "419ca34f424adbd9276c09e0271cb6b718e8da1d"
MODELS = {
    "q6_k": dict(repo=REPO, revision=REVISION, file="Huihui-Qwen3.5-9B-abliterated.Q6_K.gguf", size=7359260032,
                 sha256="c57ef5dc56ead87f054e808c14e4edbd4be60b3a32717cc38ea54e90dc296d2c", license="apache-2.0", abliterated=True),
    "q8_0": dict(repo=REPO, revision=REVISION, file="Huihui-Qwen3.5-9B-abliterated.Q8_0.gguf", size=9527502208,
                 sha256="9df7ce00f4df74344dd788ade97c412ef9850e58b44ff337e56fbf07be24a97f", license="apache-2.0", abliterated=True),
    "q4_k_m": dict(repo=REPO, revision=REVISION, file="Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf", size=5627045248,
                   sha256="ea1858ef4dc4b648b8dbb44612962a0333e945060dd0545ac0f28d7c4416e4b3", license="apache-2.0", abliterated=True),
    # A small stand-in used ONLY to exercise the tool-calling protocol on a CPU box. Not abliterated, not the 9B, not for chatting.
    "protocol_test_0.8b": dict(repo="unsloth/Qwen3.5-0.8B-GGUF", revision="6ab461498e2023f6e3c1baea90a8f0fe38ab64d0", file="Qwen3.5-0.8B-Q4_K_M.gguf", size=532517120,
                               sha256="bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517", license="apache-2.0", abliterated=False),
}
DEFAULT = "q6_k"
PORT = 8080

TAG = "b12360"
RELEASE = "https://github.com/ggml-org/llama.cpp/releases/download/" + TAG + "/"
BINARIES = {
    "cpu": dict(file=f"llama-{TAG}-bin-ubuntu-x64.tar.gz", size=23310281, sha256="b60dc211e4ba206bb04bbc9eb06294364c43d0aab8fc308c44a361477466ba4c"),
    "cuda12": dict(file=f"llama-{TAG}-bin-ubuntu-cuda-12.8-x64.tar.gz", size=199223370, sha256="1874218dad4a58b5187e01a65de1cdb68218d93a510bca59a976ccb47fafed85"),
    "cuda12_runtime": dict(file=f"cudart-llama-{TAG}-bin-ubuntu-cuda-12.8-x64.tar.gz", size=594371570, sha256="be7ec0dba5eac064460b34c02e4010deb14eb8bfba95ae9b508ae4c0a1983b5f"),
}


def sha256_of(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1 << 24):
            digest.update(block)
    return digest.hexdigest()


def target(base, key=DEFAULT):
    return Path(base) / "llm" / MODELS[key]["file"]


def installed(base, key=DEFAULT):
    return target(base, key).is_file()


def prepare(base, key=DEFAULT, progress=None):
    """Download the pinned GGUF (resumable) and refuse a file whose SHA-256 differs from the pinned one."""
    spec = MODELS[key]
    dest = target(base, key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file():
        download.fetch_hf(spec["repo"], spec["file"], dest, revision=spec["revision"], token=os.environ.get("HF_TOKEN") or None, progress=progress)
    if sha256_of(dest) != spec["sha256"]:
        dest.unlink(missing_ok=True)
        raise ValueError(f"SHA-256 de {spec['file']} diferente do publicado; o arquivo foi removido.")
    return dest


def safe_extract(archive, folder):
    """Extract a tar.gz refusing absolute paths, '..' and links that point outside the folder."""
    folder = Path(folder).resolve()
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            destination = (folder / member.name).resolve()
            if not destination.is_relative_to(folder):
                raise ValueError(f"Arquivo suspeito no pacote: {member.name}")
            if member.issym() or member.islnk():
                link = (destination.parent / member.linkname).resolve()
                if not link.is_relative_to(folder):
                    raise ValueError(f"Link suspeito no pacote: {member.name}")
        tar.extractall(folder)


def install_binary(base, variant="cuda12", progress=None):
    """Fetch the pinned llama.cpp release, verify its SHA-256 and unpack it. Returns the path of `llama-server`."""
    folder = Path(base) / "llama" / TAG
    parts = ["cuda12", "cuda12_runtime"] if variant == "cuda12" else [variant]
    for part in parts:
        spec = BINARIES[part]
        archive = Path(base) / "llama" / spec["file"]
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.is_file():
            download.fetch(RELEASE + spec["file"], archive, label=spec["file"], progress=progress)
        if sha256_of(archive) != spec["sha256"]:
            archive.unlink(missing_ok=True)
            raise ValueError(f"SHA-256 de {spec['file']} diferente do publicado pelo GitHub; o arquivo foi removido.")
        folder.mkdir(parents=True, exist_ok=True)
        safe_extract(archive, folder)
    found = next(folder.rglob("llama-server"), None)
    if found is None:
        raise ValueError("llama-server não veio no pacote.")
    found.chmod(0o755)
    os.environ["CLONFIELD_LLAMA_BIN"] = str(found)  # start() finds it even when the caller ignores the return value (the Colab cell does)
    return found


def installed_binary(base):
    """A `llama-server` already unpacked under `base` (any pinned tag), or None."""
    return next(iter(sorted((Path(base) / "llama").rglob("llama-server"))), None) if (Path(base) / "llama").is_dir() else None


def server_command(base, key=DEFAULT, binary=None, port=PORT, ctx=16384, gpu_layers=99, threads=None):
    """The llama-server command line. `--jinja` makes the model's own chat template drive native tool calls."""
    exe = binary or os.environ.get("CLONFIELD_LLAMA_BIN") or shutil.which("llama-server") or installed_binary(base)
    if not exe:
        raise ValueError("llama-server não encontrado. Use cf_llama.install_binary() ou defina CLONFIELD_LLAMA_BIN.")
    command = [str(exe), "-m", str(target(base, key)), "--port", str(port), "--host", "127.0.0.1", "-c", str(ctx), "--jinja"]
    if gpu_layers:
        command += ["-ngl", str(gpu_layers), "-fa", "on"]
    if threads:
        command += ["-t", str(threads)]
    return command


def free_port(preferred=PORT):
    """`preferred` when nothing listens on it, else any free port. Colab's own server already holds 8080, which made llama-server exit."""
    for port in (preferred, 0):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return probe.getsockname()[1]
    raise RuntimeError("Nenhuma porta local livre para o llama-server.")


def library_dirs(base, exe):
    """Folders to put on LD_LIBRARY_PATH: the binary's own, plus every folder under <base>/llama that holds shared libraries.
    The CUDA runtime (libcudart/libcublas) unpacks NEXT TO the llama.cpp folder, not inside it; without it the CUDA backend fails to
    load and llama.cpp silently falls back to the CPU (a 9B then needs minutes per prompt)."""
    dirs = [str(Path(exe).parent)]
    root = Path(base) / "llama"
    if root.is_dir():
        dirs += sorted({str(p.parent) for p in root.rglob("*.so*")} - set(dirs))
    return dirs


CUDA_LINE = re.compile(r"found \d+ CUDA devices|loaded CUDA backend|ggml_cuda_init|\bCUDA\d* (?:model|KV|compute) buffer|offloaded [1-9]\d*/\d+ layers to GPU", re.I)
CUDA_HINT = re.compile(r"cuda|cublas|cudart|libcuda|backend|device|ggml_|load_backend|offload", re.I)


def log_has_cuda(path):
    """True when ANY line of the whole log shows the CUDA backend. The banner is at the START of the log and a verbose model load can push
    it far out of a tail window, so the file is scanned from the top."""
    try:
        with Path(path).open(errors="replace") as handle:
            return any(CUDA_LINE.search(line) for line in handle)
    except OSError:
        return False


DEVICE_LINE = re.compile(r"^\s*(CUDA\d+)\s*:", re.M)


def list_devices(exe, env):
    """(ran, cuda_devices): what `llama-server --list-devices` reports. `ran` is False when the build cannot answer (then nothing is concluded from it).
    This is the decisive check: the b12360 build logs NOTHING about the backend at its default verbosity, so the log cannot prove CUDA either way."""
    try:
        done = subprocess.run([str(exe), "--list-devices"], capture_output=True, text=True, timeout=90, env=env)
    except (OSError, subprocess.SubprocessError):
        return False, [], ""
    text = (done.stdout or "") + (done.stderr or "")
    return done.returncode == 0, DEVICE_LINE.findall(text), text


def gpu_used_mib():
    """Used VRAM of GPU 0 in MiB, or None without nvidia-smi."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=20).stdout
        return int(out.strip().splitlines()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def gpu_loaded(before, minimum=1500):
    """True when VRAM use grew by at least `minimum` MiB since `before` (the model landed on the GPU). False when it cannot be measured."""
    now = gpu_used_mib()
    if before is None or now is None:
        return False
    return now - before >= minimum


def cuda_diagnosis(path, exe):
    """What a person needs to see when CUDA is missing: the backend/device lines of the log plus any shared library the CUDA backend cannot resolve."""
    lines = []
    try:
        with Path(path).open(errors="replace") as handle:
            lines = [line.rstrip()[:240] for line in handle if CUDA_HINT.search(line)][:40]
    except OSError:
        pass
    missing = ""
    backend = next(iter(sorted(Path(exe).parent.glob("libggml-cuda.so*"))), None)
    if backend is not None:
        try:
            out = subprocess.run(["ldd", str(backend)], capture_output=True, text=True, timeout=20,
                                 env=dict(os.environ, LD_LIBRARY_PATH=os.environ.get("LD_LIBRARY_PATH", ""))).stdout
            missing = "\n".join(line.strip() for line in out.splitlines() if "not found" in line)
        except (OSError, subprocess.SubprocessError):
            pass
    return "Linhas de backend/dispositivo do log:\n" + ("\n".join(lines) or "(nenhuma)") + ("\nBibliotecas não encontradas por libggml-cuda.so (sem o LD_LIBRARY_PATH do servidor):\n" + missing if missing else "")


def log_tail(path, size=1800):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[-size:]
    except OSError:
        return ""


def start(base, key=DEFAULT, wait=300, require_gpu=True, **kwargs):
    """Launch llama-server on a free port; its log goes to <base>/logs/llama-server.log (a PIPE nobody reads would block the server).
    With GPU layers requested, a server that came up without the CUDA backend is stopped with a plain error instead of crawling on the CPU."""
    kwargs["port"] = free_port(kwargs.get("port") or PORT)
    command = server_command(base, key, **kwargs)
    env = dict(os.environ, LD_LIBRARY_PATH=":".join([*library_dirs(base, command[0]), os.environ.get("LD_LIBRARY_PATH", "")]))
    log = Path(base) / "logs" / "llama-server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    wants_gpu = bool(require_gpu and kwargs.get("gpu_layers", 99))
    devices = []
    if wants_gpu:
        ran, devices, text = list_devices(command[0], env)
        if ran and not devices:  # the build answered and offers no CUDA device: stop before loading a 7 GB model onto the CPU
            raise RuntimeError("O llama-server não enxerga nenhum dispositivo CUDA e rodaria na CPU (minutos por resposta).\n"
                               "`llama-server --list-devices` respondeu:\n" + text.strip()[-800:] + "\n" + cuda_diagnosis(log, command[0]))
    vram_before = gpu_used_mib() if wants_gpu else None
    with log.open("w") as handle:
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, text=True, env=env)
    url = f"http://127.0.0.1:{kwargs['port']}"
    for _ in range(wait):
        if process.poll() is not None:
            raise RuntimeError("llama-server encerrou: " + log_tail(log))
        try:
            if requests.get(url + "/health", timeout=2).status_code == 200:
                if wants_gpu and not devices and not log_has_cuda(log) and not gpu_loaded(vram_before):
                    process.terminate()
                    raise RuntimeError("O llama-server subiu SEM o backend CUDA e rodaria na CPU (minutos por resposta).\n" + cuda_diagnosis(log, command[0]) + "\nFim do log:\n" + log_tail(log, 600))
                os.environ["CLONFIELD_LLAMA_URL"] = url
                return process
        except requests.RequestException:
            pass
        time.sleep(1)
    process.terminate()
    raise RuntimeError(f"llama-server não respondeu em {wait} s. Log:\n" + log_tail(log))


def stop(process):
    """Free the VRAM before ComfyUI needs it (a 9B model and the image models do not both fit on a 15 GB T4)."""
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
    os.environ.pop("CLONFIELD_LLAMA_URL", None)


COLAB_CELL = """# Colab (T4): chat/agent LLM, 100% local. Downloads ~7.4 GB (model) + ~0.8 GB (llama.cpp CUDA) once. NOT validated on this machine (no GPU).
import cf_llama
base = '/content/ClonField_Lab'
cf_llama.install_binary(base, 'cuda12')
cf_llama.prepare(base, 'q6_k')
llama = cf_llama.start(base, 'q6_k')
"""
