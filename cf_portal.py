"""Authenticate the static Studio client on the existing Gradio API."""

from hmac import compare_digest
from secrets import token_urlsafe

from starlette.datastructures import Headers
from starlette.responses import JSONResponse


class PortalAPI:
    def __init__(self, app, username, password):
        self.app = app
        self.username = username
        self.password = password.encode()
        self.token = token_urlsafe(32)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        authorization = Headers(scope=scope).get("authorization", "")
        scheme, _, bearer = authorization.partition(" ")
        secret = bearer.encode("latin-1")
        headers = {"Cache-Control": "no-store"}
        if path == "/clonfield/connect" and scope["method"] == "POST":
            if scheme.lower() == "bearer" and compare_digest(secret, self.password):
                response = JSONResponse({"token": self.token}, headers=headers)
            else:
                response = JSONResponse({"detail": "Senha da sessão inválida."}, status_code=401, headers=headers)
            await response(scope, receive, send)
            return

        if authorization and (path == "/config" or path.startswith("/gradio_api/")):
            if scheme.lower() != "bearer" or not compare_digest(secret, self.token.encode()):
                response = JSONResponse({"detail": "Sessão inválida. Conecte novamente."},
                                        status_code=401, headers=headers)
                await response(scope, receive, send)
                return
            gradio_app = scope["app"]
            gradio_app.tokens[self.token] = self.username
            cookie = f"access-token-{gradio_app.cookie_id}={self.token}".encode()
            scope = {**scope, "headers": [*(pair for pair in scope["headers"] if pair[0] != b"cookie"),
                                          (b"cookie", cookie)]}

        await self.app(scope, receive, send)
