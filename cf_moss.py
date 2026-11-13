"""MOSS-Image (OpenMOSS, Apache-2.0) through ComfyUI CORE nodes only: no custom node pack, no Nodes 2.0 canvas, no RES4LYF.

The Studio draws the boxes itself (portal/js/boxes.js) and hands them to core `Create Bounding Boxes` -> `MOSSImageLayoutPrompt` (the same
layout the Artfat BBox Sampler builds: 0-1000 yxyx grid, "text"/"object" items). Three modes:
  * generate : a new frame laid out by the boxes (official t2i-bboxes recipe: 25 steps, CFG 2.5, er_sde / simple).
  * edit_boxes: redraw ONLY the boxes of an existing picture: VAE-encode + latent noise mask + DifferentialDiffusion (soft edge), then the original is
                pasted back outside the mask (ImageCompositeMasked). Same idea as the Artfat sampler, with core nodes. Quality is NOT validated.
  * edit_instruction: the official `image_moss_image_edit` template (edit LoRA + reference-image encode), converted by cf_ui2api.
Weights (Comfy-Org/MOSS-Image, Apache-2.0): INT8 ConvRot diffusion 5.4 GB + Qwen3.5-9B W4A8 text encoder 7.3 GB + small Flux2 VAE 0.25 GB.
(An earlier note of mine said no quantised MOSS existed: that was wrong, these are the repackaged ones.)

STATE: all three graphs are ACCEPTED by a real ComfyUI 0.44.0 on CPU (POST /prompt validation). Nothing was generated (T4 needed): BLOQUEADO_GPU.
"""

import json
import os
import random
from pathlib import Path

import cf_edits as edits
import cf_ui2api as ui2api
from cf_seedvr2 import upload_input

REPO, REVISION = "Comfy-Org/MOSS-Image", "2929efe3cd0e3f7b1c8d50d4a3b3b1f1a9c0e1b7"
UNET = ("diffusion_models", "diffusion_models/moss_image_sft_int8_convrot.safetensors", 5_410_000_000, "b4d1475bc7")
ENCODER = ("text_encoders", "text_encoders/qwen3.5_9b_w4a8_gptq.safetensors", 7_340_000_000, "4cc6a1543a")
VAE = ("vae", "vae/flux2-vae_small.safetensors", 250_000_000, "d8d52ba036")
EDIT_LORA = ("loras", "loras/moss_image_edit_lora_rank_64_bf16.safetensors", 300_000_000, "17a48b8c60")
MODES = {"generate": "Gerar por caixas", "edit_boxes": "Editar só as caixas", "edit_instruction": "Editar por instrução"}
NEGATIVE = "nsfw, worst quality, bad anatomy, watermark, jpeg artifact"
TEMPLATE = Path(__file__).resolve().parent / "workflows" / "image_moss_image_edit.json"


def files_for(mode):
    return [UNET, ENCODER, VAE] + ([EDIT_LORA] if mode == "edit_instruction" else [])


def editor_state(boxes, width, height):
    """Studio boxes [{x, y, w, h, kind, desc, text}] (fractions) -> the canvas state core `Create Bounding Boxes` takes (pixel boxes + metadata).
    That node turns them into the `elements` the core MOSSImageLayoutPrompt reads (0-1000 yxyx grid). In an API graph a plain list is read as a LINK, so
    the boxes travel as a JSON string in the node's `bboxes` input (which the node documents and which wins over the canvas widget `editor_state`)."""
    state = []
    for box, raw in zip(edits.clean_boxes(boxes), boxes):
        kind = "text" if raw.get("kind") == "text" else "obj"
        desc, text = str(raw.get("desc") or "").strip()[:600], str(raw.get("text") or "").strip()[:200]
        if kind == "text" and not text:
            raise ValueError("Uma caixa de texto precisa das palavras exatas que devem aparecer.")
        if kind == "obj" and not desc:
            raise ValueError("Descreva o que deve aparecer em cada caixa.")
        state.append({"x": round(box["x"] * width), "y": round(box["y"] * height), "width": round(box["w"] * width), "height": round(box["h"] * height),
                      "metadata": {"type": kind, "text": text if kind == "text" else "", "desc": desc, "palette": []}})
    return state


def _node(kind, **inputs):
    return {"class_type": kind, "inputs": inputs}


def _loaders():
    return {"1": _node("UNETLoader", unet_name=Path(UNET[1]).name, weight_dtype="default"),
            "2": _node("CLIPLoader", clip_name=Path(ENCODER[1]).name, type="moss_image", device="default"),
            "3": _node("VAELoader", vae_name=Path(VAE[1]).name)}


def _seed(seed):
    if seed != int(seed) or not -1 <= seed < 2**53:
        raise ValueError("Use uma seed inteira válida.")
    return random.randrange(2**32) if seed == -1 else int(seed)


def snap16(value):
    return max(256, round(value / 16) * 16)


def generate_graph(prompt, boxes, width, height, seed=-1, steps=25, cfg=2.5, negative=NEGATIVE):
    if not (prompt or "").strip():
        raise ValueError("Descreva a cena inteira.")
    if width % 16 or height % 16 or not 256 <= width <= 2048 or not 256 <= height <= 2048:
        raise ValueError("Largura e altura: múltiplos de 16, de 256 a 2048.")
    graph = _loaders()
    graph.update({
        "11": _node("CreateBoundingBoxes", width=width, height=height, editor_state="", bboxes=json.dumps(editor_state(boxes, width, height), ensure_ascii=False)),
        "10": _node("MOSSImageLayoutPrompt", prompt=prompt.strip(), element=["11", 2], width=width, height=height, character_boxes=""),
        "4": _node("CLIPTextEncode", clip=["2", 0], text=["10", 0]),
        "5": _node("CLIPTextEncode", clip=["2", 0], text=negative),
        "6": _node("EmptyFlux2LatentImage", width=width, height=height, batch_size=1),
        "7": _node("KSampler", model=["1", 0], positive=["4", 0], negative=["5", 0], latent_image=["6", 0], seed=_seed(seed), steps=int(steps), cfg=float(cfg),
                   sampler_name="er_sde", scheduler="simple", denoise=1),
        "8": _node("VAEDecode", samples=["7", 0], vae=["3", 0]),
        "9": _node("SaveImage", images=["8", 0], filename_prefix="ClonField/MOSS"),
    })
    return graph


def edit_boxes_graph(prompt, boxes, size, image_name, mask_name, seed=-1, steps=25, cfg=2.5, negative=NEGATIVE):
    """`size` = (width, height) of the working frame. The Studio scales the picture to that size BEFORE uploading it (work_size), and the mask
    file is drawn at the same size, so no scaling node can disagree with the mask."""
    width, height = size
    if not (prompt or "").strip():
        raise ValueError("Descreva a imagem inteira como ela deve ficar DEPOIS da mudança.")
    graph = _loaders()
    graph.update({
        "20": _node("LoadImage", image=image_name),
        "22": _node("LoadImageMask", image=mask_name, channel="red"),
        "11": _node("CreateBoundingBoxes", width=width, height=height, editor_state="", bboxes=json.dumps(editor_state(boxes, width, height), ensure_ascii=False)),
        "10": _node("MOSSImageLayoutPrompt", prompt=prompt.strip(), element=["11", 2], width=width, height=height, character_boxes=""),
        "4": _node("CLIPTextEncode", clip=["2", 0], text=["10", 0]),
        "5": _node("CLIPTextEncode", clip=["2", 0], text=negative),
        "23": _node("VAEEncode", pixels=["20", 0], vae=["3", 0]),
        "24": _node("SetLatentNoiseMask", samples=["23", 0], mask=["22", 0]),
        "25": _node("DifferentialDiffusion", model=["1", 0], strength=1.0),
        "7": _node("KSampler", model=["25", 0], positive=["4", 0], negative=["5", 0], latent_image=["24", 0], seed=_seed(seed), steps=int(steps), cfg=float(cfg),
                   sampler_name="er_sde", scheduler="simple", denoise=1),
        "8": _node("VAEDecode", samples=["7", 0], vae=["3", 0]),
        "26": _node("ImageCompositeMasked", destination=["20", 0], source=["8", 0], x=0, y=0, resize_source=False, mask=["22", 0]),
        "9": _node("SaveImage", images=["26", 0], filename_prefix="ClonField/MOSS-edit"),
    })
    return graph


def work_size(image_size, megapixels=1.5):
    """The working frame for an edit: the picture's proportions, about `megapixels` of area, sides snapped to 16 (1.5 MP is a T4-friendly default; unmeasured)."""
    w, h = image_size
    scale = (megapixels * 1024 * 1024 / (w * h)) ** 0.5
    return snap16(w * scale), snap16(h * scale)


def instruction_graph(objinfo, instruction, image_name, seed=-1, steps=30):
    if not (instruction or "").strip():
        raise ValueError("Diga o que mudar e o que deve ficar igual.")
    wf = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    return ui2api.convert(wf, objinfo, outputs=[9], overrides={8: {"image": image_name}, 39: {"prompt": instruction.strip()}, 37: {"seed": _seed(seed), "steps": int(steps)}})


def download_gb(mode, models_root=None):
    root = Path(models_root or os.environ.get("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models"))
    files = files_for(mode)
    return round(sum(f[2] for f in files) / 1e9, 1), round(sum(f[2] for f in files if not (root / f[0] / Path(f[1]).name).is_file()) / 1e9, 1)


def prepare(session, graph, progress, *, mode, image=None, mask=None):
    import cf_download
    from cf_workflows import require_nodes
    require_nodes(session, graph)
    root = Path(os.environ.get("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models"))
    files = files_for(mode)
    for index, (folder, path, size, _sha) in enumerate(files):
        target = root / folder / Path(path).name
        if not (target.is_file() and target.stat().st_size):
            try:
                cf_download.fetch_hf(REPO, path, target, revision=REVISION, token=os.environ.get("HF_TOKEN") or None,
                                     progress=(lambda f, desc=None, **_: progress((index + f) / len(files), desc=desc)) if progress else None)
            except cf_download.DownloadError as exc:
                raise ValueError(str(exc)) from None
        if abs(target.stat().st_size - size) > max(8_000_000, size // 50):
            target.unlink(missing_ok=True)
            raise ValueError(f"{target.name} baixou com tamanho diferente do publicado; removido. Tente de novo.")
    for node in graph.values():
        if node["class_type"] == "LoadImage" and image:
            node["inputs"]["image"] = upload_input(session, image)
        if node["class_type"] == "LoadImageMask" and mask:
            node["inputs"]["image"] = upload_input(session, mask)
