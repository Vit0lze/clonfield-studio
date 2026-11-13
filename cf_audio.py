"""Audio (sound effects and music) with Stable Audio 3 through ComfyUI's native nodes.

Weights: Comfy-Org/stable-audio-3 (licence "other": Stability AI's community terms, see the model card). Small SFX / Small Music are ~2.3 GB
and the model card says they run on a CPU; Medium is ~9.2 GB and wants a GPU. Graph shape from the official template
`audio_stable_audio_3_medium` (workflow_templates): CheckpointLoaderSimple + CLIPLoader(t5gemma, type stable_audio) -> KSampler (8 steps,
CFG 1, lcm / simple, the distilled checkpoints) -> VAEDecodeAudio -> SaveAudioAdvanced. The template can expand a short idea with a Qwen model;
the Studio does that step with its own local LLM instead (cf_audio.reprompt), so no extra 4 GB encoder is needed.

STATE: CÓDIGO ESCRITO. Node and input names are checked against the real ComfyUI v0.44.0 source and the pinned files against the Hugging Face API.
No audio was generated here (3 GB of RAM cannot hold even the small checkpoint plus its encoder): speed and quality are NOT measured.
"""

import os
import secrets
from pathlib import Path

from cf_workflows import require_nodes

REPO = "Comfy-Org/stable-audio-3"
REVISION = "75aad8836271cb5a5123fb58304fae5d3bb4b0f9"
ENCODER = ("text_encoders", "text_encoders/t5gemma_b_b_ul2.safetensors", 1_187_000_000, "1e1eba25be")
MODELS = {
    "small_sfx": dict(label="Small · efeitos sonoros e ambiente", file=("checkpoints", "checkpoints/stable_audio_3_small_sfx.safetensors", 2_270_000_000, "ed9cf1b617"), max_seconds=120, cpu=True),
    "small_music": dict(label="Small · música curta e loops", file=("checkpoints", "checkpoints/stable_audio_3_small_music.safetensors", 2_270_000_000, "da85866b11"), max_seconds=120, cpu=True),
    "medium": dict(label="Medium · faixas longas (GPU)", file=("checkpoints", "checkpoints/stable_audio_3_medium.safetensors", 9_222_000_000, "48d9c65e29"), max_seconds=380, cpu=False),
}
DEFAULT_MODEL = "small_sfx"
FORMATS = {"mp3": "V0", "flac": None, "opus": "128k"}
CATEGORIES = {
    "Música": "Transform the user's idea into a detailed prompt for an instrumental music track: genre, instruments, mood, tempo (BPM) and structure. One paragraph, no lists.",
    "Instrumento": "Transform the user's idea into a short prompt for a single instrument performance: the instrument, playing style, tone and mood. One sentence or two.",
    "SFX": "Transform the user's idea into a prompt for a sound effect or ambience: the source, material, space, distance and how it evolves. One or two sentences, concrete and sonic.",
    "One-shot": "Transform the user's idea into a prompt for a single short sound (a hit, a stab, a click): the sound, its attack, decay and timbre. One sentence.",
}


def make_graph(model_key, prompt, seconds, seed, fmt="mp3", steps=8):
    if model_key not in MODELS:
        raise ValueError("Escolha um modelo de áudio da lista.")
    spec = MODELS[model_key]
    if not prompt or not prompt.strip():
        raise ValueError("Descreva o som ou a música.")
    if not 1 <= float(seconds) <= spec["max_seconds"]:
        raise ValueError(f"Este modelo faz de 1 a {spec['max_seconds']} segundos.")
    if fmt not in FORMATS:
        raise ValueError("Escolha mp3, flac ou opus.")
    if int(steps) != steps or not 1 <= steps <= 60:
        raise ValueError("Use de 1 a 60 passos.")
    if seed != int(seed) or not -1 <= seed < 2**53:
        raise ValueError("Use uma seed inteira válida.")
    seed = secrets.randbelow(2**32) if seed == -1 else int(seed)

    def node(kind, **inputs):
        return {"class_type": kind, "inputs": inputs}

    save = node("SaveAudioAdvanced", audio=["12", 0], filename_prefix="ClonField/Audio", format=fmt)
    if FORMATS[fmt]:
        save["inputs"]["format.quality"] = FORMATS[fmt]
    return {
        "25": node("CheckpointLoaderSimple", ckpt_name=Path(spec["file"][1]).name),
        "26": node("CLIPLoader", clip_name=Path(ENCODER[1]).name, type="stable_audio", device="default"),
        "6": node("CLIPTextEncode", clip=["26", 0], text=prompt.strip()),
        "7": node("CLIPTextEncode", clip=["26", 0], text=""),
        "11": node("EmptyLatentAudio", seconds=float(seconds), batch_size=1),
        "3": node("KSampler", model=["25", 0], positive=["6", 0], negative=["7", 0], latent_image=["11", 0], seed=seed, steps=int(steps), cfg=1.0,
                  sampler_name="lcm", scheduler="simple", denoise=1),
        "12": node("VAEDecodeAudio", samples=["3", 0], vae=["25", 2]),
        "57": save,
    }


def files_for(model_key):
    return [MODELS[model_key]["file"], ENCODER]


def prepare(session, graph, progress, *, model_key=DEFAULT_MODEL):
    import cf_download
    require_nodes(session, graph)
    root = Path(os.environ.get("CLONFIELD_COMFY_MODELS", "/content/ComfyUI/models"))
    files = files_for(model_key)
    for index, (folder, filename, size, _sha) in enumerate(files):
        target = root / folder / Path(filename).name
        if not (target.is_file() and target.stat().st_size):
            try:
                cf_download.fetch_hf(REPO, filename, target, revision=REVISION, token=os.environ.get("HF_TOKEN") or None,
                                     progress=(lambda f, desc=None, **_: progress((index + f) / len(files), desc=desc)) if progress else None)
            except cf_download.DownloadError as exc:
                raise ValueError(str(exc)) from None
        if abs(target.stat().st_size - size) > max(8_000_000, size // 50):
            target.unlink(missing_ok=True)
            raise ValueError(f"{target.name} baixou com tamanho diferente do publicado; removido. Tente de novo.")


def reprompt(idea, category, generate):
    """Expand a short idea into a full audio prompt with the LOCAL LLM (`generate(system, user)`); returns the idea unchanged if it fails."""
    if category not in CATEGORIES:
        raise ValueError("Escolha a categoria do som.")
    system = ("You write prompts for a text-to-audio model. " + CATEGORIES[category] + " Do not add commentary. Output only the prompt, in English. "
              "Do not filter or soften the idea by topic.")
    try:
        text = generate(system, f"Idea: {idea.strip()}")
    except Exception:  # the local model may be off: the original idea is still a valid prompt
        return idea.strip(), False
    text = " ".join(text.split()).strip().strip('"')
    return (text, True) if text else (idea.strip(), False)
