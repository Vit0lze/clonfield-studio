"""File sizes of the recipe weights, read from Hugging Face without downloading them (HEAD on the pinned revision) and cached."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

import cf_model_lab as lab

_lock = threading.Lock()


def cache_path(base):
    return Path(base) / "sizes.json"


def load(base):
    try:
        return json.loads(cache_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def head(repo, filename):
    revision = lab.REVISIONS.get(repo, "main")
    url = f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"
    try:
        response = requests.head(url, allow_redirects=False, timeout=6)
        size = response.headers.get("x-linked-size") or response.headers.get("content-length")
        return int(size) if size and int(size) > 1_000_000 else None
    except (requests.RequestException, ValueError):
        return None


def sizes_for(base, preset_keys=None):
    """{ 'repo/file': bytes } for every recipe file, filling the cache for what is missing."""
    cache = load(base)
    wanted = {}
    for key, preset in lab.PRESETS.items():
        if preset_keys and key not in preset_keys:
            continue
        for repo, filename, *_ in preset.files.values():
            wanted[f"{repo}/{filename}"] = (repo, filename)
    missing = [k for k in wanted if k not in cache]
    if missing:
        with ThreadPoolExecutor(8) as pool:
            for key, size in zip(missing, pool.map(lambda k: head(*wanted[k]), missing)):
                if size:
                    cache[key] = size
        with _lock:
            cache_path(base).parent.mkdir(parents=True, exist_ok=True)
            cache_path(base).write_text(json.dumps(cache), encoding="utf-8")
    return {k: cache[k] for k in wanted if k in cache}
