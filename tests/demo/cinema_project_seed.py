"""Saves «A última luz» as a CinemaProject.v1 in a Studio data folder, from the assets cinema_alfa_demo.py published.
Two cuts share the picture and the voice: «mar» (the music leaves after «Ninguém mais sobe a escada» and the sea takes over)
and «musica» (the music runs to the end). Shot 4 starts on take v1 so the screen can swap it to v2.
Usage: python tests/demo/cinema_project_seed.py <work_dir>   -> prints the project id"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import cf_cinema  # noqa: E402

WORK = Path(sys.argv[1]).resolve()
sys.argv = [sys.argv[0], str(WORK)]
sys.path.insert(0, str(Path(__file__).parent))
import cinema_alfa_demo as demo  # noqa: E402  (same shot list and cuts as the API proof)

ids = json.loads((WORK / "ids.json").read_text())["ids"]
base = demo.timeline(ids, ids["lembranca_v1"])
lines = {"v1": "Meu pai acendia o farol todo fim de tarde.",
         "v2": "Ele dizia que a luz não era para quem chega. Era para quem ainda está no mar.",
         "v3": "Eu achava que era só uma lâmpada, girando.", "v4": "Hoje a cidade acende sozinha. Ninguém mais sobe a escada.",
         "v5": "Mas toda tarde, eu ainda olho para o mar."}
for clip, key in zip(base["audio"]["voice"], lines):
    clip["note"] = lines[key]
sea_takes_over = dict(label="O mar toma conta", note="A música sai depois de «Ninguém mais sobe a escada»; o mar ocupa o plano segurado.",
                      music=base["audio"]["music"], sfx=base["audio"]["sfx"], mix=base["mix"])
b = json.loads((WORK / "timeline-B.json").read_text())
music_to_end = dict(label="Música até o fim", note="A música continua sob o plano segurado; o mar fica baixo.",
                    music=b["audio"]["music"], sfx=b["audio"]["sfx"], mix=b["mix"])
timeline = {k: v for k, v in base.items() if k not in ("audio", "mix", "name")}
timeline["audio"] = {"voice": base["audio"]["voice"]}
project = cf_cinema.create_project(WORK / "data", "A última luz", timeline, {"mar": sea_takes_over, "musica": music_to_end}, "mar")
print(project["id"])
