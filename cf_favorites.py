"""User favourites (the yellow star), kept on the server so they follow the user across browsers and sessions.
Distinct from the red ★ of default compatibility, which belongs to a recipe, not to a user."""

import json
import threading
import time
from pathlib import Path

KINDS = {"app", "model", "lora", "upscaler", "component", "result"}
META_KEYS = {"title", "family", "role", "source", "url", "model", "version", "file", "name", "app", "base"}
_lock = threading.Lock()


def path(base):
    return Path(base) / "favorites.json"


def load(base):
    try:
        items = json.loads(path(base).read_text(encoding="utf-8"))
        return [i for i in items if isinstance(i, dict) and i.get("kind") in KINDS and isinstance(i.get("id"), str)]
    except (OSError, ValueError):
        return []


def clean_meta(meta):
    if not isinstance(meta, dict):
        return {}
    out = {}
    for key, value in meta.items():
        if key in META_KEYS and isinstance(value, (str, int)) and len(str(value)) <= 300:
            out[key] = value
    return out


def toggle(base, kind, ident, meta=None):
    """Flip one favourite. Returns True when it is now a favourite."""
    if kind not in KINDS:
        raise ValueError("Tipo de favorito desconhecido.")
    if not isinstance(ident, str) or not ident or len(ident) > 240:
        raise ValueError("Identificador de favorito inválido.")
    with _lock:
        items = load(base)
        kept = [i for i in items if not (i["kind"] == kind and i["id"] == ident)]
        now = len(kept) == len(items)
        if now:
            kept.append(dict(kind=kind, id=ident, meta=clean_meta(meta), time=time.time()))
        target = path(base)
        partial = target.with_suffix(".part")
        partial.write_text(json.dumps(kept[-2000:], ensure_ascii=False), encoding="utf-8")
        partial.replace(target)
        return now
