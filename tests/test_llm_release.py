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


class Scripted:
    """Scripted model, clearly labelled: it asks for one tool call per step."""
    name = "script"

    def __init__(self, refuse_after_tool=False):
        self.calls, self.refuse = 0, refuse_after_tool

    def step(self, system, messages, tools):
        self.calls += 1
        if self.calls > 1 and self.refuse:
            raise cf_agent.AgentError("A GPU está ocupada com um job; o modelo de texto fica descarregado enquanto ele roda.")
        return dict(text="", calls=[dict(id="1", name="start", args={})], model="x")


def toolbox(result, on_call=None):
    def start():
        if on_call:
            on_call()
        return result
    return type("TB", (), {"tools": [dict(name="start", description="d", parameters=dict(type="object", properties={}))],
                           "by_name": {"start": dict(fn=start, parameters=dict(properties={}))}})()


def test_the_agent_turn_ends_with_a_fixed_answer_once_a_tool_has_started_a_gpu_job_whatever_shape_the_tool_returns():
    state = {"busy": False}
    cf_llm.set_gpu_guard(lambda: state["busy"])
    try:
        model = Scripted()
        out = cf_agent.run_agent(model, toolbox({"started": True, "jobs": ["job_1"]}, on_call=lambda: state.update(busy=True)), "gere um vídeo")
        assert model.calls == 1 and out["stop"] == "job de GPU iniciado" and "descarregado" in out["final"]
    finally:
        cf_llm.set_gpu_guard(lambda: False)


def test_a_refusal_right_after_the_tool_is_read_as_the_gpu_job_having_started_not_as_a_failure():
    """The GPU lane picks the job up in its own thread, so the flag can rise between the tool call and the next model step."""
    readings = iter([False, True])  # 1st look (right after the tool): not up yet; 2nd (after the model refused): up
    cf_llm.set_gpu_guard(lambda: next(readings))
    try:
        model = Scripted(refuse_after_tool=True)
        out = cf_agent.run_agent(model, toolbox({"ok": True}), "gere um vídeo")
        assert out["stop"] == "job de GPU iniciado" and model.calls == 2
    finally:
        cf_llm.set_gpu_guard(lambda: False)


def test_a_refusal_without_a_gpu_job_is_a_real_error_and_is_raised():
    cf_llm.set_gpu_guard(lambda: False)
    with pytest.raises(cf_agent.AgentError, match="GPU está ocupada"):
        cf_agent.run_agent(Scripted(refuse_after_tool=True), toolbox({"ok": True}), "gere um vídeo")


def test_comfyui_is_asked_to_free_its_models_right_before_a_sleeping_text_model_is_woken(llama):
    freed = []
    cf_llm.set_comfy_release(lambda: freed.append(1))
    try:
        llama.asleep = False
        cf_llm.ensure_gpu_free()
        assert freed == []  # awake already: nothing to make room for
        llama.asleep = True
        cf_llm.ensure_gpu_free()
        assert freed == [1]
        cf_llm.set_gpu_guard(lambda: True)
        with pytest.raises(cf_llm.LLMError):
            cf_llm.ensure_gpu_free()
        assert freed == [1]  # while a job runs the model is refused, ComfyUI is left alone
    finally:
        cf_llm.set_gpu_guard(lambda: False)
        cf_llm.set_comfy_release(None)


def test_the_api_wires_a_real_comfy_release_that_posts_free_to_the_worker(tmp_path, monkeypatch):
    """build_app registers the hook; calling it must reach ComfyUI's /free (a wrong module name would only show up at runtime)."""
    import cf_api
    import cf_workflows
    posted = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            posted.append((self.path, json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(cf_workflows, "SERVER", f"http://127.0.0.1:{server.server_address[1]}")
    try:
        cf_api.build_app(tmp_path, tmp_path / "out", lambda t: True, "s")
        cf_llm._gpu["free_comfy"]()
    finally:
        server.shutdown()
        cf_llm.set_comfy_release(None)
        cf_llm.set_gpu_guard(lambda: False)
    assert posted == [("/free", {"unload_models": True, "free_memory": True})]
