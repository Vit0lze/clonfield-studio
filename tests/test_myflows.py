"""Meus fluxos: a graph the agent composed is saved as a reusable recipe (media -> form slots, chosen params -> fields) and runs on other files."""
import json
import subprocess

import pytest
from PIL import Image

import cf_myflows
import cf_recipes
from tests.test_agent import world  # noqa: F401
from tests.test_recipes_api import api, up  # noqa: F401
from tests.test_agent_api import BASE, wait_job


@pytest.fixture(autouse=True)
def clean(world):
    yield
    folder = cf_myflows.folder(world.env.base)
    for path in folder.glob("meu_*.json") if folder.is_dir() else []:
        path.unlink()


def second_clip(world):
    target = world.tmp / "media" / "clipe2.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=duration=2:size=128x128:rate=8", "-pix_fmt", "yuv420p", str(target)], check=True)
    world.media["m-clipe2"] = dict(type="video", path=str(target), name="clipe2.mp4")


def frames_graph(tools):
    return tools.compose_chain(json.dumps([
        dict(cap="video_frames", inputs=dict(video="m-clipe"), params=dict(every_s=0.25, max=3)),
        dict(cap="look", params=dict(look="Frio suave")),
        dict(cap="contact_sheet", params=dict(columns=3)),
    ]))["graph"]


def test_saved_flow_becomes_a_recipe_with_slots_and_exposed_fields_and_runs_on_other_media(world):
    second_clip(world)
    tools = world.tools()
    graph = frames_graph(tools)
    look_id = graph["nodes"][1]["id"]
    out = tools.save_flow(json.dumps(graph), "Folha de quadros fria", "Tira quadros e dá um look", json.dumps([dict(node=look_id, name="look", label="Look")]))
    assert out["saved"] and out["id"] == "meu_folha_de_quadros_fria"
    recipe = cf_recipes.get(out["id"], world.env.base)
    assert recipe.group == "Meus fluxos" and recipe.state == "CÓDIGO ESCRITO" and not recipe.gpu
    kinds = {i["id"]: i["kind"] for i in recipe.inputs}
    assert kinds == {"entrada_1": "video", f"p_{look_id}_look": "enum"}
    assert next(i for i in recipe.inputs if i["kind"] == "enum")["default"] == "Frio suave"
    entry = next(r for r in cf_recipes.catalog(world.env.base) if r["id"] == out["id"])
    assert entry["custom"] is True and entry["steps"] == 3
    assert not any(r["custom"] for r in cf_recipes.catalog(world.env.base) if r["id"] == "polir_lote")
    # the same flow on ANOTHER clip with another look, run for real through the agent tool
    ran = tools.run_recipe(out["id"], json.dumps(dict(entrada_1="m-clipe2", **{f"p_{look_id}_look": "Preto e branco"})))
    assert ran["runs"][0].get("status") != "invalid", ran
    built = cf_recipes.graph_for(out["id"], dict(entrada_1="m-clipe2", **{f"p_{look_id}_look": "Preto e branco"}), world.env.base)
    nodes = {n["id"]: n for n in built["nodes"]}
    assert nodes[graph["nodes"][0]["id"]]["inputs"]["video"] == {"media": "m-clipe2"} and nodes[look_id]["params"]["look"] == "Preto e branco"
    assert graph["nodes"][0]["inputs"]["video"] == {"media": "m-clipe"}  # the source graph is untouched
    listed = tools.list_recipes()["recipes"]
    assert any(r["id"] == out["id"] for r in listed)


def test_a_list_of_media_becomes_an_images_slot(world):
    import cf_recipes as recipes
    registry = world.registry
    world.media["m-foto2"] = world.media["m-foto"]
    graph = recipes.build_polish(dict(images=["m-foto", "m-foto2"], ratio="Quadrado · 1:1", look="Frio suave", strength=50))
    saved = cf_myflows.save(world.env.base, registry, graph, "Polir meu jeito", "", [dict(node="look", name="strength", label="Força")], world.env.resolve_media, world.env.tier)
    spec = next(i for i in saved["inputs"] if i["id"] == "entrada_1")
    assert spec["kind"] == "images" and spec["max"] == 16
    assert next(i for i in saved["inputs"] if i["id"].endswith("strength"))["kind"] == "number"
    rebuilt = cf_recipes.graph_for(saved["id"], dict(entrada_1=["m-foto", "m-foto", "m-foto2"], p_look_strength=20), world.env.base)
    assert rebuilt["nodes"][0]["inputs"]["image"] == [{"media": "m-foto"}, {"media": "m-foto"}, {"media": "m-foto2"}]
    assert rebuilt["nodes"][1]["params"]["strength"] == 20
    with pytest.raises(ValueError, match="envie de 1 a 16"):
        cf_recipes.graph_for(saved["id"], dict(entrada_1=[], p_look_strength=20), world.env.base)
    with pytest.raises(ValueError, match="use um número"):
        cf_recipes.graph_for(saved["id"], dict(entrada_1=["m-foto"], p_look_strength=500), world.env.base)


def test_saving_refuses_bad_input_in_plain_language(world):
    tools = world.tools()
    graph = frames_graph(tools)
    with pytest.raises(ValueError, match="Dê um nome"):
        tools.save_flow(json.dumps(graph), "x")
    with pytest.raises(ValueError, match="não é válido"):
        tools.save_flow(json.dumps({"nodes": [dict(id="a", cap="look")]}), "Sem entrada nenhuma")
    with pytest.raises(ValueError, match="não existe"):
        tools.save_flow(json.dumps(graph), "Expor o que não existe", "", json.dumps([dict(node="fantasma", name="look")]))
    with pytest.raises(ValueError, match="não tem o parâmetro"):
        tools.save_flow(json.dumps(graph), "Expor parâmetro falso", "", json.dumps([dict(node=graph["nodes"][1]["id"], name="nada")]))
    with pytest.raises(ValueError, match="não é JSON"):
        tools.save_flow(json.dumps(graph), "JSON quebrado aqui", "", "{")
    assert not list(cf_myflows.folder(world.env.base).glob("meu_*.json")) if cf_myflows.folder(world.env.base).is_dir() else True


def test_saving_again_replaces_and_a_damaged_file_does_not_hide_the_others(world):
    tools = world.tools()
    graph = frames_graph(tools)
    first = tools.save_flow(json.dumps(graph), "Meu fluxo repetido")
    again = tools.save_flow(json.dumps(graph), "Meu fluxo repetido")
    assert first["replaced"] is False and again["replaced"] is True
    (cf_myflows.folder(world.env.base) / "meu_quebrado.json").write_text("{nao é json", encoding="utf-8")
    assert list(cf_myflows.load(world.env.base)) == ["meu_meu_fluxo_repetido"]


def test_api_saves_lists_runs_and_deletes_a_flow_over_http(api):
    first, other = up(api, 1), up(api, 2)
    graph = {"nodes": [dict(id="warm", label="Dar o look", cap="look", inputs={"image": {"media": first}}, params=dict(look="Cinema quente", strength=60)),
                       dict(id="up", label="Ampliar", cap="upscale", inputs={"image": {"from": "warm.image"}}, params=dict(scale=2))]}
    bad = api.post(f"{BASE}/recipes", json=dict(graph=graph, title="x"))
    assert bad.status_code == 400 and "Dê um nome" in bad.json()["detail"]
    saved = api.post(f"{BASE}/recipes", json=dict(graph=graph, title="Look e ampliação", tagline="Dois passos", expose=[dict(node="warm", name="look", label="Look")]))
    assert saved.status_code == 201, saved.text
    rid = saved.json()["id"]
    try:
        items = api.get(f"{BASE}/recipes").json()
        mine = next(r for r in items if r["id"] == rid)
        assert mine["custom"] is True and mine["group"] == "Meus fluxos" and mine["steps"] == 2
        assert all(r["custom"] is False for r in items if r["id"] != rid)
        preview = api.post(f"{BASE}/recipes/{rid}/preview", json=dict(vars=dict(entrada_1=other, p_warm_look="Preto e branco"))).json()
        assert preview["ok"] and [s["label"] for s in preview["steps"]] == ["Dar o look", "Ampliar"]
        job = api.post(f"{BASE}/recipes/{rid}/run", json=dict(vars=dict(entrada_1=other, p_warm_look="Preto e branco"))).json()["jobs"][0]
        done = wait_job(api, job["id"])
        assert done["status"] == "concluído" and done["results"] and done["run"]
        run = api.get(f"{BASE}/dag/runs/{done['run']}").json()
        assert run["nodes"]["warm"]["status"] == "concluído" and run["graph"]["nodes"][0]["params"]["look"] == "Preto e branco"
        assert api.delete(f"{BASE}/recipes/polir_lote").status_code == 404  # built-in recipes cannot be deleted
    finally:
        assert api.delete(f"{BASE}/recipes/{rid}").status_code == 200
    assert api.delete(f"{BASE}/recipes/{rid}").status_code == 404
    assert rid not in {r["id"] for r in api.get(f"{BASE}/recipes").json()}


def test_api_revises_a_finished_run_from_one_step(api):
    first = up(api, 3)
    graph = {"nodes": [dict(id="warm", label="Dar o look", cap="look", inputs={"image": {"media": first}}, params=dict(look="Cinema quente")),
                       dict(id="cap", label="Legenda", cap="caption", inputs={"image": {"from": "warm.image"}}, params=dict(text="um"))]}
    plain = api.post(f"{BASE}/dag/run", json=dict(graph=graph)).json()
    assert wait_job(api, plain["id"])["run"]  # a plain graph job exposes its run record too
    saved = api.post(f"{BASE}/recipes", json=dict(graph=graph, title="Para refazer", expose=[dict(node="cap", name="text", label="Legenda")]))
    rid = saved.json()["id"]
    try:
        original = wait_job(api, api.post(f"{BASE}/recipes/{rid}/run", json=dict(vars=dict(entrada_1=first, p_cap_text="um"))).json()["jobs"][0]["id"])
        record = api.get(f"{BASE}/dag/runs/{original['run']}").json()
        assert record["status"] == "concluído"
        redo = api.post(f"{BASE}/dag/runs/{original['run']}/revise", json=dict(ops=[dict(op="set_param", node="cap", name="text", value="dois")], title="Para refazer · refeito"))
        assert redo.status_code == 202
        redone = wait_job(api, redo.json()["id"])
        assert redone["status"] == "concluído" and redone["run"] != original["run"]
        after = api.get(f"{BASE}/dag/runs/{redone['run']}").json()
        assert after["nodes"]["warm"]["status"] == "em cache" and after["nodes"]["cap"]["status"] == "concluído"  # the look was not redone
        assert api.post(f"{BASE}/dag/runs/{original['run']}/revise", json=dict(force=["fantasma"])).status_code == 400
        assert api.post(f"{BASE}/dag/runs/naoexiste/revise", json={}).status_code == 404
    finally:
        api.delete(f"{BASE}/recipes/{rid}")


def test_api_saves_a_finished_run_as_a_flow_and_reuses_it_on_another_file(api):
    first, other = up(api, 4), up(api, 5)
    graph = {"nodes": [dict(id="warm", label="Dar o look", cap="look", inputs={"image": {"media": first}}, params=dict(look="Frio suave")),
                       dict(id="cap", label="Legenda", cap="caption", inputs={"image": {"from": "warm.image"}}, params=dict(text="original"))]}
    done = wait_job(api, api.post(f"{BASE}/dag/run", json=dict(graph=graph)).json()["id"])
    assert done["status"] == "concluído"
    assert api.post(f"{BASE}/dag/runs/naoexiste/save", json=dict(title="Qualquer nome")).status_code == 404
    assert "Dê um nome" in api.post(f"{BASE}/dag/runs/{done['run']}/save", json=dict(title="")).json()["detail"]
    saved = api.post(f"{BASE}/dag/runs/{done['run']}/save", json=dict(title="Do chat para a fila", expose=[dict(node="cap", name="text", label="Legenda")]))
    assert saved.status_code == 201, saved.text
    rid = saved.json()["id"]
    try:
        again = wait_job(api, api.post(f"{BASE}/recipes/{rid}/run", json=dict(vars=dict(entrada_1=other, p_cap_text="outra"))).json()["jobs"][0]["id"])
        assert again["status"] == "concluído" and again["results"]
        record = api.get(f"{BASE}/dag/runs/{again['run']}").json()
        assert record["graph"]["nodes"][0]["inputs"]["image"] == {"media": other} and record["graph"]["nodes"][1]["params"]["text"] == "outra"
    finally:
        api.delete(f"{BASE}/recipes/{rid}")


def test_api_lists_the_settings_a_run_could_expose(api):
    first = up(api, 6)
    graph = {"nodes": [dict(id="warm", label="Dar o look", cap="look", inputs={"image": {"media": first}}, params=dict(look="Frio suave", strength=40)),
                       dict(id="cap", label="Legenda", cap="caption", inputs={"image": {"from": "warm.image"}}, params=dict(text="oi"))]}
    done = wait_job(api, api.post(f"{BASE}/dag/run", json=dict(graph=graph)).json()["id"])
    items = api.get(f"{BASE}/dag/runs/{done['run']}/exposable").json()
    assert {(i["node"], i["name"], i["type"]) for i in items} == {("warm", "look", "enum"), ("warm", "strength", "number"), ("cap", "text", "text")}
    assert next(i for i in items if i["name"] == "strength")["value"] == 40 and next(i for i in items if i["name"] == "look")["step"] == "Dar o look"
    assert api.get(f"{BASE}/dag/runs/naoexiste/exposable").status_code == 404
