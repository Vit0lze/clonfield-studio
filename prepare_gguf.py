"""Install the ComfyUI-GGUF pack (node `UnetLoaderGGUF`, needed by the Wan 2.2 GGUF weights) at the pinned commit (idempotent)."""
import argparse
import subprocess
import sys
from pathlib import Path

import cf_wan as wan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", type=Path, help="ComfyUI directory")
    parser.add_argument("--pip", default=sys.executable, help="python of the ComfyUI venv")
    args = parser.parse_args()
    repo, commit = wan.GGUF_PACK
    target = args.checkout / "custom_nodes" / "ComfyUI-GGUF"
    if not target.exists():
        subprocess.run(["git", "clone", "-q", repo, str(target)], check=True)
    subprocess.run(["git", "-C", str(target), "fetch", "-q", "--depth", "50", "origin"], check=False)
    subprocess.run(["git", "-C", str(target), "checkout", "-q", commit], check=True)
    subprocess.run([args.pip, "-m", "pip", "install", "-q", "-r", str(target / "requirements.txt")], check=True)
    (args.checkout / "models" / "unet").mkdir(parents=True, exist_ok=True)
    print("ComfyUI-GGUF pronto em", target)


if __name__ == "__main__":
    main()
