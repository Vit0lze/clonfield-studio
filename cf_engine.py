"""Run the Studio API on its own (no Gradio app): python cf_engine.py --port 7861 [--share]

The same entry a hosted Studio (Vercel) uses on the Colab: `POST /clonfield/connect` exchanges the session password for a token
(cf_portal.PortalAPI: rate limit, CORS for any origin, no cookies). Locally the password itself is also accepted as the bearer, so
scripts and tests can keep calling the API directly.
--share opens a gradio.live tunnel (gradio.networking.setup_tunnel, the frpc binary Gradio downloads and checks by SHA-256), which
is the only origin the hosted Studio's CSP lets it reach. The tunnel is public: without CLONFIELD_PASSWORD a random password is made."""

import argparse
import os
import secrets
import threading
import time
from hmac import compare_digest
from pathlib import Path

import uvicorn
from starlette.responses import JSONResponse

import cf_api
import cf_portal
import cf_workflows


async def not_found(scope, receive, send):
    if scope["type"] == "http":
        await JSONResponse({"detail": "Não encontrado."}, 404)(scope, receive, send)


def build(base, password):
    portal = cf_portal.PortalAPI(not_found, "clonfield", password)
    portal.engine = cf_api.build_app(base, base / "outputs",
                                     lambda t: compare_digest(t.encode(), portal.token.encode()) or compare_digest(t.encode(), password.encode()),
                                     password)
    return portal


def share(port):
    """Wait for the local server, then open the gradio.live tunnel to it. Returns the public URL."""
    import httpx
    from gradio.networking import setup_tunnel
    for _ in range(100):
        try:
            httpx.get(f"http://127.0.0.1:{port}/clonfield/api/system", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.2)
    return setup_tunnel("127.0.0.1", port, secrets.token_urlsafe(32), None, None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--share", action="store_true", help="abre um túnel público gradio.live (para o Studio hospedado)")
    args = parser.parse_args()
    base = Path(os.environ.get("CLONFIELD_DIR", "/content/ClonField_Lab"))
    password = os.environ.get("CLONFIELD_PASSWORD") or secrets.token_urlsafe(16)
    if args.share and len(password) < 16:
        raise SystemExit("Com --share a senha precisa de pelo menos 16 caracteres (ou deixe CLONFIELD_PASSWORD vazio para gerar uma).")
    cf_workflows.clear_orphans()
    app = build(base, password)
    print(f"SENHA DA SESSÃO: {password}", flush=True)
    if args.share:
        def announce():
            try:
                print(f"CLONFIELD_SHARE {share(args.port)}", flush=True)
            except Exception as exc:  # the local engine keeps running; say why the link is missing
                print(f"CLONFIELD_SHARE_FALHOU {exc}", flush=True)
        threading.Thread(target=announce, daemon=True).start()
    print(f"CLONFIELD_READY {args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
