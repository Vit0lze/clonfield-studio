"""Resumable downloads that report bytes and give up when the server goes quiet."""

import time
from pathlib import Path
from urllib.parse import urlparse

import requests

HF_HOSTS = ("huggingface.co",)


class DownloadError(RuntimeError):
    pass


def hf_url(repo, filename, revision="main"):
    return f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"


def human(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def fetch(url, dest, progress=None, label=None, token=None, attempts=4, stall=45, chunk=1 << 20):
    """Download url to dest through a .part file. A read that stays silent for `stall` seconds is retried
    with a Range request; after `attempts` failures the error says which file stopped."""
    dest, label = Path(dest), label or Path(dest).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    headers = {}
    host = urlparse(url).hostname or ""
    if token and host.endswith(HF_HOSTS) or token and host.endswith("civitai.com"):
        headers["Authorization"] = f"Bearer {token}"
    last_error = None
    for attempt in range(1, attempts + 1):
        have = partial.stat().st_size if partial.exists() else 0
        request_headers = dict(headers, **({"Range": f"bytes={have}-"} if have else {}))
        try:
            with requests.get(url, headers=request_headers, stream=True, timeout=(15, stall)) as response:
                if response.status_code == 416:
                    break
                response.raise_for_status()
                if have and response.status_code != 206:
                    have = 0
                    partial.unlink(missing_ok=True)
                length = int(response.headers.get("content-length", 0))
                total = have + length if length else 0
                started, window, seen = time.monotonic(), time.monotonic(), have
                with partial.open("ab" if have else "wb") as handle:
                    for block in response.iter_content(chunk):
                        handle.write(block)
                        have += len(block)
                        now = time.monotonic()
                        if progress and now - window >= 1:
                            speed = (have - seen) / (now - window)
                            window, seen = now, have
                            eta = f" · faltam {int((total - have) / speed // 60)} min" if total and speed else ""
                            share = f"{have / total:.0%} de {human(total)}" if total else human(have)
                            progress(0.1, desc=f"Baixando {label} · {share} · {human(speed)}/s{eta}")
                if total and have < total:
                    raise requests.ConnectionError(f"{have} de {total} bytes")
            break
        except (requests.RequestException, OSError) as exc:
            last_error = exc
            if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in (401, 403, 404):
                raise DownloadError(f"{label}: acesso negado ou arquivo inexistente (HTTP {exc.response.status_code}). "
                                    "Confira o token e as condições do modelo.") from None
            if progress:
                progress(0.1, desc=f"Conexão parou em {label}; tentativa {attempt + 1}/{attempts}")
            time.sleep(min(2 ** attempt, 10))
    else:
        raise DownloadError(f"{label}: o download parou após {attempts} tentativas ({last_error}). "
                            "O progresso fica salvo; execute de novo para continuar.")
    if not partial.exists() or not partial.stat().st_size:
        raise DownloadError(f"{label}: arquivo vazio.")
    partial.replace(dest)
    return dest


def fetch_hf(repo, filename, dest, revision="main", token=None, **options):
    return fetch(hf_url(repo, filename, revision), dest, token=token, label=Path(filename).name, **options)
