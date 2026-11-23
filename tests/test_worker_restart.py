"""The Studio restarts the ComfyUI worker itself. REAL processes: a tiny stand-in `main.py --listen --port N` HTTP server is started, found, restarted,
killed and revived. It proves the process handling, NOT that ComfyUI gives its memory back (that is measured on the Colab).

Safety: every lookup and every kill is scoped to the test's OWN free port, so no other process that merely looks alike can be touched."""
import os
import signal
import socket
import subprocess
import sys
import time

import pytest

import cf_worker

SERVER = '''
import http.server, sys
port = int(sys.argv[sys.argv.index("--port") + 1])
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
'''


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture()
def worker(tmp_path):
    (tmp_path / "main.py").write_text(SERVER)
    port = free_port()
    env = dict(os.environ, CLONFIELD_COMFY_LOG=str(tmp_path / "comfy.log"))
    proc = subprocess.Popen([sys.executable, "main.py", "--listen", "127.0.0.1", "--port", str(port)], cwd=tmp_path, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if cf_worker.up(url):
            break
        time.sleep(0.1)
    cf_worker.forget()
    yield proc, url, port
    cf_worker.forget()
    found = cf_worker.find(port)  # only the process started for this test's port
    if found:
        os.kill(found[0], signal.SIGKILL)
    proc.kill()
    proc.wait()


def test_the_worker_is_found_remembered_and_restarted_with_its_own_command(worker):
    proc, url, port = worker
    assert cf_worker.ensure_up(url) is True and cf_worker.find(port)[0] == proc.pid
    assert cf_worker.restart(url, wait=30) is True
    assert cf_worker.find(port)[0] != proc.pid and cf_worker.up(url)
    proc.wait(timeout=10)  # the old one really exited


def test_a_dead_worker_is_revived_from_the_copy_taken_while_it_was_alive(worker):
    proc, url, port = worker
    assert cf_worker.ensure_up(url) is True  # remembers it
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait()
    assert not cf_worker.up(url)
    assert cf_worker.ensure_up(url, progress=lambda text: None) is True and cf_worker.up(url)


def test_nothing_is_started_when_the_worker_was_never_seen(worker):
    proc, url, port = worker
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait()
    cf_worker.forget()
    assert cf_worker.ensure_up(url) is False and not cf_worker.up(url)


def test_a_bloated_worker_is_restarted_and_a_small_one_is_left_alone(worker):
    proc, url, port = worker
    cf_worker.ensure_up(url)
    assert cf_worker.restart_if_bloated(url, limit_gb=1000) is False and cf_worker.find(port)[0] == proc.pid
    assert cf_worker.restart_if_bloated(url, limit_gb=0.0001) is True and cf_worker.find(port)[0] != proc.pid


def test_a_look_alike_on_another_port_is_never_found(worker):
    proc, url, port = worker
    assert cf_worker.find(port + 1) is None or cf_worker.find(port + 1)[0] != proc.pid
