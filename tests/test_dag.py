"""Typed DAG: validation that explains, content-hash cache, partial re-run, cancel/resume, provenance, jobs. Real files, CPU."""
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

import cf_apps
import cf_capabilities as caps
import cf_dag as dag
import cf_jobs
import cf_tiers


class Ctx:
    """Minimal job context: progress sink + cancel flag. The Manager-driven test below uses the real cf_jobs.Context."""

    def __init__(self, cancel_after=None):
        self.cancel_after, self.calls, self.control = cancel_after, 0, SimpleNamespace(cancelled=False, prompt_id=None)

    def progress(self, fraction=None, desc=None, **_):
        pass

    def check(self):
        self.calls += 1
        if self.cancel_after is not None and self.calls > self.cancel_after:
            raise cf_jobs.JobError("Cancelado por você.", "cancelado")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    import os
    import cf_factory
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path_factory.mktemp("dag")
    os.environ["CLONFIELD_FAKE_VRAM"] = "15"
    cf_apps.configure(base, base / "outputs")
    tier = cf_tiers.detect()
    registry = caps.Registry(cf_apps.registry(), tier)
    media = {}
    folder = tmp_path_factory.mktemp("media")
    image = Image.new("RGB", (160, 120), (30, 40, 60))
    ImageDraw.Draw(image).ellipse((30, 20, 130, 100), fill=(220, 180, 120))
    ImageDraw.Draw(image).line((0, 0, 160, 120), fill=(255, 255, 255), width=3)
    image.save(folder / "a.png")
    image.save(folder / "copy_of_a.png")  # same bytes, other name
    Image.new("RGB", (160, 120), (200, 20, 20)).save(folder / "b.png")
    media["img-a"] = dict(type="image", path=str(folder / "a.png"))
    media["img-copy"] = dict(type="image", path=str(folder / "copy_of_a.png"))
    media["img-b"] = dict(type="image", path=str(folder / "b.png"))
    media["vid"] = dict(type="video", path=str(folder / "clip.mp4"))
    return registry, tier, media, base


def env_for(world, tmp_path):
    registry, tier, media, base = world
    return dag.Env(base, tmp_path / "out", tier, lambda ident: media.get(ident))


def chain():
    return {"nodes": [
        {"id": "look", "cap": "look", "inputs": {"image": {"media": "img-a"}}, "params": {"look": "Preto e branco", "strength": 100}},
        {"id": "big", "cap": "upscale", "inputs": {"image": {"from": "look.image"}}, "params": {"scale": 2}},
        {"id": "gate", "cap": "quality_gate", "inputs": {"image": {"from": "big.image"}}, "params": {}},
        {"id": "framed", "cap": "frame", "inputs": {"image": {"media": "img-a"}}, "params": {"ratio": next(iter(__import__("cf_finish").SIZES))}},
    ]}


def test_validation_explains_every_incompatibility(world, tmp_path):
    registry, tier, media, _ = world
    env = env_for(world, tmp_path)
    ok = dag.validate(chain(), registry, tier, env.resolve_media)
    assert ok["ok"] and ok["order"].index("look") < ok["order"].index("big") < ok["order"].index("gate")
    bad = {"nodes": [
        {"id": "a", "cap": "nao_existe", "inputs": {}},
        {"id": "b", "cap": "upscale", "inputs": {"image": {"media": "vid"}}},                       # video into an image port
        {"id": "c", "cap": "upscale", "inputs": {}},                                                  # missing input
        {"id": "d", "cap": "compare", "inputs": {"before": {"media": "img-a"}, "after": {"from": "zzz.image"}}},
        {"id": "e", "cap": "upscale", "inputs": {"image": {"media": "ghost"}}, "params": {"scale": 99}},
        {"id": "f", "cap": "gate_x", "inputs": {}}]}
    codes = {e["code"] for e in dag.validate(bad, registry, tier, env.resolve_media)["errors"]}
    assert {"unknown_capability", "type_mismatch", "missing_input", "unknown_source", "unresolved_media", "bad_param"} <= codes
    mismatch = next(e for e in dag.validate(bad, registry, tier, env.resolve_media)["errors"] if e["code"] == "type_mismatch")
    assert "image" in mismatch["message"] and "video" in mismatch["message"]  # says what was expected and what arrived


def test_cycle_and_not_enough_vram_are_refused_with_the_reason(world, tmp_path):
    registry, tier, media, _ = world
    env = env_for(world, tmp_path)
    cyc = {"nodes": [{"id": "x", "cap": "upscale", "inputs": {"image": {"from": "y.image"}}}, {"id": "y", "cap": "upscale", "inputs": {"image": {"from": "x.image"}}}]}
    assert "cycle" in {e["code"] for e in dag.validate(cyc, registry, tier, env.resolve_media)["errors"]}
    small = SimpleNamespace(vram_gb=4)
    heavy = next(c for c in registry.items.values() if c.requires["vram_gb"] > 4)
    graph = {"nodes": [{"id": "n", "cap": heavy.id, "inputs": {p.name: {"media": "img-a"} for p in heavy.inputs if p.required and p.type == "image"}}]}
    result = dag.validate(graph, registry, small, env.resolve_media)
    assert any(e["code"] == "resource" and "VRAM" in e["message"] for e in result["errors"]), result["errors"]


def test_chain_runs_for_real_and_records_provenance(world, tmp_path):
    registry, tier, media, _ = world
    env = env_for(world, tmp_path)
    run = dag.execute(chain(), registry, env, Ctx())
    assert run["status"] == "concluído" and set(run["recomputed"]) == {"look", "big", "gate", "framed"} and run["cached"] == []
    big = run["nodes"]["big"]["outputs"]["image"]
    with Image.open(big["path"]) as out:
        assert out.size == (320, 240)  # real 2x upscale of a real image
    gate = run["nodes"]["gate"]["outputs"]["report"]["value"]
    assert gate["verdicts"] and {"not_blank", "sharp", "exposure"} == {v["line"] for v in gate["verdicts"]}
    for nid, rec in run["nodes"].items():  # provenance: which capability version, which input hashes, which params
        assert rec["version"] == "1.0" and rec["hash"] and "capability" in rec
    assert run["nodes"]["big"]["inputs"]["image"] == [run["nodes"]["look"]["outputs"]["image"]["sha256"]]
    assert dag.load_run(env, run["id"])["status"] == "concluído"


def test_second_run_is_all_cache_and_a_changed_param_recomputes_only_its_branch(world, tmp_path):
    registry, tier, media, _ = world
    env = env_for(world, tmp_path)
    first = dag.execute(chain(), registry, env, Ctx())
    again = dag.execute(chain(), registry, env, Ctx())
    assert again["recomputed"] == [] and set(again["cached"]) == {"look", "big", "gate", "framed"}
    assert again["nodes"]["big"]["outputs"]["image"]["sha256"] == first["nodes"]["big"]["outputs"]["image"]["sha256"]
    changed = chain()
    changed["nodes"][1]["params"] = {"scale": 3}
    partial = dag.execute(changed, registry, env, Ctx())
    assert set(partial["recomputed"]) == {"big", "gate"} and set(partial["cached"]) == {"look", "framed"}  # partial re-run: look and framed untouched
    with Image.open(partial["nodes"]["big"]["outputs"]["image"]["path"]) as out:
        assert out.size == (480, 360)


def test_force_recomputes_a_node_and_its_descendants(world, tmp_path):
    registry, tier, media, _ = world
    env = env_for(world, tmp_path)
    dag.execute(chain(), registry, env, Ctx())
    forced = dag.execute(chain(), registry, env, Ctx(), force=["big"])
    assert set(forced["recomputed"]) == {"big", "gate"} and set(forced["cached"]) == {"look", "framed"}


def test_same_bytes_uploaded_twice_hit_the_same_cache(world, tmp_path):
    registry, tier, media, _ = world
    env = env_for(world, tmp_path)
    one = {"nodes": [{"id": "n", "cap": "upscale", "inputs": {"image": {"media": "img-a"}}, "params": {"scale": 2}}]}
    two = {"nodes": [{"id": "n", "cap": "upscale", "inputs": {"image": {"media": "img-copy"}}, "params": {"scale": 2}}]}
    assert dag.execute(one, registry, env, Ctx())["recomputed"] == ["n"]
    assert dag.execute(two, registry, env, Ctx())["cached"] == ["n"]  # content hash, not file name


def test_cancel_then_resume_reuses_what_finished(world, tmp_path):
    registry, tier, media, _ = world
    env = env_for(world, tmp_path)
    with pytest.raises(cf_jobs.JobError):
        dag.execute(chain(), registry, env, Ctx(cancel_after=2), run_id="resume-1")  # stops before the third node
    stopped = dag.load_run(env, "resume-1")
    assert stopped["status"] == "cancelado"
    done = [n for n, r in stopped["nodes"].items() if r["status"] == "concluído"]
    assert done and len(done) < 4
    resumed = dag.execute(chain(), registry, env, Ctx(), run_id="resume-1")
    assert resumed["status"] == "concluído" and resumed.get("resumed") is True
    assert set(done) <= set(resumed["cached"])  # nothing that finished ran again
    straight = dag.execute(chain(), registry, env_for(world, tmp_path / "other"), Ctx())
    assert resumed["nodes"]["gate"]["outputs"]["report"]["sha256"] == straight["nodes"]["gate"]["outputs"]["report"]["sha256"]


def test_a_whole_app_runs_as_a_node(world, tmp_path):
    registry, tier, media, _ = world
    env = env_for(world, tmp_path)
    graph = {"nodes": [{"id": "l", "cap": "app.look", "inputs": {"image": {"media": "img-a"}}, "params": {"look": "Cinema quente"}},
                       {"id": "c", "cap": "compare", "inputs": {"before": {"media": "img-a"}, "after": {"from": "l.result"}}}]}
    run = dag.execute(graph, registry, env, Ctx())
    assert run["status"] == "concluído"
    with Image.open(run["nodes"]["c"]["outputs"]["image"]["path"]) as sheet:
        assert sheet.width > 160 * 2


def test_dag_runs_as_a_real_job_and_publishes_its_files(world, tmp_path):
    registry, tier, media, _ = world
    env = env_for(world, tmp_path)
    manager = cf_jobs.Manager(env.out_dir, cpu_workers=1)
    box = {}

    def runner(ctx):
        box["run"] = dag.execute(chain(), registry, env, ctx)
        return dag.final_files(box["run"])

    job = manager.submit("dag", "teste", {}, "cpu", runner)
    for _ in range(150):
        if job.status in cf_jobs.FINAL:
            break
        time.sleep(0.2)
    assert job.status == "concluído", job.message
    assert job.results and all(r["path"].startswith("dag/cache/") for r in job.results)
    assert {r["kind"] for r in job.results} <= {"image"}
