"""The text model must not stay loaded while a GPU job runs (a resident 9B + Wan A14B killed the ComfyUI worker on the 12.7 GB Colab).
Real parts: a real HTTP server that answers /props like llama-server's sleep mode, and the real job manager running real jobs.
The model itself is not involved: this proves the scheduling, not the memory saving (that is measured on the T4)."""
import http.server
import json
import threading
import time

import pytest

import cf_agent
import cf_jobs
import cf_llama
import cf_llm


class PropsServer:
    """Answers /health and /props {"is_sleeping": ...} like llama-server --sleep-idle-seconds; `asleep` is flipped by the test."""

    def __init__(self, asleep=False, report=True):
        self.asleep, self.report = asleep, report
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"is_sleeping": outer.asleep} if outer.report else {"total_slots": 4}).encode() if self.path == "/props" else b"ok"
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def close(self):
        self.http.shutdown()


@pytest.fixture()
def llama(monkeypatch):
    server = PropsServer()
    monkeypatch.setenv("CLONFIELD_LLAMA_URL", server.url)
    monkeypatch.setenv("CLONFIELD_LLM_BACKEND", "llama")
    cf_llm._health.update(at=0.0, pick=None, key=None)
    yield server
    server.close()
    cf_llm._health.update(at=0.0, pick=None, key=None)
    cf_llm.set_gpu_guard(lambda: False)


def test_server_command_asks_llama_server_to_sleep_when_idle(tmp_path, monkeypatch):
    monkeypatch.delenv("CLONFIELD_LLM_SLEEP", raising=False)
    command = cf_llama.server_command(tmp_path, binary="/x/llama-server")
    assert command[command.index("--sleep-idle-seconds") + 1] == "30"
    monkeypatch.setenv("CLONFIELD_LLM_SLEEP", "0")
    assert "--sleep-idle-seconds" not in cf_llama.server_command(tmp_path, binary="/x/llama-server")
    assert cf_llama.server_command(tmp_path, binary="/x/llama-server", sleep_idle=5)[-1] == "5"


def test_release_waits_until_the_server_reports_it_is_asleep(llama):
    llama.asleep = False
    threading.Timer(0.6, lambda: setattr(llama, "asleep", True)).start()
    started = time.monotonic()
    assert cf_llm.release_gpu(timeout=10, poll=0.1) is True
    assert 0.5 <= time.monotonic() - started < 5


def test_release_reports_a_model_that_never_unloads(llama):
    llama.asleep = False
    assert cf_llm.release_gpu(timeout=0.5, poll=0.1) is False


def test_release_does_not_conclude_anything_from_a_backend_that_cannot_report(monkeypatch):
    server = PropsServer(report=False)
    monkeypatch.setenv("CLONFIELD_LLAMA_URL", server.url)
    monkeypatch.setenv("CLONFIELD_LLM_BACKEND", "llama")
    cf_llm._health.update(at=0.0, pick=None, key=None)
    try:
        assert cf_llm.release_gpu(timeout=0.5, poll=0.1) is None
    finally:
        server.close()
        cf_llm._health.update(at=0.0, pick=None, key=None)


def test_nothing_to_release_when_no_text_model_runs(monkeypatch):
    monkeypatch.setenv("CLONFIELD_LLAMA_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("CLONFIELD_LLM_BACKEND", "llama")
    cf_llm._health.update(at=0.0, pick=None, key=None)
    assert cf_llm.release_gpu(timeout=0.5) is True
    cf_llm._health.update(at=0.0, pick=None, key=None)


def wait_final(job, seconds=15):
    end = time.monotonic() + seconds
    while job.status not in ("concluído", "falhou", "cancelado") and time.monotonic() < end:
        time.sleep(0.05)
    return job.status


def test_a_gpu_job_unloads_the_text_model_first_and_blocks_it_while_it_runs(tmp_path):
    manager = cf_jobs.Manager(tmp_path, cpu_workers=1)
    log = []
    manager.before_gpu = lambda: log.append(("unload", manager.gpu_active)) or True
    cf_llm.set_gpu_guard(lambda: manager.gpu_active)
    try:
        def runner(ctx):
            log.append(("run", manager.gpu_active))
            with pytest.raises(cf_llm.LLMError, match="GPU está ocupada"):
                cf_llm.generate("s", "u")
            return []
        job = manager.submit("t", "gpu job", {}, "gpu", runner)
        assert wait_final(job) == "concluído", job.message
        assert log == [("unload", True), ("run", True)]  # the guard is already up while the model is being unloaded
        assert manager.gpu_active is False
        cf_llm.ensure_gpu_free()  # and the text model is allowed again after the job
    finally:
        cf_llm.set_gpu_guard(lambda: False)


def test_a_gpu_job_does_not_start_while_the_text_model_is_still_loaded(tmp_path):
    manager = cf_jobs.Manager(tmp_path, cpu_workers=1)
    manager.before_gpu = lambda: False
    ran = []
    job = manager.submit("t", "gpu job", {}, "gpu", lambda ctx: ran.append(1) or [])
    assert wait_final(job) == "falhou"
    assert "continua carregado" in job.message and not ran and manager.gpu_active is False


def test_cpu_jobs_neither_unload_the_model_nor_raise_the_gpu_flag(tmp_path):
    manager = cf_jobs.Manager(tmp_path, cpu_workers=1)
    called, seen = [], []
    manager.before_gpu = lambda: called.append(1) or True
    job = manager.submit("t", "cpu job", {}, "cpu", lambda ctx: seen.append(manager.gpu_active) or [])
    assert wait_final(job) == "concluído" and not called and seen == [False]


def test_the_agent_provider_is_refused_while_a_gpu_job_runs(monkeypatch):
    cf_llm.set_gpu_guard(lambda: True)
    try:
        with pytest.raises(cf_agent.AgentError, match="GPU está ocupada"):
            cf_agent.OpenAICompatProvider(base_url="http://127.0.0.1:9").step("s", [dict(role="user", text="oi")], [])
    finally:
        cf_llm.set_gpu_guard(lambda: False)


def test_the_agent_turn_ends_with_a_fixed_answer_once_it_has_started_a_gpu_job():
    """Scripted model, clearly labelled: it asks for one tool call; after the tool reports a queued GPU job the loop must NOT call the model again."""
    class Scripted:
        name = "script"
        calls = 0

        def step(self, system, messages, tools):
            Scripted.calls += 1
            return dict(text="", calls=[dict(id="1", name="start", args={})], model="x")

    toolbox = type("TB", (), {"tools": [dict(name="start", description="d", parameters=dict(type="object", properties={}))],
                              "by_name": {"start": dict(fn=lambda: dict(status="queued", job_id="job_1", lane="gpu"), parameters=dict(properties={}))}})()
    out = cf_agent.run_agent(Scripted(), toolbox, "gere um vídeo")
    assert Scripted.calls == 1 and out["stop"] == "job de GPU iniciado" and "descarregado" in out["final"]
