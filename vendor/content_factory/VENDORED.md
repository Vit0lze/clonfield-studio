# Vendored: jutsuhq/content-factory

- Source: https://github.com/jutsuhq/content-factory  commit 0ea76329ce23201d11fcfcebc9b236a9e3f58b93  (MIT, © 2026 Content Factory contributors; LICENSE alongside)
- Copied unmodified: engine/src/factory -> engine/factory, formats/, render/ (sources only; node_modules not vendored).
- Not copied: app/ (Tauri desktop), skills/, docs/, tests (run upstream's 74 tests against this snapshot: all pass).
- Remotion (render/) is NOT MIT: it has its own source-available licence (free for individuals and small teams, paid
  company licence otherwise). Check https://www.remotion.dev/license before commercial use.
- Local changes: stages/render.py — skip loudness normalisation when the render has no audio stream (silent script + no music crashed ffmpeg loudnorm with exit 234).
- Local change 2: stages/render.py passes `--concurrency=${CF_RENDER_CONCURRENCY:-1}` to remotion. Upstream default (CPU-count tabs of headless Chromium) OOM-killed a 3 GB RAM machine.
- Addition 3 (ClonField, new files): providers/tts/kokoro_onnx.py (Kokoro-82M int8 via kokoro-onnx, SHA-256-verified model download) and providers/stt/faster_whisper.py (CPU int8), registered in the two `__init__.py`. Gives narration + word alignment on Linux/Colab where upstream has only MLX (Apple) and Vosk (Russian).
