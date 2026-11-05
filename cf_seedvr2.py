"""Single-job SeedVR2 execution through the local ComfyUI worker."""
import json
import math
import shutil
import subprocess
import time
import os
import uuid
from pathlib import Path

import requests
from PIL import Image

SERVER = "http://127.0.0.1:8188"
REPO = "Comfy-Org/SeedVR2"
REVISION = "df48879708206a403d2a61acd55578c2e80fd233"
VAE = "seedvr2_ema_vae_fp16.safetensors"
LIGHT = "3B leve · INT8"
PROFILES = {
    "7B normal · INT8": "seedvr2_7b_int8_convrot.safetensors",
    "7B Sharp · INT8": "seedvr2_7b_sharp_int8_convrot.safetensors",
    LIGHT: "seedvr2_3b_int8_convrot.safetensors",
}
DEFAULT = "7B normal · INT8"
DEFAULT_TILE = 384


def make_graph(kind, filename, profile, scale, seed, tile, video_chunk):
    """Flatten the official image and video graph paths into ComfyUI API inputs."""
    def node(cls, **inputs):
        return {"class_type": cls, "inputs": inputs}

    video = kind == "Vídeo"
    graph = {"1": node("LoadVideo" if video else "LoadImage", **{"file" if video else "image": filename})}
    if video:
        graph["2"] = node("GetVideoComponents", video=["1", 0])
        source = ["2", 0]
    else:
        graph["2"] = node("JoinImageWithAlpha", image=["1", 0], alpha=["1", 1])
        source = ["2", 0]
    latent = ["14", 0] if video else ["7", 0]
    sampled = ["15", 0] if video else ["9", 0]
    graph.update({
        "3": node("ResizeImageMaskNode", input=source, resize_type="scale by multiplier",
                  **{"resize_type.multiplier": float(scale)}, scale_method="lanczos"),
        "4": node("UNETLoader", unet_name=PROFILES[profile], weight_dtype="default"),
        "5": node("VAELoader", vae_name=VAE),
        "6": node("SeedVR2Preprocess", resized_images=["3", 0]),
        "7": node("VAEEncodeTiled", pixels=["6", 0], vae=["5", 0], tile_size=tile,
                  overlap=tile//4, temporal_size=64 if video else 4096, temporal_overlap=8),
        "8": node("SeedVR2Conditioning", model=["4", 0], vae_conditioning=latent),
        "9": node("KSampler", model=["4", 0], positive=["8", 0], negative=["8", 1],
                  latent_image=latent, seed=seed, steps=1, cfg=1,
                  sampler_name="euler", scheduler="simple", denoise=1),
        "10": node("VAEDecodeTiled", samples=sampled, vae=["5", 0], tile_size=tile,
                   overlap=tile//4, temporal_size=64 if video else 4096, temporal_overlap=8),
        "11": node("SeedVR2PostProcessing", images=["10", 0], original_resized_images=["3", 0],
                   color_correction_method="none"),
    })
    if video:
        graph["14"] = node("SeedVR2TemporalChunk", latent=["7", 0], temporal_overlap=1,
                           chunking_mode="manual", **{"chunking_mode.frames_per_chunk": video_chunk})
        graph["15"] = node("SeedVR2TemporalMerge", latents=["9", 0], temporal_overlap=["14", 1])
        graph["12"] = node("CreateVideo", images=["11", 0], audio=["2", 1], fps=["2", 2], bit_depth=["2", 3])
        graph["13"] = node("SaveVideo", video=["12", 0],
                           filename_prefix="ClonField/SeedVR2", format="mp4", **{"format.codec": "h264"})
    else:
        graph["13"] = node("SaveImage", images=["11", 0], filename_prefix="ClonField/SeedVR2")
    return graph



def install_weights(profile, directory, token, progress=None):
    import cf_download

    for filename in ("vae/" + VAE, "diffusion_models/" + PROFILES[profile]):
        target = Path(directory) / filename
        if target.is_file() and target.stat().st_size:
            continue
        try:
            cf_download.fetch_hf(REPO, filename, target, revision=REVISION, token=token or None, progress=progress)
        except cf_download.DownloadError as exc:
            raise ValueError(str(exc)) from None


def probe_media(path, kind):
    if kind == "Imagem":
        with Image.open(path) as image:
            size = {"width": image.width, "height": image.height}
            image.verify()
            return size
    if not shutil.which("ffprobe"):
        raise ValueError("Instala o ffprobe para validar o clipe antes de executar.")
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    info = json.loads(completed.stdout)
    stream = next((item for item in info["streams"] if item["codec_type"] == "video"), None)
    if stream is None:
        raise ValueError("O arquivo não contém vídeo.")
    from fractions import Fraction
    return {
        "width": stream["width"], "height": stream["height"],
        "frames": int(stream.get("nb_read_frames") or 0),
        "fps": float(Fraction(stream["avg_frame_rate"])),
        "duration": float(info["format"]["duration"]),
        "audio": any(item["codec_type"] == "audio" for item in info["streams"]),
    }


def validate(path, kind, profile, scale, seed, tile):
    if not path or kind not in ("Imagem", "Vídeo"):
        raise ValueError("Seleciona imagem ou vídeo e envia o arquivo.")
    if profile not in PROFILES:
        raise ValueError("Escolhe um modelo SeedVR2.")
    scale, seed, tile = float(scale), int(seed), int(tile)
    if not math.isfinite(scale) or not 1 <= scale <= 4 or not 0 <= seed < 2**53 or tile not in (256, 384, 512):
        raise ValueError("Escala 1–4, seed inteira não negativa e tile de 256, 384 ou 512.")
    if kind == "Vídeo" and Path(path).stat().st_size > 32 * 1024**2:
        raise ValueError("O upscale aceita clipes de até 32 MiB.")
    media = probe_media(path, kind)
    if kind == "Vídeo" and (not 1 <= media["frames"] <= 24 or media["duration"] > 2):
        raise ValueError("O upscale de vídeo aceita até 2 segundos e 24 quadros por execução.")
    pixels = media["width"] * media["height"] * scale**2
    if pixels > (1920 * 1080 if kind == "Vídeo" else 4096**2):
        raise ValueError("Resolução de saída acima do limite desta operação. Reduz a escala ou a entrada.")
    return media


def missing_weights(session, graph):
    response = session.get(SERVER + "/object_info", timeout=15)
    response.raise_for_status()
    schemas = response.json()
    missing = sorted({item["class_type"] for item in graph.values()} - schemas.keys())
    if missing:
        raise ValueError("Nós ausentes no ComfyUI: " + ", ".join(missing))
    absent = []
    for node_id, field in [("4", "unet_name"), ("5", "vae_name")]:
        node = graph[node_id]
        schema = schemas[node["class_type"]]["input"]["required"][field]
        options = schema[0] if isinstance(schema[0], list) else schema[1].get("options", [])
        if node["inputs"][field] not in options:
            absent.append(node["inputs"][field])
    return absent


class WorkerError(RuntimeError):
    def __init__(self, messages):
        errors = [
            item[1] for item in messages
            if isinstance(item, list) and len(item) == 2
            and item[0] == "execution_error" and isinstance(item[1], dict)
        ]
        detail = errors[-1] if errors else {}
        message = str(detail.get("exception_message") or "Falha no ComfyUI.")
        error_type = str(detail.get("exception_type", ""))
        self.out_of_memory = (
            error_type.endswith(("OutOfMemoryError", "OOM_EXCEPTION"))
            or "out of memory" in message.lower()
            or "allocation on device" in message.lower()
        )
        node = detail.get("node_type")
        super().__init__(f"{node}: {message[:800]}" if node else message[:800])


def download_result(session, prompt_id, directory, suffix, timeout=900):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = session.get(f"{SERVER}/history/{prompt_id}", timeout=20)
        response.raise_for_status()
        result = response.json().get(prompt_id)
        if not result:
            time.sleep(1)
            continue
        status = result.get("status", {})
        if status.get("status_str") == "error":
            raise WorkerError(status.get("messages") or [])
        output = result.get("outputs", {}).get("13", {})
        files = [item for values in output.values() if isinstance(values, list)
                 for item in values if isinstance(item, dict) and item.get("filename")]
        if not files:
            raise RuntimeError("O nó de saída terminou sem devolver um arquivo.")
        params = {key: files[0].get(key, "") for key in ("filename", "subfolder", "type")}
        with session.get(SERVER + "/view", params=params, stream=True, timeout=120) as response:
            response.raise_for_status()
            path = directory / ("resultado" + suffix)
            partial = path.with_suffix(path.suffix + ".part")
            try:
                with partial.open("wb") as file:
                    for chunk in response.iter_content(1024 * 1024):
                        file.write(chunk)
                probe_media(partial, "Vídeo" if suffix == ".mp4" else "Imagem")
                partial.replace(path)
            finally:
                partial.unlink(missing_ok=True)
        return path
    raise TimeoutError(f"O resultado ainda não está disponível. Job remoto: {prompt_id}.")



def persist(folder, job):
    path = folder / "job.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def collect(session, folder, job, timeout):
    suffix = ".mp4" if job["kind"] == "Vídeo" else ".png"
    try:
        output = download_result(session, job["prompt_id"], folder, suffix, timeout)
        job["output"] = probe_media(output, job["kind"])
    except WorkerError as exc:
        job.update(status="falhou", error=str(exc))
        if exc.out_of_memory:
            job["out_of_memory"] = True
    except (requests.RequestException, OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        job.update(status="aguardando_coleta", error=str(exc))
    else:
        job.update(status="concluído", result=output.name)
        job.pop("error", None)
    persist(folder, job)
    return job


def prepare_weights(session, graph, model, progress):
    missing = missing_weights(session, graph)
    if not missing:
        return
    progress(0.12, desc=f"Baixando SeedVR2 {model}")
    models = Path(os.environ.get("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models"))
    install_weights(model, models, os.environ.get("HF_TOKEN"), progress)
    missing = missing_weights(session, graph)
    if missing:
        raise ValueError(f"O worker ainda não vê {', '.join(missing)} no diretório {models}.")


def submit(session, folder, job, graph):
    job["status"] = "enviando"
    persist(folder, job)
    response = session.post(SERVER + "/prompt", json={"prompt": graph}, timeout=25)
    if not response.ok:
        job["status"] = "falhou"
        raise RuntimeError(response.text[:1200])
    job.update(status="enviado", prompt_id=response.json()["prompt_id"])
    persist(folder, job)


def upload_input(session, path):
    path = Path(path)
    with path.open("rb") as source:
        response = session.post(
            SERVER + "/upload/image", files={"image": (uuid.uuid4().hex + path.suffix, source)},
            data={"type": "input"}, timeout=90,
        )
        response.raise_for_status()
    info = response.json()
    return "/".join(filter(None, (info.get("subfolder"), info["name"])))


def collect_with_fallback(session, folder, job, timeout, progress):
    collect(session, folder, job, timeout)
    if not job.get("out_of_memory") or job["model"] == LIGHT or not job.get("uploaded_file"):
        return job
    job["fallback"] = {"model": job["model"], "prompt_id": job.pop("prompt_id"), "error": job.pop("error")}
    job.pop("out_of_memory", None)
    job.update(status="preparando", model=LIGHT, checkpoint=PROFILES[LIGHT], tile=256)
    if job["kind"] == "Vídeo":
        job["frames_por_bloco"] = 5
    persist(folder, job)
    try:
        graph = make_graph(job["kind"], job["uploaded_file"], LIGHT, job["scale"], job["seed"], 256, 5)
        progress(0.10, desc="VRAM insuficiente no 7B. Preparando 3B INT8.")
        prepare_weights(session, graph, LIGHT, progress)
        submit(session, folder, job, graph)
        progress(0.5, desc="Processando upscale com 3B INT8")
    except (requests.RequestException, OSError, ValueError, RuntimeError, KeyError) as exc:
        state = "envio_indeterminado" if job["status"] == "enviando" else "falhou"
        job.update(status=state, error=str(exc))
        persist(folder, job)
        return job
    return collect(session, folder, job, timeout)


def run(path, kind, profile, scale, seed, tile, output_dir, progress):
    media = validate(path, kind, profile, scale, seed, tile)
    pixels = media["width"] * media["height"] * float(scale)**2
    # Keep temporal context on small outputs while limiting DiT activation peaks at 1080p.
    video_chunk = 9 if pixels <= 1280 * 720 else 5
    graph = make_graph(kind, "preflight", profile, float(scale), int(seed), int(tile), video_chunk)
    folder = Path(output_dir) / ("seedvr2_" + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    job = {
        "id": folder.name, "recipe": "R23", "kind": kind, "model": profile,
        "checkpoint": PROFILES[profile], "revision": REVISION, "input": media,
        "seed": int(seed), "scale": float(scale), "tile": int(tile),
        "status": "preparando",
    }
    if kind == "Vídeo":
        job["frames_por_bloco"] = video_chunk
    persist(folder, job)
    with requests.Session() as session:
        session.trust_env = False
        try:
            prepare_weights(session, graph, profile, progress)
            progress(0.35, desc="Enviando mídia ao ComfyUI")
            filename = upload_input(session, path)
            job["uploaded_file"] = filename
            graph["1"]["inputs"]["file" if kind == "Vídeo" else "image"] = filename
            submit(session, folder, job, graph)
        except (requests.RequestException, OSError, ValueError, RuntimeError, KeyError) as exc:
            state = "envio_indeterminado" if job["status"] == "enviando" else "falhou"
            job.update(status=state, error=str(exc))
            persist(folder, job)
            return job
        progress(0.5, desc="Processando upscale")
        return collect_with_fallback(session, folder, job, 900, progress)


def recent_jobs(output_dir):
    jobs = []
    for path in sorted(Path(output_dir).glob("seedvr2_*/job.json"),
                       key=lambda value: value.stat().st_mtime, reverse=True):
        job = json.loads(path.read_text(encoding="utf-8"))
        jobs.append((f"{job['kind']} · {job['model']} · {job['status']} · {job['id'][-8:]}", job["id"]))
    return jobs


def reopen(output_dir, job_id, progress):
    if not job_id or not job_id.startswith("seedvr2_") or Path(job_id).name != job_id:
        raise ValueError("Escolhe um upscale do histórico.")
    folder = Path(output_dir) / job_id
    job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    if job.get("prompt_id") and (job["status"] in ("enviado", "aguardando_coleta")
                                 or (job.get("out_of_memory") and job["model"] != LIGHT and job.get("uploaded_file"))):
        with requests.Session() as session:
            session.trust_env = False
            return collect_with_fallback(session, folder, job, 4, progress)
    return job
