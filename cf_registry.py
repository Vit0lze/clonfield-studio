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
        if role == "Upscaler" and not options:
            continue
        out.append(dict(id=role, kind="file", label=ROLES.get(role, role), options=options,
                        search=dict(role=role, family=model_key, sources=["huggingface", "civitai", "local"])))
    out.append(dict(id="sampler", kind="algorithm", label="Sampler", options=algorithm_options("KSampler", "sampler_name", preset.sampler),
                    search=None))
    out.append(dict(id="scheduler", kind="algorithm", label="Scheduler", options=algorithm_options("KSampler", "scheduler", preset.scheduler),
                    search=None))
    return out


# ---------------------------------------------------------------- whole-set presets
SETS = ["Rápido", "Moderado", "Qualidade"]  # Manual = no set: every slot edited by hand
NOTE = "Receita inicial derivada dos dados do preset; ainda sem benchmark A/B nesta placa (use Sistema › Benchmark)."


def distilled(preset):
    return preset.steps <= 16


def set_values(set_name, preset, tier):
    """Whole-set recipe for one model: generation steps/CFG, sampler/scheduler, generation-size factor and the component
    list. Few-step (distilled) models keep their steps: more steps do not buy quality there."""
    if set_name not in SETS:
        raise ValueError("Conjunto desconhecido: " + str(set_name))
    base = preset.steps
    if distilled(preset):
        steps = base if set_name != "Rápido" else max(4, min(base, math.ceil(base * 0.5)))
    else:
        steps = {"Rápido": math.ceil(base * 0.5), "Moderado": base, "Qualidade": min(80, round(base * 1.25))}[set_name]
    values = dict(steps=steps, cfg=preset.cfg, sampler="", scheduler="", gen_factor={"Rápido": 0.75, "Moderado": 1.0, "Qualidade": 1.0}[set_name])
    components = {role: ("★ " + Path(spec[1]).name) for role, spec in preset.files.items()}
    return dict(values=values, components=components, note=NOTE)


def describe_sets(tier):
    """Per-model values so the form can apply a set when the model changes."""
    out = []
    for name, text in (("Rápido", "Menos passos e geração menor: menor latência, qualidade mínima aceitável."),
                       ("Moderado", "Passos e tamanho recomendados do modelo."),
                       ("Qualidade", "Mais passos (modelos não destilados) e geração no limite da sua placa."),
                       ("Manual", "Você escolhe cada componente e parâmetro.")):
        entry = dict(value=name, label=name, hint=text)
        if name != "Manual":
            entry["by_model"] = {key: set_values(name, preset, tier) for key, preset in lab.PRESETS.items()}
        out.append(entry)
    return out
