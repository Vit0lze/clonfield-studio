"""Seam meter for a looping video: how big is the jump from the LAST frame back to the FIRST, compared with a normal step between neighbours?

Method (all measured on the pixels, nothing assumed): decode the clip at a small size, take the mean absolute difference between consecutive
frames (the clip's own motion step: its median is the baseline) and the mean absolute difference between the last and the first frame (the seam).
`ratio = seam / baseline`: about 1 means the wrap looks like any other step; well above 1 means a visible jump. The thresholds are a rule of
thumb, not a perceptual model; they say "check the join", they do not certify it. Pure CPU: ffmpeg + numpy, tested with real encoded clips.
"""

import subprocess

import numpy as np

SIDE = 96
MAX_FRAMES = 400
GOOD, OK = 1.5, 3.0  # ratio limits for "sem emenda visível" and "emenda leve"


class LoopError(ValueError):
    pass


def frames(path, side=SIDE, limit=MAX_FRAMES):
    """The clip as a float32 array (n, side, side, 3) in 0..1, resized (not cropped) to side x side."""
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={side}:{side}:flags=area", "-frames:v", str(limit), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    done = subprocess.run(command, capture_output=True, timeout=120)
    if done.returncode or not done.stdout:
        raise LoopError("Não consegui ler os quadros do vídeo: " + (done.stderr.decode(errors="replace")[-200:] or "saída vazia"))
    size = side * side * 3
    count = len(done.stdout) // size
    if count < 3:
        raise LoopError("O vídeo tem poucos quadros para medir a emenda.")
    return np.frombuffer(done.stdout[:count * size], dtype=np.uint8).reshape(count, side, side, 3).astype(np.float32) / 255.0


def seam(path):
    """-> dict(frames, baseline, seam, ratio, verdict, label). `baseline` is the median step between neighbours."""
    clip = frames(path)
    steps = np.abs(np.diff(clip, axis=0)).mean(axis=(1, 2, 3))
    baseline = float(np.median(steps))
    jump = float(np.abs(clip[0] - clip[-1]).mean())
    ratio = jump / max(baseline, 1e-6)
    if baseline < 1e-4:  # a frozen clip has no motion to compare against
        verdict, label = ("parado", "o vídeo quase não se mexe; não há emenda para medir")
    elif ratio <= GOOD:
        verdict, label = ("sem emenda visível", f"a volta ao início é do tamanho de um passo normal ({ratio:.1f}×)")
    elif ratio <= OK:
        verdict, label = ("emenda leve", f"a volta ao início salta {ratio:.1f}× um passo normal; confira a junção")
    else:
        verdict, label = ("emenda visível", f"a volta ao início salta {ratio:.1f}× um passo normal; o loop tem um corte")
    return dict(frames=int(len(clip)), baseline=round(baseline, 5), seam=round(jump, 5), ratio=round(ratio, 2), verdict=verdict, label=label)
