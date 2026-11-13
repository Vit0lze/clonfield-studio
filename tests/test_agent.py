"""The tool-calling agent. Loop mechanics are tested with a scripted model (clearly labelled). The wire format and the end-to-end path
are tested against a REAL local llama-server (CLONFIELD_LLAMA_URL), driving the real tools, DAG executor and job manager. On this
CPU-only machine that server runs a Qwen3.5-0.8B stand-in: it proves the protocol, NOT the quality of the 9B abliterated model."""
import json
import os
import shutil
import subprocess

import pytest
from PIL import Image, ImageDraw

import cf_agent as agent
import cf_apps
import cf_capabilities as caps
import cf_dag as dag
import cf_llm
import cf_jobs
import cf_tiers

LIVE = pytest.mark.skipif(not cf_llm.available(), reason="nenhum llama-server local rodando (defina CLONFIELD_LLAMA_URL)")


@pytest.fixture()
def world(tmp_path):
    import cf_factory
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path
    os.environ["CLONFIELD_FAKE_VRAM"] = "15"
    cf_apps.configure(base, base / "outputs")
    tier = cf_tiers.detect()
    registry = caps.Registry(cf_apps.registry(), tier)
    folder = tmp_path / "media"
    folder.mkdir()
    image = Image.new("RGB", (160, 120), (30, 40, 60))
    ImageDraw.Draw(image).ellipse((30, 20, 130, 100), fill=(220, 180, 120))
    image.save(folder / "foto.png")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=128x128:rate=8", "-pix_fmt", "yuv420p", str(folder / "clipe.mp4")], check=True)
    media = {"m-foto": dict(type="image", path=str(folder / "foto.png"), name="foto.png"), "m-clipe": dict(type="video", path=str(folder / "clipe.mp4"), name="clipe.mp4")}
    env = dag.Env(base, tmp_path / "out", tier, lambda ident: media.get(ident))
    manager = cf_jobs.Manager(env.out_dir, cpu_workers=1)
    attached = []
    host = agent.LocalHost(registry, env, manager, lambda: [dict(id=k, name=v["name"], kind=v["type"], origin="upload") for k, v in media.items()],
                           on_result=lambda files, job: attached.extend(str(f) for f in files), wait=90)
    box = type("W", (), {})()
    box.registry, box.env, box.manager, box.host, box.media, box.attached, box.tmp = registry, env, manager, host, media, attached, tmp_path
    box.tools = lambda allow_confirm=False: agent.Toolbox(registry, env, host, allow_confirm)
    return box


class Scripted:
    """A model that replays prepared tool calls. Used ONLY to test the loop (errors, repetition, limits), never to claim what a real model does."""
    name = "scripted"

    def __init__(self, turns):
        self.turns, self.seen = list(turns), []

    def step(self, system, messages, tools):
        self.seen.append(messages[-1])
        turn = self.turns.pop(0)
        return dict(text=turn.get("text", ""), calls=[dict(id=f"c{i}", name=n, args=a) for i, (n, a) in enumerate(turn.get("calls", []))])


def call(name, **args):
    return (name, args)


def graph(*nodes):
    return json.dumps({"nodes": list(nodes)})


def test_provider_wire_formats_carry_tool_calls_and_results():
    messages = [dict(role="user", text="oi"), dict(role="assistant", text="", calls=[dict(id="c1", name="list_media", args={})]), dict(role="tool", id="c1", name="list_media", result={"media": []})]
    wire = agent.OpenAICompatProvider.wire("sys", messages)
    assert wire[0]["role"] == "system" and wire[2]["tool_calls"][0]["function"]["name"] == "list_media" and wire[3]["tool_call_id"] == "c1"


def test_loop_recovers_from_an_invalid_graph_and_repeats_a_step(world):
    bad = graph({"id": "a", "cap": "upscale", "inputs": {"image": {"media": "m-clipe"}}})  # video into an image port
    good = graph({"id": "a", "cap": "upscale", "inputs": {"image": {"media": "m-foto"}}, "params": {"scale": 2}},
                 {"id": "b", "cap": "upscale", "inputs": {"image": {"from": "a.image"}}, "params": {"scale": 2}})  # the SAME capability twice
    model = Scripted([dict(calls=[call("validate_graph", graph_json=bad)]), dict(calls=[call("validate_graph", graph_json=good)]),
                      dict(calls=[call("execute_graph", graph_json=good)]), dict(text="Ampliei duas vezes.")])
    out = agent.run_agent(model, world.tools(), "amplie 2x duas vezes")
    assert out["stop"] == "resposta final" and out["final"] == "Ampliei duas vezes."
    first = json.loads(model.seen[1]["result"] if isinstance(model.seen[1]["result"], str) else json.dumps(model.seen[1]["result"]))
    assert first["ok"] is False and any("image" in e and "video" in e for e in first["errors"])  # the model got the reason back
    assert out["trace"][2]["ok"] and len(world.attached) == 1
    with Image.open(world.attached[0]) as result:
        assert result.size == (640, 480)  # 160x120, doubled twice by two real upscale nodes


def test_unknown_tool_and_tool_exceptions_go_back_to_the_model(world):
    model = Scripted([dict(calls=[call("fly_to_the_moon")]), dict(calls=[call("inspect_capability", id="nao_existe")]), dict(text="ok")])
    out = agent.run_agent(model, world.tools(), "x")
    assert "não existe" in out["trace"][0]["result"] and "não existe" in out["trace"][1]["result"] and out["stop"] == "resposta final"


def test_step_limit_stops_a_looping_model(world):
    model = Scripted([dict(calls=[call("list_media")])] * 5)
    out = agent.run_agent(model, world.tools(), "x", max_steps=3)
    assert out["stop"] == "limite de passos" and out["steps"] == 3


def test_high_risk_graph_needs_confirmation_and_creates_no_job(world):
    from types import SimpleNamespace
    big = dag.Env(world.env.base, world.env.out_dir, SimpleNamespace(vram_gb=200), world.env.resolve_media)  # only so the VRAM check does not pre-empt the risk gate
    g = graph({"id": "a", "cap": "app.openjutsu", "inputs": {p.name: {"media": "m-clipe" if p.type == "video" else "m-foto"} for p in world.registry.get("app.openjutsu").inputs if p.required}})
    before = len(world.manager.jobs)
    result = agent.Toolbox(world.registry, big, world.host).execute_graph(g)
    assert result["status"] == "needs_confirmation" and len(world.manager.jobs) == before
    small = world.tools().execute_graph(g)  # on the real 15 GB tier it is refused for the reason, before any risk question
    assert small["status"] == "invalid" and any("VRAM" in e for e in small["errors"])


def test_search_models_finds_real_civitai_variants_and_downloads_nothing(world):
    import requests
    try:
        requests.head("https://civitai.com", timeout=5)
    except requests.RequestException:
        pytest.skip("sem rede")
    found = world.tools().search_models("Difusão", "qwen21", "Uncensored Omni Quantized", "civitai")
    assert found["count"] and all(i["title"] and i["status"] in ("compatível", "instalado") for i in found["items"])
    assert any(i["quant"] for i in found["items"])
    with pytest.raises(ValueError):
        world.tools().search_models("Difusão", "qwen21", "x", "ftp")


def test_inspect_artifact_measures_a_real_result(world):
    g = graph({"id": "a", "cap": "look", "inputs": {"image": {"media": "m-foto"}}, "params": {"look": "Preto e branco", "strength": 100}})
    out = world.tools().execute_graph(g)
    assert out["status"] == "concluído" and out["outputs"][0]["type"] == "image"
    info = world.tools().inspect_artifact(out["outputs"][0]["ref"])
    assert info["width"] == 160 and {v["line"] for v in info["technical_gate"]} == {"not_blank", "sharp", "exposure"}


# ------------------------------------------------------------------ real local model, real tools, real jobs
@LIVE
def test_live_local_server_makes_a_native_tool_call():
    """Wire format: the server returns a structured tool call (name + JSON args) that the provider parses. A 0.8B stand-in sometimes answers in text
    instead of calling, so it gets 3 tries; what this proves is that the PROTOCOL works, not how reliably a small model chooses to use it."""
    provider = agent.OpenAICompatProvider()
    tools = [dict(name="list_capabilities", description="Lista capacidades do Studio", parameters={"type": "object", "properties": {"query": {"type": "string", "description": "palavras-chave"}}})]
    replies = [provider.step("Você opera um estúdio de mídia. Chame ferramentas.", [dict(role="user", text="Quais capacidades servem para ampliar imagem? Use a ferramenta.")], tools) for _ in range(3)]
    called = [r for r in replies if r["calls"]]
    assert called, "nenhuma das 3 respostas trouxe chamada de ferramenta estruturada"
    assert called[0]["calls"][0]["name"] == "list_capabilities" and isinstance(called[0]["calls"][0]["args"], dict)


@LIVE
def test_live_agent_loop_executes_real_tools_from_the_real_server_and_terminates(world):
    """Path: real server -> tool call -> real Toolbox/registry -> result back to the server -> loop ends. With a tiny stand-in the loop may stop at the
    step limit instead of answering; the quality of the answer is the 9B's job on the T4 and is NOT asserted here."""
    out = agent.run_agent(agent.OpenAICompatProvider(), world.tools(), "Quais capacidades do Studio servem para ampliar imagem? Só responda, não execute nada.", max_steps=4)
    assert out["stop"] in ("resposta final", "limite de passos") and out["provider"] == "llama-server"
    assert out["steps"] >= 1 and all(t["tool"] in world.tools().by_name for t in out["trace"])
    assert any(t["ok"] for t in out["trace"]), out["trace"]  # at least one tool really ran and returned data
    assert len(world.manager.jobs) == 0  # nothing was executed for a question


def test_choose_provider_is_none_without_a_local_server(monkeypatch):
    monkeypatch.setenv("CLONFIELD_LLAMA_URL", "http://127.0.0.1:9")  # nothing listens here
    cf_llm._health.update(at=0.0, ok=False)
    assert agent.choose_provider() is None
    cf_llm._health.update(at=0.0, ok=False)
