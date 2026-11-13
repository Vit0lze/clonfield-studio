"""Chat sessions through the real Starlette engine app (TestClient): persistence, plan, missing-input guard, job + results.
The router uses the live Jev when a token is present, otherwise the local heuristic; both paths are accepted."""
import io

import pytest
from PIL import Image
from starlette.testclient import TestClient

import cf_api
import cf_apps
import cf_chat
import cf_llm

_ORIG_AVAILABLE = cf_llm.available


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    import cf_factory
    # The vendored engine binds its data folder once per process, so reuse it when another module configured it first.
    tmp_path = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path_factory.mktemp("chat")
    mp = pytest.MonkeyPatch()
    mp.setenv("CLONFIELD_FAKE_VRAM", "15")
    mp.setenv("CLONFIELD_COMFY_MODELS", str(tmp_path / "models"))
    mp.setenv("CLONFIELD_AGENT", "0")  # these tests cover the Jev/heuristic path; the agent has its own tests (test_agent.py, test_agent_api.py)
    mp.setenv("CLONFIELD_JEV", "1")
    mp.setattr(cf_llm, "available", lambda: False)  # unit tests stay offline for the LLM; the live ones switch it back on
    cf_apps.configure(tmp_path, tmp_path / "outputs")
    app = cf_api.build_app(tmp_path, tmp_path / "outputs", lambda t: t == "pw", "secret")
    client = TestClient(app, headers={"Authorization": "Bearer pw"})
    client.base = tmp_path
    yield client
    mp.undo()


def png_bytes(color=(40, 90, 200)):
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, "PNG")
    return buffer.getvalue()


def upload(client):
    r = client.post("/clonfield/api/upload", files={"files": ("foto.png", png_bytes(), "image/png")})
    assert r.status_code == 200, r.text
    return r.json()[0]


def test_sessions_are_created_listed_renamed_and_deleted_on_disk(api):
    created = api.post("/clonfield/api/sessions", json={}).json()
    sid = created["id"]
    assert (api.base / "sessions" / f"{sid}.json").is_file()
    assert sid in [s["id"] for s in api.get("/clonfield/api/sessions").json()]
    assert api.post(f"/clonfield/api/sessions/{sid}/rename", json={"title": "Campanha"}).status_code == 200
    assert api.get(f"/clonfield/api/sessions/{sid}").json()["title"] == "Campanha"
    assert api.post(f"/clonfield/api/sessions/{sid}/delete").status_code == 200
    assert api.get(f"/clonfield/api/sessions/{sid}").status_code == 404
    assert api.get("/clonfield/api/sessions/../etc").status_code in (404, 405)


def test_message_keeps_media_in_the_session_and_proposes_a_plan(api):
    sid = api.post("/clonfield/api/sessions", json={}).json()["id"]
    media = upload(api)
    reply = api.post(f"/clonfield/api/sessions/{sid}/message", json={"text": "amplia essa foto em 2x", "media": [media]})
    assert reply.status_code == 200, reply.text
    session = reply.json()
    assert [m["role"] for m in session["messages"]] == ["user", "assistant", "assistant"]  # user, plan card, (silent) reply slot
    assert session["media"][0]["id"] == media["id"] and session["media"][0]["origin"] == "upload" and session["media"][0]["url"]
    plan = session["messages"][1]["plan"]
    assert plan["steps"] and plan["steps"][0]["app"] in cf_apps.registry()
    assert session["title"].startswith("amplia")
    # persisted: a fresh load from disk sees the same thing
    assert cf_chat.load(api.base, sid)["messages"][1]["plan"]["steps"] == plan["steps"]


def test_two_sessions_never_share_media(api):
    a = api.post("/clonfield/api/sessions", json={}).json()["id"]
    b = api.post("/clonfield/api/sessions", json={}).json()["id"]
    api.post(f"/clonfield/api/sessions/{a}/message", json={"text": "olá", "media": [upload(api)]})
    assert api.get(f"/clonfield/api/sessions/{b}").json()["media"] == []


def test_running_a_step_without_its_input_is_refused_and_names_what_is_missing(api):
    sid = api.post("/clonfield/api/sessions", json={}).json()["id"]
    r = api.post(f"/clonfield/api/sessions/{sid}/run", json={"app": "upscale", "text": "amplia"})
    assert r.status_code == 409 and r.json()["missing"]


def test_a_cpu_step_runs_from_session_media_and_its_result_joins_the_session(api):
    sid = api.post("/clonfield/api/sessions", json={}).json()["id"]
    api.post(f"/clonfield/api/sessions/{sid}/message", json={"text": "só uma foto", "media": [upload(api)]})
    run = api.post(f"/clonfield/api/sessions/{sid}/run", json={"app": "look", "text": ""})
    assert run.status_code == 202, run.text
    job_id = run.json()["id"]
    import time
    for _ in range(100):
        job = api.get(f"/clonfield/api/jobs/{job_id}").json()
        if job["status"] in ("concluído", "falhou", "cancelado"):
            break
        time.sleep(0.2)
    assert job["status"] == "concluído", job
    session = api.get(f"/clonfield/api/sessions/{sid}").json()
    assert [m["role"] for m in session["messages"]][-1] == "job"
    results = [m for m in session["media"] if m["origin"] == "result"]
    assert results and results[0]["app"] == "look" and results[0]["url"]
    originals = [m for m in session["media"] if m["origin"] == "upload"]
    assert len(originals) == 1  # the original is kept next to its revision


def test_build_params_applies_the_conjunto_recipe_like_the_form_does(api):
    session = dict(id="x" * 32, title="t", messages=[], media=[])
    app = cf_apps.registry()["create"]
    tier = api.app.state.tier
    params = cf_chat.build_params(app, app.fields(tier), "um gato astronauta", session)
    recipe = next(o for f in app.fields(tier) if f["id"] == "set" for o in f["options"] if o["value"] == "Moderado")["recipe"]
    assert params["prompt"] == "um gato astronauta" and params["model"] == recipe["model"] and params["steps"] == recipe["steps"]
    with pytest.raises(cf_chat.Missing):
        cf_chat.build_params(app, app.fields(tier), "", session)


def wait_reply(api, sid, timeout=150):
    import time
    end = time.time() + timeout
    while time.time() < end:
        session = api.get(f"/clonfield/api/sessions/{sid}").json()
        if not any(m.get("pending") for m in session["messages"]):
            return session
        time.sleep(3)
    raise AssertionError("Gemma reply never finished")


needs_keys = pytest.mark.skipif(not (_ORIG_AVAILABLE() and cf_chat.__name__), reason="no Gemma key in the environment")


@needs_keys
def test_live_gemma_answers_a_question_without_proposing_any_job(api, monkeypatch):
    monkeypatch.setattr(cf_llm, "available", _ORIG_AVAILABLE)
    sid = api.post("/clonfield/api/sessions", json={}).json()["id"]
    first = api.post(f"/clonfield/api/sessions/{sid}/message", json={"text": "oi! o que significa o conjunto Qualidade?"}).json()
    assert any(m.get("pending") for m in first["messages"])  # the reply is written in the background
    assert not any(m.get("plan") for m in first["messages"])  # Jev saw conversation, not a task: no plan card
    done = wait_reply(api, sid)
    reply = next(m for m in done["messages"] if m.get("kind") == "text")
    assert reply["text"] and not reply.get("error") and reply["model"].startswith("gemma-4")
    assert any(w in reply["text"].lower() for w in ("fidelidade", "qualidade", "modelo"))  # grounded in the manual we send


@needs_keys
def test_live_gemma_writes_the_reply_and_fills_the_prompt_box_for_a_task(api, monkeypatch):
    monkeypatch.setattr(cf_llm, "available", _ORIG_AVAILABLE)
    sid = api.post("/clonfield/api/sessions", json={}).json()["id"]
    api.post(f"/clonfield/api/sessions/{sid}/message", json={"text": "só uma foto", "media": [upload(api)]})
    wait_reply(api, sid)
    api.post(f"/clonfield/api/sessions/{sid}/message", json={"text": "dá um look de filme com bastante contraste nessa foto"})
    done = wait_reply(api, sid)
    plans = [m for m in done["messages"] if m.get("plan")]
    assert plans and plans[-1]["plan"]["steps"][0]["app"] == "look"
    last_reply = [m for m in done["messages"] if m.get("kind") == "text" and m.get("text")][-1]
    assert last_reply["text"] and "executado" not in last_reply["text"].lower()
    assert plans[-1]["plan"]["prompt"]  # editable box is never empty
