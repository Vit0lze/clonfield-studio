#!/usr/bin/env bash
# Fresh data dir -> seed real LoRA files -> real engine -> Playwright. Usage: CF_PY=/path/to/python tests/e2e/run.sh [playwright args]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
PY="${CF_PY:-python3}"; PORT="${CF_E2E_PORT:-7871}"
export CF_E2E_DATA="$(mktemp -d /tmp/cf-e2e-XXXXXX)"
"$PY" "$HERE/seed.py" "$CF_E2E_DATA" || exit 2
( cd "$ROOT" && CLONFIELD_FAKE_VRAM=15 CLONFIELD_PASSWORD=testpw-e2e CLONFIELD_DIR="$CF_E2E_DATA" CLONFIELD_COMFY_MODELS="$CF_E2E_DATA/comfy-models" exec "$PY" cf_engine.py --port "$PORT" >"$CF_E2E_DATA/engine.log" 2>&1 ) &
ENGINE=$!
trap 'kill $ENGINE 2>/dev/null; rm -rf "$CF_E2E_DATA"' EXIT
for _ in $(seq 1 40); do curl -fs "http://127.0.0.1:$PORT/studio/" >/dev/null 2>&1 && break; sleep 0.5; done
cd "$HERE" && CF_E2E_REUSE=1 npx playwright test "$@" < /dev/null
