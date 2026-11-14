"""Feature flags for the Studio, read from CLONFIELD_<NAME> environment variables.

The chat has no outside service and needs no key: the model is local (cf_llm: llama-server or colibri). Tokens for Hugging Face and
Civitai are read where they are used (the Colab secrets / HF_TOKEN / CIVITAI_TOKEN), never from here.
"""

import os

# The agent is the default decision-maker whenever a local model answers.
FLAG_DEFAULTS = {"agent": True}


def flag(name):
    value = os.environ.get(f"CLONFIELD_{name.upper()}")
    if value is None:
        return FLAG_DEFAULTS.get(name, False)
    return value.strip().lower() in ("1", "true", "yes", "on", "sim")
