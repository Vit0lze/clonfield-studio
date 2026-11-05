"""Authenticate the static Studio client on the existing Gradio API."""

import asyncio
import time
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
        self.failures = {}
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
        if path.startswith("/clonfield/") or path == "/studio" or path.startswith("/studio/"):
            # The Studio may be hosted anywhere, so these routes answer any origin. Nothing here relies on cookies:
            # every call carries the session bearer, which a foreign page cannot obtain without the password.
            cors = [(b"access-control-allow-origin", b"*"), (b"access-control-expose-headers", b"content-length, content-type"),
                    (b"vary", b"Origin")]
            if scope["method"] == "OPTIONS":
                await Response(status_code=204, headers={
                    "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "authorization, content-type", "Access-Control-Max-Age": "600"})(scope, receive, send)
                return
            inner_send = send

            async def send(message):
                if message["type"] == "http.response.start":
                    kept = [(k, v) for k, v in message.get("headers", []) if not k.lower().startswith(b"access-control-")]
                    message = {**message, "headers": [*kept, *cors]}
                await inner_send(message)

        authorization = Headers(scope=scope).get("authorization", "")
        scheme, _, bearer = authorization.partition(" ")
        secret = bearer.encode("latin-1")
        headers = {"Cache-Control": "no-store"}
        if path == "/clonfield/connect" and scope["method"] == "POST":
            who = (Headers(scope=scope).get("x-forwarded-for", "").split(",")[0].strip()
                   or (scope.get("client") or ("?",))[0])
            now = time.monotonic()
            recent = [t for t in self.failures.get(who, []) if now - t < 60]
            if len(recent) >= 8:
                response = JSONResponse({"detail": "Muitas tentativas. Aguarde um minuto."}, status_code=429,
                                        headers={**headers, "Retry-After": "60"})
            elif scheme.lower() == "bearer" and compare_digest(secret, self.password):
                self.failures.pop(who, None)
                response = JSONResponse({"token": self.token}, headers=headers)
            else:
                self.failures[who] = [*recent, now]
                await asyncio.sleep(0.4)
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


def let_studio_answer_cors():
    """Gradio's strict CORS layer sits outside our middleware and would reject preflights from a hosted Studio.
    Route /clonfield and /studio around it; PortalAPI answers those itself, and everything else stays strict."""
    import gradio.routes as routes

    base = routes.CustomCORSMiddleware
    if getattr(base, "_studio_aware", False):
        return

    class StudioAwareCORS(base):
        _studio_aware = True

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and (scope["path"].startswith("/clonfield/") or scope["path"] == "/studio"
                                            or scope["path"].startswith("/studio/")):
                await self.app(scope, receive, send)
                return
            await super().__call__(scope, receive, send)

    routes.CustomCORSMiddleware = StudioAwareCORS
