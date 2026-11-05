"""LoRA library: local files plus the pinned Hugging Face catalog, tagged by model family."""

import os
from pathlib import Path

import cf_download as download

CATALOGO = [
    {'repo': 'Viggle/Qwen-Image-2.1-viggle-turbo', 'revision': '009a44a895ef85f7e643c80fdca9543795248867', 'file': 'Qwen-Image-2.1-viggle-turbo-4step-lora-r64.safetensors'},
    {'repo': 'Viggle/Qwen-Image-2.1-viggle-turbo', 'revision': '009a44a895ef85f7e643c80fdca9543795248867', 'file': 'Qwen-Image-2.1-viggle-turbo-v0.2-5step-lora-r128.safetensors'},
    {'repo': 'Viggle/Qwen-Image-2.1-viggle-turbo', 'revision': '009a44a895ef85f7e643c80fdca9543795248867', 'file': 'Qwen-Image-2.1-viggle-turbo-v0.2-5step-lora-r256.safetensors'},
    {'repo': 'Viggle/Qwen-Image-2.1-viggle-turbo', 'revision': '009a44a895ef85f7e643c80fdca9543795248867', 'file': 'Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-lora-r128.safetensors'},
    {'repo': 'Viggle/Qwen-Image-2.1-viggle-turbo', 'revision': '009a44a895ef85f7e643c80fdca9543795248867', 'file': 'Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-lora-r256.safetensors'},
    {'repo': 'Viggle/Qwen-Image-2.1-viggle-turbo', 'revision': '009a44a895ef85f7e643c80fdca9543795248867', 'file': 'Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors'},
    {'repo': 'Viggle/Qwen-Image-2.1-viggle-turbo', 'revision': '009a44a895ef85f7e643c80fdca9543795248867', 'file': 'Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r256.safetensors'},
    {'repo': 'Alissonerdx/BFS-Best-Face-Swap', 'revision': '0ca3913ade4b4ada458d60c232354e8586c4c181', 'file': 'bfs_body_swap_v1.0_qwen_2.1.safetensors'},
    {'repo': 'Alissonerdx/BFS-Best-Face-Swap', 'revision': '0ca3913ade4b4ada458d60c232354e8586c4c181', 'file': 'bfs_head_swap_v1_ltx2_ic_lora_12000_train_3.safetensors'},
    {'repo': 'Alissonerdx/BFS-Best-Face-Swap', 'revision': '0ca3913ade4b4ada458d60c232354e8586c4c181', 'file': 'bfs_head_swap_v1_ltx2_ic_lora_5000.safetensors'},
    {'repo': 'Alissonerdx/BFS-Best-Face-Swap', 'revision': '0ca3913ade4b4ada458d60c232354e8586c4c181', 'file': 'bfs_head_swap_v1_ltx2_ic_lora_6000.safetensors'},
    {'repo': 'Alissonerdx/BFS-Best-Face-Swap', 'revision': '0ca3913ade4b4ada458d60c232354e8586c4c181', 'file': 'bfs_head_v1.1_alternative_qwen_2.1.safetensors'},
    {'repo': 'Alissonerdx/BFS-Best-Face-Swap', 'revision': '0ca3913ade4b4ada458d60c232354e8586c4c181', 'file': 'bfs_head_v1.1_qwen_2.1.safetensors'},
    {'repo': 'Alissonerdx/BFS-Best-Face-Swap', 'revision': '0ca3913ade4b4ada458d60c232354e8586c4c181', 'file': 'bfs_head_v1_qwen_2.1.safetensors'},
    {'repo': 'Comfy-Org/SCAIL-2', 'revision': 'fe3c728bc793ba21ca674688f822afb709ad44fb', 'file': 'loras/wan2.1_SCAIL_2_DPO_lora_bf16.safetensors'},
    {'repo': 'Comfy-Org/SCAIL-2', 'revision': 'fe3c728bc793ba21ca674688f822afb709ad44fb', 'file': 'loras/wan2.1_SCAIL_2_relight_lora_bf16.safetensors'},
    {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_darkbrush.safetensors'},
    {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_dotmatrix.safetensors'},
    {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_kidsdrawing.safetensors'},
    {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_neondrip.safetensors'},
    {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_rainywindow.safetensors'},
    {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_retroanime.safetensors'},
    {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_softwatercolor.safetensors'},
    {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_style_reference.safetensors'},
    {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_sunsetblur.safetensors'},
    {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_turbo_lora_rank_64_bf16.safetensors'},
    {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_vintagetarot.safetensors'},
]
CATALOGO_BY_ID = {f"{r['repo']} :: {r['file']}": r for r in CATALOGO}


def family(repo, filename):
    """Which preset keys a catalog LoRA fits. Empty means not an image LoRA the Studio can apply."""
    name = filename.lower()
    if "viggle" in repo.lower() or "qwen_2.1" in name or "qwen-image-2.1" in name:
        return ["qwen21"]
    if "krea" in repo.lower():
        return ["krea2", "krea2-turbo"]
    return []


def label(filename):
    return Path(filename).stem.replace("_", " ").replace("-", " ")


def catalog(base):
    items = []
    for ident, item in CATALOGO_BY_ID.items():
        fam = family(item["repo"], item["file"])
        if not fam:
            continue
        name = Path(item["file"]).name
        items.append({"id": ident, "name": name, "label": label(name), "source": "catálogo", "families": fam,
                      "installed": (Path(base) / "loras" / name).is_file(), "repo": item["repo"]})
    return items


def local(base):
    directory = Path(base) / "loras"
    known = {Path(i["file"]).name for i in CATALOGO}
    return [{"id": "local::" + p.name, "name": p.name, "label": label(p.name), "source": "local",
             "families": [], "installed": True, "repo": None}
            for p in sorted(directory.glob("*.safetensors")) if p.name not in known]


def ensure(base, name, progress=None):
    """Make a LoRA file available under base/loras. Catalog entries download with progress."""
    target = Path(base) / "loras" / Path(name).name
    if target.is_file() and target.stat().st_size:
        return target
    item = next((i for i in CATALOGO if Path(i["file"]).name == Path(name).name), None)
    if item is None:
        raise ValueError(f"LoRA {name} não está na biblioteca.")
    download.fetch_hf(item["repo"], item["file"], target, revision=item["revision"],
                      token=os.environ.get("HF_TOKEN") or None, progress=progress)
    return target
