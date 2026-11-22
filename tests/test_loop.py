"""Seam meter, with real encoded clips: a dot that goes round a circle (a true loop), the same dot that stops short (a visible jump), a still clip."""

import subprocess

import numpy as np
import pytest
from PIL import Image, ImageDraw

import cf_loop as loop


def clip(tmp_path, name, fraction, count=48, size=128):
    """A white dot on a dark background moving along a circle for `fraction` of a turn (1.0 = back where it started)."""
    folder = tmp_path / name
    folder.mkdir()
    for i in range(count):
        angle = 2 * np.pi * fraction * (i / count)
        x, y = size / 2 + 40 * np.cos(angle), size / 2 + 40 * np.sin(angle)
        image = Image.new("RGB", (size, size), (20, 24, 40))
        ImageDraw.Draw(image).ellipse((x - 10, y - 10, x + 10, y + 10), fill=(250, 240, 200))
        image.save(folder / f"f{i:03d}.png")
    out = tmp_path / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "24", "-i", str(folder / "f%03d.png"), "-pix_fmt", "yuv420p", "-crf", "12", str(out)], check=True)
    return out


def test_a_clip_that_returns_to_where_it_started_has_no_visible_seam(tmp_path):
    report = loop.seam(clip(tmp_path, "full", 1.0))
    assert report["ratio"] <= loop.GOOD and report["verdict"] == "sem emenda visível" and report["frames"] == 48


def test_a_clip_that_stops_short_has_a_visible_seam_and_the_numbers_say_how_much(tmp_path):
    full, half = loop.seam(clip(tmp_path, "full", 1.0)), loop.seam(clip(tmp_path, "half", 0.5))
    assert half["verdict"] == "emenda visível" and half["ratio"] > loop.OK and half["ratio"] > 4 * full["ratio"]
    assert "salta" in half["label"] and half["seam"] > half["baseline"]


def test_a_frozen_clip_is_reported_as_unmeasurable_not_as_a_perfect_loop(tmp_path):
    out = tmp_path / "still.mp4"
    Image.new("RGB", (128, 128), (40, 90, 160)).save(tmp_path / "s.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(tmp_path / "s.png"), "-t", "2", "-r", "24", "-pix_fmt", "yuv420p", str(out)], check=True)
    assert loop.seam(out)["verdict"] == "parado"


def test_unreadable_or_tiny_inputs_are_refused_with_the_reason(tmp_path):
    (tmp_path / "bad.mp4").write_bytes(b"not a video")
    with pytest.raises(loop.LoopError, match="quadros"):
        loop.seam(tmp_path / "bad.mp4")
    one = tmp_path / "one.mp4"
    Image.new("RGB", (64, 64), (1, 2, 3)).save(tmp_path / "o.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(tmp_path / "o.png"), "-frames:v", "2", "-pix_fmt", "yuv420p", str(one)], check=True)
    with pytest.raises(loop.LoopError, match="poucos"):
        loop.seam(one)


def test_loop_job_reports_the_measured_seam_in_the_job_message(tmp_path, monkeypatch):
    """run_wan with a seamless-loop request: after the (replaced) generation, the real clip is measured and the verdict lands in the job message."""
    import cf_apps
    import cf_tiers
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    good, bad = clip(tmp_path, "g", 1.0), clip(tmp_path, "b", 0.5)
    latent = tmp_path / "estagio1.latent"
    latent.write_bytes(b"x")
    # the A14B now runs two prompts per take (expert 1 saves a latent, expert 2 makes the clip): the replaced collect returns that pair each time
    made = iter([[latent], [good], [latent], [good], [latent], [bad]])
    monkeypatch.setattr(cf_apps.workflows, "run", lambda *a, **k: {"status": "concluído"})
    monkeypatch.setattr(cf_apps.workflows, "free_models", lambda *a, **k: None)
    monkeypatch.setattr(cf_apps, "collect_job", lambda ctx, job: next(made))

    class Job:
        message = ""
        id = "j"
        def update(self, **kw): self.message = kw.get("message", self.message)

    class Ctx:
        control = None
        out_dir = tmp_path
        job = Job()
        def progress(self, *a, **k): pass
        def check(self): pass
    base = dict(mode="Entre dois quadros", model="a14b-q4", prompt="loop", size="Horizontal · 512 × 288 (rápido)", seconds=2, steps=20, seed=3, image=["/x/a.png"], loop=True)
    ctx = Ctx()
    cf_apps.run_wan(ctx, dict(base), cf_tiers.detect())
    assert ctx.job.message.startswith("Emenda do loop: sem emenda visível")
    ctx.job.message = ""
    cf_apps.run_wan(ctx, dict(base, variations=2), cf_tiers.detect())  # two takes: the worst one is reported
    assert "emenda visível" in ctx.job.message and "pior de 2" in ctx.job.message
