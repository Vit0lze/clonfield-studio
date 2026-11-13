"""Central capability registry: typed I/O, versions, requirements, validation state and who uses what. Real engines on CPU."""
import pytest

import cf_apps
import cf_capabilities as caps
import cf_tiers


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    import os
    import cf_factory
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path_factory.mktemp("caps")
    os.environ["CLONFIELD_FAKE_VRAM"] = "15"
    cf_apps.configure(base, base / "outputs")
    tier = cf_tiers.detect()
    return caps.Registry(cf_apps.registry(), tier), tier


def test_every_capability_declares_typed_io_version_requirements_and_validation(world):
    registry, _ = world
    assert len(registry.items) >= 7 + 15
    for cap in registry.items.values():
        assert cap.version and cap.kind in caps.KINDS and cap.source and cap.license, cap.id
        assert all(p.type in caps.MEDIA for p in (*cap.inputs, *cap.outputs)), cap.id
        assert cap.outputs, cap.id
        assert cap.validation["state"] in caps.STATES, cap.id
        assert set(cap.requires) >= {"vram_gb", "ram_gb", "disk_gb", "lane"}, cap.id


def test_no_gpu_claim_without_a_gpu_measurement(world):
    registry, _ = world
    for cap in registry.items.values():
        if cap.requires["lane"] == "gpu":
            assert cap.validation["state"] in ("BLOQUEADO_GPU", "CÓDIGO ESCRITO", "NÃO INICIADO"), (cap.id, cap.validation)
        assert cap.validation["state"] != "TESTADO GPU" and cap.validation["state"] != "INTEGRADO E VALIDADO", cap.id


def test_every_app_is_reachable_as_a_capability_with_types_from_its_form(world):
    registry, tier = world
    for app in cf_apps.registry().values():
        if app.hidden:
            continue
        cap = registry.get(f"app.{app.id}")
        files = [f for f in app.fields(tier) if f["type"] == "files"]
        assert [p.name for p in cap.inputs] == [f["id"] for f in files], app.id
    animate = registry.get("app.animate")
    assert animate.inputs[0].type == "image" and animate.outputs[0].type == "video"
    assert registry.get("app.openjutsu").risk == "high"


def test_bindings_point_at_real_apps_and_capabilities(world):
    registry, _ = world
    apps = cf_apps.registry()
    for cap_id, app_id, mode, note in caps.BINDINGS:
        assert cap_id in registry.items and app_id in apps, (cap_id, app_id)
        assert mode in ("app", "step", "insertion") and note
    for app_id, points in caps.INSERTION_POINTS:
        assert app_id in apps
        for point in points:
            assert all(c in registry.items for c in point["accepts"])


def test_shared_capabilities_have_at_least_two_consumers(world):
    registry, _ = world
    for cap_id in ("upscale", "quality_gate"):
        consumers = registry.describe(cap_id)["consumers"]
        assert len({c["app"] for c in consumers}) >= 2, (cap_id, consumers)
    assert {"app", "step"} <= {c["mode"] for c in registry.describe("upscale")["consumers"]}  # shared engine AND a step inside other apps
    assert any(i["app"] == "create" for i in registry.describe("upscale")["insertable_in"])


def test_catalog_filters_by_what_a_step_accepts_and_produces(world):
    registry, _ = world
    from_video = {c["id"] for c in registry.catalog(accepts="video")}
    assert "still" in from_video and "upscale" not in from_video
    makes_image = {c["id"] for c in registry.catalog(produces="image", kind="step")}
    assert {"look", "frame", "still"} <= makes_image
    assert [c["id"] for c in registry.catalog(query="ampliar")][:1] == ["upscale"]


def test_params_are_checked_with_reasons(world):
    registry, _ = world
    up = registry.get("upscale")
    assert caps.check_params(up, {"scale": 2, "sharpen": 10}) == []
    problems = " | ".join(caps.check_params(up, {"scale": 9, "mode": "inexistente", "nope": 1}))
    assert "scale" in problems and "mode" in problems and "nope" in problems
