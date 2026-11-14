# Provenance of vendored official workflows

- `3d_pixal3d_trellis2_image_to_model.json`: Comfy-Org/workflow_templates (MIT), `templates/3d_pixal3d_trellis2_image_to_model.json` at commit
  `ea7faae6999fb31338f43408ff4a575bd3f7d9a0` (2026-11-08). UI-format workflow, converted at run time by `cf_ui2api.py` with the worker's own `/object_info`.
- `image_moss_image_edit.json`: Comfy-Org/workflow_templates (MIT), `templates/image_moss_image_edit.json` (same repo, fetched 2026-11-13). Used by the MOSS "editar por instrução" mode.
- `video_wan21_scail2_character_replacement_int8.json` and `video_wan_animate2_distilled.json`: Comfy-Org/workflow_templates (MIT), fetched 2026-11-13. `template_files.json` lists the weights their notes link to, with the Hugging Face revision, byte size and SHA-256 prefix read from the HF API on the same day.
