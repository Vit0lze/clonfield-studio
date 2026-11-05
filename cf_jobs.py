"""Job queue for the Studio API: one GPU lane, a small CPU pool, persisted snapshots, cancel."""

import json
import threading
import time
import uuid
from collections import deque
from pathlib import Path

import cf_workflows as workflows

FINAL = ("concluído", "falhou", "cancelado", "travado")
KINDS = {".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image", ".avif": "image",
         ".bmp": "image", ".mp4": "video", ".webm": "video", ".mkv": "video", ".mov": "video",
         ".wav": "audio", ".mp3": "audio", ".flac": "audio", ".ogg": "audio", ".m4a": "audio"}


class JobError(Exception):
    def __init__(self, message, status="falhou"):
        super().__init__(message)
        self.status = status


class Job:
    def __init__(self, app, title, params, lane):
        self.id = "job_" + uuid.uuid4().hex[:16]
        self.app, self.title, self.params, self.lane = app, title, params, lane
        self.status, self.fraction, self.desc, self.message = "fila", 0.0, "Na fila", ""
        self.results, self.created = [], time.time()
        self.started = self.finished = None
        self.control = workflows.Control()
        self.version = 0
        self.lock = threading.Lock()

    def update(self, **fields):
        with self.lock:
            for key, value in fields.items():
                setattr(self, key, value)
            self.version += 1

    def snapshot(self, position=None):
        return {"id": self.id, "app": self.app, "title": self.title, "status": self.status,
                "fraction": round(self.fraction, 4), "desc": self.desc, "message": self.message,
                "results": self.results, "created": self.created, "started": self.started,
                "finished": self.finished, "lane": self.lane, "position": position,
                "params": self.params, "version": self.version}


class Context:
    def __init__(self, job, out_dir, manager):
        self.job, self.out_dir, self.manager = job, Path(out_dir), manager
        self.control = job.control

    def progress(self, fraction=None, desc=None, **_):
        # Downloads and ComfyUI waits report progress often, which makes this the cancellation point.
        self.check()
        fields = {}
        if fraction is not None:
            fields["fraction"] = min(1.0, max(0.0, float(fraction)))
        if desc:
            fields["desc"] = str(desc)
        self.job.update(**fields)

    def check(self):
        if self.control.cancelled:
            raise JobError("Cancelado por você.", "cancelado")


class Manager:
    def __init__(self, out_dir, cpu_workers=2):
        self.out_dir = Path(out_dir)
        self.store = self.out_dir / "jobs"
        self.store.mkdir(parents=True, exist_ok=True)
        self.jobs, self.order = {}, deque(maxlen=500)
        self.queues = {"gpu": deque(), "cpu": deque()}
        self.cv = threading.Condition()
        self.save_lock = threading.Lock()
        self.runners = {}
        self._load()
        threading.Thread(target=self._loop, args=("gpu",), daemon=True, name="cf-gpu").start()
        for index in range(cpu_workers):
            threading.Thread(target=self._loop, args=("cpu",), daemon=True, name=f"cf-cpu-{index}").start()

    def _load(self):
        for path in sorted(self.store.glob("job_*.json"), key=lambda p: p.stat().st_mtime):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                job = Job(data["app"], data["title"], data.get("params", {}), data.get("lane", "cpu"))
                job.id, job.created = data["id"], data["created"]
                job.status, job.fraction, job.desc = data["status"], data["fraction"], data["desc"]
                job.message, job.results = data.get("message", ""), data.get("results", [])
                job.started, job.finished = data.get("started"), data.get("finished")
                if job.status not in FINAL:
                    job.status, job.message = "falhou", "A sessão foi encerrada durante este job."
                self.jobs[job.id] = job
                self.order.append(job.id)
            except (OSError, ValueError, KeyError):
                continue

    def _save(self, job):
        """Persist a snapshot. Never raises: a full disk must not kill the worker lane."""
        with self.save_lock:
            path = self.store / f"{job.id}.json"
            tmp = path.with_suffix(f".{uuid.uuid4().hex[:6]}.tmp")
            try:
                tmp.write_text(json.dumps(job.snapshot(), ensure_ascii=False), encoding="utf-8")
                tmp.replace(path)
            except OSError:
                tmp.unlink(missing_ok=True)

    def submit(self, app, title, params, lane, runner):
        job = Job(app, title, params, lane)
        with self.cv:
            self.jobs[job.id] = job
            self.order.append(job.id)
            self.runners[job.id] = runner
            self.queues[lane].append(job.id)
            self.cv.notify_all()
        self._save(job)
        return job

    def position(self, job):
        queue = self.queues.get(job.lane, ())
        try:
            return list(queue).index(job.id) + 1
        except ValueError:
            return None

    def get(self, job_id):
        return self.jobs.get(job_id)

    def recent(self, limit=60):
        return [self.jobs[i] for i in reversed(self.order) if i in self.jobs][:limit]

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if not job or job.status in FINAL:
            return False
        with self.cv:
            if job.id in self.queues[job.lane]:
                self.queues[job.lane].remove(job.id)
                job.update(status="cancelado", message="Cancelado antes de começar.", finished=time.time(), desc="Cancelado")
                self._save(job)
                return True
        job.control.cancelled = True
        if job.lane == "gpu":
            workflows.interrupt(job.control.prompt_id)
        return True

    def clear_queue(self):
        cancelled = 0
        for job in list(self.jobs.values()):
            cancelled += bool(self.cancel(job.id))
        workflows.clear_orphans()
        return cancelled

    def _loop(self, lane):
        while True:
            with self.cv:
                while not self.queues[lane]:
                    self.cv.wait()
                job = self.jobs[self.queues[lane].popleft()]
                runner = self.runners.pop(job.id, None)
            if job.control.cancelled or runner is None:
                continue
            job.update(status="executando", started=time.time(), desc="Preparando")
            self._save(job)
            ctx = Context(job, self.out_dir, self)
            try:
                files = runner(ctx) or []
                results = self._publish(job, files)
                job.update(status="concluído", fraction=1.0, desc="Concluído", results=results)
            except JobError as exc:
                job.update(status=exc.status, message=str(exc), desc=exc.status.capitalize())
            except Exception as exc:  # a failed runner must never kill the lane
                import traceback
                traceback.print_exc()
                job.update(status="falhou", message=f"{type(exc).__name__}: {exc}", desc="Falhou")
            job.update(finished=time.time())
            self._save(job)

    def _publish(self, job, files):
        results = []
        root = self.out_dir.resolve()
        for entry in files:
            path = Path(entry)
            try:
                rel = path.resolve().relative_to(root)
            except ValueError:
                continue
            kind = KINDS.get(path.suffix.lower(), "file")
            results.append({"path": rel.as_posix(), "name": path.name, "kind": kind, "size": path.stat().st_size})
        return results
