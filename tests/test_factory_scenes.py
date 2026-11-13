"""Content Factory `states` mode with scenes from the Studio's own generator (no paid API): the real vendored engine runs its real `frames`
stage; only the image generator is a stand-in (a PIL painter), because ComfyUI needs a GPU. What is verified is the wiring: which provider the
engine is told to use, what each scene is asked for (prompt, references), the stage cache and the 9:16 crops."""
import copy

import pytest
from PIL import Image, ImageDraw

pytest.importorskip("jsonschema")
pytest.importorskip("yaml")
import cf_factory as factory  # noqa: E402


@pytest.fixture(scope="module")
def configured(tmp_path_factory):
    if factory._state["data"] is None:
        factory.configure(tmp_path_factory.mktemp("cfbase"))
    return factory.data().parent


class Painter:
    """Stand-in generator: paints a distinct image per call and records what the engine asked for."""

    def __init__(self):
        self.calls = []

    def __call__(self, prompt, shape, refs, out):
        self.calls.append(dict(prompt=prompt, shape=shape, refs=[str(r) for r in refs], out=str(out)))
        image = Image.new("RGB", (768, 1152) if shape == "v" else (1152, 768), (len(self.calls) * 20 % 255, 60, 90))
        ImageDraw.Draw(image).text((20, 20), prompt[:30], fill=(255, 255, 255))
        image.save(out)


@pytest.fixture()
def painter():
    p = Painter()
    factory.set_image_generator(p)
    yield p
    factory.set_image_generator(None)


def states_script():
    script = factory.example_script(mode="states")
    script["voice"] = False
    return script


def test_states_scenes_come_from_the_local_worker_only_and_later_scenes_are_edits_of_the_first(configured, painter, monkeypatch):
    import factory.stages.frames as frames_stage
    seen = {}
    real = frames_stage.run_jobs

    def spy(jobs, workers, *a, **k):
        seen.setdefault("workers", []).append(dict(workers))
        return real(jobs, workers, *a, **k)
    monkeypatch.setattr(frames_stage, "run_jobs", spy)
    monkeypatch.setenv("OPENAI_API_KEY", "x")  # a paid key in the environment must not make the engine pick that provider
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    slug = factory.create(copy.deepcopy(states_script()), "Cenas locais")
    factory.run(slug, names=["frames"])
    assert seen["workers"] and all(w == {"clonfield": 1} for w in seen["workers"])
    beats = len(states_script()["beats"])
    assert len(painter.calls) == beats
    first, later = painter.calls[0], painter.calls[1:]
    assert first["refs"] == [] and all(first["out"] in c["refs"] for c in later)  # scene 2..n are edits of scene 1
    from factory.core import Episode
    frames = Episode.load(slug).work("frames")
    assert len(list(frames.glob("*-916.png"))) == beats  # every scene cropped to 9:16


def test_scenes_are_cached_per_prompt_so_editing_one_beat_regenerates_one_scene(configured, painter):
    script = states_script()
    slug = factory.create(copy.deepcopy(script), "Cache de cenas")
    factory.run(slug, names=["frames"])
    first_run = len(painter.calls)
    factory.run(slug, names=["frames"])
    assert len(painter.calls) == first_run  # nothing changed: no scene is made again
    edited = copy.deepcopy(script)
    key = next(k for k in ("state", "caption") if k in edited["beats"][2])
    edited["beats"][2][key] = str(edited["beats"][2][key]) + " — com um detalhe novo"
    slug2 = factory.create(edited, "Cache de cenas")
    assert slug2 == slug
    factory.run(slug, names=["frames"])
    assert len(painter.calls) in (first_run + 1,), len(painter.calls) - first_run  # exactly the edited beat


def test_drawn_mode_and_no_generator_never_use_any_image_provider(configured, monkeypatch):
    factory.set_image_generator(None)
    from factory.providers.image import private
    assert private.available() == {}
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    slug = factory.create(copy.deepcopy(factory.example_script()), "Desenhado")
    status = factory.status(slug)
    assert status is not None  # the drawn example plans without an image worker


def test_a_generator_that_writes_nothing_fails_the_scene_with_a_reason(configured):
    factory.set_image_generator(lambda prompt, shape, refs, out: None)
    try:
        slug = factory.create(copy.deepcopy(states_script()), "Sem arquivo")
        with pytest.raises(SystemExit, match="style frame failed"):
            factory.run(slug, names=["frames"])
    finally:
        factory.set_image_generator(None)
