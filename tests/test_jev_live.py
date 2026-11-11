"""Live Jev (TypeSafe) routing regression: 30 labelled requests (labels written by the maintainer, unambiguous by design)
plus multi-step plans. Skipped without a token in TYPESAFE_API_TOKEN / TYPESAFE_API_KEY / JEV_API_KEY."""
import pytest

import cf_apps
import cf_router as r
import cf_tiers

pytestmark = pytest.mark.skipif(not r.jev_token(), reason="no Jev token in the environment")
I, V = {"image"}, {"video"}
CASES = [
    ("uma capivara astronauta em estilo aquarela", set(), "create"), ("generate a cinematic photo of a rainy neon street", set(), "create"),
    ("desenha um logo minimalista de raposa", set(), "create"), ("troca a camisa dela por uma jaqueta de couro", I, "edit"),
    ("remove the car in the background", I, "edit"), ("mude o céu para pôr do sol mantendo o resto", I, "edit"),
    ("coloca uma luz laranja vindo da esquerda", I, "relight"), ("make the lighting dramatic with a blue rim light from behind", I, "relight"),
    ("pinta só a área do cabelo e deixa o resto", I, "region"), ("retouch only the masked area", I, "region"),
    ("faz essa foto se mexer, câmera aproximando devagar", I, "animate"), ("animate this portrait with subtle wind", I, "animate"),
    ("um clipe de um drone sobrevoando uma floresta", set(), "text2video"), ("a 5 second video of waves crashing at sunset", set(), "text2video"),
    ("aumenta a resolução dessa imagem em 2x", I, "upscale"), ("restaura essa foto antiga borrada e recupera os detalhes", I, "seedvr2"),
    ("separa esse desenho anime em camadas pra editar no photoshop", I, "seethrough"),
    ("decompose this anime character into transparent layers psd", I, "seethrough"),
    ("dá um look de filme com mais contraste e tom quente", I, "look"), ("recorta pra story do instagram 9:16", I, "frame"),
    ("crop this for a youtube thumbnail ratio", I, "frame"), ("corta do segundo 10 ao 20 desse vídeo", V, "clip"),
    ("trim the first 5 seconds", V, "clip"), ("extrai o frame do segundo 3", V, "still"),
    ("faz uma prancha com os principais momentos do vídeo", V, "board"), ("junta esses três clipes em um só", V, "sequence"),
    ("mostra antes e depois lado a lado", I, "compare"), ("troca a pessoa do vídeo pelo personagem da foto", {"video", "image"}, "openjutsu"),
    ("replace the actor in this clip with my character", {"video", "image"}, "openjutsu"),
]


@pytest.fixture(autouse=True)
def gpu(monkeypatch):
    monkeypatch.setenv("CLONFIELD_FAKE_VRAM", "96")


def test_jev_routes_labelled_requests_at_least_90_percent():
    registry, tier = cf_apps.registry(), cf_tiers.detect()
    misses = []
    for text, media, gold in CASES:
        got = r.route(text, media, registry, tier)
        assert got["provider"] == "jev", got["fallback"]
        if got["choice"] != gold:
            misses.append((text, gold, got["choice"]))
    assert len(misses) <= 3, misses


@pytest.mark.parametrize("request_text,media,expected", [
    ("troca a roupa dessa foto, depois amplia 2x e recorta pra story", I, ["edit", "upscale", "frame"]),
    ("faz um clipe de uma capivara surfando e corta só os 3 primeiros segundos", set(), ["text2video", "clip"]),
    ("só amplia 2x", I, ["upscale"]),
    ("make a video of a city at night then pick a still frame", set(), ["text2video", "still"]),
])
def test_jev_plans_chain_apps_without_padding(request_text, media, expected):
    plan = r.plan(request_text, media, cf_apps.registry(), cf_tiers.detect())
    assert [s["app"] for s in plan["steps"]] == expected and plan["complete"]
