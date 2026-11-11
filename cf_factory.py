"""Content Factory adapter: project/episode pipeline with per-input stage cache, driven by ClonField's job runner.

Reuses jutsuhq/content-factory (MIT) vendored in vendor/content_factory (see VENDORED.md for commit and the one local
patch). This module only configures its paths, creates episodes from a script, and runs its stages with progress.
Remotion (the renderer) has its own licence; see VENDORED.md.
"""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "vendor" / "content_factory"
_state = {"data": None}


def configure(base):
    """Point the engine at <base>/factory. Must run before the first engine import (the engine reads env at import)."""
    data = Path(base) / "factory"
    if _state["data"] is not None and _state["data"] != data:
        raise RuntimeError("Content Factory já foi configurado com outra pasta nesta sessão.")
    data.mkdir(parents=True, exist_ok=True)
    os.environ["CF_ROOT"], os.environ["CF_DATA"] = str(ROOT), str(data)
    for entry in (str(ROOT / "engine"),):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    _state["data"] = data
    return data


def data():
    if _state["data"] is None:
        raise RuntimeError("Content Factory não configurado.")
    return _state["data"]


def ensure_render(log=lambda line: None):
    """DATA/render: the Remotion project copied from the vendored sources, with node_modules installed once."""
    target = data() / "render"
    if not target.exists():
        shutil.copytree(ROOT / "render", target, ignore=shutil.ignore_patterns("node_modules"))
    if not (target / "node_modules").exists():
        if not shutil.which("npm"):
            raise RuntimeError("npm (Node.js) não encontrado: necessário para renderizar o vídeo.")
        log("Instalando o renderizador Remotion (uma vez)")
        subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=target, check=True, capture_output=True, text=True)
    return target


def ensure_profile():
    from factory.core import paths
    if not paths.PROFILE.exists():
        from factory import doctor
        with contextlib.redirect_stdout(io.StringIO()):
            doctor.run()


def formats():
    from factory.core import formats as f
    return [{"id": i, "title": f.load(i).get("title", i), "modes": list(f.load(i)["render_modes"])} for i in f.ids()]


def example_script(fmt="what-if", mode="drawn"):
    from factory.core import formats as f
    for path in f.examples(f.load(fmt)):
        script = json.loads(path.read_text(encoding="utf-8"))
        if script.get("render_mode") == mode:
            return script
    raise ValueError("Sem exemplo para esse modo.")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "episodio"


def create(script, title=None):
    """Validate the script against its format's schema and write episodes/<slug>/beats.json. Returns the slug."""
    from jsonschema import ValidationError, validate
    from factory.core import formats as f
    from factory.core.paths import EPISODES
    fmt = f.load(script.get("format"))
    try:
        validate(script, f.schema(fmt))
    except ValidationError as exc:
        raise ValueError("Roteiro inválido: " + exc.message[:300] + (f" (em {'/'.join(map(str, exc.path))})" if exc.path else "")) from None
    from factory.studio import compose
    issues = compose.problems(script)
    if issues:
        raise ValueError("Roteiro com problemas: " + "; ".join(issues[:5]))
    slug = slugify(title or script.get("title") or "episodio")
    folder = EPISODES / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "beats.json").write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    return slug


def status(slug):
    from factory import stages
    from factory.core import Episode
    ep = Episode.load(slug)
    out = ep.dir / "out"
    video = out / f"{slug}.mp4"
    qa = out / "qa.json"
    keys = sorted(p.name for p in (ep.dir / "work").rglob("*.key")) if (ep.dir / "work").exists() else []
    return dict(slug=slug, stages=stages.plan(ep), video=video if video.exists() else None,
                qa=json.loads(qa.read_text()) if qa.exists() else None, cached_outputs=len(keys))


def run(slug, progress=lambda fraction=None, desc=None: None, names=None):
    """Run the episode's stages; every stage skips outputs whose input hash is unchanged. Progress follows stage lines."""
    from factory import stages
    from factory.core import Episode
    from factory.core.profile import load_profile
    ensure_profile()
    ep = Episode.load(slug)
    todo = stages.plan(ep, names)
    if "render" in todo:
        ensure_render(lambda line: progress(0.05, desc=line))
    class Tap(io.StringIO):
        def write(self, text):
            for line in text.splitlines():
                if line.strip():
                    progress(None, desc=line.strip()[:140])
            return super().write(text)
    tap = Tap()
    profile = load_profile()
    done = 0
    for name in todo:
        progress(done / max(len(todo), 1), desc=f"Etapa {name}")
        with contextlib.redirect_stdout(tap):
            __import__(f"factory.stages.{name}", fromlist=["run"]).run(ep, profile)
        done += 1
    progress(1.0, desc="Vídeo pronto")
    return status(slug)
