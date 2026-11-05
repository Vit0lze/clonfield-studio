"""Allow a static portal to hand off a top-level login to Gradio."""

from starlette.responses import HTMLResponse


class PortalLogin:
    """Use Gradio's existing password check and cookies, then open the app."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/clonfield/connect":
            await self.app(scope, receive, send)
            return

        login_scope = {**scope, "path": "/login", "raw_path": b"/login"}
        handled = False

        async def send_login(message):
            nonlocal handled
            if message["type"] == "http.response.start" and message["status"] == 200:
                handled = True
                cookies = [(key, value) for key, value in message["headers"] if key.lower() == b"set-cookie"]
                await send({"type": "http.response.start", "status": 303,
                            "headers": [*cookies, (b"location", b"/"), (b"cache-control", b"no-store"),
                                        (b"content-length", b"0")]})
                await send({"type": "http.response.body", "body": b""})
            elif message["type"] == "http.response.start" and message["status"] in (400, 422):
                handled = True
                response = HTMLResponse(
                    '<!doctype html><html lang="pt-BR"><meta charset="utf-8">'
                    '<title>ClonField · Acesso negado</title><main>'
                    '<h1>Senha da sessão inválida</h1>'
                    '<p>Volte ao portal e confira a senha exibida na última célula do Colab.</p></main></html>',
                    status_code=400, headers={"Cache-Control": "no-store"},
                )
                await response(login_scope, receive, send)
            elif not handled:
                await send(message)

        await self.app(login_scope, receive, send_login)
