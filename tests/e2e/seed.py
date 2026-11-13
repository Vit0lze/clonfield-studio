"""Seeds a fresh data dir with real (tiny) safetensors LoRAs: Civitai-style downloads with sidecars + loose ComfyUI files."""
import json
import sys
from pathlib import Path

import numpy as np
from safetensors.numpy import save_file


def lora(path, meta=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    save_file({"lora_down.weight": np.zeros((2, 4), dtype=np.float32), "lora_up.weight": np.zeros((4, 2), dtype=np.float32)}, str(path), metadata=meta)


def civitai(base, stem, version, title, families):
    lora(base / "loras" / f"{stem}__cv{version}.safetensors")
    (base / "loras" / f"{stem}__cv{version}.json").write_text(json.dumps({"title": title, "families": families, "model": version, "version": version, "creator": "e2e"}))


data = Path(sys.argv[1])
base, comfy = data, data / "comfy-models"
civitai(base, "pixel_style", 11, "Pixel style", ["qwen21"])
civitai(base, "film_grain", 13, "Film grain", ["z-image", "z-image-turbo"])
lora(comfy / "loras" / "my_flux2_portrait.safetensors")
lora(comfy / "loras" / "mystery.safetensors")
print("seeded", data)


# Finished "create" jobs with real image files, so the recents strip has something to show without a GPU worker.
import time
from PIL import Image

out = data / "outputs"
(out / "jobs").mkdir(parents=True, exist_ok=True)
(out / "e2e").mkdir(parents=True, exist_ok=True)
for index, colour in enumerate([(180, 40, 60), (40, 120, 180), (60, 160, 90)], 1):
    name = f"img{index}.png"
    Image.new("RGB", (96, 96), colour).save(out / "e2e" / name)
    job_id = f"job_e2e{index:02d}"
    snapshot = {"id": job_id, "app": "create", "title": f"Seed {index}", "status": "concluído", "fraction": 1.0, "desc": "pronto", "message": "",
                "results": [{"path": f"e2e/{name}", "name": name, "kind": "image", "size": (out / "e2e" / name).stat().st_size}],
                "created": time.time() - 100 * (4 - index), "started": time.time() - 100 * (4 - index), "finished": time.time() - 90 * (4 - index),
                "lane": "gpu", "position": None, "params": {}, "version": 1}
    (out / "jobs" / f"{job_id}.json").write_text(json.dumps(snapshot), encoding="utf-8")
print("seeded jobs")


# A conversation the agent already answered (same persisted shape the engine writes), to check how the chat renders its tool calls.
(data / "sessions").mkdir(parents=True, exist_ok=True)
SESSION = "a" * 32
now = time.time()
trace = [dict(step=1, tool="list_capabilities", args='{"query": "ampliar"}', ok=True, ms=412, result="{}"),
         dict(step=2, tool="validate_graph", args='{"graph_json": "{...}"}', ok=False, ms=35, result='{"ok": false}'),
         dict(step=3, tool="execute_graph", args='{"graph_json": "{...}"}', ok=True, ms=1830, result="{}")]
(data / "sessions" / f"{SESSION}.json").write_text(json.dumps(dict(
    id=SESSION, title="Ampliar a foto", created=now - 60, updated=now, media=[],
    messages=[dict(id="u1", role="user", time=now - 50, text="amplie a foto em 2x", media=[]),
              dict(id="b1", role="assistant", kind="text", time=now - 10, pending=False, text="Ampliei a foto 2x: 160×120 virou 320×240.",
                   agent=dict(trace=trace, provider="gemma-api", model="gemma-4-31b-it", steps=3, stop="resposta final"))])), encoding="utf-8")
