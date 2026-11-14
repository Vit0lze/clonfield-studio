"""Elenco (cast): characters saved once and called by `@name` in a prompt.

A character has a name, a short description and, optionally, a reference picture. In a prompt, `@Marina` becomes "Marina (the description)" the
first time and plain "Marina" afterwards; when the app takes reference images (an image model with reference slots), the picture of every
mentioned character is added as a reference, in the order they are mentioned, up to the free slots. Video apps get the description only.
`@@` writes a literal `@`. A mention of someone who is not in the cast is refused with the reason, so a typo never reaches the model as "@Marnia".

Idea from OpenField's Cast (github.com/wexloops/openfield, MIT); this implementation is the Studio's own. Pure CPU code, tested with real images.
Whether a model keeps a character on model from the description and the reference is NOT measured (BLOQUEADO_GPU).
"""

import json
import re
import threading
import time
import uuid
from pathlib import Path

from PIL import Image, ImageOps

NAME = re.compile(r"[A-Za-zÀ-ÿ0-9_-]{2,24}")
MENTION = re.compile(r"(?<![\w@])@([A-Za-zÀ-ÿ0-9_-]{2,24})")
MAX_DESCRIPTION = 400
MAX_CAST = 60
MAX_SIDE = 1536
_lock = threading.Lock()


def folder(base):
    return Path(base) / "cast"


def _index(base):
    return folder(base) / "cast.json"


def load(base):
    try:
        items = json.loads(_index(base).read_text(encoding="utf-8"))
        return [i for i in items if isinstance(i, dict) and isinstance(i.get("id"), str) and isinstance(i.get("name"), str)]
    except (OSError, ValueError):
        return []


def _save(base, items):
    target = _index(base)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    partial.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    partial.replace(target)


def image_path(base, item):
    return folder(base) / item["image"] if item.get("image") else None


def add(base, name, description="", image=None):
    """Save a character. `image`: a path to a picture (re-encoded as PNG, longest side <= 1536). Returns the stored item."""
    name = (name or "").strip().lstrip("@")
    if not NAME.fullmatch(name):
        raise ValueError("O nome precisa ter de 2 a 24 letras, números, _ ou - (sem espaços).")
    description = " ".join((description or "").split())
    if len(description) > MAX_DESCRIPTION:
        raise ValueError(f"A descrição passa de {MAX_DESCRIPTION} caracteres.")
    with _lock:
        items = load(base)
        if any(i["name"].casefold() == name.casefold() for i in items):
            raise ValueError(f"Já existe um personagem chamado {name}.")
        if len(items) >= MAX_CAST:
            raise ValueError(f"O elenco comporta até {MAX_CAST} personagens.")
        ident = uuid.uuid4().hex[:12]
        stored = None
        if image:
            try:
                with Image.open(image) as opened:
                    picture = ImageOps.exif_transpose(opened).convert("RGB")
            except OSError:
                raise ValueError("Não consegui abrir a imagem do personagem.") from None
            if max(picture.size) > MAX_SIDE:
                picture.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            folder(base).mkdir(parents=True, exist_ok=True)
            stored = f"{ident}.png"
            picture.save(folder(base) / stored)
        item = dict(id=ident, name=name, description=description, image=stored, created=int(time.time()))
        _save(base, items + [item])
        return item


def remove(base, ident):
    with _lock:
        items = load(base)
        gone = next((i for i in items if i["id"] == ident), None)
        if gone is None:
            raise ValueError("Personagem não encontrado.")
        _save(base, [i for i in items if i["id"] != ident])
        if gone.get("image"):
            (folder(base) / gone["image"]).unlink(missing_ok=True)
        return gone


def mentions(text):
    """Distinct mentioned names in order of appearance (case-insensitive)."""
    seen, out = set(), []
    for match in MENTION.finditer(text or ""):
        if match.group(1).casefold() not in seen:
            seen.add(match.group(1).casefold())
            out.append(match.group(1))
    return out


def expand(base, prompt, ref_slots=0):
    """-> dict(prompt, refs, used, dropped). Raises ValueError when a mentioned name is not in the cast."""
    prompt = prompt or ""
    names = mentions(prompt)
    if not names:
        return dict(prompt=prompt.replace("@@", "@"), refs=[], used=[], dropped=[])
    cast = {i["name"].casefold(): i for i in load(base)}
    missing = [n for n in names if n.casefold() not in cast]
    if missing:
        raise ValueError(f"@{missing[0]} não está no Elenco. Cadastre o personagem ou escreva @@{missing[0]} para usar o @ de verdade.")
    first = set()

    def swap(match):
        item = cast[match.group(1).casefold()]
        key = item["id"]
        if key in first or not item.get("description"):
            return item["name"]
        first.add(key)
        return f"{item['name']} ({item['description'].rstrip('.')})"
    text = MENTION.sub(swap, prompt).replace("@@", "@")
    refs, dropped, used = [], [], []
    for name in names:
        item = cast[name.casefold()]
        used.append(item["name"])
        path = image_path(base, item)
        if path and path.is_file():
            if len(refs) < max(0, ref_slots):
                refs.append(str(path))
            else:
                dropped.append(item["name"])
    return dict(prompt=text, refs=refs, used=used, dropped=dropped)
