"""Authenticate the static Studio client on the existing Gradio API."""

from hmac import compare_digest
from secrets import token_urlsafe

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.responses import JSONResponse, Response


class PortalAPI:
    def __init__(self, app, username, password, engine_paths=None):
        self.app = app
        self.username = username
        self.password = password.encode()
        self.token = token_urlsafe(32)
        self.engine = None
        if engine_paths:
            import cf_api

            base, out = engine_paths
            self.engine = cf_api.build_app(base, out, lambda value: compare_digest(value.encode("latin-1"), self.token.encode()),
                                           self.token)

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

        if self.engine is not None and (path.startswith("/clonfield/api/") or path == "/studio" or path.startswith("/studio/")):
            await self.engine(scope, receive, send)
            return

        cover_prefix = "/clonfield/catalog-cover/"
        if path.startswith(cover_prefix) and scope["method"] == "GET":
            if scheme.lower() != "bearer" or not compare_digest(secret, self.token.encode()):
                response = JSONResponse({"detail": "Sessão inválida."}, status_code=401, headers=headers)
            else:
                from cf_civitai import read_catalog_cover

                try:
                    body, media_type = await run_in_threadpool(read_catalog_cover, path.removeprefix(cover_prefix))
                    response = Response(body, media_type=media_type,
                                        headers={**headers, "X-Content-Type-Options": "nosniff"})
                except FileNotFoundError as exc:
                    response = JSONResponse({"detail": str(exc)}, status_code=404, headers=headers)
                except OSError as exc:
                    response = JSONResponse({"detail": str(exc)}, status_code=502, headers=headers)
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
