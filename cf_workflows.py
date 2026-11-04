"""Submit local ComfyUI API graphs and collect saved media by prompt ID."""

import hashlib
import json
import time
import uuid
from pathlib import Path

import requests

from cf_seedvr2 import SERVER, WorkerError, persist, upload_input

IMAGE_SUFFIXES = {".png", ".jpeg", ".jpg", ".webp", ".gif", ".avif", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov", ".avi"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".opus"}
MEDIA_SUFFIXES = IMAGE_SUFFIXES | VIDEO_SUFFIXES | AUDIO_SUFFIXES
MEDIA_INPUTS = {"LoadImage": "image", "LoadImageMask": "image", "LoadVideo": "file", "LoadAudio": "audio"}


def read_graph(path):
    graph = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(graph, dict):
        raise ValueError("O arquivo deve conter um workflow ComfyUI em API JSON.")
    graph = graph.get("prompt", graph)
    if not isinstance(graph, dict) or not graph or any(
        not isinstance(node, dict) or not isinstance(node.get("class_type"), str)
        or not isinstance(node.get("inputs"), dict)
        for node in graph.values()
    ):
        raise ValueError("Exporte o workflow pelo ComfyUI usando o formato API JSON.")
    return graph


def media_entries(history):
    for node in history.get("outputs", {}).values():
        for entries in node.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("filename")
                kind = entry.get("type", "output")
                subfolder = entry.get("subfolder", "")
                if (not isinstance(name, str) or name != Path(name).name or "\\" in name
                        or Path(name).suffix.lower() not in MEDIA_SUFFIXES
                        or kind not in ("output", "temp") or not isinstance(subfolder, str)):
                    continue
                yield name, subfolder, kind


def bind_uploads(session, graph, files):
    if not files:
        return
    targets = {}
    for node in graph.values():
        key = MEDIA_INPUTS.get(node["class_type"])
        original = node["inputs"].get(key)
        if isinstance(original, str):
            name = Path(original.removesuffix(" [input]")).name
            targets.setdefault(name, []).append((node["inputs"], key))
    paths = [Path(file) for file in files]
    names = {path.name for path in paths}
    if len(names) != len(paths):
        raise ValueError("As mídias anexadas precisam ter nomes diferentes.")
    unmatched = names - targets.keys()
    if unmatched:
        raise ValueError("Nenhum nó nativo correspondente para: " + ", ".join(sorted(unmatched)))
    for path in paths:
        uploaded_name = upload_input(session, path)
        for inputs, key in targets[path.name]:
            inputs[key] = uploaded_name


def collect(session, folder, job, timeout):
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            response = session.get(f"{SERVER}/history/{job['prompt_id']}", timeout=20)
            response.raise_for_status()
            history = response.json().get(job["prompt_id"])
            if history:
                break
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        else:
            raise TimeoutError("O resultado ainda está no worker. Use Retomar coleta.")
        status = history.get("status") or {}
        if status.get("status_str") == "error":
            raise WorkerError(status.get("messages") or [])
        for name, subfolder, kind in dict.fromkeys(media_entries(history)):
            key = hashlib.sha256(json.dumps([name, subfolder, kind]).encode()).hexdigest()[:16]
            dest = folder / (key + Path(name).suffix.lower())
            if not dest.is_file():
                partial = dest.with_suffix(".part")
                try:
                    with session.get(f"{SERVER}/view", params={
                        "filename": name, "subfolder": subfolder, "type": kind,
                    }, stream=True, timeout=(15, 90)) as media:
                        media.raise_for_status()
                        with partial.open("wb") as handle:
                            for chunk in media.iter_content(1024 * 1024):
                                handle.write(chunk)
                    if not partial.stat().st_size:
                        raise ValueError(f"O worker devolveu um arquivo vazio: {name}")
                    partial.replace(dest)
                finally:
                    partial.unlink(missing_ok=True)
            if dest.name not in job["results"]:
                job["results"].append(dest.name)
                persist(folder, job)
    except WorkerError as exc:
        job.update(status="falhou", message=str(exc))
    except (requests.RequestException, OSError, ValueError) as exc:
        job.update(status="aguardando_coleta", message=str(exc))
    else:
        message = "" if job["results"] else "Workflow concluído sem arquivos de imagem, vídeo ou áudio."
        job.update(status="concluído", message=message)
    persist(folder, job)
    return job


def require_nodes(session, graph):
    response = session.get(f"{SERVER}/object_info", timeout=20)
    response.raise_for_status()
    schemas = response.json()
    missing = sorted({node["class_type"] for node in graph.values()} - schemas.keys())
    if missing:
        raise ValueError("Nós ausentes no ComfyUI local: " + ", ".join(missing))
    return schemas


def run(graph, output_dir, progress, files=None, prepare=None, title=None):
    folder = Path(output_dir) / ("workflow_" + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    job = {"id": folder.name, "status": "preparando", "results": []}
    if title:
        job["title"] = title
    persist(folder, job)
    with requests.Session() as session:
        session.trust_env = False
        try:
            if prepare:
                prepare(session, graph, progress)
            else:
                require_nodes(session, graph)
            if files:
                progress(0.08, desc="Enviando mídias ao ComfyUI")
                bind_uploads(session, graph, files)
            job["status"] = "enviando"
            persist(folder, job)
            response = session.post(f"{SERVER}/prompt", json={"prompt": graph}, timeout=25)
            if not response.ok:
                job.update(status="falhou", message=response.text[:1600])
                persist(folder, job)
                return job
            job.update(status="enviado", prompt_id=response.json()["prompt_id"])
        except (requests.RequestException, OSError, ValueError, KeyError) as exc:
            if job["status"] == "enviando":
                job.update(status="envio_indeterminado", message=f"{exc}. Verifique a fila no ComfyUI.")
            else:
                job.update(status="falhou", message=str(exc))
            persist(folder, job)
            return job
        persist(folder, job)
        progress(0.2, desc=f"Aguardando ComfyUI · {job['prompt_id']}")
        return collect(session, folder, job, 3600)


def recent(output_dir):
    jobs = []
    for path in sorted(Path(output_dir).glob("workflow_*/job.json"),
                       key=lambda file: file.stat().st_mtime, reverse=True):
        try:
            job = json.loads(path.read_text())
            jobs.append((f"{job.get('title', 'Workflow')} · {job['status']} · {job['id'][-8:]}", job["id"]))
        except (OSError, ValueError, KeyError):
            continue
    return jobs


def reopen(output_dir, job_id):
    if not job_id or not job_id.startswith("workflow_") or Path(job_id).name != job_id:
        raise ValueError("Selecione um workflow do histórico.")
    folder = Path(output_dir) / job_id
    job = json.loads((folder / "job.json").read_text())
    if job.get("prompt_id") and job["status"] in ("enviado", "aguardando_coleta"):
        with requests.Session() as session:
            session.trust_env = False
            return collect(session, folder, job, 4)
    return job
