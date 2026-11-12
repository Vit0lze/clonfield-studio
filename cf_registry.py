"""Component registry: which file/algorithm fills each slot of a model recipe, which is the ★ default, what is installed,
and the whole-set presets (Rápido / Moderado / Qualidade / Manual).

★ means "default compatibility for this model + task" (the recipe's own file or algorithm), never an exclusive choice.
Options are ordered ★ → other installed compatible → (search adds the rest). Nothing here downloads or runs anything.
"""

import math
from pathlib import Path

import requests

import cf_civitai as civitai
import cf_model_lab as lab
import cf_workflows as workflows

ROLES = {"Difusão": "Modelo de difusão", "Checkpoint": "Checkpoint", "Encoder": "Encoder de texto", "VAE": "VAE", "Upscaler": "Upscaler"}
FALLBACK_SAMPLERS = ["euler", "euler_ancestral", "heun", "dpmpp_2m", "dpmpp_2m_sde", "res_multistep", "uni_pc"]
FALLBACK_SCHEDULERS = ["simple", "normal", "karras", "exponential", "sgm_uniform", "beta"]


def installed_file(repo_file):
    _repo, filename = repo_file[0], repo_file[1]
    target = lab.models_root() / Path(filename).parts[-2] / Path(filename).name
    return target.is_file() and target.stat().st_size > 0


def worker_choices(node, field):
    """The values the running ComfyUI actually accepts (so a slot never offers an algorithm the worker lacks)."""
    try:
        with requests.Session() as session:
            session.trust_env = False
            info = session.get(f"{workflows.SERVER}/object_info/{node}", timeout=3).json()
        spec = info[node]["input"]["required"][field]
        return list(spec[0]), True
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError):
        return None, False


def file_options(preset, role, civitai_dir):
    options = []
    default = preset.files.get(role)
    if default:
        name = Path(default[1]).name
        options.append(dict(value="", label=name, star=True, installed=installed_file(default), source="huggingface",
                            hint=("instalado" if installed_file(default) else "baixa ao usar") + f" · {default[0]}"))
    for key, data, path in civitai.inventory(civitai_dir, preset, role):
        options.append(dict(value=key, label=data.get("name") or path.name, star=False, installed=True, source="civitai",
                            hint=f"instalado · {data.get('base', '')}"))
    return options


def algorithm_options(node, field, default):
    values, live = worker_choices(node, field)
    values = values or (FALLBACK_SAMPLERS if field == "sampler_name" else FALLBACK_SCHEDULERS)
    ordered = [default] + [v for v in values if v != default]
    return [dict(value="" if v == default else v, label=v, star=(v == default), installed=True, source="worker" if live else "padrão",
                 hint="padrão da receita" if v == default else ("disponível no worker" if live else "worker não consultado"))
            for v in ordered]


def slots(model_key, civitai_dir):
    """Slots for one model recipe. `value` "" means the ★ default; anything else is a stored key or algorithm name."""
    preset = lab.PRESETS[model_key]
    out = []
    for role in preset.roles:
        if role == "LoRA":
            continue  # LoRAs have their own multi-slot panel
        options = file_options(preset, role, civitai_dir)
        out.append(dict(id=role, kind="file", label=ROLES.get(role, role), options=options,
                        search=dict(role=role, family=model_key, sources=["huggingface", "civitai", "local"])))
    out.append(dict(id="sampler", kind="algorithm", label="Sampler", options=algorithm_options("KSampler", "sampler_name", preset.sampler),
                    search=None))
    out.append(dict(id="scheduler", kind="algorithm", label="Scheduler", options=algorithm_options("KSampler", "scheduler", preset.scheduler),
                    search=None))
    return out


# ---------------------------------------------------------------- whole-set presets
# A set is a WHOLE pipeline, not a slider position: it chooses the model (and with it the encoder and VAE files), the
# step count and the generation size. Rápido = lightest model that fits the card, Moderado = best speed/quality balance,
# Qualidade = highest-fidelity model (may be heavy for the card, and says so). Choices come from MODEL_INFO's speed/quality
# ratings and the card's VRAM; they are initial recipes, not measurements (see NOTE).
SETS = ["Rápido", "Moderado", "Qualidade"]  # Manual = no set: every slot edited by hand
NOTE = "Receita inicial: escolhida pelas notas de velocidade e qualidade do catálogo, ainda sem benchmark A/B nesta placa."
GEN_FACTOR = {"Rápido": 0.75, "Moderado": 1.0, "Qualidade": 1.0}
EXCLUDED_FROM_AUTO = {"flux3"}  # needs a long visual caption or the local prompt expander, so it is never picked silently


def distilled(preset):
    return preset.steps <= 16


def steps_for(set_name, preset):
    if distilled(preset):
        return preset.steps
    return {"Rápido": math.ceil(preset.steps * 0.5), "Moderado": preset.steps, "Qualidade": min(80, round(preset.steps * 1.25))}[set_name]


def pick_models(tier, info, allowed, needs_refs):
    """{'Rápido': key, 'Moderado': key, 'Qualidade': key} from the catalogue ratings and the card's VRAM."""
    pool = [k for k in allowed if k in lab.PRESETS and k not in EXCLUDED_FROM_AUTO and (not needs_refs or lab.PRESETS[k].refs >= 1)]
    if not pool:
        return {}
    fits = [k for k in pool if tier.vram_gb >= info[k]["min_vram"]] or pool
    fast = max(fits, key=lambda k: (info[k]["speed"], info[k]["quality"]))
    best = max(pool, key=lambda k: (info[k]["quality"], -info[k]["speed"]))
    rest = [k for k in fits if k not in (fast, best)]
    better = [k for k in rest if info[k]["quality"] >= info[fast]["quality"]] or rest  # Moderado must not be worse than Rápido
    middle = max(better, key=lambda k: (info[k]["quality"], info[k]["speed"])) if better else fast
    return {"Rápido": fast, "Moderado": middle, "Qualidade": best}


def set_recipe(set_name, model_key, tier, info):
    preset = lab.PRESETS[model_key]
    heavy = tier.vram_gb < info[model_key]["min_vram"]
    why = {"Rápido": "o mais rápido que cabe na sua placa", "Moderado": "melhor equilíbrio entre velocidade e qualidade",
           "Qualidade": "a maior fidelidade do catálogo"}[set_name]
    return dict(model=model_key, title=info[model_key]["name"], why=why, steps=steps_for(set_name, preset), cfg=preset.cfg,
                gen_factor=GEN_FACTOR[set_name], sampler="", scheduler="",
                components={role: Path(spec[1]).name for role, spec in preset.files.items()},
                warning=(f"Pesado para a sua placa (recomendado ≥ {info[model_key]['min_vram']} GB): usa offload e fica mais lento." if heavy else ""),
                note=NOTE)


def describe_sets(tier, info, allowed, needs_refs=False):
    """Options for the Conjunto control; each carries the whole recipe so the form can apply it without asking the server."""
    chosen = pick_models(tier, info, allowed, needs_refs)
    chosen_refs = pick_models(tier, info, allowed, True)  # the same sets once the user attaches reference images
    texts = {"Rápido": "Menor latência", "Moderado": "Equilíbrio", "Qualidade": "Fidelidade", "Manual": "Tudo à mão"}
    out = []
    for name in (*SETS, "Manual"):
        entry = dict(value=name, label=name, hint=texts[name])
        if name != "Manual" and name in chosen:
            entry["recipe"] = set_recipe(name, chosen[name], tier, info)
            if name in chosen_refs and chosen_refs[name] != chosen[name]:
                entry["recipe_refs"] = set_recipe(name, chosen_refs[name], tier, info)
        out.append(entry)
    return out
