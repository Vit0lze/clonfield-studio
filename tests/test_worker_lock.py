"""V9-P0: one owner for the ComfyUI worker. Two callers of `cf_workflows.run` (the Studio's GPU lane and the classic Gradio mode, which does
not go through `cf_jobs.Manager`) must never restart the worker under each other's running prompt.

FAKE WORKER, labelled: a tiny `main.py --listen --port N` HTTP server that speaks the handful of ComfyUI routes `cf_workflows.run` uses
(/system_stats, /object_info, /prompt, /queue, /history, /view, /free, /interrupt). It keeps its prompts in memory, so a restarted process
forgets them exactly like a restarted ComfyUI. It is a REAL process found and restarted through /proc by `cf_worker`; it proves the
locking and the restart handling, NOT anything about ComfyUI's memory (that is measured on the Colab T4).
Every lookup and kill is scoped to this test's own free port."""
import os
import signal
import socket
import subprocess
import sys
import threading
import time

import pytest

import cf_jobs
import cf_worker
import cf_workflows

FAKE_COMFY = r'''
import http.server, json, os, sys, time, uuid
port = int(sys.argv[sys.argv.index("--port") + 1])
prompts = {}
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360f8ffff3f0005fe02fea7d6a0b40000000049454e44ae426082")
class H(http.server.BaseHTTPRequestHandler):
    def reply(self, data, kind="application/json"):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(200); self.send_header("Content-Type", kind); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/object_info":
            return self.reply({"FakeNode": {}})
        if path == "/queue":
            return self.reply({"queue_running": [[0, pid] for pid in prompts if not os.path.exists("release")], "queue_pending": []})
        if path.startswith("/history/"):
            pid = path.rsplit("/", 1)[1]
            if pid in prompts and os.path.exists("release"):
                return self.reply({pid: {"status": {"status_str": "success"},
                                         "outputs": {"9": {"images": [{"filename": "fake.png", "subfolder": "", "type": "output"}]}}}})
            return self.reply({})
        if path == "/view":
            return self.reply(PNG, "image/png")
        return self.reply({})
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        if self.path == "/prompt":
            pid = uuid.uuid4().hex
            prompts[pid] = True
            with open("prompts.log", "a") as log:
                log.write(f"{os.getpid()} {pid}\n")
            while os.path.exists("slow_prompt") and not os.path.exists("answer"):  # lets a test cancel while POST /prompt is in flight
                time.sleep(0.05)
            return self.reply({"prompt_id": pid})
        if self.path == "/interrupt":
            with open("interrupts.log", "a") as log:
                log.write((json.loads(body or b"{}").get("prompt_id") or "ALL") + "\n")
        return self.reply({})
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
'''

GRAPH = {"1": {"class_type": "FakeNode", "inputs": {}}}


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture()
def comfy(tmp_path, monkeypatch):
    home = tmp_path / "worker"
    home.mkdir()
    (home / "main.py").write_text(FAKE_COMFY)
    port = free_port()
    proc = subprocess.Popen([sys.executable, "main.py", "--listen", "127.0.0.1", "--port", str(port)], cwd=home,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if cf_worker.up(url):
            break
        time.sleep(0.1)
    monkeypatch.setattr(cf_workflows, "SERVER", url)
    monkeypatch.setattr(cf_workflows, "open_worker_socket", lambda *a: None)  # the fake speaks plain HTTP only: follow by history
    cf_worker.forget()
    yield home, url, port
    cf_worker.forget()
    found = cf_worker.find(port)
    if found:
        os.kill(found[0], signal.SIGKILL)
    proc.kill()
    proc.wait()


def wait_for(predicate, seconds=30.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_a_second_caller_never_restarts_the_worker_under_a_running_prompt(comfy, tmp_path, monkeypatch):
    """Reproduces the audit's P0: job A (say, a Studio job) is waiting on its prompt; caller B (the classic mode) starts with a worker over
    the RAM limit. Before the fix B restarted the worker at once and A's prompt vanished ("O ComfyUI perdeu este job")."""
    home, url, port = comfy
    first_pid = cf_worker.find(port)[0]
    out = tmp_path / "out"
    out.mkdir()
    seen_a, seen_b, result = [], [], {}

    monkeypatch.setenv("CLONFIELD_WORKER_RESTART_GB", "1000")
    a = threading.Thread(target=lambda: result.__setitem__("a", cf_workflows.run(dict(GRAPH), out, lambda *x, desc=None, **k: seen_a.append(desc))))
    a.start()
    assert wait_for(lambda: any(d and d.startswith("Aguardando ComfyUI") for d in seen_a)), seen_a

    monkeypatch.setenv("CLONFIELD_WORKER_RESTART_GB", "0.0001")  # B finds the worker "bloated" and wants to restart it
    b = threading.Thread(target=lambda: result.__setitem__("b", cf_workflows.run(dict(GRAPH), out, lambda *x, desc=None, **k: seen_b.append(desc))))
    b.start()
    time.sleep(4)  # long enough for an unguarded restart (SIGTERM + new process) to happen
    assert cf_worker.find(port)[0] == first_pid, "the worker was restarted while job A was still waiting for its prompt"
    assert any(d and "Aguardando" in d and "outro job" in d for d in seen_b), seen_b  # B says why it waits

    (home / "release").write_text("go")
    a.join(60)
    b.join(120)
    assert result["a"]["status"] == "concluído" and result["a"]["results"], result["a"]
    assert result["b"]["status"] == "concluído" and result["b"]["results"], result["b"]
    assert cf_worker.find(port)[0] != first_pid  # B did restart, after A was done
    lines = (home / "prompts.log").read_text().split()
    assert lines[0] == str(first_pid) and lines[2] != str(first_pid)  # A ran on the old process, B on the new one


def test_restart_holds_the_same_ownership(comfy, tmp_path):
    """A direct `cf_worker.restart` (the A14B between its two experts) from another thread also waits for the running owner."""
    home, url, port = comfy
    cf_worker.ensure_up(url)
    first_pid = cf_worker.find(port)[0]
    entered, release, done = threading.Event(), threading.Event(), []

    def owner():
        with cf_worker.hold():
            entered.set()
            release.wait(30)

    t = threading.Thread(target=owner)
    t.start()
    entered.wait(10)
    assert cf_worker.busy()
    r = threading.Thread(target=lambda: done.append(cf_worker.restart(url, wait=30)))
    r.start()
    time.sleep(2)
    assert cf_worker.find(port)[0] == first_pid and not done
    release.set()
    t.join(10)
    r.join(60)
    assert done == [True] and cf_worker.find(port)[0] != first_pid and not cf_worker.busy()


def test_a_failed_restart_is_reported_and_the_job_does_not_go_on(comfy, tmp_path):
    """`restart_if_bloated` used to return False both for "not needed" and "tried and failed", and `run` ignored it."""
    home, url, port = comfy
    cf_worker.ensure_up(url)  # remembers `python main.py ...` in that folder
    (home / "main.py").write_text("import sys\nsys.exit(3)\n")  # the next start dies at once
    with pytest.raises(cf_worker.WorkerUnavailable, match="não voltou"):
        cf_worker.restart_if_bloated(url, 0.0001, wait=4)
    assert not cf_worker.up(url)


def test_a_worker_that_is_down_and_was_never_seen_fails_the_run_with_the_reason(comfy, tmp_path):
    home, url, port = comfy
    os.kill(cf_worker.find(port)[0], signal.SIGKILL)
    assert wait_for(lambda: not cf_worker.up(url), 10)
    cf_worker.forget()
    out = tmp_path / "out"
    out.mkdir()
    job = cf_workflows.run(dict(GRAPH), out, lambda *a, **k: None)
    assert job["status"] == "falhou" and "ComfyUI" in job["message"] and "célula" in job["message"], job
    assert "prompt_id" not in job


def test_the_text_model_guard_also_sees_a_classic_mode_job(comfy):
    """The LLM guard looked only at the Manager's GPU lane; a classic-mode prompt now counts as a busy GPU too."""
    with cf_worker.hold():
        assert cf_worker.busy()
    assert not cf_worker.busy()


# --- cf_jobs: a job is "concluído" only with a result it can show (V9-P0, audit cf_jobs.py:178-180) ---

def wait_final(job, seconds=20):
    wait_for(lambda: job.status in cf_jobs.FINAL, seconds)
    return job.status


def test_a_media_job_that_returns_nothing_fails(tmp_path):
    manager = cf_jobs.Manager(tmp_path, cpu_workers=1)
    for runner in (lambda ctx: [], lambda ctx: None):
        job = manager.submit("t", "vazio", {}, "cpu", runner)
        assert wait_final(job) == "falhou" and "nenhum arquivo" in job.message and job.results == []


def test_files_outside_the_output_folder_are_not_a_result(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.png"
    outside.write_bytes(b"x")
    try:
        manager = cf_jobs.Manager(tmp_path / "out", cpu_workers=1)
        job = manager.submit("t", "fora", {}, "cpu", lambda ctx: [outside])
        assert wait_final(job) == "falhou" and "fora da pasta" in job.message
    finally:
        outside.unlink()


def test_a_job_whose_result_is_an_effect_says_so(tmp_path):
    manager = cf_jobs.Manager(tmp_path, cpu_workers=1)
    job = manager.submit("t", "instalar", {}, "cpu", lambda ctx: cf_jobs.Effect("Instalado e conferido (SHA-256)."))
    assert wait_final(job) == "concluído" and job.results == [] and job.message == "Instalado e conferido (SHA-256)."


def test_a_media_job_with_a_real_file_still_succeeds(tmp_path):
    manager = cf_jobs.Manager(tmp_path, cpu_workers=1)
    target = tmp_path / "a.png"
    target.write_bytes(b"png")
    job = manager.submit("t", "ok", {}, "cpu", lambda ctx: [target])
    assert wait_final(job) == "concluído" and [r["name"] for r in job.results] == ["a.png"]


def test_cancelling_a_job_that_waits_for_the_worker_never_interrupts_the_owner(comfy, tmp_path, monkeypatch):
    """Review finding: a GPU job still waiting on `hold()` has no prompt id; cancelling it used to send a bare /interrupt, which in
    ComfyUI 0.44 stops WHATEVER prompt runs (server.py post_interrupt: targeted only when prompt_id is given)."""
    home, url, port = comfy
    monkeypatch.setenv("CLONFIELD_WORKER_RESTART_GB", "1000")
    out = tmp_path / "out"
    out.mkdir()
    seen_a, result = [], {}
    a = threading.Thread(target=lambda: result.__setitem__("a", cf_workflows.run(dict(GRAPH), out, lambda *x, desc=None, **k: seen_a.append(desc))))
    a.start()
    assert wait_for(lambda: any(d and d.startswith("Aguardando ComfyUI") for d in seen_a)), seen_a

    manager = cf_jobs.Manager(out, cpu_workers=1)
    job = manager.submit("t", "espera", {}, "gpu", lambda ctx: cf_apps_collect(ctx, cf_workflows.run(dict(GRAPH), ctx.out_dir, ctx.progress, control=ctx.control)))
    assert wait_for(lambda: "outro job" in (job.desc or ""), 20), job.desc
    assert manager.cancel(job.id)
    assert wait_final(job) == "cancelado", job.message
    assert not (home / "interrupts.log").exists()  # the owner's prompt was not touched
    (home / "release").write_text("go")
    a.join(60)
    assert result["a"]["status"] == "concluído" and result["a"]["results"]
    assert len((home / "prompts.log").read_text().split()) == 2  # only A ever reached the worker


def test_a_cancel_that_arrives_while_the_prompt_is_being_posted_still_stops_that_prompt(comfy, tmp_path, monkeypatch):
    """Owner's review race: the cancel lands after POST /prompt left but before its reply (no prompt_id yet), so Control.cancel sends
    nothing. Before the fix the run then returned «cancelado» and released the lock while its prompt kept running on the worker."""
    home, url, port = comfy
    monkeypatch.setenv("CLONFIELD_WORKER_RESTART_GB", "1000")
    out = tmp_path / "out"
    out.mkdir()
    (home / "slow_prompt").write_text("1")
    control, result = cf_workflows.Control(), {}
    a = threading.Thread(target=lambda: result.__setitem__("a", cf_workflows.run(dict(GRAPH), out, lambda *x, **k: None, control=control)))
    a.start()
    assert wait_for(lambda: (home / "prompts.log").exists())  # the worker has the prompt; its reply is held back
    control.cancel()
    assert not (home / "interrupts.log").exists()  # nothing to target yet, and a bare /interrupt would hit anyone's prompt
    (home / "answer").write_text("1")
    a.join(30)
    pid = (home / "prompts.log").read_text().split()[1]
    assert result["a"]["status"] == "cancelado"
    assert (home / "interrupts.log").read_text().split() == [pid]  # our own prompt, by id, never a global interrupt
    assert not cf_worker.busy()


def test_reopening_a_seedvr2_upscale_waits_for_the_worker_owner(comfy, tmp_path, monkeypatch):
    """Owner's review race: «Retomar» on an upscale that ran out of VRAM on the 7B posts the 3B fallback prompt; it used to do that
    outside cf_worker.hold(), so it could land while another job owned the worker."""
    import json as _json
    import cf_seedvr2
    home, url, port = comfy
    monkeypatch.setattr(cf_seedvr2, "SERVER", url)
    folder = tmp_path / "out" / "seedvr2_reopen"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(_json.dumps({"id": folder.name, "kind": "Imagem", "model": "7B", "status": "enviado",
                                                  "prompt_id": "gone", "scale": 2.0, "seed": 1, "tile": 512}))
    seen, result = [], {}
    with cf_worker.hold():
        b = threading.Thread(target=lambda: result.__setitem__("b", cf_seedvr2.reopen(tmp_path / "out", folder.name,
                                                                                     lambda *x, desc=None, **k: seen.append(desc))))
        b.start()
        assert wait_for(lambda: any(d and "outro job" in d for d in seen), 10), seen
        assert b.is_alive()  # it waits instead of talking to the worker under the owner
    b.join(60)
    assert not b.is_alive() and result["b"]["status"] in ("aguardando_coleta", "falhou")


def cf_apps_collect(ctx, job):
    import cf_apps
    return cf_apps.collect_job(ctx, job)


def test_a_dag_whose_sinks_are_only_text_or_json_is_an_explicit_outcome(tmp_path):
    """Review finding: `value` artifacts (text/JSON, no file) are legitimate DAG results; they must not fail as "no file"."""
    import cf_dag
    text_run = {"final": {"n": {"texts": [dict(type="text", path=None, value="a"), dict(type="text", path=None, value="b")]}}}
    json_run = {"final": {"n": {"plan": dict(type="json", path=None, value={"w": 1})}}}
    empty_run = {"final": {"n": {"texts": []}}}
    t, j = cf_dag.job_result(text_run), cf_dag.job_result(json_run)
    assert isinstance(t, cf_jobs.Effect) and t.kind == "text" and "2 valor(es)" in t.note
    assert isinstance(j, cf_jobs.Effect) and j.kind == "json"
    assert cf_dag.job_result(empty_run) == []
    target = tmp_path / "x.png"
    target.write_bytes(b"p")
    assert cf_dag.job_result({"final": {"n": {"image": dict(type="image", path=str(target), value=None)}}}) == [target]
    with pytest.raises(ValueError):
        cf_jobs.Effect("x", kind="video")
