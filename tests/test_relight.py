"""Pure logic of the light app and the framing options: real PIL files, no mocks."""
import cf_apps
import cf_tiers
from PIL import Image


def test_auto_framing_follows_first_reference(tmp_path):
    tier = cf_tiers.detect()
    wide = tmp_path / "wide.png"
    Image.new("RGB", (3000, 1000)).save(wide)
    width, height = cf_apps.dimensions("auto", "standard", tier, [wide])
    assert width > height and abs(width / height - 21 / 9) < 0.1
    assert cf_apps.dimensions("auto", "standard", tier) == cf_apps.dimensions("1:1", "standard", tier)


def test_light_prompt_describes_position_depth_and_colour():
    text = cf_apps.describe_light({"x": 0.1, "y": 0.1, "z": 0.9, "color": "#ff8a3d", "intensity": 80, "size": 20, "kind": "spot"})
    assert "orange" in text and "far left" in text and "in front of the subject" in text and "spotlight" in text
    back = cf_apps.describe_light({"x": 0.5, "y": 0.5, "z": 0.1, "color": "#3da0ff", "intensity": 30, "size": 90, "kind": "rim"})
    assert "blue" in back and "backlight" in back and "diffused" in back


def test_relight_app_only_offers_models_that_take_references():
    fields = {f["id"]: f for f in cf_apps.registry()["relight"].describe(cf_tiers.detect())["fields"]}
    assert fields["lights"]["min"] == 1 and fields["refs"]["max"] == 1
    assert {o["value"] for o in fields["model"]["options"]} <= {k for k, p in cf_apps.lab.PRESETS.items() if p.refs > 0}
