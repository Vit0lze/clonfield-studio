"""Capabilities, DAG and agent through the real Starlette engine app: catalog endpoints, graph validation/run with real uploads,
and the chat driven by the agent on a REAL local llama-server (real tools, real jobs). On this CPU machine the server is a small
Qwen3.5 stand-in: the test proves the path (message -> agent -> tool calls -> conversation), not the 9B's judgement."""
import io
import time

import pytest
from PIL import Image, ImageDraw
from starlette.testclient import TestClient

import cf_api
import cf_apps
import cf_llm

BASE = "/clonfield/api"


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    import cf_factory
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path_factory.mktemp("agentapi")
    mp = pytest.MonkeyPatch()
    mp.setenv("CLONFIELD_FAKE_VRAM", "15")
    mp.setenv("CLONFIELD_COMFY_MODELS", str(base / "models"))
    mp.setenv("CLONFIELD_AGENT", "1")
    cf_apps.configure(base, base / "outputs")
    client = TestClient(cf_api.build_app(base, base / "outputs", lambda t: t == "pw", "secret"), headers={"Authorization": "Bearer pw"})
    client.base = base
    yield client
    mp.undo()


def png():
    out = io.BytesIO()
    image = Image.new("RGB", (160, 120), (30, 40, 60))
    ImageDraw.Draw(image).ellipse((30, 20, 130, 100), fill=(220, 180, 120))
    image.save(out, "PNG")
    return out.getvalue()


def upload(api, name="foto.png", data=None, mime="image/png"):
    return api.post(f"{BASE}/upload", files={"files": (name, data or png(), mime)}).json()[0]


def wait_job(api, job_id, seconds=60):
    for _ in range(int(seconds / 0.3)):
        job = api.get(f"{BASE}/jobs/{job_id}").json()
        if job["status"] in ("concluído", "falhou", "cancelado"):
            return job
        time.sleep(0.3)
    raise AssertionError("job não terminou")


def test_catalog_endpoints_filter_and_describe(api):
    everything = api.get(f"{BASE}/capabilities").json()
    ids = {c["id"] for c in everything}
    assert {"upscale", "quality_gate", "look", "frame", "app.create", "app.seethrough"} <= ids
    assert [c["id"] for c in api.get(f"{BASE}/capabilities", params={"accepts": "video", "kind": "step"}).json()] == ["still"]
    for_create = {c["id"] for c in api.get(f"{BASE}/capabilities", params={"app": "create"}).json()}
    assert {"upscale", "quality_gate", "resolution_plan"} <= for_create  # what the Criar screen uses or lets you insert
    one = api.get(f"{BASE}/capabilities/upscale").json()
    assert one["consumers"] and one["validation"]["state"] and one["inputs"][0]["type"] == "image"
    assert api.get(f"{BASE}/capabilities/nope").status_code == 404


def test_dag_validate_explains_and_run_executes_a_real_job(api):
    up = upload(api)
    bad = {"graph": {"nodes": [{"id": "a", "cap": "upscale", "inputs": {"image": {"media": "0" * 32}}}]}}
    report = api.post(f"{BASE}/dag/validate", json=bad).json()
    assert report["ok"] is False and report["errors"][0]["code"] == "unresolved_media"
    assert api.post(f"{BASE}/dag/run", json=bad).status_code == 409
    graph = {"nodes": [{"id": "g", "cap": "look", "inputs": {"image": {"media": up["id"]}}, "params": {"look": "Preto e branco", "strength": 100}},
                       {"id": "u", "cap": "upscale", "inputs": {"image": {"from": "g.image"}}, "params": {"scale": 2}}]}
    job = api.post(f"{BASE}/dag/run", json={"graph": graph})
    assert job.status_code == 202
    done = wait_job(api, job.json()["id"])
    assert done["status"] == "concluído" and done["results"][0]["kind"] == "image"
    file = api.get(done["results"][0]["url"])
    assert Image.open(io.BytesIO(file.content)).size == (320, 240)
    # same graph again: every node comes from the cache (provenance on the run record)
    again = wait_job(api, api.post(f"{BASE}/dag/run", json={"graph": graph}).json()["id"])
    assert again["status"] == "concluído"


def test_low_risk_graph_runs_without_asking_over_the_api(api):
    registry_graph = {"nodes": [{"id": "a", "cap": "app.upscale", "inputs": {"image": {"media": upload(api)["id"]}}}]}
    assert api.post(f"{BASE}/dag/run", json={"graph": registry_graph}).status_code == 202  # low risk runs without asking


@pytest.mark.skipif(not cf_llm.available(), reason="nenhum llama-server local rodando (defina CLONFIELD_LLAMA_URL)")
def test_live_chat_agent_path_runs_tools_and_answers(api):
    """The chat hands the message to the agent on the local server: the reply is pending, tool calls show up in its trace, and it ends with text."""
    session = api.post(f"{BASE}/sessions", json={"title": "agente"}).json()
    up = upload(api)
    reply = api.post(f"{BASE}/sessions/{session['id']}/message", json={"text": "Quais capacidades servem para ampliar imagem? Só responda.", "media": [dict(id=up["id"], name=up["name"], kind="image")]}).json()
    assert reply["messages"][-1]["pending"] is True and "agent" in reply["messages"][-1]  # the agent path, not the Jev/heuristic plan
    final = None
    for _ in range(400):
        time.sleep(1)
        current = api.get(f"{BASE}/sessions/{session['id']}").json()
        last = current["messages"][-1]
        if last["role"] == "assistant" and not last.get("pending"):
            final = current
            break
    assert final is not None, "o agente não terminou"
    message = final["messages"][-1]
    assert not message.get("error"), message["text"]
    assert message["agent"]["provider"] == "llama-server" and message["agent"]["trace"] and message["text"]
