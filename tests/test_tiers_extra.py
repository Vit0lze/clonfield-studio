import cf_tiers


def test_extra_comfy_flags_come_only_from_the_environment_and_only_as_flags(monkeypatch):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "15")
    monkeypatch.delenv("CLONFIELD_COMFY_EXTRA", raising=False)
    base = cf_tiers.detect().comfy_flags
    monkeypatch.setenv("CLONFIELD_COMFY_EXTRA", "--fast-disk  rm --disable-pinned-memory --use-pytorch-cross-attention")
    tier = cf_tiers.detect()
    assert tier.comfy_flags == base + ("--fast-disk", "--disable-pinned-memory")  # no stray words, no duplicate of a flag the tier already has
    assert tier.key == "leve"
