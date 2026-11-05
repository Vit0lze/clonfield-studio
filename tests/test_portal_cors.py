"""Public-front access: CORS preflight, Bearer login and lockout, through the real PortalAPI middleware."""
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from cf_portal import PortalAPI

ORIGIN = {"Origin": "https://painel.example"}


def client():
    inner = Starlette(routes=[Route("/", lambda request: PlainTextResponse("gradio"))])
    return TestClient(PortalAPI(inner, "user", "segredo-da-sessao"))


def test_preflight_and_login_allow_a_foreign_origin():
    http = client()
    pre = http.options("/clonfield/connect", headers={**ORIGIN, "Access-Control-Request-Method": "POST",
                                                         "Access-Control-Request-Headers": "authorization"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == "*"
    ok = http.post("/clonfield/connect", headers={**ORIGIN, "Authorization": "Bearer segredo-da-sessao"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "*" and ok.json()["token"]


def test_wrong_password_is_refused_then_locked_out():
    http = client()
    codes = [http.post("/clonfield/connect", headers={"Authorization": "Bearer errada"}).status_code for _ in range(10)]
    assert codes[:8] == [401] * 8 and codes[8:] == [429, 429]
    assert http.post("/clonfield/connect", headers={"Authorization": "Bearer segredo-da-sessao"}).status_code == 429
