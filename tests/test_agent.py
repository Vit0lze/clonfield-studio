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
    small = world.tools().execute_graph(g)  # on the 15 GB tier it is no longer refused for VRAM (it offloads, slowly): the risk gate still stops it
    assert small["status"] == "needs_confirmation" and len(world.manager.jobs) == before


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
    assert out["stop"] in ("resposta final", "limite de passos") and out["provider"] in ("llama-server", "colibri")
    assert out["steps"] >= 1 and all(t["tool"] in world.tools().by_name for t in out["trace"])
    assert any(t["ok"] for t in out["trace"]), out["trace"]  # at least one tool really ran and returned data
    assert len(world.manager.jobs) == 0  # nothing was executed for a question


def test_choose_provider_is_none_without_a_local_server(monkeypatch):
    monkeypatch.setenv("CLONFIELD_LLAMA_URL", "http://127.0.0.1:9")  # nothing listens here
    cf_llm._health.update(at=0.0, ok=False)
    assert agent.choose_provider() is None
    cf_llm._health.update(at=0.0, ok=False)


def test_system_info_and_free_memory_say_so_when_the_worker_is_down(world, monkeypatch):
    import cf_workflows
    monkeypatch.setattr(cf_workflows, "SERVER", "http://127.0.0.1:9")  # nothing listens here
    info = world.tools().system_info()
    assert info["gpu"] and info["vram_gb"] == 15.0 and info["disk_free_gb"] > 0 and info["worker"] is None and "não respondeu" in info["worker_note"]
    assert world.tools().free_memory() == dict(ok=False, note="o ComfyUI não respondeu; nada foi descarregado")
    assert {"system_info", "free_memory"} <= set(world.tools().by_name)


def test_list_cast_gives_the_agent_the_names_to_mention(world):
    import cf_cast
    for item in cf_cast.load(world.env.base):
        cf_cast.remove(world.env.base, item["id"])
    assert world.tools().list_cast() == dict(count=0, cast=[])
    cf_cast.add(world.env.base, "Marina", "mulher ruiva", None)
    out = world.tools().list_cast()
    assert out["count"] == 1 and out["cast"][0] == dict(name="Marina", mention="@Marina", description="mulher ruiva", has_image=False)
    assert "list_cast" in world.tools().by_name
    cf_cast.remove(world.env.base, cf_cast.load(world.env.base)[0]["id"])


def test_agent_lists_and_runs_recipes_as_a_queue(world):
    tools = world.tools()
    listed = tools.list_recipes()["recipes"]
    assert {"polir_lote", "storyboard_em_filme"} <= {r["id"] for r in listed}
    one = tools.run_recipe("looks_lado_a_lado", json.dumps(dict(image="m-foto", strength=80)))
    assert len(one["runs"]) == 1 and one["runs"][0].get("status") != "invalid", one
    queue = tools.run_recipe("looks_lado_a_lado", json.dumps([dict(image="m-foto", strength=40), dict(image="m-foto", strength=90)]))
    assert len(queue["runs"]) == 2
    with pytest.raises(ValueError, match="não existe"):
        tools.run_recipe("nada", "{}")
    with pytest.raises(ValueError, match="envie uma imagem"):
        tools.run_recipe("looks_lado_a_lado", json.dumps(dict(strength=50)))
    with pytest.raises(ValueError, match="1 a 12"):
        tools.run_recipe("looks_lado_a_lado", json.dumps([dict(image="m-foto", strength=50)] * 13))


def test_compose_chain_links_image_upscale_video_and_picks_models(world):
    tools = world.tools()
    out = tools.compose_chain(json.dumps([
        dict(cap="app.create", params=dict(prompt="uma raposa no outono", quality="high", model="qwen21-turbo")),
        dict(cap="upscale", params=dict(scale=2)),
        dict(cap="app.animate", params=dict(prompt="vento nas folhas", model="5b-q6", fast=True)),
    ]))
    assert out["ok"], out["errors"]
    nodes = out["graph"]["nodes"]
    assert [n["cap"] for n in nodes] == ["app.create", "upscale", "app.animate"]
    assert nodes[1]["inputs"] == {"image": {"from": f"{nodes[0]['id']}.result"}}
    assert nodes[2]["inputs"] == {"image": {"from": f"{nodes[1]['id']}.image"}}
    assert out["resources"]["lane"] == "gpu"
    bad = tools.compose_chain(json.dumps([dict(cap="app.create", params=dict(prompt="x", model="modelo-que-nao-existe"))]))
    assert not bad["ok"] and "modelo-que-nao-existe" in bad["errors"][0]
    with pytest.raises(ValueError, match="não aceita o que"):
        tools.compose_chain(json.dumps([dict(cap="look", inputs=dict(image="m-foto")), dict(cap="video_join")]))
    with pytest.raises(ValueError, match="não existe no catálogo"):
        tools.compose_chain(json.dumps([dict(cap="app.nada")]))


def test_compose_chain_fans_out_lists_and_runs_cpu_chains_for_real(world):
    tools = world.tools()
    out = tools.compose_chain(json.dumps([
        dict(cap="video_frames", inputs=dict(video="m-clipe"), params=dict(every_s=0.25, max=3)),
        dict(cap="look", params=dict(look="Frio suave")),
        dict(cap="contact_sheet", params=dict(columns=3)),
    ]), run="sim")
    assert out["ok"], out["errors"]
    nodes = out["graph"]["nodes"]
    assert nodes[1]["each"] == "image" and "each" not in nodes[2]  # one look per frame, then the list folds into one sheet
    assert out["execution"].get("status") != "invalid", out["execution"]


def test_edit_graph_revises_a_flow_without_rewriting_it(world):
    tools = world.tools()
    base = tools.compose_chain(json.dumps([
        dict(cap="video_frames", inputs=dict(video="m-clipe"), params=dict(every_s=0.25, max=3)),
        dict(cap="look", params=dict(look="Frio suave")),
        dict(cap="contact_sheet", params=dict(columns=3)),
    ]))["graph"]
    look_id, sheet_id = base["nodes"][1]["id"], base["nodes"][2]["id"]
    out = tools.edit_graph(json.dumps(base), json.dumps([
        dict(op="set_param", node=look_id, name="look", value="Cinema quente"),
        dict(op="insert_after", node=look_id, cap="frame", params=dict(ratio="Quadrado · 1:1"), id="quadro"),
        dict(op="insert_after", node="quadro", cap="caption", params=dict(text="plano"), id="legenda"),
    ]))
    assert out["ok"], out["errors"]
    nodes = {n["id"]: n for n in out["graph"]["nodes"]}
    assert nodes[look_id]["params"]["look"] == "Cinema quente"
    assert nodes["quadro"]["each"] == "image" and nodes["legenda"]["each"] == "image"
    assert nodes[sheet_id]["inputs"]["images"] == {"from": "legenda.image"}  # the sheet now reads the last inserted step
    assert [n["id"] for n in out["graph"]["nodes"]] == [base["nodes"][0]["id"], look_id, "quadro", "legenda", sheet_id]
    assert base["nodes"][1]["params"]["look"] == "Frio suave"  # the original graph is untouched
    removed = tools.edit_graph(json.dumps(out["graph"]), json.dumps([dict(op="remove", node="quadro")]))
    assert removed["ok"] and {n["id"]: n for n in removed["graph"]["nodes"]}["legenda"]["inputs"]["image"] == {"from": f"{look_id}.image"}
    swapped = tools.edit_graph(json.dumps(base), json.dumps([dict(op="replace_cap", node=look_id, cap="caption", params=dict(text="oi"))]))
    assert swapped["ok"] and swapped["graph"]["nodes"][1]["cap"] == "caption"
    ran = tools.edit_graph(json.dumps(base), json.dumps([dict(op="set_param", node=look_id, name="strength", value=40)]), run="sim")
    assert ran["execution"].get("status") != "invalid", ran["execution"]


def test_edit_graph_refuses_what_it_cannot_do(world):
    tools = world.tools()
    base = tools.compose_chain(json.dumps([dict(cap="look", inputs=dict(image="m-foto")), dict(cap="upscale")]))["graph"]
    a, b = base["nodes"][0]["id"], base["nodes"][1]["id"]
    with pytest.raises(ValueError, match="não existe no grafo"):
        tools.edit_graph(json.dumps(base), json.dumps([dict(op="set_param", node="fantasma", name="x", value=1)]))
    with pytest.raises(ValueError, match="não recebe e devolve"):
        tools.edit_graph(json.dumps(base), json.dumps([dict(op="insert_after", node=a, cap="video_join")]))
    with pytest.raises(ValueError, match="operação «gira» desconhecida"):
        tools.edit_graph(json.dumps(base), json.dumps([dict(op="gira", node=a)]))
    with pytest.raises(ValueError, match="falta o campo"):
        tools.edit_graph(json.dumps(base), json.dumps([dict(op="set_param", node=a)]))
    bad = tools.edit_graph(json.dumps(base), json.dumps([dict(op="set_param", node=b, name="scale", value=99)]))
    assert not bad["ok"] and "scale" in bad["errors"][0]  # edit applies, validation still speaks
    # removing the first step: the second one reads the media the first read
    gone = tools.edit_graph(json.dumps(base), json.dumps([dict(op="remove", node=a)]))
    assert gone["ok"] and gone["graph"]["nodes"][0]["inputs"]["image"] == {"media": "m-foto"}
