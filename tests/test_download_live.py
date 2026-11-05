"""Real Hugging Face downloads (needs HF_TOKEN). Z-Image-Turbo's VAE is 335 MB with a published SHA-256."""

import hashlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import cf_download

REPO, REV = "Comfy-Org/Z-Image-Turbo", "6fc90a3b1b653e935a0d175e260736de25b84df5"
FILE = "split_files/vae/ae.safetensors"
SHA = "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38"
pytestmark = pytest.mark.skipif(not os.environ.get("HF_TOKEN"), reason="HF_TOKEN ausente")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(1 << 22):
            digest.update(block)
    return digest.hexdigest()


def test_resume_after_kill_matches_published_sha(tmp_path):
    target = tmp_path / "ae.safetensors"
    code = ("import cf_download,os;cf_download.fetch_hf(%r,%r,%r,revision=%r,token=os.environ['HF_TOKEN'])"
            % (REPO, FILE, str(target), REV))
    child = subprocess.Popen([sys.executable, "-c", code], cwd=Path(__file__).parent.parent)
    partial = target.with_suffix(".safetensors.part")
    for _ in range(100):
        if partial.exists() and partial.stat().st_size > 20 * 1024**2:
            break
        time.sleep(0.2)
    child.send_signal(signal.SIGKILL)
    child.wait()
    got = partial.stat().st_size
    assert 0 < got < 335_304_388 and not target.exists()
    seen = []
    cf_download.fetch_hf(REPO, FILE, target, revision=REV, token=os.environ["HF_TOKEN"],
                         progress=lambda f, desc=None, **_: seen.append(desc))
    assert target.stat().st_size == 335_304_388
    assert sha256(target) == SHA
    assert not partial.exists()
    assert seen and "MB/s" in seen[-1] or "KB/s" in seen[-1] or "GB/s" in seen[-1]


def test_missing_file_fails_fast_with_actionable_message(tmp_path):
    started = time.monotonic()
    with pytest.raises(cf_download.DownloadError, match="acesso negado ou arquivo inexistente"):
        cf_download.fetch_hf(REPO, "nao/existe.safetensors", tmp_path / "x", revision=REV, token=os.environ["HF_TOKEN"])
    assert time.monotonic() - started < 15


def test_bad_token_is_reported_not_retried_forever(tmp_path):
    started = time.monotonic()
    with pytest.raises(cf_download.DownloadError):
        cf_download.fetch_hf("meta-llama/Llama-3.1-8B", "config.json", tmp_path / "c.json", token="hf_invalido")
    assert time.monotonic() - started < 15
