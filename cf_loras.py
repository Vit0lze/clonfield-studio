"""LoRA library: local files plus the pinned Hugging Face catalog, tagged by model family."""

import json
import os
import re
import shutil
import struct
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
    {'repo': 'ausboss/Qwen-Image-2.1-Outpaint-LoRA', 'revision': 'dca5bdc7eb328f6021f330140f64b00a820ae5cd', 'file': 'qwen-image-2.1-outpaint-v2.safetensors'},
    {'repo': 'ausboss/Qwen-Image-2.1-Restore-LoRA', 'revision': 'a223f1255f4738b89b36d79c44d61740d3b3546f', 'file': 'qwen-image-2.1-restore.safetensors'},
    {'repo': 'ausboss/Qwen-Image-2.1-Outfit-Swap-Consistency-LoRA', 'revision': 'f0e0fc4e4c65527963d875536aa4e77fe1e9b165', 'file': 'qwen-image-2.1-outfit-swap.safetensors'},
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
                      "installed": (Path(base) / "loras" / name).is_file() or (comfy_loras() / name).is_file(), "repo": item["repo"]})
    return items


def sidecar(path):
    try:
        return json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def local(base):
    directory = Path(base) / "loras"
    known = {Path(i["file"]).name for i in CATALOGO}
    items = []
    for p in sorted(directory.glob("*.safetensors")):
        if p.name in known:
            continue
        meta = sidecar(p)
        items.append({"id": "local::" + p.name, "name": p.name, "label": meta.get("title") or label(p.name),
                      "source": "civitai" if meta else "local", "families": meta.get("families") or [], "installed": True,
                      "repo": None, "creator": meta.get("creator"), "model": meta.get("model"), "version": meta.get("version"),
                      "covers": meta.get("covers") or [], "page": meta.get("page")})
    return items


# ---------------------------------------------------------------- one source of truth
# Every LoRA the worker could load, from three places: base/loras (downloads + sidecars), ComfyUI/models/loras (loose
# files) and the pinned catalog. Each one is classified against the model the user is on, and nothing is hidden: the
# UI shows the ones for other families too, with the reason, instead of an empty list.
GROUP = {"krea2-turbo": "krea2", "z-image-turbo": "z-image", "qwen21-turbo": "qwen21"}
LABELS = {"qwen21": "Qwen Image 2.1", "flux2": "FLUX.2", "flux3": "FLUX.3", "krea2": "Krea 2", "z-image": "Z-Image", "sdxl": "SDXL", "sd15": "SD 1.5"}
NAME_HINTS = (("flux2", r"flux[._ -]?2"), ("flux3", r"flux[._ -]?3"), ("qwen21", r"qwen"), ("krea2", r"krea"),
              ("z-image", r"z[-_ ]?image|zimage"), ("sd15", r"sd[-_ ]?1[._]?5|sd_v1"), ("sdxl", r"sdxl|\bxl\b"))
ORDER = {"confirmada": 0, "provável": 1, "desconhecida": 2, "incompatível": 3}


def norm(key):
    return GROUP.get(key, key)


def label_of(key):
    return LABELS.get(norm(key), key)


def comfy_loras(comfy_root=None):
    return Path(comfy_root or os.getenv("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models")) / "loras"


_HEADERS = {}


def header_family(path):
    """The base model a safetensors file names in its own header (only what it states; never guessed from tensors)."""
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        if key in _HEADERS:
            return _HEADERS[key]
        with path.open("rb") as handle:
            size = struct.unpack("<Q", handle.read(8))[0]
            meta = json.loads(handle.read(min(size, 8 << 20))).get("__metadata__", {}) if size < (64 << 20) else {}
    except (OSError, ValueError, struct.error):
        return None
    text = " ".join(str(meta.get(k, "")) for k in ("modelspec.architecture", "ss_base_model_version", "base_model")).lower()
    found = "sdxl" if ("stable-diffusion-xl" in text or "sdxl" in text) else "sd15" if ("stable-diffusion-v1" in text or "sd_v1" in text) else None
    _HEADERS[key] = found
    return found


def name_family(name):
    lowered = name.lower()
    for key, pattern in NAME_HINTS:
        if re.search(pattern, lowered):
            return key
    return None


def classify(item, family):
    """-> (compat, reason, hint_source). `confirmada` needs a declared family (catalog or Civitai sidecar); a hint is only `provável`."""
    want = norm(family)
    declared = {norm(f) for f in item.get("families") or []}
    if declared:
        if want in declared:
            return "confirmada", f"declarada para {label_of(want)} ({'catálogo' if item.get('source') == 'catálogo' else 'fonte do download'})", "declarada"
        return "incompatível", "feita para " + ", ".join(sorted(label_of(f) for f in declared)) + f"; o modelo atual é {label_of(want)}", "declarada"
    path = item.get("_path")
    for hint, source in ((header_family(path) if path else None, "cabeçalho do arquivo"), (name_family(item["name"]), "nome do arquivo")):
        if hint:
            if hint == want:
                return "provável", f"o {source} indica {label_of(hint)}; não confirmado", source
            return "incompatível", f"o {source} indica {label_of(hint)}; o modelo atual é {label_of(want)}", source
    return "desconhecida", "o arquivo não diz para qual modelo foi feito; teste antes de confiar", None


def scan(base, comfy_root=None):
    """Installed LoRA files, base/loras first, then loose files in ComfyUI/models/loras (top level only)."""
    seen, items = set(), []
    known = {Path(i["file"]).name for i in CATALOGO}
    for where, directory in (("base", Path(base) / "loras"), ("comfy", comfy_loras(comfy_root))):
        for p in sorted(directory.glob("*.safetensors")) if directory.is_dir() else []:
            if p.name in seen:
                continue
            seen.add(p.name)
            meta = sidecar(p) if where == "base" else {}
            catalog_entry = p.name in known
            fam = meta.get("families") or (family(*next((i["repo"], i["file"]) for i in CATALOGO if Path(i["file"]).name == p.name)) if catalog_entry else [])
            items.append({"id": ("local::" if not catalog_entry else "") + p.name, "name": p.name, "label": meta.get("title") or label(p.name),
                          "source": "catálogo" if catalog_entry else "civitai" if meta else "local", "families": fam, "installed": True,
                          "repo": None, "creator": meta.get("creator"), "model": meta.get("model"), "version": meta.get("version"),
                          "covers": meta.get("covers") or [], "page": meta.get("page"), "adult": bool(meta.get("adult")), "size": p.stat().st_size, "location": where, "_path": p})
    return items


def available(base, comfy_root, family_key):
    """Everything usable (installed or downloadable), classified for `family_key`, plus counts that explain the empty cases."""
    items = scan(base, comfy_root)
    have = {i["name"] for i in items}
    for entry in catalog(base):
        if entry["name"] not in have:
            entry.update(installed=False, location="catálogo", size=None, covers=[], model=None, version=None, page=None, creator=None)
            items.append(entry)
    for item in items:
        item["fav_id"] = f"{'civitai' if item.get('model') else 'huggingface' if item.get('repo') else 'worker'}:{item['name']}"  # same id the Library stars use
        item["compat"], item["compat_reason"], item["hint_source"] = classify(item, family_key)
        item.pop("_path", None)
    items.sort(key=lambda i: (not i["installed"], ORDER[i["compat"]], i["label"].lower()))
    installed = [i for i in items if i["installed"]]
    by_family = {}
    for item in installed:
        hint = norm(next(iter(item["families"]), None) or "") if item["families"] else None
        if not hint:
            hint = header_family(Path(base) / "loras" / item["name"]) if (Path(base) / "loras" / item["name"]).is_file() else header_family(comfy_loras(comfy_root) / item["name"])
            hint = hint or name_family(item["name"])
        if hint:
            by_family[norm(hint)] = by_family.get(norm(hint), 0) + 1
    counts = {"installed_total": len(installed),
              "installed_for_family": sum(i["compat"] in ("confirmada", "provável") for i in installed),
              "installed_other": sum(i["compat"] == "incompatível" for i in installed),
              "unknown": sum(i["compat"] == "desconhecida" for i in installed),
              "by_family": by_family}
    return {"family": norm(family_key), "family_label": label_of(family_key), "items": items, "counts": counts}


def linked_name(file_name, version):
    """The name a Civitai LoRA file gets in base/loras: one per FILE of a version, so two ranks of one version never collide."""
    return f'{re.sub(r"[^a-zA-Z0-9._-]", "_", Path(file_name).stem)[:90]}__cv{version}.safetensors'


def link_civitai(base, entry, source, families, covers, page, adult=False):
    """Make a Civitai download usable as a normal LoRA: file in base/loras plus a sidecar with its card data."""
    directory = Path(base) / "loras"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / linked_name(entry["name"], entry["version"])
    if not target.exists():
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
    target.with_suffix(".json").write_text(json.dumps({
        "title": entry["title"], "creator": entry.get("creator"), "model": entry["model"], "version": entry["version"],
        "families": families, "covers": covers, "page": page, "revision": entry.get("revision"),
        "adult": bool(adult), "file": entry.get("file"), "file_name": entry.get("name"), "sha256": entry.get("sha256"), "quant": entry.get("quant"), "size_bytes": entry.get("size_bytes")}, ensure_ascii=False), encoding="utf-8")
    return target


def ensure(base, name, progress=None):
    """Make a LoRA file available under base/loras. Catalog entries download with progress."""
    target = Path(base) / "loras" / Path(name).name
    if target.is_file() and target.stat().st_size:
        return target
    loose = comfy_loras() / Path(name).name
    if loose.is_file() and loose.stat().st_size:  # a file the user dropped straight into ComfyUI/models/loras
        return loose
    item = next((i for i in CATALOGO if Path(i["file"]).name == Path(name).name), None)
    if item is None:
        raise ValueError(f"LoRA {name} não está na biblioteca.")
    download.fetch_hf(item["repo"], item["file"], target, revision=item["revision"],
                      token=os.environ.get("HF_TOKEN") or None, progress=progress)
    return target
