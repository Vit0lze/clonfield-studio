"""Submit local ComfyUI API graphs and collect saved media by prompt ID."""

import hashlib
import json
import time
import uuid
from contextlib import ExitStack
from pathlib import Path

import requests

from cf_seedvr2 import SERVER, WorkerError, persist, upload_input

IMAGE_SUFFIXES = {".png", ".jpeg", ".jpg", ".webp", ".gif", ".avif", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov", ".avi"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".opus"}
MODEL_3D_SUFFIXES = {".glb", ".gltf", ".obj", ".stl", ".fbx", ".usdz"}
MEDIA_SUFFIXES = IMAGE_SUFFIXES | VIDEO_SUFFIXES | AUDIO_SUFFIXES | MODEL_3D_SUFFIXES
_last_family = [None]
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


def open_worker_socket(connections, client_id):
    try:
        from websockets.exceptions import WebSocketException
        from websockets.sync.client import connect
    except ImportError:
        return None
    address = SERVER.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
    try:
        return connections.enter_context(connect(f"{address}/ws?clientId={client_id}",
                                                 open_timeout=3, close_timeout=1))
    except (OSError, WebSocketException):
        return None


class Control:
    """Lets another thread cancel a running ComfyUI job and tells it why it stopped."""

    def __init__(self):
        self.cancelled = False
        self.prompt_id = None

    def cancel(self, session=None):
        self.cancelled = True
        interrupt(self.prompt_id)


def interrupt(prompt_id=None):
    """Stop the running prompt and drop it from the pending queue. Safe to call when nothing runs."""
    try:
        with requests.Session() as session:
            session.trust_env = False
            session.post(f"{SERVER}/interrupt", json={"prompt_id": prompt_id} if prompt_id else {}, timeout=5)
            if prompt_id:
                session.post(f"{SERVER}/queue", json={"delete": [prompt_id]}, timeout=5)
    except requests.RequestException:
        pass


def clear_orphans():
    """Called at startup: a previous session may have left prompts that would block new ones for hours."""
    try:
        with requests.Session() as session:
            session.trust_env = False
            session.post(f"{SERVER}/queue", json={"clear": True}, timeout=5)
            session.post(f"{SERVER}/interrupt", json={}, timeout=5)
    except requests.RequestException:
        pass


def free_models(session, unload=True):
    try:
        session.post(f"{SERVER}/free", json={"unload_models": unload, "free_memory": unload}, timeout=10)
    except requests.RequestException:
        pass


def queue_state(session, prompt_id):
    """Return ('running'|'pending', position) or (None, None) when ComfyUI no longer knows the prompt."""
    data = session.get(f"{SERVER}/queue", timeout=10).json()
    for entry in data.get("queue_running", []):
        if len(entry) > 1 and entry[1] == prompt_id:
            return "running", 0
    for position, entry in enumerate(sorted(data.get("queue_pending", []), key=lambda e: e[0]), 1):
        if len(entry) > 1 and entry[1] == prompt_id:
            return "pending", position
    return None, None


def worker_log_tail(lines=12, sep=" | ", limit=900):
    from pathlib import Path as _Path
    import os as _os
    log = _Path(_os.environ.get("CLONFIELD_COMFY_LOG", "/content/clonfield_runtime/comfyui.log"))
    try:
        return sep.join(log.read_text(errors="replace").strip().splitlines()[-lines:])[-limit:]
    except OSError:
        return ""


def wait_events(socket, duration, prompt_id, graph, progress):
    """Listen to the worker for up to `duration`. Returns True when an event for this prompt arrived."""
    from websockets.exceptions import WebSocketException

    deadline = time.monotonic() + duration
    seen = False
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            raw = socket.recv(timeout=remaining)
        except TimeoutError:
            return seen
        except WebSocketException as exc:
            raise ConnectionError("WebSocket do ComfyUI desconectado") from exc
        if not isinstance(raw, str):
            continue
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        data = event.get("data")
        if not isinstance(data, dict) or data.get("prompt_id") != prompt_id:
            continue
        seen = True
        kind = event.get("type")
        if kind in ("execution_success", "execution_error", "execution_interrupted"):
            return seen
        if kind == "executing":
            node = data.get("node")
            if node is None:
                return seen
            label = graph.get(str(node), {}).get("class_type", f"nó {node}")
            progress(0.25, desc=f"ComfyUI · {label}")
        elif kind == "progress":
            current, total = data.get("value"), data.get("max")
            if isinstance(current, int) and isinstance(total, int) and 0 <= current <= total and total > 0:
                label = graph.get(str(data.get("node")), {}).get("class_type", "ComfyUI")
                progress(0.3 + 0.55 * current / total, desc=f"{label} · passo {current}/{total}")
    return seen


class Stalled(RuntimeError):
    pass


def collect(session, folder, job, timeout, progress=None, socket=None, graph=None, control=None, stall=900):
    """Wait for the prompt, reporting queue position, and stop early when the worker is gone, the prompt
    vanished, the user cancelled, or nothing has moved for `stall` seconds while it runs."""
    start = time.monotonic()
    deadline = start + timeout
    last_move = start
    next_report = start
    failures = 0
    absent = 0
    say = progress or (lambda *args, **kwargs: None)
    try:
        while time.monotonic() < deadline:
            if control is not None and control.cancelled:
                job.update(status="cancelado", message="Cancelado por você.")
                persist(folder, job)
                return job
            try:
                response = session.get(f"{SERVER}/history/{job['prompt_id']}", timeout=20)
                response.raise_for_status()
                history = response.json().get(job["prompt_id"])
                failures = 0
            except requests.RequestException as exc:
                failures += 1
                if failures >= 3:
                    tail = worker_log_tail()
                    raise WorkerDown("O worker ComfyUI parou de responder." + (f" Últimas linhas: {tail}" if tail else "")) from exc
                time.sleep(2)
                continue
            if history:
                break
            now = time.monotonic()
            try:
                where, position = queue_state(session, job["prompt_id"])
            except (requests.RequestException, ValueError):
                where, position = "running", 0
            if where is None:
                absent += 1
                if absent >= 3:
                    raise WorkerDown("O ComfyUI perdeu este job (não está na fila nem no histórico). "
                                           "Provável reinício do worker; envie de novo.")
            else:
                absent = 0
            if where == "pending":
                last_move = now
                if now >= next_report:
                    say(0.2, desc=f"Na fila do ComfyUI · posição {position} · {now - start:.0f} s")
                    next_report = now + 5
            elif where == "running" and now >= next_report:
                say(0.25, desc=f"ComfyUI executando · {now - start:.0f} s")
                next_report = now + 10
            delay = min(2, max(0, deadline - time.monotonic()))
            if socket is None:
                time.sleep(delay)
                if where == "running":
                    last_move = now  # sem WebSocket não há como medir; o limite geral continua valendo
            else:
                try:
                    if wait_events(socket, delay, job["prompt_id"], graph, say):
                        last_move = time.monotonic()
                except OSError:
                    socket = None
                    say(0.2, desc="WebSocket desconectado; acompanhando pelo histórico do ComfyUI")
            if where == "running" and socket is not None and time.monotonic() - last_move > stall:
                interrupt(job["prompt_id"])
                raise Stalled(f"Sem progresso há {stall // 60} min; o job foi interrompido. "
                              "Reduza a resolução ou use um modelo mais leve.")
        else:
            raise TimeoutError("O resultado ainda está no worker. Use Retomar coleta.")
        status = history.get("status") or {}
        if status.get("status_str") == "error":
            raise WorkerError(status.get("messages") or [])
        say(0.9, desc="Recebendo os arquivos do ComfyUI")
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
        interrupted = "interrupt" in str(exc).lower()
        job.update(status="cancelado" if interrupted and control is not None and control.cancelled else "falhou",
                   message=str(exc))
    except (Stalled, WorkerDown) as exc:
        job.update(status="travado" if isinstance(exc, Stalled) else "falhou", message=str(exc))
    except (requests.RequestException, OSError, ValueError) as exc:
        job.update(status="aguardando_coleta", message=str(exc))
    else:
        message = "" if job["results"] else "Workflow concluído sem arquivos de imagem, vídeo ou áudio."
        job.update(status="concluído", message=message)
    persist(folder, job)
    return job


class WorkerDown(RuntimeError):
    pass


def require_nodes(session, graph):
    response = session.get(f"{SERVER}/object_info", timeout=20)
    response.raise_for_status()
    schemas = response.json()
    missing = sorted({node["class_type"] for node in graph.values()} - schemas.keys())
    if missing:
        raise ValueError("Nós ausentes no ComfyUI local: " + ", ".join(missing))
    return schemas


def run(graph, output_dir, progress, files=None, prepare=None, title=None, control=None, family=None, stall=900):
    folder = Path(output_dir) / ("workflow_" + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    job = {"id": folder.name, "status": "preparando", "results": []}
    if title:
        job["title"] = title
    persist(folder, job)
    with requests.Session() as session, ExitStack() as connections:
        session.trust_env = False
        socket = None
        try:
            if family is not None and family != _last_family[0]:
                free_models(session)
            _last_family[0] = family
            if prepare:
                prepare(session, graph, progress)
            else:
                require_nodes(session, graph)
            if files:
                progress(0.08, desc="Enviando mídias ao ComfyUI")
                bind_uploads(session, graph, files)
            payload = {"prompt": graph}
            client_id = uuid.uuid4().hex
            socket = open_worker_socket(connections, client_id)
            if socket is None:
                progress(0.16, desc="WebSocket indisponível; acompanhando pelo histórico do ComfyUI")
            else:
                payload["client_id"] = client_id
            progress(0.17, desc="Enviando o grafo ao ComfyUI")
            job["status"] = "enviando"
            persist(folder, job)
            response = session.post(f"{SERVER}/prompt", json=payload, timeout=25)
            if not response.ok:
                job.update(status="falhou", message=response.text[:1600])
                persist(folder, job)
                return job
            job.update(status="enviado", prompt_id=response.json()["prompt_id"])
            if control is not None:
                control.prompt_id = job["prompt_id"]
        except (requests.RequestException, OSError, ValueError, KeyError) as exc:
            if job["status"] == "enviando":
                job.update(status="envio_indeterminado", message=f"{exc}. Verifique a fila no ComfyUI.")
            else:
                job.update(status="falhou", message=str(exc))
            persist(folder, job)
            return job
        persist(folder, job)
        progress(0.2, desc=f"Aguardando ComfyUI · {job['prompt_id']}")
        return collect(session, folder, job, 3600, progress, socket, graph, control, stall)


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
