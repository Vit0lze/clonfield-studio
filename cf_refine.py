"""Technical quality gate + capped refine loop.

Method adapted (not code) from scenario-labs/skills (MIT, b96506d): scenario-quality-gate and
scenario-refine-loop. Kept from them: a rubric of checkable lines fixed before judging, a per-line verdict that names
the failed line, cheapest-fix-first routing, one variable per round, regenerate from the baseline (never from the last
attempt), a hard round cap, stop when one line fails under two different fixes, keep the best attempt.

What this is NOT: an aesthetic or identity judge. There is no AI critic wired in, so only measurable properties are
scored; free-text rubric lines are recorded as "não avaliado". No numeric quality score is invented.
"""

import dataclasses
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

PASS, FAIL, SKIPPED = "pass", "fail", "não avaliado"


def luma(image, side=512):
    image = ImageOps.exif_transpose(image).convert("L")
    image.thumbnail((side, side))
    return np.asarray(image, dtype=np.float32)


def laplacian_variance(gray):
    lap = (-4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:])
    return float(lap.var())


@dataclasses.dataclass
class Verdict:
    line: str
    status: str
    reason: str = ""
    value: float | None = None


def check_not_blank(image, ctx):
    spread = float(luma(image).std())
    return Verdict("not_blank", PASS if spread >= 4 else FAIL, f"desvio de luminância {spread:.1f}" + ("" if spread >= 4 else " — imagem quase uniforme"), spread)


def check_sharp(image, ctx):
    value = laplacian_variance(luma(image))
    floor = ctx.get("sharp_floor", 25.0)
    return Verdict("sharp", PASS if value >= floor else FAIL, f"variância do Laplaciano {value:.1f} (mín. {floor:g})", value)


def check_exposure(image, ctx):
    gray = luma(image)
    dark, bright = float((gray <= 3).mean()), float((gray >= 252).mean())
    limit = ctx.get("clip_limit", 0.35)
    bad = max(dark, bright) > limit
    return Verdict("exposure", FAIL if bad else PASS, f"preto estourado {dark:.0%}, branco estourado {bright:.0%} (máx. {limit:.0%})", max(dark, bright))


def check_size(image, ctx):
    want = ctx.get("size")
    if not want:
        return Verdict("size", SKIPPED, "sem tamanho esperado")
    ok = image.size == tuple(want)
    return Verdict("size", PASS if ok else FAIL, f"{image.size[0]}×{image.size[1]} (esperado {want[0]}×{want[1]})")


def check_structure(image, ctx):
    """For edit/relight apps: the composition must stay close to the reference (low-res luminance correlation)."""
    reference = ctx.get("reference")
    if reference is None:
        return Verdict("structure", SKIPPED, "sem referência")
    a = np.asarray(ImageOps.exif_transpose(image).convert("L").resize((64, 64)), dtype=np.float32).ravel()
    b = np.asarray(ImageOps.exif_transpose(reference).convert("L").resize((64, 64)), dtype=np.float32).ravel()
    if a.std() < 1e-6 or b.std() < 1e-6:
        return Verdict("structure", FAIL, "imagem sem variação para comparar", 0.0)
    corr = float(np.corrcoef(a, b)[0, 1])
    floor = ctx.get("structure_floor", 0.5)
    return Verdict("structure", PASS if corr >= floor else FAIL, f"correlação com a referência {corr:.2f} (mín. {floor:g})", corr)


CHECKS = {f.__name__.removeprefix("check_"): f for f in (check_not_blank, check_sharp, check_exposure, check_size, check_structure)}


def judge(path, ctx, names, manual=()):
    """The verdict list for one image. Free-text rubric lines are recorded, never scored."""
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    out = [CHECKS[name](image, ctx) for name in names]
    out += [Verdict(line, SKIPPED, "linha de texto sem avaliador automático") for line in manual]
    return out


# ---- fixes, cheapest first. "finish" = deterministic pass over the baseline output; "regenerate" = new seed only.
def unsharp(path, dest):
    with Image.open(path) as image:
        image.convert("RGB").filter(ImageFilter.UnsharpMask(radius=2, percent=160, threshold=2)).save(dest)


def autocontrast(path, dest):
    with Image.open(path) as image:
        ImageOps.autocontrast(image.convert("RGB"), cutoff=1).save(dest)


LADDER = {
    "sharp": [("finish", "unsharp", unsharp), ("regenerate", "nova seed", None)],
    "exposure": [("finish", "autocontrast", autocontrast), ("regenerate", "nova seed", None)],
    "not_blank": [("regenerate", "nova seed", None)],
    "structure": [("regenerate", "nova seed", None)],
    "size": [("regenerate", "nova seed", None)],
}


def failures(verdicts):
    return [v for v in verdicts if v.status == FAIL]


def refine(generate, params, ctx, names, workdir, manual=(), max_rounds=3):
    """generate(params) -> Path. Returns a report; `best` is the attempt with fewest failed lines (earliest wins ties)."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    baseline = Path(generate(params))
    attempts = [dict(round=0, how="baseline", path=baseline, verdicts=judge(baseline, ctx, names, manual))]
    used = {}  # line -> number of rungs already tried
    stop = "passou"
    for round_no in range(1, max_rounds + 1):
        failed = failures(attempts[-1]["verdicts"])
        if not failed:
            break
        line = failed[0].line
        rung = used.get(line, 0)
        ladder = LADDER.get(line, [("regenerate", "nova seed", None)])
        if rung >= len(ladder):
            stop = f"a linha «{line}» falhou sob {rung} correções diferentes: troque modelo/receita em vez de repetir"
            break
        kind, label, func = ladder[rung]
        used[line] = rung + 1
        if kind == "finish":
            target = workdir / f"{baseline.stem}_r{round_no}.png"
            func(baseline, target)  # always from the baseline output, never from the previous attempt
        else:
            changed = dict(params, seed=int(params.get("seed", 0)) + round_no)  # one variable per round
            target = Path(generate(changed))
        attempts.append(dict(round=round_no, how=f"{kind}: {label}", fixes=line, path=target,
                             verdicts=judge(target, ctx, names, manual)))
    else:
        stop = "limite de rodadas" if failures(attempts[-1]["verdicts"]) else "passou"
    if stop == "passou" and failures(attempts[-1]["verdicts"]):
        stop = "limite de rodadas"
    best = min(attempts, key=lambda a: (len(failures(a["verdicts"])), a["round"]))
    return dict(best=best, attempts=attempts, stop=stop, passed=not failures(best["verdicts"]))


def summarize(report):
    lines = []
    for a in report["attempts"]:
        bad = [v.line for v in failures(a["verdicts"])]
        lines.append(f"rodada {a['round']} ({a['how']}): " + ("ok" if not bad else "falhou " + ", ".join(bad)))
    return " · ".join(lines) + f" → {report['stop']}"
