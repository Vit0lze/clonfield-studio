"""Install the See-through ComfyUI pack at the pinned commit into a ComfyUI checkout (idempotent)."""
import argparse
import subprocess
import sys
from pathlib import Path

import cf_seethrough as st


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", type=Path, help="ComfyUI directory")
    parser.add_argument("--pip", default=sys.executable, help="python of the ComfyUI venv")
    args = parser.parse_args()
    target = args.checkout / "custom_nodes" / "ComfyUI-See-through"
    if not target.exists():
        subprocess.run(["git", "clone", "-q", st.PACK_REPO, str(target)], check=True)
    subprocess.run(["git", "-C", str(target), "fetch", "-q", "--depth", "50", "origin"], check=False)
    subprocess.run(["git", "-C", str(target), "checkout", "-q", st.PACK_COMMIT], check=True)
    subprocess.run([args.pip, "-m", "pip", "install", "-q", "-r", str(target / "requirements.txt"), "psd-tools"], check=True)
    print("See-through pronto em", target)


if __name__ == "__main__":
    main()
