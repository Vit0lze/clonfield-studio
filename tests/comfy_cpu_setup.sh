#!/usr/bin/env bash
# Builds the scratch CPU ComfyUI used to VALIDATE graphs (tests/test_comfy_real.py): ~/.cache/clonfield-comfyui/{src,venv,start.sh}.
# It never loads a model: it only serves /object_info and POST /prompt validation. ~1.5 GB of disk (torch CPU), ~0.5 GB of RAM while running.
set -euo pipefail
HOME_DIR="${CLONFIELD_COMFY_CPU_HOME:-$HOME/.cache/clonfield-comfyui}"
mkdir -p "$HOME_DIR"; cd "$HOME_DIR"
[ -d src ] || git clone -q --depth 1 --branch v0.44.0 https://github.com/comfyanonymous/ComfyUI.git src
python3 -m venv venv
venv/bin/pip install -q torch torchvision --index-url https://download.pytorch.org/whl/cpu
venv/bin/pip install -q -r src/requirements.txt
mkdir -p src/custom_nodes
[ -d src/custom_nodes/ComfyUI-GGUF ] || git clone -q https://github.com/city96/ComfyUI-GGUF src/custom_nodes/ComfyUI-GGUF
git -C src/custom_nodes/ComfyUI-GGUF checkout -q 6ea2651e7df66d7585f6ffee804b20e92fb38b8a   # same pin as prepare_gguf.py
venv/bin/pip install -q -r src/custom_nodes/ComfyUI-GGUF/requirements.txt
cat > start.sh <<'INNER'
#!/usr/bin/env bash
cd "$(dirname "$0")/src" && exec ../venv/bin/python main.py --cpu --listen 127.0.0.1 --port "${1:-8199}" --disable-auto-launch
INNER
chmod +x start.sh
echo "pronto: $HOME_DIR/start.sh 8199  (CLONFIELD_COMFY_CPU_URL=http://127.0.0.1:8199 usa um servidor já rodando)"
