"""Variant integrity: one identity per FILE (provider, model, version, file, sha256, quantisation, size) and a refusal when the
list announces one thing and Civitai delivers another (the NVFP4 ~4 GB vs INT8 ~6.9 GB case)."""
import json
import struct
from pathlib import Path

import pytest
import requests

import cf_civitai as c
import cf_contracts as C
import cf_model_lab as lab
import cf_search

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "civitai_3034876.json").read_text(encoding="utf-8"))  # a real, recorded Civitai response
PRESET = lab.PRESETS["qwen21"]


def raw_safetensors(path, tensors):
    """Write a real safetensors file with arbitrary dtypes: tensors = {name: (dtype, shape)} filled with zero bytes."""
    sizes = {"I8": 1, "U8": 1, "F8_E4M3": 1, "F16": 2, "BF16": 2, "F32": 4}
    header, offset = {}, 0
    for name, (dtype, shape) in tensors.items():
        n = sizes[dtype]
        for dim in shape:
            n *= dim
        header[name] = {"dtype": dtype, "shape": list(shape), "data_offsets": [offset, offset + n]}
        offset += n
    blob = json.dumps(header).encode()
    blob += b" " * (-len(blob) % 8)
    Path(path).write_bytes(struct.pack("<Q", len(blob)) + blob + bytes(offset))
    return path


@pytest.mark.parametrize("name,key", [
    ("qwen-image-2.1-step90000-NVFP4-comfy.safetensors", "nvfp4"),
    ("qwen-image-2.1-step90000-INT8-ConvRot-comfy.safetensors", "int8"),
    ("qwen_image_2.1_turbo_int8_convrot.safetensors", "int8"),
    ("qwen-image-2.1-step90000-FP8-comfy.safetensors", "fp8"),
    ("qwen_image_v21_quant_mxfp8.safetensors", "mxfp8"),
    ("qwen_image_2.1_W6A8_g32.safetensors", "int6"),
    ("qwen_image_2.1W4A8.safetensors", "int4"),
    ("NoctQ_V4_int4_mixed.safetensors", "int4"),
    ("NoctQ_V4_bf16.safetensors", "bf16"),
    ("NoctQ_V4_fp16.safetensors", "fp16"),
    ("Qwen Image 2.1 – Vince Fidelity.safetensors", None),
])
def test_quantisation_is_read_from_the_real_file_names(name, key):
    assert c.quant_of(name) == key


def test_every_file_of_a_version_keeps_its_own_identity():
    version = FIXTURE["modelVersions"][0]
    entries = c.matching_files(FIXTURE, version, PRESET, "Difusão")
    by_quant = {e["quant"]: e for e in entries}
    assert {"nvfp4", "fp8", "int8"} <= set(by_quant)  # the .gguf files are not loadable by the worker and are not offered
    assert not any(e["name"].endswith(".gguf") for e in entries)
    nvfp4, int8 = by_quant["nvfp4"], by_quant["int8"]
    assert nvfp4["file"] != int8["file"] and nvfp4["sha256"] != int8["sha256"]
    assert 4.1e9 < nvfp4["size_bytes"] < 4.3e9 and 7.2e9 < int8["size_bytes"] < 7.3e9  # sizeKB is KiB: 4003 MiB = 4,2 GB
    assert by_quant["fp8"]["primary"] is True and nvfp4["primary"] is False  # Civitai's page highlights FP8; the card must not pretend otherwise
    assert all(e["version"] == 3448331 and e["model"] == 3034876 for e in entries)


def test_search_offers_one_item_per_file_with_the_variant_on_it(monkeypatch):
    listing = {"items": [FIXTURE], "metadata": {}}
    monkeypatch.setattr(c, "api_json", lambda endpoint, params=None: listing)  # replays a REAL recorded response
    monkeypatch.setattr(c, "inventory", lambda *a, **k: [])
    items, _ = cf_search.civitai_search("Difusão", "qwen21", Path("/nonexistent"), "nvfp4", None)
    nv = [i for i in items if i["variant"]["quant"] == "nvfp4"]
    i8 = [i for i in items if i["variant"]["quant"] == "int8"]
    assert nv and i8, [i["title"] for i in items]
    assert nv[0]["variant"]["file_id"] != i8[0]["variant"]["file_id"]
    assert "NVFP4" in nv[0]["title"] and "INT8" in i8[0]["title"]
    assert nv[0]["variant"]["size_bytes"] < 4.3e9 and i8[0]["variant"]["size_bytes"] > 7.2e9  # each card shows ITS file size, not files[0]'s
    assert abs(nv[0]["size_mb"] * 1e6 - nv[0]["variant"]["size_bytes"]) < 6e5  # and the unit is real MB (the old code multiplied MiB by 1e6)
    assert "modelVersionId=3448331" in nv[0]["url"]
    assert nv[0]["install"]["file"] == nv[0]["variant"]["file_id"]
    assert nv[0]["install"]["expect"]["quant"] == "nvfp4" and nv[0]["install"]["expect"]["size_bytes"] == nv[0]["variant"]["size_bytes"]


def entry(quant="nvfp4"):
    version = FIXTURE["modelVersions"][0]
    return next(e for e in c.matching_files(FIXTURE, version, PRESET, "Difusão") if e["quant"] == quant)


def test_delivery_check_accepts_what_was_announced():
    e = entry("int8")
    c.check_delivery(e, {"Content-Disposition": f'attachment; filename="{e["name"]}"', "Content-Length": str(e["size_bytes"])})
    c.check_delivery(e, {})  # nothing to compare is not a mismatch


def test_delivery_check_refuses_an_int8_file_announced_as_nvfp4():
    nv, i8 = entry("nvfp4"), entry("int8")
    with pytest.raises(ValueError) as caught:
        c.check_delivery(nv, {"Content-Disposition": f'attachment; filename="{i8["name"]}"', "Content-Length": str(i8["size_bytes"])})
    text = str(caught.value)
    assert "NVFP4" in text and "INT8" in text and "7,3 GB" in text and "4,2 GB" in text


def test_delivery_check_refuses_a_size_that_does_not_match():
    nv = entry("nvfp4")
    with pytest.raises(ValueError, match="tamanho"):
        c.check_delivery(nv, {"Content-Disposition": f'attachment; filename="{nv["name"]}"', "Content-Range": f"bytes 0-0/{nv['size_bytes'] * 2}"})


def test_entry_for_blocks_when_the_client_expected_another_variant(monkeypatch):
    monkeypatch.setattr(c, "api_json", lambda endpoint, params=None: FIXTURE)
    nv, i8 = entry("nvfp4"), entry("int8")
    good, _ = c.entry_for(PRESET, 3034876, 3448331, nv["file"], "Difusão", expect=dict(quant="nvfp4", size_bytes=nv["size_bytes"], name=nv["name"], sha256=nv["sha256"]))
    assert good["file"] == nv["file"]
    with pytest.raises(ValueError, match="divergência|Divergência"):
        c.entry_for(PRESET, 3034876, 3448331, i8["file"], "Difusão", expect=dict(quant="nvfp4", size_bytes=nv["size_bytes"], name=nv["name"], sha256=nv["sha256"]))


def test_sniffed_dtypes_catch_a_file_that_is_not_what_its_name_says(tmp_path):
    int8_file = raw_safetensors(tmp_path / "a.safetensors", {"transformer_blocks.0.attn.weight": ("I8", (64, 64)), "transformer_blocks.0.attn.scale": ("F16", (64,))})
    fp16_file = raw_safetensors(tmp_path / "b.safetensors", {"transformer_blocks.0.attn.weight": ("F16", (64, 64))})
    fp4_file = raw_safetensors(tmp_path / "c.safetensors", {"transformer_blocks.0.attn.weight": ("U8", (64, 32)), "transformer_blocks.0.attn.weight_scale": ("F8_E4M3", (64, 4)),
                                                         "transformer_blocks.0.attn.weight_scale_2": ("F32", (1,))})
    assert c.sniff_quant(int8_file) == "int8" and c.sniff_quant(fp16_file) == "fp16" and c.sniff_quant(fp4_file) == "nvfp4"
    c.verify_variant(int8_file, dict(entry("int8")))
    c.verify_variant(fp4_file, dict(entry("nvfp4")))
    with pytest.raises(ValueError, match="NVFP4"):
        c.verify_variant(int8_file, dict(entry("nvfp4")))  # announced NVFP4, the bytes are INT8
    with pytest.raises(ValueError, match="INT8"):
        c.verify_variant(fp16_file, dict(entry("int8")))


def test_contract_carries_the_variant_and_rejects_a_partial_one():
    variant = dict(provider="civitai", model_id=1, version_id=2, file_id=3, sha256="a" * 64, quant="nvfp4", size_bytes=10, file_name="x.safetensors")
    item = C.item("model", "1/2/3", "X", "civitai", "descoberto", variant=variant)
    assert item["variant"] == variant
    with pytest.raises(C.ContractError):
        C.item("model", "1/2/4", "Y", "civitai", "descoberto", variant=dict(provider="civitai"))


def online():
    try:
        return requests.head("https://civitai.com", timeout=5).status_code < 500
    except requests.RequestException:
        return False


@pytest.mark.skipif(not online(), reason="sem rede")
def test_live_real_delivery_headers_match_the_announced_file():
    """Real Civitai: a ranged request for one byte of a real file; the delivered name and total size must match the API record."""
    record = c.api_json("models/2970862")
    version = next(v for v in record["modelVersions"] if v["id"] == 3366607)
    e = c.matching_files(record, version, PRESET, "VAE")[0]
    with requests.Session() as s, c.request(s, e["download"], None, stream=True, byte_range="bytes=0-0", timeout=(5, 10)) as r:
        assert r.status_code == 206
        c.check_delivery(e, dict(r.headers))
    wrong = dict(e, name="qwen_image_2.1_turbo_int8_convrot.safetensors", quant="int8")
    with requests.Session() as s, c.request(s, e["download"], None, stream=True, byte_range="bytes=0-0", timeout=(5, 10)) as r:
        with pytest.raises(ValueError):
            c.check_delivery(wrong, dict(r.headers))


@pytest.mark.skipif(not online(), reason="sem rede")
def test_live_library_explore_lists_each_quantisation_as_its_own_card(tmp_path):
    """Real Civitai through the real /library endpoint: the NVFP4 and the INT8 file of one version are separate cards with their own size."""
    from starlette.testclient import TestClient
    import cf_api
    import cf_factory
    base = cf_factory.data().parent if cf_factory._state["data"] is not None else tmp_path
    client = TestClient(cf_api.build_app(base, base / "outputs", lambda t: t == "pw", "secret"), headers={"Authorization": "Bearer pw"})
    body = client.get("/clonfield/api/library", params=dict(kind="model", view="explore", family="qwen21", source="civitai", q="Uncensored Omni Quantized")).json()
    items = [i for i in body["items"] if i.get("variant")]
    assert items, body
    versions = {}
    for item in items:
        versions.setdefault((item["variant"]["model_id"], item["variant"]["version_id"]), []).append(item)
    many = [group for group in versions.values() if len({i["variant"]["file_id"] for i in group}) > 1]
    assert many, "nenhuma versão com vários arquivos apareceu como cartas separadas"
    group = many[0]
    assert len({i["variant"]["size_bytes"] for i in group}) > 1 or len({i["variant"]["quant"] for i in group}) > 1
    for item in group:
        install = next(a for a in item["actions"] if a["id"] == "install")
        assert install["call"]["body"]["file"] == item["variant"]["file_id"] and install["call"]["body"]["expect"]["name"] == item["variant"]["file_name"]
