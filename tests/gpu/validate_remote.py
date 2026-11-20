"""Remote validation of a running Studio (Colab/T4 or a local engine) through its real HTTP API.

  python tests/gpu/validate_remote.py [--env /path/.env] [--only id,id] [--list] [--timeout 1800] [--out tests/gpu/out]

Credentials: the .env file holds `api=<public Studio link>` and `bearer=<session password>`. They are read, used in the
Authorization header and NEVER printed or written to the results (every message is scrubbed). A wrong bearer stops the run at
the first 401 (the Studio locks the client out after a few failures, so this never retries).

Each case submits real jobs (apps or recipes), waits for them, downloads every result, and checks the FILES: an image is decoded
and must not be blank or flat, a video is probed with ffprobe (duration, size) and must have motion between two frames, audio must have
a duration. A job that "concluiu" without a valid file is a FAIL. Status vocabulary of the report: OK (files checked) / FALHOU /
PULADO (precondition missing, reason given). Results go to <out>/results-<time>.json and the files to <out>/<case>/ so a person can LOOK
at them; nothing here is a benchmark: the seconds are wall time of one run on whatever GPU the Colab gave.
"""
import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageStat

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "/clonfield/api"
DEFAULT_ENV = ROOT.parent / ".env"
FINAL = ("concluído", "falhou", "cancelado", "travado")


class Stop(Exception):
    """The run cannot continue (bad credentials, Studio unreachable)."""


def read_env(path):
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip().lower()] = value.strip().strip('"').strip("'")
    return values


class Client:
    def __init__(self, api, bearer):
        api = api.strip().rstrip("/")
        api = re.sub(r"/clonfield(/api)?$", "", api)
        api = re.sub(r"/studio/?$", "", api)
        self.base, self.password, self.bearer = api, bearer, bearer
        self.http = requests.Session()
        self.http.trust_env = False

    def connect(self):
        """Exchange the session password for the API token (POST /clonfield/connect), like the portal does. A local engine without that route
        (cf_engine.py) takes the password itself as the bearer, so a 404 keeps it. Stops on a refused password (the server blocks 8 failures a minute)."""
        try:
            response = self.http.post(self.base + "/clonfield/connect", headers={"Authorization": f"Bearer {self.password}"}, timeout=60)
        except requests.RequestException as exc:
            raise Stop(self.scrub(f"Studio inalcançável: {type(exc).__name__}")) from None
        if response.status_code == 200 and response.json().get("token"):
            self.bearer = response.json()["token"]
        elif response.status_code == 429:
            raise Stop("429: muitas tentativas de senha; espere 1 minuto.")
        elif response.status_code == 401:
            raise Stop("401: a senha da sessão do .env foi recusada. Copie a senha da execução atual da célula do Studio (ela muda a cada subida).")
        elif response.status_code != 404:
            raise Stop(f"connect respondeu {response.status_code}")
        return self

    def scrub(self, text):
        text = str(text)
        for secret in (self.bearer, self.password, self.base):
            if secret:
                text = text.replace(secret, "<oculto>")
        return text

    def call(self, method, path, **kwargs):
        headers = {"Authorization": f"Bearer {self.bearer}"}
        url = self.base + (path if path.startswith("/") and path.startswith(PREFIX) else PREFIX + path)
        try:
            response = self.http.request(method, url, headers=headers, timeout=kwargs.pop("timeout", 60), **kwargs)
        except requests.RequestException as exc:
            raise Stop(self.scrub(f"Studio inalcançável: {type(exc).__name__}")) from None
        if response.status_code == 401:
            raise Stop("401: o token da sessão foi recusado (o Studio reiniciou?). Rode de novo para reconectar.")
        return response

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, json=body if body is not None else {}, **kw)

    def download(self, url, target):
        response = self.http.get(self.base + url if url.startswith("/") else url, timeout=300, stream=True)
        response.raise_for_status()
        with open(target, "wb") as handle:
            for block in response.iter_content(1 << 20):
                handle.write(block)
        return target


# ------------------------------------------------------------------ file checks (what "worked" means)
def check_image(path):
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        small = rgb.resize((64, 64))
        spread = max(ImageStat.Stat(small).stddev)
        info = dict(kind="image", size=list(rgb.size), spread=round(spread, 1))
    if info["size"][0] < 64 or info["size"][1] < 64:
        raise ValueError(f"imagem pequena demais {info['size']}")
    if info["spread"] < 3:
        raise ValueError(f"imagem lisa/vazia (desvio {info['spread']})")
    return info


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_type", "-of", "json", str(path)], capture_output=True, text=True)
    if out.returncode:
        raise ValueError("ffprobe não leu o arquivo")
    data = json.loads(out.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    return dict(duration=float(data["format"].get("duration") or 0), width=video.get("width"), height=video.get("height"), has_audio=any(s.get("codec_type") == "audio" for s in streams))


def check_video(path):
    info = probe(path)
    if info["duration"] < 0.5 or not info["width"]:
        raise ValueError(f"vídeo sem duração/imagem: {info}")
    folder = Path(tempfile.mkdtemp(prefix="cf-frames-"))
    try:
        for name, at in (("a", 0.1), ("b", max(0.2, info["duration"] - 0.3))):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(path), "-frames:v", "1", str(folder / f"{name}.png")], capture_output=True, check=True)
        with Image.open(folder / "a.png") as a, Image.open(folder / "b.png") as b:
            first, last = a.convert("L").resize((64, 64)), b.convert("L").resize((64, 64))
            diff = sum(abs(x - y) for x, y in zip(first.tobytes(), last.tobytes())) / (64 * 64)
            spread = ImageStat.Stat(first).stddev[0]
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if spread < 2:
        raise ValueError("primeiro quadro liso/vazio")
    return dict(kind="video", **{k: info[k] for k in ("duration", "width", "height", "has_audio")}, motion=round(diff, 2))


def check_audio(path):
    info = probe(path)
    if info["duration"] < 0.5:
        raise ValueError(f"áudio curto demais: {info['duration']}s")
    return dict(kind="audio", duration=info["duration"])


CHECKS = {"image": check_image, "video": check_video, "audio": check_audio}


def check_file(path):
    suffix = Path(path).suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg", ".webp"):
        return CHECKS["image"](path)
    if suffix in (".mp4", ".webm", ".mov", ".mkv"):
        return CHECKS["video"](path)
    if suffix in (".mp3", ".wav", ".flac", ".ogg"):
        return CHECKS["audio"](path)
    return dict(kind="file", bytes=Path(path).stat().st_size)


# ------------------------------------------------------------------ one run
class Run:
    def __init__(self, client, out_dir, timeout):
        self.c, self.out, self.timeout = client, Path(out_dir), timeout
        self.apps = {a["id"]: a for a in client.get("/apps").json()}
        self.recipes = {r["id"]: r for r in client.get("/recipes").json()}
        self.kept = {}  # named files produced by earlier cases (e.g. the generated image a later case animates)

    # -- helpers
    def defaults(self, app_id):
        app = self.apps[app_id]
        return {f["id"]: f["default"] for f in app["fields"] if f.get("default") is not None and f["type"] != "files"}  # hidden fields too: the portal sends them and some runners read p["mode"]

    def upload(self, path):
        with open(path, "rb") as handle:
            response = self.c.call("POST", "/upload", files={"files": (Path(path).name, handle, mimetypes.guess_type(str(path))[0] or "application/octet-stream")}, timeout=300)
        response.raise_for_status()
        return response.json()[0]["id"]

    def import_result(self, result):
        response = self.c.post("/import", {"path": result["path"]})
        response.raise_for_status()
        return response.json()["id"]

    def wait(self, job_id, label):
        started = time.monotonic()
        last = None
        while True:
            response = self.c.get(f"/jobs/{job_id}")
            response.raise_for_status()
            job = response.json()
            if job["status"] != last:
                last = job["status"]
                print(f"    [{label}] {last} {job.get('desc') or ''}", flush=True)
            if job["status"] in FINAL:
                return job, round(time.monotonic() - started, 1)
            if time.monotonic() - started > self.timeout:
                self.c.post(f"/jobs/{job_id}/cancel")
                raise ValueError(f"passou de {self.timeout}s; cancelei o job")
            time.sleep(4)

    def collect(self, case, job):
        """Download and check every result of a finished job. Returns the per-file report; raises when the job failed or a file is bad."""
        if job["status"] != "concluído":
            raise ValueError(f"job {job['status']}: {self.c.scrub(job.get('message') or '')[:300]}")
        if not job["results"]:
            raise ValueError("o job concluiu sem nenhum arquivo")
        folder = self.out / case
        folder.mkdir(parents=True, exist_ok=True)
        files = []
        for index, result in enumerate(job["results"]):
            target = folder / f"{index:02d}-{re.sub(r'[^A-Za-z0-9._-]', '_', result['name'])}"
            self.c.download(result["url"], target)
            try:
                report = check_file(target)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                raise ValueError(f"arquivo {result['name']} inválido: {exc}") from None
            files.append(dict(name=result["name"], file=str(target.relative_to(self.out)), **report))
        return files

    def run_job(self, case, app_id, params, label=None):
        response = self.c.post("/jobs", dict(app=app_id, params=params))
        if response.status_code >= 400:
            raise ValueError(f"{app_id}: {response.json().get('detail', response.status_code)}")
        job, seconds = self.wait(response.json()["id"], label or app_id)
        return job, seconds

    def run_recipe(self, case, recipe_id, values):
        response = self.c.post(f"/recipes/{recipe_id}/run", {"vars": values})
        if response.status_code >= 400:
            raise ValueError(f"{recipe_id}: {response.json().get('detail', response.status_code)}")
        jobs = response.json()["jobs"]
        finished = [self.wait(j["id"], recipe_id) for j in jobs]
        return finished[0][0], round(sum(s for _, s in finished), 1)


# ------------------------------------------------------------------ cases (cheap -> heavy). Each returns (files, note) or raises.
def make_picture(path, colour=(200, 120, 60), text="ClonField"):
    image = Image.new("RGB", (640, 480), (30, 40, 70))
    draw = ImageDraw.Draw(image)
    draw.ellipse((160, 90, 480, 400), fill=colour)
    draw.rectangle((0, 400, 640, 480), fill=(20, 90, 60))
    draw.text((20, 20), text, fill=(255, 255, 255))
    image.save(path)
    return path


def case_system(run):
    info = run.c.get("/system").json()
    tier = info.get("tier", {})
    note = f"GPU {tier.get('gpu') or tier.get('name') or '?'} · VRAM {tier.get('vram_gb')} GB · RAM {info.get('ram_gb')} GB · worker {'ok' if info.get('worker', {}).get('ok') else 'FORA'}"
    if tier.get("gpu") == "GPU simulada":
        raise ValueError("este Studio roda com VRAM SIMULADA (CLONFIELD_FAKE_VRAM): não é GPU real e nada daqui vale como evidência de GPU")
    if not info.get("worker", {}).get("ok"):
        raise ValueError("o ComfyUI (worker) não está respondendo: " + run.c.scrub(str(info.get("worker", {}).get("log", ""))[:200]))
    return [], note


def case_llm(run):
    info = run.c.get("/llm").json()
    if not (info.get("available") or info.get("ok") or info.get("ready")):
        raise ValueError("modelo local do chat indisponível: " + run.c.scrub(json.dumps(info, ensure_ascii=False))[:200])
    return [], json.dumps({k: v for k, v in info.items() if not isinstance(v, (dict, list))}, ensure_ascii=False)[:200]


def case_cpu_recipe(run):
    folder = Path(tempfile.mkdtemp(prefix="cf-pics-"))
    ids = [run.upload(make_picture(folder / f"p{i}.png", c)) for i, c in enumerate([(200, 120, 60), (60, 120, 200), (90, 180, 110)])]
    job, secs = run.run_recipe("cpu_recipe", "apresentacao_de_imagens", dict(images=ids, ratio="Quadrado · 1:1", look="Preto e branco", seconds=1, zoom=True))
    return run.collect("cpu_recipe", job), f"{secs}s"


def _create(run, case, model, prompt, aspect="1:1", **extra):
    params = {**run.defaults("create"), "prompt": prompt, "model": model, "aspect": aspect, **extra}
    job, secs = run.run_job(case, "create", params)
    files = run.collect(case, job)
    images = [r for r in job["results"] if r["kind"] == "image"]
    if images:
        run.kept[case] = run.import_result(images[0])
    return files, f"{secs}s"


def make_clip(path, seconds=2):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=320x240:rate=12", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def auto_values(run, recipe, folder):
    """A form filled from the recipe's own spec: media from generated files, everything else at its default (first option for a choice)."""
    values, count = {}, 0
    for spec in recipe["inputs"]:
        kind = spec["kind"]
        if kind in ("image", "images"):
            n = 1 if kind == "image" else max(2, spec.get("min") or 2)
            ids = []
            for _ in range(n):
                count += 1
                ids.append(run.upload(make_picture(folder / f"img{count}.png", [(200, 120, 60), (60, 120, 200), (90, 180, 110), (180, 90, 160)][count % 4], f"p{count}")))
            values[spec["id"]] = ids[0] if kind == "image" else ids
        elif kind in ("video", "videos"):
            n = 1 if kind == "video" else max(2, spec.get("min") or 2)
            ids = []
            for _ in range(n):
                count += 1
                ids.append(run.upload(make_clip(folder / f"clip{count}.mp4")))
            values[spec["id"]] = ids[0] if kind == "video" else ids
        elif kind == "enum":
            values[spec["id"]] = spec.get("default") or spec["options"][0]
        elif kind == "enumlist":
            values[spec["id"]] = list(spec.get("default") or spec["options"][:1])
        elif "default" in spec:
            values[spec["id"]] = spec["default"]
    return values


def case_cpu_recipes_all(run):
    """Every CPU recipe of the catalogue, run for real on the Colab host with generated inputs; each one's files are checked."""
    folder = Path(tempfile.mkdtemp(prefix="cf-auto-"))
    files, notes, failed = [], [], []
    for recipe in [r for r in run.recipes.values() if r["lane"] == "cpu" and not r.get("custom")]:
        try:
            job, secs = run.run_recipe(f"cpu_{recipe['id']}", recipe["id"], auto_values(run, recipe, folder))
            got = run.collect(f"cpu_{recipe['id']}", job)
            files += got
            notes.append(f"{recipe['id']} ok {secs}s ({len(got)} arq.)")
        except Stop:
            raise
        except Exception as exc:
            failed.append(f"{recipe['id']}: {run.c.scrub(str(exc))[:160]}")
    if failed:
        raise ValueError(" | ".join(failed) + " || ok: " + "; ".join(notes))
    return files, "; ".join(notes)


def case_cpu_apps_all(run):
    """Every CPU-lane app, one job each, with generated media for its file fields and the form's own defaults. Apps that need something
    this harness cannot invent (drawn boxes, a mask, a script) are listed as skipped inside the note, not hidden."""
    folder = Path(tempfile.mkdtemp(prefix="cf-apps-"))
    files, ok, failed, skipped = [], [], [], []
    for app_id, app in run.apps.items():
        if app.get("lane") != "cpu" or app.get("blocked_reason") or app_id == "faceswap":  # face swap = deepfake: never run on Colab (its FAQ forbids it)
            continue
        params = run.defaults(app_id)
        try:
            for field in app["fields"]:
                if field["type"] != "files":
                    if field.get("required") and not params.get(field["id"]):
                        raise Skip(f"campo obrigatório «{field['id']}»")
                    continue
                need = max(int(field.get("min") or 0), 0)
                if not need:
                    continue
                kind = "video" if "video" in str(field.get("accept")) and "image" not in str(field.get("accept")) else "image"
                ids = [run.upload(make_clip(folder / f"{app_id}-{i}.mp4") if kind == "video" else make_picture(folder / f"{app_id}-{i}.png", [(200, 120, 60), (60, 120, 200)][i % 2], f"{app_id}{i}")) for i in range(need)]
                params[field["id"]] = ids
            job, secs = run.run_job(f"cpuapp_{app_id}", app_id, params, label=app_id)
            got = run.collect(f"cpuapp_{app_id}", job)
            files += got
            ok.append(f"{app_id} {secs}s")
        except Skip as exc:
            skipped.append(f"{app_id} ({exc})")
        except Stop:
            raise
        except Exception as exc:
            failed.append(f"{app_id}: {run.c.scrub(str(exc))[:150]}")
    note = f"ok: {', '.join(ok)}" + (f" || pulados: {', '.join(skipped)}" if skipped else "")
    if failed:
        raise ValueError(" | ".join(failed) + " || " + note)
    return files, note


def case_create_turbo(run):
    return _create(run, "create_turbo", "qwen21-turbo", "um farol branco numa ilha ao entardecer, mar calmo, fotografia")


def case_create_std(run):
    return _create(run, "create_std", "qwen21", "um gato laranja dormindo numa janela com cortina azul, luz da manhã", steps=0)


def _need(run, key):
    if key not in run.kept:
        raise Skip(f"precisa do resultado do caso «{key}», que não rodou ou falhou")
    return run.kept[key]


class Skip(Exception):
    pass


def case_upscale_gpu(run):
    source = _need(run, "create_turbo")
    params = {**run.defaults("upscale"), "image": [source], "mode": next((o["value"] for o in next(f for f in run.apps["upscale"]["fields"] if f["id"] == "mode")["options"] if "Lanczos" not in o["value"]), "Lanczos (rápido, sem IA)"), "scale": 2}
    job, secs = run.run_job("upscale_gpu", "upscale", params)
    return run.collect("upscale_gpu", job), f"{secs}s · modo {params['mode']}"


def case_animate(run):
    source = _need(run, "create_turbo")
    params = {**run.defaults("animate"), "image": [source], "prompt": "slow gentle camera drift, subtle motion", "seconds": 2, "fast": False}
    job, secs = run.run_job("animate", "animate", params)
    files = run.collect("animate", job)
    videos = [r for r in job["results"] if r["kind"] == "video"]
    if videos:
        run.kept["animate"] = run.import_result(videos[0])
    return files, f"{secs}s"


def case_recipe_seeds(run):
    job, secs = run.run_recipe("recipe_seeds", "melhor_de_n_sementes", dict(prompt="um farol à noite, mar agitado", genre="drama", aspect="1:1", count=2, seed=1000))
    return run.collect("recipe_seeds", job), f"{secs}s (2 sementes → conferir → melhor → ampliar)"


def case_recipe_matrix(run):
    job, secs = run.run_recipe("recipe_matrix", "cenarios_em_matriz", dict(template="{a} em {b}", axis_a="uma detetive\num robô velho", axis_b="um beco chuvoso", genre="noir", aspect="1:1"))
    files = run.collect("recipe_matrix", job)
    return files, f"{secs}s"


def case_recipe_loop(run):
    source = _need(run, "create_turbo")
    job, secs = run.run_recipe("recipe_loop", "loop_de_imagem", dict(image=source, prompt="slow gentle camera drift, subtle motion", seconds=2))
    return run.collect("recipe_loop", job), f"{secs}s"


def case_recipe_shots_to_film(run):
    first, second = _need(run, "create_turbo"), run.kept.get("create_std") or _need(run, "create_turbo")
    job, secs = run.run_recipe("recipe_shots_film", "planos_em_filme", dict(images=[first, second], motion="slow push in, subtle motion", ratio="Paisagem · 16:9", seconds=2))
    return run.collect("recipe_shots_film", job), f"{secs}s"


def case_recipe_animatic(run):
    first, second = _need(run, "create_turbo"), run.kept.get("create_std") or _need(run, "create_turbo")
    job, secs = run.run_recipe("recipe_animatic", "animatic_do_storyboard", dict(images=[first, second], ratio="Paisagem · 16:9", look="Sem look", seconds=1, zoom=True, fade=True))
    return run.collect("recipe_animatic", job), f"{secs}s"


def case_recipe_character(run):
    source = _need(run, "create_turbo")
    options = run.recipes["personagem_pronto"]["inputs"]
    sets = next(i for i in options if i["id"] == "set")["options"]
    job, secs = run.run_recipe("recipe_character", "personagem_pronto", dict(image=source, set=sets[0]))
    return run.collect("recipe_character", job), f"{secs}s · conjunto {sets[0]}"


def case_storyboard_recipe(run):
    job, secs = run.run_recipe("recipe_story", "storyboard_em_filme", dict(shots="uma mulher abre uma porta velha\nela lê uma carta sobre a mesa", motion="slow push in, subtle motion", genre="drama", seconds=2))
    return run.collect("recipe_story", job), f"{secs}s"


def case_agent_chain(run):
    """The chat agent (local Qwen) is asked for an image -> enlarge -> video chain; we check what it built AND the files."""
    session = run.c.post("/sessions", {}).json()
    sid = session["id"]
    reply = run.c.post(f"/sessions/{sid}/message", {"text": "crie uma imagem de um farol ao entardecer, depois amplie 2x e faça um vídeo curto dela"}, timeout=600)
    if reply.status_code >= 400:
        raise ValueError(f"agente: {run.c.scrub(reply.text)[:300]}")
    started = time.monotonic()
    while True:  # the reply is produced by a background thread: poll until it is no longer pending
        body = run.c.get(f"/sessions/{sid}").json()
        last = [m for m in body["messages"] if m["role"] == "assistant"][-1]
        if not last.get("pending"):
            break
        if time.monotonic() - started > min(run.timeout, 900):
            raise ValueError("o agente continuou «pendente» por 15 min")
        time.sleep(5)
    if "Não consegui concluir com o agente" in (last.get("text") or ""):
        raise ValueError(run.c.scrub(last["text"])[:300])
    trace = (last.get("agent") or {}).get("trace") or []
    tools = [t["tool"] for t in trace]
    note = f"ferramentas: {', '.join(tools) or 'nenhuma'}"
    job_ids = [m.get("job") for m in body["messages"] if m.get("job")]
    if not tools:
        raise ValueError("o agente respondeu sem usar nenhuma ferramenta. " + note)
    return [], note + (f" · jobs {job_ids}" if job_ids else "")


CASES = [
    ("system", "Sistema: GPU, VRAM, RAM e worker do ComfyUI", case_system),
    ("llm", "Modelo local do chat/agente no ar", case_llm),
    ("cpu_recipe", "Receita de CPU de ponta a ponta (upload → fluxo → MP4)", case_cpu_recipe),
    ("cpu_recipes_all", "Todas as receitas de CPU do catálogo, entradas geradas", case_cpu_recipes_all),
    ("cpu_apps_all", "Todos os apps de CPU, um job por app", case_cpu_apps_all),
    ("create_turbo", "Criar imagem com Qwen 2.1 Turbo", case_create_turbo),
    ("create_std", "Criar imagem com Qwen 2.1 padrão", case_create_std),
    ("upscale_gpu", "Ampliar com upscaler de IA (GPU)", case_upscale_gpu),
    ("animate", "Foto em movimento (Wan 5B Q6)", case_animate),
    ("recipe_seeds", "Receita Melhor de N sementes", case_recipe_seeds),
    ("recipe_matrix", "Receita Cenários em matriz", case_recipe_matrix),
    ("recipe_loop", "Receita Imagem em loop perfeito", case_recipe_loop),
    ("recipe_animatic", "Receita Animatic do storyboard (planos reais)", case_recipe_animatic),
    ("recipe_shots_film", "Receita Planos prontos em filme", case_recipe_shots_to_film),
    ("recipe_character", "Receita Personagem pronto", case_recipe_character),
    ("recipe_story", "Receita Storyboard em filme", case_storyboard_recipe),
    ("agent_chain", "Agente local monta cadeia imagem → ampliar → vídeo", case_agent_chain),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=str(DEFAULT_ENV))
    parser.add_argument("--only", default="")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--out", default=str(ROOT / "tests" / "gpu" / "out"))
    args = parser.parse_args()
    if args.list:
        for ident, title, _ in CASES:
            print(f"{ident:20s} {title}")
        return 0
    values = read_env(args.env)
    if not values.get("api") or not values.get("bearer"):
        print("O .env precisa ter as chaves `api` e `bearer` (os valores não são mostrados). Faltando: " + ", ".join(k for k in ("api", "bearer") if not values.get(k)))
        return 2
    print("credenciais carregadas (valores ocultos)")
    client = Client(values["api"], values["bearer"])
    try:
        client.connect()
    except Stop as exc:
        print("\nPARADO:", exc)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wanted = [w for w in args.only.split(",") if w]
    report = []
    try:
        run = Run(client, out, args.timeout)
        for ident, title, fn in CASES:
            if wanted and ident not in wanted:
                continue
            print(f"\n== {ident}: {title}", flush=True)
            started = time.monotonic()
            record = dict(id=ident, title=title)
            try:
                files, note = fn(run)
                record.update(status="OK", note=note, files=files)
            except Skip as exc:
                record.update(status="PULADO", note=str(exc))
            except Stop:
                raise
            except Exception as exc:  # one failed case must not hide the others
                record.update(status="FALHOU", note=client.scrub(f"{type(exc).__name__}: {exc}")[:600])
            record["seconds"] = round(time.monotonic() - started, 1)
            report.append(record)
            print(f"   -> {record['status']} {record.get('note', '')[:200]}", flush=True)
    except Stop as exc:
        print("\nPARADO:", exc)
        record = dict(id="parada", status="PARADO", note=str(exc))
        report.append(record)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out / f"results-{stamp}.json").write_text(client.scrub(json.dumps(dict(date=stamp, report=report), ensure_ascii=False, indent=1)), encoding="utf-8")
    summary = {s: sum(1 for r in report if r["status"] == s) for s in ("OK", "FALHOU", "PULADO", "PARADO")}
    print("\nResumo:", summary, "→", out / f"results-{stamp}.json")
    return 1 if summary["FALHOU"] or summary["PARADO"] else 0


if __name__ == "__main__":
    sys.exit(main())
