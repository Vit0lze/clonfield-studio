"""Restart the ComfyUI worker from the Studio.

Measured on the Colab T4 (12.7 GB of RAM): one Wan 5B job leaves the worker process at 6.5-9 GB resident, and `POST /free` does not give that
memory back to the system (the allocator keeps it), so the next big model (the Wan A14B experts, ~9 GB each) kills the worker. A fresh process
starts at ~1.3 GB. The Studio and the worker run on the same machine, so the Studio copies the worker's own command line, working folder and
environment while it is alive (in memory only, never written to disk: the environment can hold tokens) and can start it again the same way.

It also revives a worker that died: the notebook cell that started it is not needed again.

One owner at a time (V9-P0). Every caller that talks to the worker for a job (`cf_workflows.run`, the SeedVR2 runner, the A14B's two stages)
and every restart holds `hold()`. The Studio's GPU lane, the classic Gradio mode (which does not go through `cf_jobs.Manager`) and a restart
from another thread therefore never overlap: a restart waits for the running prompt instead of killing it. The lock is reentrant, so a job
that restarts the worker itself (bloated worker, A14B between experts) keeps ownership."""
import os
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import requests

_saved = {}  # argv, cwd, env of the last worker seen alive. Memory only.
_lock = threading.RLock()
_owner = {"thread": None, "depth": 0}


class WorkerUnavailable(RuntimeError):
    """The worker is down and could not be brought back, or a restart did not bring it back."""


DOWN_HELP = "O worker do ComfyUI não responde e o Studio não sabe como reiniciá-lo (ele não foi visto vivo nesta sessão). Rode a célula do ComfyUI no Colab."


@contextmanager
def hold(progress=None, poll=2.0):
    """Own the worker for the duration of the block. When another thread owns it, say so through `progress(text)` and wait.
    `progress` may raise (a cancelled job's context does): the wait then stops without taking the worker."""
    if not _lock.acquire(blocking=False):
        if progress:
            progress("Aguardando outro job do ComfyUI terminar")
        while not _lock.acquire(timeout=poll):
            if progress:
                progress("Aguardando outro job do ComfyUI terminar")
    _owner["thread"] = threading.get_ident()
    _owner["depth"] += 1
    try:
        yield
    finally:
        _owner["depth"] -= 1
        if not _owner["depth"]:
            _owner["thread"] = None
        _lock.release()


def busy():
    """True while some caller owns the worker (a job is talking to it or it is being restarted)."""
    return _owner["thread"] is not None


def port_of(url):
    try:
        return int(url.rsplit(":", 1)[1].split("/")[0])
    except (IndexError, ValueError):
        return None


def find(port=None):
    """(pid, argv) of the ComfyUI worker (`python ... main.py --listen ... --port N`), or None. With `port`, only the process started for THAT port:
    the Studio never touches another process that merely looks alike."""
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            argv = [part.decode("utf-8", "replace") for part in (entry / "cmdline").read_bytes().split(b"\0") if part]
        except OSError:
            continue
        if argv and "python" in Path(argv[0]).name and any(Path(part).name == "main.py" for part in argv[1:4]) and "--listen" in argv and "--port" in argv:
            if port is not None and argv[argv.index("--port") + 1:argv.index("--port") + 2] != [str(port)]:
                continue
            return int(entry.name), argv
    return None


def rss_gb(pid):
    try:
        for line in (Path("/proc") / str(pid) / "status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024**2, 2)
    except (OSError, ValueError, IndexError):
        pass
    return None


def capture(url=None):
    """Remember how the live worker was started. False when there is none to look at."""
    found = find(port_of(url) if url else None)
    if found is None:
        return False
    pid, argv = found
    try:
        raw = (Path("/proc") / str(pid) / "environ").read_bytes().decode("utf-8", "replace").split("\0")
        env = dict(item.split("=", 1) for item in raw if "=" in item)
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return False
    _saved.update(argv=argv, cwd=cwd, env=env)
    return True


def forget():
    _saved.clear()


def up(url, timeout=3):
    try:
        return requests.get(url + "/system_stats", timeout=timeout).status_code == 200
    except requests.RequestException:
        return False


def gone(pid):
    """True when the process no longer exists or is a zombie waiting for its parent."""
    try:
        for line in (Path("/proc") / str(pid) / "status").read_text().splitlines():
            if line.startswith("State:"):
                return "Z" in line.split(":", 1)[1].split()[0]
    except OSError:
        return True
    return False


def stop(pid, grace=30):
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and not gone(pid):
        time.sleep(0.5)
    if not gone(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        for _ in range(20):
            if gone(pid):
                break
            time.sleep(0.5)


def restart(url, wait=240, progress=None):
    """Stop the worker (when it runs) and start it again with the command it was started with. True once it answers.
    Waits for the current owner first: a restart never lands in the middle of someone else's prompt."""
    with hold(progress):
        return _restart(url, wait, progress)


def _restart(url, wait, progress):
    capture(url)  # refresh while it is alive; a dead worker keeps the copy taken earlier
    if not _saved:
        return False
    found = find(port_of(url))
    if found is not None:
        if progress:
            progress("Reiniciando o ComfyUI para zerar a memória")
        stop(found[0])
    log = _saved["env"].get("CLONFIELD_COMFY_LOG")
    out = open(log, "ab") if log else subprocess.DEVNULL
    try:
        subprocess.Popen(_saved["argv"], cwd=_saved["cwd"], env=_saved["env"], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        if out is not subprocess.DEVNULL:
            out.close()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if up(url):
            return True
        time.sleep(2)
    return False


def ensure_up(url, progress=None, wait=240):
    """Before a job: remember the worker while it answers, and bring it back when it does not (and its command is known).
    True when it answers; False when it is down (never seen alive, or the revive did not bring it back)."""
    if up(url):
        capture(url)
        return True
    if _saved:
        return restart(url, wait=wait, progress=progress)
    return False


def restart_if_bloated(url, limit_gb=3.0, progress=None, wait=240):
    """Restart when the worker's resident memory is above `limit_gb`. True when it was restarted, False when it was not needed.
    Raises WorkerUnavailable when the restart was needed and the worker did not come back: the caller must not go on against it."""
    found = find(port_of(url))
    if found is None:
        return False
    size = rss_gb(found[0])
    if size is not None and size > limit_gb:
        if restart(url, wait=wait, progress=progress):
            return True
        raise WorkerUnavailable(f"O ComfyUI estava com {size:g} GB de RAM, foi reiniciado e não voltou em {wait} s." + (
            "" if _saved else " O Studio não tinha o comando do worker para iniciá-lo de novo: rode a célula do ComfyUI no Colab."))
    return False
