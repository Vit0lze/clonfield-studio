"""Elenco: storage, @mentions, the references a mention adds, the API with real uploads, and the wiring into the image and video jobs."""

import io

import pytest
from PIL import Image
from starlette.testclient import TestClient

import cf_api
import cf_apps
import cf_cast as cast
import cf_jobs
import cf_tiers


def photo(path, size=(600, 900), color=(180, 90, 60)):
    Image.new("RGB", size, color).save(path)
    return str(path)


def test_add_validates_the_name_the_description_and_re_encodes_the_picture(tmp_path):
    item = cast.add(tmp_path, "@Marina", "  mulher de 30 anos,   cabelo ruivo ", photo(tmp_path / "big.jpg", (3000, 2000)))
    assert item["name"] == "Marina" and item["description"] == "mulher de 30 anos, cabelo ruivo"
    stored = Image.open(cast.image_path(tmp_path, item))
    assert max(stored.size) == cast.MAX_SIDE and stored.format == "PNG"
    for bad in ("a", "com espaço", "x" * 25, "", "ni$"):
        with pytest.raises(ValueError, match="nome"):
            cast.add(tmp_path, bad)
    with pytest.raises(ValueError, match="Já existe"):
        cast.add(tmp_path, "marina")  # names are unique ignoring case
    with pytest.raises(ValueError, match="descrição"):
        cast.add(tmp_path, "Longa", "x" * 401)
    with pytest.raises(ValueError, match="imagem"):
        (tmp_path / "bad.png").write_bytes(b"not an image")
        cast.add(tmp_path, "Quebrada", "", str(tmp_path / "bad.png"))
    assert [i["name"] for i in cast.load(tmp_path)] == ["Marina"]


def test_mentions_ignore_emails_and_double_at():
    assert cast.mentions("@Marina e @joão-pedro vão; @marina de novo") == ["Marina", "joão-pedro"]
    assert cast.mentions("escreva a@b.com ou @@literal") == []


def test_expand_describes_the_first_mention_only_and_collects_the_pictures_in_order(tmp_path):
    cast.add(tmp_path, "Marina", "mulher ruiva de jaqueta jeans.", photo(tmp_path / "a.png"))
    cast.add(tmp_path, "Leo", "garoto de boné", photo(tmp_path / "b.png", color=(10, 10, 200)))
    cast.add(tmp_path, "Rex", "cachorro caramelo")  # no picture
    out = cast.expand(tmp_path, "@Marina passeia com @Rex e @Leo; depois @marina ri", ref_slots=5)
    assert out["prompt"] == "Marina (mulher ruiva de jaqueta jeans) passeia com Rex (cachorro caramelo) e Leo (garoto de boné); depois Marina ri"
    assert out["used"] == ["Marina", "Rex", "Leo"] and [r.rsplit("/", 1)[-1][-4:] for r in out["refs"]] == [".png", ".png"] and len(out["refs"]) == 2
    assert out["refs"][0] != out["refs"][1] and out["dropped"] == []
    few = cast.expand(tmp_path, "@Marina e @Leo", ref_slots=1)
    assert len(few["refs"]) == 1 and few["dropped"] == ["Leo"]  # the description of both still goes in the text
    assert "garoto de boné" in few["prompt"] and cast.expand(tmp_path, "@Marina", ref_slots=0)["refs"] == []


def test_unknown_mention_is_refused_and_double_at_is_a_literal_at(tmp_path):
    cast.add(tmp_path, "Marina", "ruiva")
    with pytest.raises(ValueError, match=r"@Marnia não está no Elenco.*@@Marnia"):
        cast.expand(tmp_path, "@Marnia corre")
    assert cast.expand(tmp_path, "mande para @@Marnia hoje")["prompt"] == "mande para @Marnia hoje"
    assert cast.expand(tmp_path, "sem menção")["prompt"] == "sem menção"


def test_remove_deletes_the_picture(tmp_path):
    item = cast.add(tmp_path, "Marina", "", photo(tmp_path / "a.png"))
    path = cast.image_path(tmp_path, item)
    assert path.is_file()
    cast.remove(tmp_path, item["id"])
    assert not path.exists() and cast.load(tmp_path) == []
    with pytest.raises(ValueError, match="não encontrado"):
        cast.remove(tmp_path, item["id"])


# ---------------------------------------------------------------- the API
@pytest.fixture(scope="module")
def api(tmp_path_factory):
    import cf_factory
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path_factory.mktemp("cast")
    cf_apps.configure(base, base / "outputs")
    client = TestClient(cf_api.build_app(base, base / "outputs", lambda t: t == "pw", "secret"), headers={"Authorization": "Bearer pw"})
    client.base = base
    return client


def test_api_creates_from_a_real_upload_lists_serves_the_picture_and_deletes(api):
    buf = io.BytesIO()
    Image.new("RGB", (400, 600), (20, 120, 220)).save(buf, "PNG")
    upload = api.post("/clonfield/api/upload", files={"files": ("rosto.png", buf.getvalue(), "image/png")}).json()[0]
    made = api.post("/clonfield/api/cast/create", json={"name": "ApiHero", "description": "capa azul", "upload": upload["id"]})
    assert made.status_code == 200 and made.json()["name"] == "ApiHero"
    listed = [c for c in api.get("/clonfield/api/cast").json() if c["name"] == "ApiHero"][0]
    served = api.get(listed["image"])
    assert served.status_code == 200 and Image.open(io.BytesIO(served.content)).size == (400, 600)
    dup = api.post("/clonfield/api/cast/create", json={"name": "apihero"})
    assert dup.status_code == 400 and "Já existe" in dup.json()["detail"]
    assert api.post("/clonfield/api/cast/create", json={"name": "Sem", "upload": "zz"}).status_code == 400
    assert api.delete(f"/clonfield/api/cast/{listed['id']}").json() == {"ok": True}
    assert api.delete(f"/clonfield/api/cast/{listed['id']}").status_code == 400
    assert api.get("/clonfield/api/cast").status_code == 200 and not [c for c in api.get("/clonfield/api/cast").json() if c["name"] == "ApiHero"]
    assert TestClient(api.app).get("/clonfield/api/cast").status_code == 401  # signed in only


# ---------------------------------------------------------------- the jobs
class Ctx:
    control = None
    class job: id = "j"
    def progress(self, *a, **k): pass
    def check(self): pass


@pytest.fixture()
def world(tmp_path, monkeypatch):
    import cf_factory
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path
    cf_apps.configure(base, base / "outputs")
    for item in cast.load(base):
        cast.remove(base, item["id"])
    cast.add(base, "Marina", "mulher ruiva de jaqueta jeans", photo(tmp_path / "m.png"))
    ctx = Ctx()
    ctx.out_dir = tmp_path
    return base, ctx


def test_image_job_expands_the_mention_and_adds_the_picture_while_slots_are_free(world, monkeypatch):
    base, ctx = world
    seen = {}

    def fake(ctx, preset, p, files, width, height, count, progress_total=None):
        seen.update(prompt=p["prompt"], files=list(files), model=preset.key)
        return []
    monkeypatch.setattr(cf_apps, "run_graph_images", fake)
    monkeypatch.setattr(cf_apps, "reach_final_size", lambda ctx, outputs, plan, method: outputs)
    monkeypatch.setattr(cf_apps, "post_upscale", lambda ctx, outputs, choice: outputs)
    tier = cf_tiers.detect()
    cf_apps.run_image(ctx, dict(model="flux2", prompt="@Marina caminha na praia", refs=["/x/user.png"]), tier)
    assert seen["prompt"] == "Marina (mulher ruiva de jaqueta jeans) caminha na praia" and seen["files"][0] == "/x/user.png" and len(seen["files"]) == 2  # flux2 takes 2 references
    cf_apps.run_image(ctx, dict(model="flux2", prompt="@Marina de novo", refs=["/x/1.png", "/x/2.png"]), tier)
    assert seen["files"] == ["/x/1.png", "/x/2.png"]  # no free slot: description only
    cf_apps.run_image(ctx, dict(model="krea2", prompt="@Marina posa"), tier)
    assert seen["files"] == [] and "ruiva" in seen["prompt"]  # a model without reference slots still gets the words
    with pytest.raises(cf_jobs.JobError, match="não está no Elenco"):
        cf_apps.run_image(ctx, dict(model="flux2", prompt="@Fantasma"), tier)


def test_video_job_gets_the_description_in_the_encoder_text(world, monkeypatch):
    base, ctx = world
    seen = {}

    def run(graph, out_dir, progress, **kwargs):
        seen["text"] = graph["6"]["inputs"]["text"]
        raise cf_jobs.JobError("parou antes do ComfyUI", "falhou")
    monkeypatch.setattr(cf_apps.workflows, "run", run)
    job = dict(mode="Texto em vídeo", model="5b-q6", size="Horizontal · 512 × 288 (rápido)", seconds=2, steps=20, seed=3, negative="blur")
    with pytest.raises(cf_jobs.JobError, match="parou"):
        cf_apps.run_wan(ctx, dict(job, prompt="@Marina corre na neve"), cf_tiers.detect())
    assert seen["text"] == "Marina (mulher ruiva de jaqueta jeans) corre na neve"
