"""Chat sessions: persistent conversations that keep the user's originals, the plan the router proposed, the jobs that ran
and their results, so a project never mixes references between sessions. Storage is plain JSON under <base>/sessions.

Decision-only by default: the router proposes steps, the user presses «Executar» for each one. A step is built from the
session's own media and the message text; if a required input is missing the step is not started and says what is missing.
"""

import json
import re
import threading
import time
import uuid
from pathlib import Path

MAX_MESSAGES = 400
MAX_MEDIA = 200
_lock = threading.Lock()


class Missing(Exception):
    def __init__(self, labels):
        super().__init__("Falta: " + ", ".join(labels))
        self.labels = labels


def folder(base):
    path = Path(base) / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def valid(ident):
    return isinstance(ident, str) and re.fullmatch(r"[0-9a-f]{32}", ident) is not None


def path_of(base, ident):
    if not valid(ident):
        raise KeyError(ident)
    return folder(base) / f"{ident}.json"


def create(base, title=""):
    ident = uuid.uuid4().hex
    now = time.time()
    session = dict(id=ident, title=(title or "Nova conversa").strip()[:80], created=now, updated=now, messages=[], media=[])
    save(base, session)
    return session


def save(base, session):
    session["updated"] = time.time()
    target = path_of(base, session["id"])
    with _lock:
        partial = target.with_suffix(".part")
        partial.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
        partial.replace(target)


def load(base, ident):
    try:
        return json.loads(path_of(base, ident).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise KeyError(ident) from None


def listing(base):
    out = []
    for item in folder(base).glob("*.json"):
        try:
            s = json.loads(item.read_text(encoding="utf-8"))
            out.append(dict(id=s["id"], title=s["title"], updated=s["updated"], messages=len(s["messages"]), media=len(s["media"])))
        except (OSError, ValueError, KeyError):
            continue
    return sorted(out, key=lambda s: -s["updated"])


def delete(base, ident):
    path_of(base, ident).unlink(missing_ok=True)


def add_media(session, items, origin, **extra):
    known = {m["id"] for m in session["media"]}
    for item in items:
        if item["id"] in known:
            continue
        session["media"].append(dict(id=item["id"], name=item["name"], kind=item["kind"], origin=origin, time=time.time(), **extra))
    del session["media"][:-MAX_MEDIA]


def add_message(session, role, **fields):
    message = dict(id=uuid.uuid4().hex[:12], role=role, time=time.time(), **fields)
    session["messages"].append(message)
    del session["messages"][:-MAX_MESSAGES]
    return message


def retitle(session, text):
    if session["title"] == "Nova conversa" and text.strip():
        session["title"] = re.sub(r"\s+", " ", text.strip())[:56]


def kinds(session):
    return {m["kind"] for m in session["media"] if m["kind"] in ("image", "video", "audio")}


def latest(session, accept):
    wanted = {a.strip() for a in str(accept or "").split(",")}
    for item in reversed(session["media"]):
        if item["kind"] in wanted:
            return item
    return None


def build_params(app, fields, text, session):
    """Fill an app's form from the session. Raises Missing(labels) instead of guessing a required input."""
    params, missing = {}, []
    for f in fields:
        kind = f["type"]
        if kind == "files":
            need = int(f.get("min", 0))
            found = []
            for item in reversed(session["media"]):
                if item["kind"] in {a.strip() for a in str(f.get("accept", "")).split(",")} and len(found) < max(need, 1 if need else 0):
                    found.append(item["id"])
            found.reverse()
            if len(found) < need:
                missing.append(f["label"])
            params[f["id"]] = found
        elif kind in ("textarea", "text") and f["id"] == "prompt":
            params[f["id"]] = text.strip()
            if f.get("required") and not text.strip():
                missing.append(f["label"])
        elif "default" in f and kind not in ("lights",):
            params[f["id"]] = f["default"]
        if f.get("required") and kind not in ("files", "textarea", "text") and f["id"] not in params:
            missing.append(f["label"])
    option = next((o for f in fields if f["id"] == "set" for o in f.get("options", []) if o["value"] == params.get("set")), None)
    if option:  # the Conjunto's whole recipe, exactly as the form applies it
        has_refs = bool(params.get("refs"))
        recipe = (has_refs and option.get("recipe_refs")) or option.get("recipe")
        if recipe:
            params.update(model=recipe["model"], steps=recipe["steps"], cfg=recipe["cfg"], gen_factor=recipe["gen_factor"])
    if missing:
        raise Missing(missing)
    return params


# ---------------------------------------------------------------- atomic edits (a background writer and requests share files)
_edit_lock = threading.RLock()


def update(base, ident, change):
    """Load, apply `change(session)` and save under one lock. Returns False if the conversation no longer exists."""
    with _edit_lock:
        try:
            session = load(base, ident)
        except KeyError:
            return False
        change(session)
        save(base, session)
        return True


def history_for_llm(session, limit=8):
    out = []
    for m in session["messages"][-limit:]:
        if m["role"] == "user" and m.get("text"):
            out.append({"usuario": m["text"][:300]})
        elif m["role"] == "assistant" and m.get("text") and not m.get("pending"):
            out.append({"assistente": m["text"][:300]})
    return out
