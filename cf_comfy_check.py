"""Ask a REAL ComfyUI whether an API graph is acceptable, without running it.

POST /prompt validates every node (types, ranges, combo values, links) before anything executes. Model files that are not on this machine
make the `value_not_in_list` checks fail, so `validate()` can drop an empty placeholder of each missing name into the models folders of a
SCRATCH ComfyUI (never a real install) and ask again; execution then fails on the empty files, which is cancelled right away.
Used by the tests with a CPU ComfyUI (see tests/test_comfy_real.py) to check graphs the Studio builds against the worker's own node definitions."""

import time
from pathlib import Path

import requests


def _cancel(url, prompt_id):
    requests.post(f"{url}/interrupt", timeout=10)
    requests.post(f"{url}/queue", json={"clear": True, "delete": [prompt_id]}, timeout=10)


def _errors(body):
    out = []
    err = body.get("error") or {}
    if err and not body.get("node_errors"):
        out.append(dict(node=None, type=err.get("type"), message=err.get("message"), details=err.get("details")))
    for node, info in (body.get("node_errors") or {}).items():
        for e in info.get("errors", []):
            out.append(dict(node=node, class_type=info.get("class_type"), type=e.get("type"), message=e.get("message"), details=e.get("details"), extra=e.get("extra_info") or {}))
    return out


def validate(graph, url, models_dir=None, input_dir=None, image=None, rounds=3):
    """-> list of remaining validation errors ([] means the worker accepts the graph).
    `models_dir` / `input_dir` / `image`: scratch ComfyUI folders and a real image file used for LoadImage placeholders."""
    import shutil
    errors = []
    for _ in range(rounds):
        response = requests.post(f"{url}/prompt", json={"prompt": graph, "client_id": "clonfield-check"}, timeout=30)
        if response.status_code == 200:
            _cancel(url, response.json().get("prompt_id"))
            time.sleep(0.3)
            return []
        errors = _errors(response.json())
        fixable = False
        if models_dir:
            missing = [e for e in errors if e["type"] == "value_not_in_list" and e["extra"].get("received_value")]
            if missing:
                folders = requests.get(f"{url}/models", timeout=10).json()  # every model folder this ComfyUI knows, even ones not created yet
                for folder in folders:
                    (Path(models_dir) / folder).mkdir(parents=True, exist_ok=True)
                for e in missing:
                    name = str(e["extra"]["received_value"])
                    for folder in folders:
                        if folder != "custom_nodes":
                            (Path(models_dir) / folder / Path(name).name).touch()
                fixable = True
        if input_dir and image:
            for e in errors:
                text = f"{e['message']} {e['details']}"
                if e["type"] == "custom_validation_failed" and "Invalid image file" in text:
                    name = text.rsplit("Invalid image file:", 1)[1].strip()
                    shutil.copyfile(image, Path(input_dir) / name)
                    fixable = True
        if not fixable:
            return errors
        time.sleep(1.5)  # ComfyUI re-reads folders by modification time
    return errors
