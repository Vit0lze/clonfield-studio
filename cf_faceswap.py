"""Face swap with FaceFusion (CLI, `headless-run`), pinned at 3.9.2, in its own venv so its pins never touch the Studio or ComfyUI.

Why FaceFusion first: it runs on CPU (onnxruntime), handles images and video, and needs no ComfyUI graph. VERIFIED here on CPU with the
real program: an image swap through `headless-run` (see tests/test_faceswap.py) changed only the face region. NOT verified: video,
GPU execution providers, the other swapper models, and quality on two different people (only a public-domain portrait was available).

Licence and consent: FaceFusion's licence is "other" (see LICENSE.md in the repo) and several swapper/enhancer weights carry their own
terms (e.g. inswapper is research / non-commercial). The app refuses to run unless the user confirms they have the permission of the
people whose faces are used. This is a tool for consenting use; the confirmation is recorded in the job parameters.
"""

import os
import re
import subprocess
from pathlib import Path

REPO = "https://github.com/facefusion/facefusion"
TAG = "3.9.2"
COMMIT = "decc6c9d8f8e014878624452c6e8fe208726b4ec"

# Names as printed by `headless-run --help` at the pinned tag (checked by the tests against the real program).
SWAPPERS = {"inswapper_128": "inswapper 128 (padrão; testado)", "hyperswap_1c_256": "HyperSwap 1c 256", "ghost_2_256": "Ghost 2 256", "blendswap_256": "BlendSwap 256"}
ENHANCERS = {"gfpgan_1.4": "GFPGAN 1.4", "codeformer": "CodeFormer", "gpen_bfr_512": "GPEN BFR 512"}
SELECTOR_MODES = {"one": "Só um rosto", "many": "Todos os rostos"}
ORDERS = ("left-right", "right-left", "top-bottom", "bottom-top", "large-small", "small-large", "best-worst")
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def root(base=None):
    return Path(os.environ.get("CLONFIELD_FACEFUSION_DIR") or (Path(base or "/content/ClonField_Lab") / "facefusion"))


def python_of(path):
    return Path(path) / "venv" / "bin" / "python"


def installed(path):
    return (Path(path) / "src" / "facefusion.py").is_file() and python_of(path).is_file()


def command(path, sources, target, output, *, swapper="inswapper_128", enhancer=None, mode="one", order="left-right", providers=("cpu",), threads=None,
            pixel_boost="256x256", temp=None, jobs=None):
    """The `headless-run` command line. Every option is validated here so a bad value fails with a reason, not inside the subprocess."""
    if swapper not in SWAPPERS:
        raise ValueError("Escolha um modelo de troca da lista.")
    if enhancer and enhancer not in ENHANCERS:
        raise ValueError("Escolha um melhorador de rosto da lista.")
    if mode not in SELECTOR_MODES or order not in ORDERS:
        raise ValueError("Modo ou ordem de seleção de rostos inválidos.")
    if pixel_boost not in ("256x256", "512x512", "768x768", "1024x1024"):
        raise ValueError("Use 256x256, 512x512, 768x768 ou 1024x1024 em pixel boost.")
    if not sources:
        raise ValueError("Envie pelo menos uma foto com o rosto de origem.")
    if not set(providers) <= {"cpu", "cuda", "tensorrt", "coreml", "openvino", "directml", "rocm"}:
        raise ValueError("Provedor de execução desconhecido.")
    command = [str(python_of(path)), str(Path(path) / "src" / "facefusion.py"), "headless-run", "-s", *map(str, sources), "-t", str(target), "-o", str(output),
               "--processors", "face_swapper", *(["face_enhancer"] if enhancer else []), "--face-swapper-model", swapper, "--face-swapper-pixel-boost", pixel_boost,
               "--face-selector-mode", mode, "--face-selector-order", order, "--execution-providers", *providers, "--log-level", "info"]
    if enhancer:
        command += ["--face-enhancer-model", enhancer]
    if threads:
        command += ["--execution-thread-count", str(int(threads))]
    if temp:
        command += ["--temp-path", str(temp)]
    if jobs:
        command += ["--jobs-path", str(jobs)]
    return command


def kind_of(target):
    suffix = Path(target).suffix.lower()
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    raise ValueError("O destino precisa ser uma imagem (png, jpg, webp) ou um vídeo (mp4, mov, mkv, webm).")


def run(path, sources, target, output, check=lambda: None, on_line=lambda line: None, timeout=3600, **options):
    """Run one swap. Returns the output path. `check()` may raise to cancel (the subprocess is terminated)."""
    if not installed(path):
        raise ValueError("O FaceFusion não está instalado. Rode prepare_facefusion.py (célula do Colab) ou defina CLONFIELD_FACEFUSION_DIR.")
    kind_of(target)
    work = Path(output).parent / ".facefusion"
    work.mkdir(parents=True, exist_ok=True)
    args = command(path, sources, target, output, temp=work / "tmp", jobs=work / "jobs", **options)
    process = subprocess.Popen(args, cwd=str(Path(path) / "src"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    tail = []
    try:
        for line in process.stdout:
            line = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
            if line:
                tail = (tail + [line])[-12:]
                on_line(line)
            check()
        process.wait(timeout=timeout)
    except BaseException:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
        raise
    finally:
        if process.stdout:
            process.stdout.close()
    if any("no source face" in line.lower() for line in tail):
        raise ValueError("O FaceFusion não achou rosto na foto de origem. Use uma foto nítida, de frente, com o rosto inteiro.")
    if process.returncode or not Path(output).is_file() or not Path(output).stat().st_size:
        reason = next((line for line in reversed(tail) if "error" in line.lower() or "no face" in line.lower() or "failed" in line.lower()), tail[-1] if tail else "sem saída")
        raise ValueError(f"O FaceFusion não gerou o resultado: {reason[:240]}")
    if kind_of(target) == "image" and unchanged(target, output):
        # FaceFusion copies the image silently when the target has no face: say so instead of delivering a "swap" that did nothing
        raise ValueError("Nenhum rosto foi trocado: o FaceFusion não achou rosto na imagem de destino (ou o rosto é pequeno/cortado demais).")
    return Path(output)


def unchanged(before, after):
    from PIL import Image, ImageChops
    with Image.open(before) as a, Image.open(after) as b:
        a, b = a.convert("RGB"), b.convert("RGB")
        return a.size == b.size and ImageChops.difference(a, b).getbbox() is None
