"""Folha de personagem: prompts, padding without cropping, the labelled sheet (real images), and the app's orchestration with the generation
call replaced by a function that writes a real PNG (the model itself needs a GPU)."""

import numpy as np
import pytest
from PIL import Image

import cf_apps
import cf_character as character
import cf_jobs
import cf_tiers


def png(path, size, color):
    Image.new("RGB", size, color).save(path)
    return str(path)


def test_every_view_names_what_stays_and_the_one_thing_that_changes():
    for key, (title, chosen) in character.SETS.items():
        assert len(chosen) in (4, 8) and len({v[0] for v in chosen}) == len(chosen), key
        for view in chosen:
            text = character.prompt_for(view)
            assert view[2] in text and "face, hair, skin, outfit" in text and "grey studio background" in text
    assert [v[0] for v in character.views("full")] == [v[0] for v in character.TURNAROUND + character.EXPRESSIONS]
    with pytest.raises(ValueError):
        character.views("nope")


def test_user_notes_are_appended_trimmed_and_whitespace_collapsed():
    view = character.TURNAROUND[0]
    assert character.prompt_for(view, "  cicatriz   no olho\nesquerdo ").endswith("Also keep: cicatriz no olho esquerdo.")
    assert "Also keep" not in character.prompt_for(view, "   ")
    assert len(character.prompt_for(view, "x" * 2000)) < len(character.prompt_for(view)) + 330


def test_fit_pads_a_tall_figure_instead_of_cropping_it(tmp_path):
    tall = Image.new("RGB", (200, 800), (255, 0, 0))
    out = character.fit(tall, (768, 1152))
    assert out.size == (768, 1152)
    pixels = np.asarray(out)
    assert pixels[0, 0].tolist() == list(character.BACKGROUND) and pixels[1151, 383].tolist() == [255, 0, 0]  # side bars are grey; head and feet row both present
    red = np.argwhere((pixels == [255, 0, 0]).all(axis=2))
    assert red[:, 0].min() == 0 and red[:, 0].max() == 1151  # the figure touches the top and bottom edges: nothing cut
    wide = character.fit(Image.new("RGB", (900, 300), (0, 0, 255)), (768, 1152))
    assert np.asarray(wide)[0, 0].tolist() == list(character.BACKGROUND) and np.asarray(wide)[576, 384].tolist() == [0, 0, 255]


def test_sheet_lays_views_in_a_grid_with_labels(tmp_path):
    pics = [(name, png(tmp_path / f"{i}.png", (384, 576), (40 * i + 20, 90, 200 - 20 * i))) for i, name in enumerate(["Frente", "3/4", "Perfil", "Costas", "Alegre", "Triste"])]
    image = character.sheet(pics, columns=4)
    cell = round(384 * character.CELL_HEIGHT / 576)
    assert image.size == (4 * cell + 5 * character.GAP, 2 * (character.CELL_HEIGHT + character.LABEL) + 3 * character.GAP)
    arr = np.asarray(image)
    assert arr[character.GAP + 10, character.GAP + 10].tolist() == [20, 90, 200]  # first picture at the top-left of the grid
    label_band = arr[character.GAP + character.CELL_HEIGHT + 2: character.GAP + character.CELL_HEIGHT + character.LABEL, character.GAP: character.GAP + cell]
    assert len({tuple(p) for p in label_band.reshape(-1, 3)}) > 3  # a label was drawn under it
    with pytest.raises(ValueError):
        character.sheet([])


@pytest.fixture()
def world(tmp_path, monkeypatch):
    import cf_factory
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path
    cf_apps.configure(base, base / "outputs")
    calls = []

    def fake(ctx, preset, p, files, width, height, count, progress_total=None):
        calls.append(dict(model=preset.key, prompt=p["prompt"], seed=p["seed"], files=files, size=(width, height)))
        return [png(ctx.out_dir / f"v{len(calls)}.png", (width, height), (30 * len(calls), 100, 150))]
    monkeypatch.setattr(cf_apps, "run_graph_images", fake)

    class Ctx:
        out_dir = base / "char-out"
        class job: id = "jobx"
        def progress(self, *a, **k): pass
        def check(self): pass
    Ctx.out_dir.mkdir(exist_ok=True)
    return calls, Ctx, base


def test_app_edits_the_same_padded_reference_once_per_view_with_one_seed(world, tmp_path):
    calls, Ctx, _ = world
    source = png(tmp_path / "hero.png", (300, 900), (200, 50, 50))
    out = cf_apps.run_character_sheet(Ctx(), dict(image=[source], set="turnaround", notes="colar dourado", model="qwen21-turbo", size="Vertical · 768 × 1152", seed=42), cf_tiers.detect())
    assert [c["model"] for c in calls] == ["qwen21-turbo"] * 4 and {c["seed"] for c in calls} == {42}
    assert len({c["files"][0] for c in calls}) == 1 and Image.open(calls[0]["files"][0]).size == (768, 1152)  # one reference, padded to the canvas
    assert [c["prompt"] for c in calls][2].startswith("Show this character in full side profile") and all("colar dourado" in c["prompt"] for c in calls)
    assert len(out) == 5 and out[0].name.startswith("folha-personagem") and Image.open(out[0]).width > 768


def test_app_refuses_without_an_image_and_falls_back_to_the_base_model_for_an_unknown_one(world, tmp_path):
    calls, Ctx, _ = world
    with pytest.raises(cf_jobs.JobError, match="imagem"):
        cf_apps.run_character_sheet(Ctx(), dict(set="turnaround"), cf_tiers.detect())
    with pytest.raises(cf_jobs.JobError, match="vistas"):
        cf_apps.run_character_sheet(Ctx(), dict(image=[png(tmp_path / "a.png", (64, 64), (1, 2, 3))], set="x"), cf_tiers.detect())
    cf_apps.run_character_sheet(Ctx(), dict(image=[png(tmp_path / "b.png", (64, 64), (1, 2, 3))], set="expressions", model="flux2", seed=1), cf_tiers.detect())
    assert {c["model"] for c in calls} == {"qwen21"} and len(calls) == 4


def test_app_is_registered_and_not_blocked_on_a_small_card(monkeypatch):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    app = cf_apps.registry()["character_sheet"]
    described = app.describe(cf_tiers.detect())
    assert described["group"] == "Identidade" and not described["blocked"] and {f["id"] for f in described["fields"]} >= {"image", "set", "notes", "model", "size"}
