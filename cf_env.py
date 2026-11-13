"""Secrets for the Studio: the process environment first, then a `.env` file. Values are never logged or returned to the
browser; `status()` reports only whether each one is present.

`.env` is searched in $CLONFIELD_ENV, the working directory, the repository folder and its parent (git-ignored in the repo).
A name matches case-insensitively, so `jev=...` and `TYPESAFE_API_TOKEN=...` both work.
"""

import os
from pathlib import Path

ALIASES = {
    "jev": ("TYPESAFE_API_TOKEN", "TYPESAFE_API_KEY", "JEV_API_KEY", "JEV"),
}
_cache = {"files": None}


def candidates():
    here = Path(__file__).resolve().parent
    listed = [os.environ.get("CLONFIELD_ENV"), Path.cwd() / ".env", here / ".env", here.parent / ".env"]
    seen, out = set(), []
    for item in listed:
        if item and Path(item).is_file() and Path(item).resolve() not in seen:
            seen.add(Path(item).resolve())
            out.append(Path(item))
    return out


def parse(path):
    values = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            values[key.casefold()] = value.strip().strip("\"'")
    except OSError:
        pass
    return values


def file_values():
    if _cache["files"] is None:
        merged = {}
        for path in reversed(candidates()):  # nearer files win
            merged.update(parse(path))
        _cache["files"] = merged
    return _cache["files"]


def reload():
    _cache["files"] = None


def secret(kind):
    """The value for 'jev', or None (the chat LLM is local and needs no key). Looks at the environment, then at the .env files."""
    names = ALIASES[kind]
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    stored = file_values()
    for name in names:
        if stored.get(name.casefold()):
            return stored[name.casefold()]
    return None


def status():
    return {kind: bool(secret(kind)) for kind in ALIASES}


# Feature flags. The agent is the default decision-maker; JEV / TypeSafe is an optional router behind a flag (off by default).
FLAG_DEFAULTS = {"agent": True, "jev": False}


def flag(name):
    value = os.environ.get(f"CLONFIELD_{name.upper()}")
    if value is None:
        return FLAG_DEFAULTS.get(name, False)
    return value.strip().lower() in ("1", "true", "yes", "on", "sim")
