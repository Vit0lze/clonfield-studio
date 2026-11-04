"""Install the pinned OpenJutsu worker pack and fetch weights on supported GPUs."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parent
PACK = "https://github.com/akatz-labs/h3-character-swap-tool.git"
REV = "0670e4fdf95adf2262caa4b81afed2a9c4ae4b7b"
PATCH = ROOT / "vendor/openjutsu/build/h3_character_swap.patch"
H3 = "Comfy-Org/MiniMax-H3"
H3_REV = "1c41cfca8ebba91d0af792a05c5761fb2c3a7975"
WEIGHTS = [
    (H3, H3_REV, "diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors", ""),
    (H3, H3_REV, "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", ""),
    (H3, H3_REV, "vae/minimax_h3_video_vae_fp16.safetensors", ""),
    (H3, H3_REV, "vae/minimax_h3_audio_vae_fp32.safetensors", ""),
    ("Comfy-Org/sam3.1", "7bb8374780a725b4353ed31f3a9395c9742b5621",
     "checkpoints/sam3.1_multiplex_fp16.safetensors", ""),
    ("akatz-ai/MiniMax-H3-Character-Swap-LoRA", "d06323b7c8e70e97cdab48b78a1e05f786c8cba9",
     "h3_character_swap_v1.5.safetensors", "loras"),
    ("lightx2v/Minimax-h3-Turbo", "3ec17a324ced54151364f24f8b5fb6bf7e26414f",
     "minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors", "loras"),
]


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--checkout", type=Path, required=True)
    cli.add_argument("--models", type=Path, required=True)
    cli.add_argument("--python", type=Path, required=True)
    args = cli.parse_args()
    if not shutil.which("nvidia-smi"):
        raise SystemExit("GPU NVIDIA indisponível.")
    sizes = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], text=True)
    if max((int(s) for s in sizes.splitlines() if s.strip().isdigit()), default=0) < 90 * 1024:
        raise SystemExit("OpenJutsu: perfil H3 reservado para GPU da classe de 96 GB; nenhum peso baixado.")
    target = args.checkout / "custom_nodes/h3_character_swap"
    target.parent.mkdir(parents=True, exist_ok=True)
    marker = target / ".clonfield-pinned"
    if not marker.is_file():
        if target.exists():
            raise SystemExit("Já há um h3_character_swap no worker. Consulte docs/OPENJUTSU.md.")
        with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "fetch", "--depth=1", PACK, REV], check=True)
            subprocess.run(["git", "-C", str(root), "checkout", "--detach", "FETCH_HEAD"], check=True)
            pack = root / "worker_nodes/h3_character_swap"
            # Run outside the enclosing git checkout so the patch is relative to this node pack.
            patch_root = root / "patched"
            shutil.copytree(pack, patch_root)
            subprocess.run(["git", "apply", "-p1", str(PATCH)],
                           cwd=patch_root, env={**os.environ, "GIT_CEILING_DIRECTORIES": str(root)}, check=True)
            requirements = patch_root / "requirements.txt"
            if requirements.is_file():
                subprocess.run([sys.executable, "-m", "pip", "--python", str(args.python),
                                "install", "-r", str(requirements)], check=True)
            (patch_root / ".clonfield-pinned").write_text(REV)
            patch_root.replace(target)
    for repo, revision, filename, subdir in WEIGHTS:
        hf_hub_download(repo, filename, revision=revision, local_dir=args.models / subdir,
                        token=os.environ.get("HF_TOKEN") or None)


if __name__ == "__main__":
    main()
