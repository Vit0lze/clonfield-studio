"""Fetch version-pinned Civitai files into a runtime cache."""

import argparse
import json
import os
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit

import requests

ROOT = Path(__file__).resolve().parent
API = "https://civitai.com"


def catalog():
    return json.loads((ROOT / "assets.json").read_text())


def request(session, url, token, stream=False):
    # Only send the Civitai bearer to the original API origin, never to a CDN.
    for _ in range(7):
        target = urlsplit(url)
        if target.scheme != "https" or target.username or target.password:
            raise ValueError("Redirecionamento inválido.")
        headers = {"Authorization": f"Bearer {token}"} if target.netloc == "civitai.com" else {}
        response = session.get(url, headers=headers, allow_redirects=False, stream=stream, timeout=(20, 120))
        if response.is_redirect:
            url = urljoin(url, response.headers["Location"])
            response.close()
            continue
        if not response.ok:
            status = response.status_code
            response.close()
            raise ValueError(f"Civitai retornou HTTP {status}. Verifique acesso à versão e ao arquivo.")
        return response
    raise ValueError("Redirecionamentos demais no download.")


def fetch(session, entry, token, root):
    version = entry["version"]
    with request(session, f"{API}/api/v1/model-versions/{version}", token) as response:
        metadata = response.json()
    files = metadata.get("files") or []
    category = (metadata.get("model") or {}).get("type", "").casefold()
    model_files = [file for file in files if file.get("type") == "Model"]
    candidates = model_files or files
    if entry.get("workflow"):
        candidates = [file for file in files if str(file.get("name", "")).lower().endswith((".json", ".zip", ".png"))]
    candidates = [file for file in candidates if Path(str(file.get("name", ""))).suffix.lower()
                  in {".safetensors", ".json", ".zip", ".png"}]
    if not candidates:
        raise ValueError("A versão não lista arquivo em formato suportado.")
    file = next((item for item in candidates if item.get("primary")), candidates[0])
    name = PurePosixPath(file["name"].replace("\\", "/")).name
    subdir = "civitai/workflows" if entry.get("workflow") else "civitai/models"
    if not entry.get("workflow") and category in {"lora", "locon"} and name.lower().endswith(".safetensors"):
        subdir = "loras"
    destination = root / subdir / f"{version}-{name}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected = next((value for key, value in (file.get("hashes") or {}).items() if key.upper() == "SHA256"), None)
    if destination.is_file() and destination.stat().st_size:
        return destination
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        url = file.get("downloadUrl") or f"{API}/api/download/models/{version}"
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc not in {"civitai.com", "www.civitai.com", "civitai.red"}:
            raise ValueError("URL inicial de download fora dos domínios Civitai.")
        if parsed.netloc != "civitai.com":
            url = parsed._replace(netloc="civitai.com").geturl()
        import hashlib
        digest = hashlib.sha256()
        with request(session, url, token, stream=True) as response, partial.open("wb") as output:
            if response.headers.get("Content-Type", "").startswith(("text/html", "text/plain")):
                raise ValueError("O servidor retornou uma página em vez do arquivo.")
            for chunk in response.iter_content(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
        if not partial.stat().st_size:
            raise ValueError("Arquivo vazio.")
        if expected and digest.hexdigest().casefold() != expected.casefold():
            raise ValueError("SHA-256 diferente do metadado da versão.")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, action="append", help="Selecione versões específicas.")
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("CLONFIELD_DIR", "/content/ClonField_Lab")))
    args = parser.parse_args()
    token = os.environ.get("CIVITAI_TOKEN")
    if not token:
        print("CIVITAI_TOKEN ausente. Downloads Civitai pulados.")
        return
    failed = 0
    with requests.Session() as session:
        for entry in catalog():
            if args.version and entry["version"] not in args.version:
                continue
            try:
                dest = fetch(session, entry, token, args.root)
                print(f'{entry["version"]}: {dest.relative_to(args.root)}', flush=True)
            except requests.RequestException:
                failed += 1
                print(f'{entry["version"]}: falha de rede; rode novamente para tentar os pendentes.', flush=True)
            except (KeyError, ValueError, OSError) as exc:
                failed += 1
                print(f'{entry["version"]}: {type(exc).__name__}: {str(exc) if type(exc) is ValueError else "falha no arquivo ou no metadado"}', flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
