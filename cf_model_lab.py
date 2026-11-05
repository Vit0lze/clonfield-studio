"""Image model recipes for the existing local ComfyUI executor."""

import math
import os
import secrets
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests

import cf_civitai as civitai
import cf_download as download
from cf_workflows import require_nodes

QWEN = "Comfy-Org/Qwen-Image-2.1"
FLUX2 = "Comfy-Org/Flux-2-Klein-4B"
FLUX3 = "black-forest-labs/flux-3-image-klein-comfy"
KREA = "Comfy-Org/Krea-2"
ZBASE = "Comfy-Org/Z-Image"
ZTURBO = "Comfy-Org/Z-Image-Turbo"
REVISIONS = {
    "Comfy-Org/Flux-2-Klein-4B": "5b3abca5c0dc1ecd4eaf3340868d09063fc1c965",
    "Comfy-Org/Krea-2": "588feaf955b08b9ac4723eeb751752ab045dba71",
    "Comfy-Org/Qwen-Image-2.1": "aacf31a6d48e707f352ecba714cee0680da3479b",
    "Comfy-Org/Z-Image": "94d47a468ec820d29a5dc09d4642539d76d49542",
    "Comfy-Org/Z-Image-Turbo": "6fc90a3b1b653e935a0d175e260736de25b84df5",
    "black-forest-labs/flux-3-image-klein-comfy": "9d36114cf7a2e03a45c28f5cc4987d20ebfdb6c1",
}


@dataclass(frozen=True)
class Preset:
    key: str
    title: str
    api_bases: tuple
    clip_type: str
    latent: str
    steps: int
    cfg: float
    files: dict
    refs: int = 0
    sampler: str = "euler"
    scheduler: str = "simple"

    @property
    def bases(self):
        return {civitai.normalized(name) for name in self.api_bases}

    @property
    def roles(self):
        if not self.clip_type:
            return ("Checkpoint", "VAE", "LoRA", "Upscaler")
        return ("Difusão", "Encoder", "VAE", "LoRA", "Upscaler")


def krea_weights(model):
    return {"Difusão": (KREA, f"diffusion_models/krea2_{model}_int8_convrot.safetensors"),
            "Encoder": (KREA, "text_encoders/qwen3vl_4b_fp8_scaled.safetensors"),
            "VAE": (KREA, "vae/qwen_image_vae.safetensors")}


def z_weights(repo, model):
    return {"Difusão": (repo, f"split_files/diffusion_models/{model}"),
            "Encoder": (ZTURBO, "split_files/text_encoders/qwen_3_4b.safetensors"),
            "VAE": (ZTURBO, "split_files/vae/ae.safetensors")}


PRESETS = {p.key: p for p in (
    Preset("qwen21", "Qwen Image 2.1 · Comfy INT8", ("Qwen 2.1",), "qwen_image", "EmptyLatentImage", 40, 1, {
        "Difusão": (QWEN, "diffusion_models/qwen_image_2.1_int8_convrot.safetensors"),
        "Encoder": (QWEN, "text_encoders/qwen3vl_8b_int8_convrot.safetensors"),
        "VAE": (QWEN, "vae/qwen_image_2.1_vae_bf16.safetensors"),
    }, refs=10),
    Preset("flux2", "FLUX.2 Klein 4B · Distilled", ("Flux.2 Klein 4B",), "flux2", "EmptyFlux2LatentImage", 4, 1, {
        "Difusão": (FLUX2, "split_files/diffusion_models/flux-2-klein-4b.safetensors"),
        "Encoder": (FLUX2, "split_files/text_encoders/qwen_3_4b.safetensors"),
        "VAE": (FLUX2, "split_files/vae/flux2-vae.safetensors"),
    }, refs=2),
    Preset("flux3", "FLUX.3 Klein · Distilled INT8", ("Flux.3 Klein",), "flux3", "EmptyFlux2LatentImage", 16, 1, {
        "Difusão": (FLUX3, "diffusion_models/flux3-image-klein-int8-convrot.safetensors"),
        "Encoder": (FLUX3, "text_encoders/qwen3vl_4b_int8_convrot.safetensors"),
        "VAE": (FLUX3, "vae/flux2-vae.safetensors"),
    }, refs=3),
    Preset("krea2", "Krea 2 · Raw INT8", ("Krea 2",), "krea2", "EmptyLatentImage", 28, 4.5, krea_weights("raw")),
    Preset("krea2-turbo", "Krea 2 · Turbo INT8", ("Krea 2 Turbo",), "krea2", "EmptyLatentImage", 8, 1, krea_weights("turbo")),
    Preset("z-image", "Z-Image · Base INT8", ("ZImageBase",), "lumina2", "EmptySD3LatentImage", 25, 4,
           z_weights(ZBASE, "z_image_int8_convrot.safetensors"), sampler="res_multistep"),
    Preset("z-image-turbo", "Z-Image · Turbo INT8", ("ZImageTurbo",), "lumina2", "EmptySD3LatentImage", 8, 1,
           z_weights(ZTURBO, "z_image_turbo_int8_convrot.safetensors"), sampler="res_multistep"),
    Preset("sdxl", "SDXL 1.0 · Checkpoint Civitai", ("SDXL 1.0",), "", "EmptyLatentImage", 28, 6, {}),
    Preset("sd15", "Stable Diffusion 1.5 · Checkpoint Civitai", ("SD 1.5",), "", "EmptyLatentImage", 25, 7, {}),
)}
PROMPT_UPSAMPLER = (FLUX3, "text_encoders/qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors")
UPSAMPLE_INSTRUCTIONS = (
    "Expand the request into one detailed English caption for an image generation model. "
    "Include subject, composition, camera, lighting, texture and atmosphere. "
    "If reference images are attached, use them in order and describe requested changes and what to preserve. "
    "Return only the caption."
)


def selections(directory, preset, selected, adapters, pending=None):
    if len(adapters or []) > 4:
        raise ValueError("Use até quatro LoRAs por geração.")
    chosen = {}
    pending = pending or {}
    for role, keys in {**selected, "LoRA": adapters or []}.items():
        keys = [keys] if isinstance(keys, str) else keys
        if not keys:
            continue
        if role not in preset.roles:
            raise ValueError(f"O preset não oferece o slot {role}.")
        available = {key: (data, path) for key, data, path in civitai.inventory(directory, preset, role)}
        for key in dict.fromkeys(keys):
            if key in available:
                data, path = available[key]
                civitai.check_tensor(path, role)
            elif key in pending and pending[key]["role"] == role and pending[key]["preset"] == preset.key:
                data = pending[key]
                if role != "Upscaler" and civitai.normalized(data["base"]) not in preset.bases:
                    raise ValueError(f"O arquivo pendente não é compatível com {preset.title}.")
                path = civitai.asset_path(data, directory)
            else:
                raise ValueError(f"Seleção {role} indisponível ou incompatível com o preset.")
            chosen.setdefault(role, []).append((data, path))
    if not preset.clip_type and "Checkpoint" not in chosen:
        raise ValueError("Selecione um checkpoint instalado do Civitai para este preset.")
    return chosen


def names_and_sources(preset, chosen, expand):
    defaults = dict(preset.files)
    if expand and preset.key == "flux3":
        defaults["Expansor"] = PROMPT_UPSAMPLER
    for role in chosen:
        defaults.pop(role, None)
    sources = [(Path(file).parts[-2], Path(file).name, (repo, file)) for repo, file in defaults.values()]
    names = {role: [Path(spec[1]).name] for role, spec in defaults.items()}
    for role, entries in chosen.items():
        names[role] = [path.name for _, path in entries]
        sources.extend((civitai.ROLE_TYPES[role], path.name, path) for _, path in entries)
    return names, sources


def make_graph(preset, names, prompt, negative, width, height, steps, cfg, seed, files, strength, expand,
               lora_weights=()):
    if not prompt or not prompt.strip():
        raise ValueError("Escreva um prompt.")
    if not all(math.isfinite(x) and int(x) == x and 256 <= x <= 2048 and x % 32 == 0 for x in (width, height)):
        raise ValueError("Use dimensões de 256 a 2048, em múltiplos de 32.")
    if not 1 <= steps <= 80 or int(steps) != steps or not 1 <= cfg <= 12 or not -2 <= strength <= 2:
        raise ValueError("Passos, CFG ou intensidade das LoRAs fora dos limites.")
    if not math.isfinite(seed) or int(seed) != seed or not -1 <= seed < 2**53:
        raise ValueError("Use uma seed inteira válida ou -1.")
    files = files or []
    if len(files) > preset.refs:
        raise ValueError(f"{preset.title} aceita {preset.refs} referência(s) neste app.")
    if negative and negative.strip() and cfg == 1:
        raise ValueError("O prompt negativo requer CFG maior que 1.")
    if preset.key == "flux3" and not expand and len(prompt.split()) < 12:
        raise ValueError("Escreva uma legenda visual detalhada para FLUX.3 ou ligue o expansor local.")
    width, height, steps = int(width), int(height), int(steps)
    seed = secrets.randbelow(2**32) if seed < 0 else int(seed)
    graph = {}

    def node(kind, **inputs):
        key = str(len(graph) + 1)
        graph[key] = {"class_type": kind, "inputs": inputs}
        return [key, 0]

    if preset.clip_type:
        model = node("UNETLoader", unet_name=names["Difusão"][0], weight_dtype="default")
        clip = node("CLIPLoader", clip_name=names["Encoder"][0], type=preset.clip_type, device="default")
        vae = node("VAELoader", vae_name=names["VAE"][0])
    else:
        model = node("CheckpointLoaderSimple", ckpt_name=names["Checkpoint"][0])
        clip, vae = [model[0], 1], [model[0], 2]
        if "VAE" in names:
            vae = node("VAELoader", vae_name=names["VAE"][0])

    for index, name in enumerate(names.get("LoRA", [])):
        weights = lora_weights[index] if index < len(lora_weights) else (None, None)
        model_weight, clip_weight = (float(strength if weight is None else weight) for weight in weights)
        if not -2 <= model_weight <= 2 or not -2 <= clip_weight <= 2:
            raise ValueError(f"Use pesos de -2 a 2 para a LoRA {index + 1}.")
        model = node("LoraLoader", model=model, clip=clip, lora_name=name,
                     strength_model=model_weight, strength_clip=clip_weight)
        clip = [model[0], 1]
    if preset.clip_type == "lumina2":
        model = node("ModelSamplingAuraFlow", model=model, shift=3.0)

    references = []
    uploads = {}
    for index, path in enumerate(files):
        image = node("LoadImage", image="")
        uploads[image[0]] = path
        if preset.key == "qwen21" and index == 0:
            scaled = node("ImageScale", image=image, upscale_method="lanczos", width=width,
                          height=height, crop="center")
        else:
            scaled = node("ImageScaleToTotalPixels", image=image, megapixels=0.65,
                          upscale_method="lanczos", resolution_steps=32)
        references.append(scaled)
    caption = prompt.strip()
    if "Expansor" in names:
        pup = node("CLIPLoader", clip_name=names["Expansor"][0], type="flux3", device="default")
        caption = node("TextGenerateV2", clip=pup, prompt=caption, system_prompt=UPSAMPLE_INSTRUCTIONS,
                       max_length=1024, sampling_mode="off", thinking=False, mtp="off",
                       **{f"images.image{i}": image for i, image in enumerate(references, 1)})
    if preset.key == "qwen21":
        positive = node("TextEncodeQwenImage21", clip=clip, vae=vae, prompt=caption,
                        negative_prompt=negative or "", resolution=0,
                        **{f"images.image_{i}": image for i, image in enumerate(references, 1)})
        negative_cond = [positive[0], 1]
    else:
        positive = node("CLIPTextEncode", clip=clip, text=caption)
        negative_cond = (node("CLIPTextEncode", clip=clip, text=negative or "") if cfg > 1
                         else node("ConditioningZeroOut", conditioning=positive))
        for reference in references:
            latent_ref = node("VAEEncode", pixels=reference, vae=vae)
            positive = node("ReferenceLatent", conditioning=positive, latent=latent_ref)
            negative_cond = node("ReferenceLatent", conditioning=negative_cond, latent=latent_ref)
    latent = ([positive[0], 2] if preset.key == "qwen21" and references else
              node(preset.latent, width=width, height=height, batch_size=1))
    if preset.key == "flux2":
        noise = node("RandomNoise", noise_seed=seed)
        guider = node("CFGGuider", model=model, positive=positive, negative=negative_cond, cfg=float(cfg))
        sampler = node("KSamplerSelect", sampler_name=preset.sampler)
        sigmas = node("Flux2Scheduler", width=width, height=height, steps=steps)
        samples = node("SamplerCustomAdvanced", noise=noise, guider=guider, sampler=sampler, sigmas=sigmas,
                       latent_image=latent)
    else:
        samples = node("KSampler", model=model, positive=positive, negative=negative_cond, latent_image=latent,
                       seed=seed, steps=steps, cfg=float(cfg), sampler_name=preset.sampler,
                       scheduler=preset.scheduler, denoise=1.0)
    decoded = node("VAEDecode", samples=samples, vae=vae)
    if "Upscaler" in names:
        upscaler = node("UpscaleModelLoader", model_name=names["Upscaler"][0])
        decoded = node("ImageUpscaleWithModel", upscale_model=upscaler, image=decoded)
    node("SaveImage", images=decoded, filename_prefix=f"ClonField/{preset.key}")
    return graph, uploads, seed


def worker_schema(session, graph, check_files):
    try:
        schemas = require_nodes(session, graph)
    except requests.RequestException:
        raise ValueError("Worker ComfyUI local indisponível. Inicie a célula do ComfyUI no Colab.") from None
    for node in graph.values():
        spec = schemas[node["class_type"]]["input"]
        fields = {**spec.get("required", {}), **spec.get("optional", {})}
        for key, value in node["inputs"].items():
            options = fields.get(key)
            if not options or isinstance(value, list) or (key.endswith("_name") and not check_files):
                continue
            allowed = options[0] if isinstance(options[0], list) else (
                options[1].get("options") if len(options) > 1 and isinstance(options[1], dict) else None)
            if isinstance(allowed, list) and allowed and isinstance(allowed[0], dict):
                allowed = [choice["key"] for choice in allowed if "key" in choice]
            if allowed is not None and value not in allowed and not (key == "image" and value == ""):
                raise ValueError(f"ComfyUI não oferece {value} em {node['class_type']}.{key}.")
    return schemas


def models_root():
    return Path(os.getenv("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models"))


def stage_local(directory, name, source):
    target = models_root() / directory / name
    if target.is_file() and target.stat().st_size:
        return target
    # Hugging Face snapshots point to cache blobs through relative symlinks.
    # Resolve the blob before hardlinking it into a different directory.
    source = Path(source).resolve(strict=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as staging:
        partial = Path(staging) / name
        try:
            os.link(source, partial)
        except OSError:
            shutil.copyfile(source, partial)
        partial.replace(target)
    return target


def prepare(session, graph, progress, *, sources, uploads, pending=(), asset_directory=None):
    from cf_seedvr2 import upload_input

    progress(0.05, desc="Verificando nós do ComfyUI")
    worker_schema(session, graph, check_files=False)
    for entry in pending:
        progress(0.08, desc=f'Baixando Civitai · versão {entry["version"]}')
        civitai.install(entry, asset_directory, progress)
    root = models_root()
    for directory, name, source in sources:
        target = root / directory / name
        if target.is_file() and target.stat().st_size:
            continue
        progress(0.12, desc=f"Preparando {name}")
        if isinstance(source, tuple):
            repo, filename, *revision = source
            try:
                download.fetch_hf(repo, filename, target, revision=(revision or [REVISIONS.get(repo, "main")])[0],
                                  token=os.getenv("HF_TOKEN") or None, progress=progress)
            except download.DownloadError as exc:
                raise ValueError(f"{exc} Confira o acesso a {repo} e o Secret HF_TOKEN.") from None
            continue
        stage_local(directory, name, source)
    worker_schema(session, graph, check_files=True)
    if uploads:
        progress(0.15, desc="Enviando referências ao ComfyUI")
    for node, path in uploads.items():
        graph[node]["inputs"]["image"] = upload_input(session, path)
