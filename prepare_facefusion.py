"""Install FaceFusion at the pinned tag into <base>/facefusion/{src,venv} (idempotent). Weights (~1 GB) download on first use."""
import argparse
import subprocess
import sys
from pathlib import Path

import cf_faceswap as ff


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base", type=Path, help="Studio data folder (the install goes to <base>/facefusion)")
    parser.add_argument("--cuda", action="store_true", help="install onnxruntime-gpu instead of the CPU build")
    args = parser.parse_args()
    target = ff.root(args.base)
    src, venv = target / "src", target / "venv"
    target.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        subprocess.run(["git", "clone", "-q", ff.REPO, str(src)], check=True)
    subprocess.run(["git", "-C", str(src), "fetch", "-q", "--depth", "50", "--tags", "origin"], check=False)
    subprocess.run(["git", "-C", str(src), "checkout", "-q", ff.COMMIT], check=True)
    if not ff.python_of(target).is_file():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    pip = [str(ff.python_of(target)), "-m", "pip", "install", "-q"]
    subprocess.run([*pip, "-r", str(src / "requirements.txt")], check=True)
    if args.cuda:
        subprocess.run([*pip, "onnxruntime-gpu"], check=True)
    print("FaceFusion", ff.TAG, "pronto em", target)


if __name__ == "__main__":
    main()
