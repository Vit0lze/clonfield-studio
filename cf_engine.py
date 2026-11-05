"""Run the Studio API on its own (no Gradio): python cf_engine.py --port 7861"""

import argparse
import os
import secrets
from hmac import compare_digest
from pathlib import Path

import uvicorn

import cf_api
import cf_workflows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    base = Path(os.environ.get("CLONFIELD_DIR", "/content/ClonField_Lab"))
    password = os.environ.get("CLONFIELD_PASSWORD") or secrets.token_urlsafe(16)
    cf_workflows.clear_orphans()
    app = cf_api.build_app(base, base / "outputs", lambda t: compare_digest(t.encode(), password.encode()), password)
    print(f"SENHA DA SESSÃO: {password}", flush=True)
    print(f"CLONFIELD_READY {args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
