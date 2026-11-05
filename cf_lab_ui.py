"""Gradio screens for the model bench, Civitai catalog and scene direction."""

from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
from pathlib import Path
import tempfile
import time

import gradio as gr
import requests

import cf_civitai as civitai
import cf_model_lab as lab
import cf_workflows as workflows

PRESET_CHOICES = [(preset.title, preset.key) for preset in lab.PRESETS.values()]
EXTRA_ROLES = ("ControlNet", "Embedding", "CLIP Vision", "Motion Module", "Workflow")
BENCH_ROLES = ("Difusão", "Checkpoint", "Encoder", "VAE", "LoRA", "Upscaler")
DEFAULT_COMPONENT = "__preset__"
LORA_LIMIT = 4


def handle_errors(callback):
    @wraps(callback)
    def call(*args, **kwargs):
        try:
            return callback(*args, **kwargs)
        except requests.RequestException:
            raise gr.Error("Não foi possível completar a conexão com o serviço.") from None
        except (OSError, ValueError, KeyError) as exc:
            raise gr.Error(str(exc), print_exception=False) from None
    return call


def render(main_tabs, directory, output_dir, result_view, release_qwen):
    def component_options(preset_key, role, pending=None):
        preset = lab.PRESETS[preset_key]
        records = civitai.inventory(directory, preset, role)
        options = [(f'{data["title"]} · {data["revision"]} · {data["name"]}', key)
                   for key, data, _ in records]
        installed = {key for _, key in options}
        options += [(f'Baixar ao gerar · {entry["title"]} · {entry["revision"]} · {entry["name"]}', key)
                    for key, entry in (pending or {}).items()
                    if key not in installed and entry["preset"] == preset_key and entry["role"] == role]
        if role in preset.files:
            options.insert(0, (f"Padrão · {Path(preset.files[role][1]).name}", DEFAULT_COMPONENT))
        elif role == "VAE" and not preset.clip_type:
            options.insert(0, ("Padrão · VAE do checkpoint", DEFAULT_COMPONENT))
        elif role == "Upscaler":
            options.insert(0, ("Nenhum · tamanho original", DEFAULT_COMPONENT))
        return options

    def choices(preset_key, role, pending=None, current=None):
        options = component_options(preset_key, role, pending)
        keys = {key for _, key in options}
        if role == "LoRA":
            selected = [key for key in current or [] if key in keys]
        else:
            selected = current if current in keys else DEFAULT_COMPONENT if DEFAULT_COMPONENT in keys else None
        return gr.update(choices=options, value=selected)

    def browse_role(role, preset_key):
        return (gr.Tabs(selected="civitai"), preset_key,
                gr.update(choices=[*lab.PRESETS[preset_key].roles, *EXTRA_ROLES], value=role),
                "", *clear_catalog())

    def sync_lora_controls(preset_key, pending, keys, previous, *weights):
        keys = (keys or [])[:LORA_LIMIT]
        old = dict(zip(previous or [], zip(weights[::2], weights[1::2])))
        labels = dict((key, label.rsplit(" · ", 1)[-1])
                      for label, key in component_options(preset_key, "LoRA", pending))
        panels, numbers = [], []
        for index in range(LORA_LIMIT):
            if index < len(keys):
                key = keys[index]
                label = f'LoRA {index + 1} · {labels.get(key, key)[:65]}'
                panels.append(gr.update(label=label, visible=True))
                numbers.extend(old.get(key, (None, None)))
            else:
                panels.append(gr.update(visible=False))
                numbers.extend((None, None))
        return (keys, *panels, *numbers)

    def catalog_roles(preset_key):
        options = [*lab.PRESETS[preset_key].roles, *EXTRA_ROLES]
        return gr.update(choices=options, value="LoRA")

    @handle_errors
    def list_catalog(preset_key, role, query, cursor, previous=None):
        entries, next_cursor = civitai.search(lab.PRESETS[preset_key], role, query, cursor)
        if cursor and previous:
            entries = [*previous.values(), *entries]
        # Keep exact version/file choices in per-session state. UI values are just identifiers.
        records = {f'{entry["version"]}:{entry["file"]}': entry for entry in entries}
        labels = [(f'{entry["title"][:75]} · {entry["revision"][:42]} · {entry["name"][:90]}', key)
                  for key, entry in records.items()]
        target = lab.PRESETS[preset_key].title
        status = (f"{len(labels)} arquivos para {target} · {role}. Compatibilidade verificada antes da listagem."
                  if labels else f"Nenhum {role} com compatibilidade verificável para {target} nesta página.")
        if next_cursor:
            status += " Você pode consultar a próxima página."
        installed = {(data.get("version"), data.get("file"))
                     for _, data, _ in civitai.inventory(directory, lab.PRESETS[preset_key], role)}
        return (gr.update(choices=labels, value=None), records, next_cursor, status,
                gr.update(interactive=bool(next_cursor)), civitai.catalog_cards(records, installed))

    def clear_catalog():
        return gr.update(choices=[], value=None), {}, None, "", gr.update(interactive=False), []

    @handle_errors
    def show_file(key, records):
        entry = (records or {}).get(key)
        if not entry:
            return ""
        size = entry.get("size_kb")
        size = f" · {float(size) / 1024:.1f} MiB" if size else ""
        checksum = " · SHA-256 publicado" if entry.get("sha256") else ""
        return f'{entry["role"]} · {entry["base"] or "base independente"} · versão {entry["version"]}{size}{checksum}'

    def get_entry(key, records, preset_key, role):
        entry = (records or {}).get(key)
        if not entry or entry["preset"] != preset_key or entry["role"] != role:
            raise ValueError("Busque e escolha um arquivo para o preset e o componente atuais.")
        return entry

    @handle_errors
    def install_asset(key, records, preset_key, role, progress=gr.Progress()):
        entry = get_entry(key, records, preset_key, role)
        progress(0.15, desc=f'Baixando a versão {entry["version"]}')
        path = civitai.install(entry, directory)
        if entry["role"] in EXTRA_ROLES and entry["role"] != "Workflow":
            lab.stage_local(civitai.ROLE_TYPES[entry["role"]], path.name, path)
            return f"Disponível no ComfyUI como {path.name}. Use um grafo que ofereça o loader correspondente."
        if entry["role"] == "Workflow":
            return f"Salvo como {path.name}. Use a aba Workflows para revisar e executar API JSON."
        return f"Instalado: {path.name}. Disponível para presets compatíveis na Bancada."

    @handle_errors
    def show_images(key, records, preset_key, role, progress=gr.Progress()):
        entry = (records or {}).get(key)
        if not entry or entry["preset"] != preset_key or entry["role"] != role:
            return [], [], None, "Selecione um arquivo dos resultados desta busca."
        progress(0.1, desc="Buscando exemplos da versão")
        images = civitai.previews(entry)

        def fetch_image(image):
            try:
                path = civitai.fetch_image(image["url"], Path(tempfile.gettempdir()) / "clonfield-civitai", image["id"])
                return path, f'Civitai · imagem {image["id"]}'
            except (ValueError, KeyError):
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            gallery = [item for item in pool.map(fetch_image, images) if item]
        return gallery, [path for path, _ in gallery], None, (
            f"{len(gallery)} imagens desta versão." if gallery else "Nenhum exemplo disponível para esta versão.")

    def select_image(paths, evt: gr.SelectData):
        index = evt.index
        return paths[index] if evt.selected and isinstance(index, int) and 0 <= index < len(paths or []) else None

    @handle_errors
    def send_image(path, preset_key):
        if not path or not Path(path).is_file():
            raise ValueError("Escolha uma imagem da galeria.")
        if not lab.PRESETS[preset_key].refs:
            raise ValueError("Este preset não aceita referências.")
        return gr.Tabs(selected="bancada"), gr.update(value=[path], visible=True)

    def catalog_actions(key, records, preset_key, role):
        entry = (records or {}).get(key)
        valid = bool(entry and entry["preset"] == preset_key and entry["role"] == role)
        bench = valid and role in lab.PRESETS[preset_key].roles
        graph = valid and role == "Workflow" and Path(entry["name"]).suffix.lower() == ".json"
        return (gr.update(visible=bench), gr.update(visible=valid),
                gr.update(visible=valid), gr.update(visible=graph))

    def reference_action(path, preset_key):
        return gr.update(visible=bool(path and lab.PRESETS[preset_key].refs))

    @handle_errors
    def open_workflow(key, records, preset_key, role):
        entry = get_entry(key, records, preset_key, role)
        if entry["role"] != "Workflow" or Path(entry["name"]).suffix.lower() != ".json":
            raise ValueError("Escolha um workflow API JSON. ZIP e PNG ficam disponíveis como arquivos para revisão.")
        path = civitai.install(entry, directory)
        workflows.read_graph(path)
        return gr.Tabs(selected="workflows"), str(path)

    def lab_fields(preset_key, pending=None):
        preset = lab.PRESETS[preset_key]
        notes = (f"Até {preset.refs} referências." if preset.refs else "Este preset gera a partir de texto.")
        if preset.key == "qwen21":
            notes += " Em edição, a primeira referência recebe o recorte central da proporção escolhida."
        if preset.key == "flux3":
            notes += " Use o expansor local ou escreva uma legenda visual completa."
        if not preset.clip_type:
            notes += " Instale e selecione um checkpoint desta família."
        size = 512 if preset.key == "sd15" else 768
        return (preset.steps, preset.cfg, size, size, gr.update(value=None, visible=bool(preset.refs)),
                gr.update(value=preset.key == "flux3", visible=preset.key == "flux3"), notes,
                *(choices(preset_key, role, pending) for role in BENCH_ROLES),
                *(gr.update(visible=role in preset.roles) for role in BENCH_ROLES))

    def refresh_lab(preset_key, pending, *values):
        return [choices(preset_key, role, pending, value) for role, value in zip(BENCH_ROLES, values)]

    @handle_errors
    def assign_asset(key, records, preset_key, role, saved, active_preset, *values):
        entry = get_entry(key, records, preset_key, role)
        role, target = entry["role"], entry["preset"]
        if role not in lab.PRESETS[target].roles:
            raise ValueError("Esse tipo usa o botão Instalar e um grafo próprio no ComfyUI.")
        entry_key = civitai.asset_key(entry)
        saved = {**(saved or {}), entry_key: entry}
        if active_preset == target:
            parameters = [gr.skip()] * 7
            rows = [gr.skip()] * len(BENCH_ROLES)
            selected = dict(zip(BENCH_ROLES, values))
        else:
            fields = lab_fields(target, saved)
            parameters = fields[:7]
            rows = fields[7 + len(BENCH_ROLES):]
            selected = {}
        if role == "LoRA":
            adapters = list(dict.fromkeys([*(selected.get(role) or []), entry_key]))
            if len(adapters) > LORA_LIMIT:
                raise ValueError("Remova uma LoRA da Bancada antes de adicionar outra.")
            selected[role] = adapters
        else:
            selected[role] = entry_key
        return (gr.Tabs(selected="bancada"), target, saved, *parameters,
                *(choices(target, item, saved, selected.get(item)) for item in BENCH_ROLES), *rows)

    def plan(preset_key, prompt, negative, width, height, steps, cfg, seed, refs, strength, expand, pending, *values):
        preset = lab.PRESETS[preset_key]
        selected = {role: value for role, value in zip(BENCH_ROLES, values) if value != DEFAULT_COMPONENT}
        adapters = selected.pop("LoRA", None)
        chosen = lab.selections(directory, preset, selected, adapters, pending)
        names, sources = lab.names_and_sources(preset, chosen, expand)
        # Bind weights to the LoRA id even if the client has just reordered the selection.
        weight_fields = values[len(BENCH_ROLES):]
        weights = {}
        if weight_fields:
            order, *numbers = weight_fields
            weights = dict(zip(order or [], zip(numbers[::2], numbers[1::2])))
        pairs = [weights.get(key, (None, None)) for key in dict.fromkeys(adapters or [])]
        graph, uploads, actual_seed = lab.make_graph(preset, names, prompt, negative, width, height, steps, cfg,
                                                      seed, refs, strength, expand, lora_weights=pairs)
        queued = [entry for entries in chosen.values() for entry, _ in entries if "download" in entry]
        return preset, graph, uploads, sources, actual_seed, queued

    @handle_errors
    def check(*values):
        _, graph, _, sources, _, _ = plan(*values)
        with requests.Session() as session:
            session.trust_env = False
            lab.worker_schema(session, graph, check_files=False)
        pending = [name for folder, name, _ in sources if not (lab.models_root() / folder / name).is_file()]
        status = "Conjunto coerente. Nós e opções conferidos no ComfyUI local."
        if pending:
            status += "\nPreparação sob demanda: " + ", ".join(pending)
        return status + "\nA geração confirma se a combinação carrega e cabe na memória.", graph

    def acknowledge():
        print("[Bancada] Clique recebido; aguardando a fila da GPU.", flush=True)
        return gr.update(value="Job na fila…", interactive=False), "Pedido recebido. Aguardando a fila da GPU."

    def generate(progress=gr.Progress(), *values):
        # Gradio only injects Progress before the variadic portion of the signature.
        started = time.monotonic()

        def report(fraction, *, desc):
            print(f"[Bancada +{time.monotonic() - started:.0f}s] {desc}", flush=True)
            progress(fraction, desc=desc)

        report(0, desc="Validando o conjunto")
        try:
            preset, graph, uploads, sources, seed, queued = plan(*values)
            release_qwen()
            prepare = partial(lab.prepare, sources=sources, uploads=uploads, pending=queued, asset_directory=directory)
            job = workflows.run(graph, output_dir, report, prepare=prepare, title=f"{preset.title} · seed {seed}")
            images, _, _, files, status = result_view(job)
        except requests.RequestException:
            status = "Falha de conexão com o serviço."
            print(f"[Bancada] {status}", flush=True)
            return gr.skip(), gr.skip(), status, gr.skip()
        except (OSError, ValueError, KeyError) as exc:
            status = f"Falhou: {exc}"
            print(f"[Bancada] {status}", flush=True)
            return gr.skip(), gr.skip(), status, gr.skip()
        report(1, desc=f"Estado final: {job['status']}")
        return images, files, status, graph

    @handle_errors
    def build_direction(subject, action, framing, motion, light, look, references):
        if not (subject or "").strip():
            raise ValueError("Descreva o assunto e a cena.")
        fields = ((None, subject), ("Ação", action), ("Enquadramento", framing), ("Movimento", motion),
                  ("Luz", light), ("Visual", look), ("Papéis das referências", references))
        return "\n".join(f"{label}: {value.strip()}" if label else value.strip()
                         for label, value in fields if (value or "").strip() and value != "Livre")

    with gr.Tab("Catálogo Civitai", id="civitai"):
        gr.Markdown("Busque por nome ou cole o link de um recurso. O preset e o tipo determinam quais arquivos aparecem.")
        with gr.Row():
            cpreset = gr.Dropdown(PRESET_CHOICES, value="qwen21", label="Preset de destino")
            crole = gr.Dropdown([*lab.PRESETS["qwen21"].roles, *EXTRA_ROLES], value="LoRA", label="Componente")
            query = gr.Textbox(label="Busca", placeholder="Nome ou https://civitai.com/models/…")
        with gr.Row():
            search_button = gr.Button("Buscar compatíveis", variant="primary")
            more = gr.Button("Próxima página", interactive=False)
        pick = gr.Dropdown(label="Arquivos compatíveis · versão exata", filterable=True)
        state, cursor = gr.State({}), gr.State(None)
        cstatus = gr.Textbox(label="Busca", interactive=False)
        details = gr.Textbox(label="Componente", interactive=False)
        with gr.Row():
            use_asset = gr.Button("Usar na Bancada · baixar ao gerar", variant="primary", visible=False)
            install = gr.Button("Instalar agora", visible=False)
            previews = gr.Button("Ver imagens da versão", visible=False)
            open_graph = gr.Button("Abrir API JSON em Workflows", visible=False)
        installed = gr.Textbox(label="Instalação", interactive=False)
        preview_gallery = gr.Gallery(label="Imagens do Civitai", columns=4, object_fit="contain")
        paths, selected_path = gr.State([]), gr.State(None)
        pstatus = gr.Markdown()
        send = gr.Button("Usar como referência na Bancada", visible=False)
        cards = gr.JSON(label="Capas do catálogo", visible=False)
        catalog_outputs = [pick, state, cursor, cstatus, more, cards]
        cpreset.input(catalog_roles, cpreset, crole, queue=False, api_name="catalogo_tipos")
        for event in (cpreset.input, crole.input, query.input):
            event(clear_catalog, None, catalog_outputs, queue=False, api_name=False)
        def search_catalog(preset_key, role, text):
            return list_catalog(preset_key, role, text, None)

        search_button.click(search_catalog, [cpreset, crole, query], catalog_outputs,
                            api_name="catalogo_buscar", concurrency_id="civitai", concurrency_limit=1)
        query.submit(search_catalog, [cpreset, crole, query], catalog_outputs, api_name=False,
                     concurrency_id="civitai", concurrency_limit=1)
        more.click(list_catalog, [cpreset, crole, query, cursor, state], catalog_outputs, api_name="catalogo_proxima",
                   concurrency_id="civitai", concurrency_limit=1)
        pick.change(show_file, [pick, state], details, queue=False, api_name=False)
        for event in (pick.change, cpreset.input, crole.input, query.input):
            event(catalog_actions, [pick, state, cpreset, crole], [use_asset, install, previews, open_graph],
                  queue=False, api_name=False)
        pick.change(lambda: ([], [], None, ""), None, [preview_gallery, paths, selected_path, pstatus],
                    queue=False, api_name=False)
        install.click(install_asset, [pick, state, cpreset, crole], installed, api_name="catalogo_instalar", concurrency_id="civitai", concurrency_limit=1)
        previews.click(show_images, [pick, state, cpreset, crole], [preview_gallery, paths, selected_path, pstatus],
                       api_name="catalogo_imagens", concurrency_id="civitai", concurrency_limit=1)
        preview_gallery.select(select_image, paths, selected_path, queue=False, api_name=False)

    with gr.Tab("Bancada de modelos", id="bancada"):
        with gr.Row(elem_id="cf-bench"):
            with gr.Column(scale=5, min_width=320):
                preset = gr.Dropdown(PRESET_CHOICES, value="qwen21", label="Preset")
                pending_assets, weight_order = gr.State({}), gr.State([])
                notes = gr.Markdown("Até 3 referências. Em edição, a primeira recebe o recorte central da proporção escolhida.")
                prompt = gr.Textbox(label="Prompt", lines=4)
                with gr.Row():
                    run = gr.Button("Gerar imagem", variant="primary")
                    preflight = gr.Button("Checar conjunto", size="sm")
                refs = gr.File(label="Referências na ordem enviada", type="filepath", file_types=["image"], file_count="multiple")
                with gr.Row():
                    width = gr.Slider(256, 2048, step=32, value=768, label="Largura")
                    height = gr.Slider(256, 2048, step=32, value=768, label="Altura")
                with gr.Accordion("Componentes do preset", open=True):
                    components, component_rows, browse = [], [], []
                    lora_panels, lora_weights = [], []
                    for role in BENCH_ROLES:
                        with gr.Row(visible=role in lab.PRESETS["qwen21"].roles, elem_classes=["cf-slot"]) as row:
                            initial = component_options("qwen21", role)
                            default = DEFAULT_COMPONENT if any(key == DEFAULT_COMPONENT for _, key in initial) else None
                            selector = gr.Dropdown(initial, value=[] if role == "LoRA" else default, label=role,
                                                   multiselect=role == "LoRA", max_choices=LORA_LIMIT if role == "LoRA" else None,
                                                   min_width=150)
                            lookup = gr.Button("Procurar mais", size="sm", scale=0, min_width=110)
                        components.append(selector)
                        component_rows.append(row)
                        browse.append(lookup)
                        if role == "LoRA":
                            for index in range(LORA_LIMIT):
                                with gr.Accordion(f"LoRA {index + 1}", open=False, visible=False) as panel:
                                    with gr.Row():
                                        lora_weights.append(gr.Number(value=.8, label=f"LoRA {index + 1} · Modelo", minimum=-2, maximum=2))
                                        lora_weights.append(gr.Number(value=.8, label=f"LoRA {index + 1} · Encoder", minimum=-2, maximum=2))
                                lora_panels.append(panel)
                    refresh = gr.Button("Atualizar arquivos instalados", size="sm")
                with gr.Accordion("Parâmetros avançados", open=False):
                    negative = gr.Textbox(label="Negativo (CFG acima de 1)")
                    with gr.Row():
                        steps = gr.Slider(1, 80, step=1, value=40, label="Passos")
                        cfg = gr.Slider(1, 12, step=.1, value=1, label="CFG")
                        seed = gr.Number(value=-1, precision=0, label="Seed (-1 aleatória)")
                    strength = gr.Slider(-2, 2, value=.8, step=.05, label="Peso padrão para LoRAs sem ajuste próprio")
                    expand = gr.Checkbox(value=False, visible=False, label="Expansor de prompt local FLUX.3")
            with gr.Column(scale=6, min_width=320):
                status = gr.Textbox(value="Pronto para gerar.", label="Estado da geração", interactive=False,
                                    lines=3, max_lines=5)
                results = gr.Gallery(label="Imagens", format="png", height=420, object_fit="contain")
                downloads = gr.File(label="Baixar arquivos", file_count="multiple")
                with gr.Accordion("Grafo API enviado ao ComfyUI", open=False):
                    graph_view = gr.JSON(label="Grafo")
        preset_outputs = [steps, cfg, width, height, refs, expand, notes, *components, *component_rows]
        preset.input(lab_fields, [preset, pending_assets], preset_outputs, queue=False, api_name="bancada_preset")
        refresh.click(refresh_lab, [preset, pending_assets, *components], components, queue=False, api_name="bancada_atualizar")
        for role, lookup in zip(BENCH_ROLES, browse):
            lookup.click(partial(browse_role, role), preset, [main_tabs, cpreset, crole, query, *catalog_outputs],
                         queue=False, api_name=False)
        use_asset.click(assign_asset, [pick, state, cpreset, crole, pending_assets, preset, *components],
                        [main_tabs, preset, pending_assets, *preset_outputs], queue=False, api_name="catalogo_usar")
        lora_selector = components[BENCH_ROLES.index("LoRA")]
        lora_selector.change(sync_lora_controls, [preset, pending_assets, lora_selector, weight_order, *lora_weights],
                             [weight_order, *lora_panels, *lora_weights], queue=False, api_name="bancada_loras")
        inputs = [preset, prompt, negative, width, height, steps, cfg, seed, refs, strength, expand,
                  pending_assets, *components, weight_order, *lora_weights]
        preflight.click(check, inputs, [status, graph_view], api_name="checar_conjunto")
        accepted = run.click(acknowledge, None, [run, status], queue=False, api_name=False, trigger_mode="once")
        job = accepted.success(generate, inputs, [results, downloads, status, graph_view], api_name="bancada_gerar",
                               concurrency_id="gpu", concurrency_limit=1, show_progress="full", show_progress_on=status)
        job.then(lambda: gr.update(value="Gerar imagem", interactive=True), None, run, queue=False, api_name=False)
        job.failure(lambda: "Falha inesperada. Confira o log do Studio antes de tentar novamente.", None, status,
                    queue=False, api_name=False)
        send.click(send_image, [selected_path, preset], [main_tabs, refs], queue=False, api_name=False)
        for event in (selected_path.change, preset.change):
            event(reference_action, [selected_path, preset], send, queue=False, api_name=False)

    with gr.Tab("Direção de cena", id="direcao"):
        gr.Markdown("Organize sujeito, ação, câmera, luz e referências em um prompt editável.")
        subject = gr.Textbox(label="Sujeito e cena", lines=2)
        action = gr.Textbox(label="Ação e expressão", lines=2)
        with gr.Row():
            framing = gr.Dropdown(["Livre", "Plano geral", "Plano médio", "Close", "Macro", "Contra-plongée"],
                                  value="Livre", label="Enquadramento", allow_custom_value=True)
            motion = gr.Dropdown(["Livre", "Câmera fixa", "Dolly in", "Pan lateral", "Órbita", "Handheld"],
                                 value="Livre", label="Movimento para vídeo", allow_custom_value=True)
        light = gr.Textbox(label="Iluminação", placeholder="Ex.: luz lateral suave e recorte azul")
        look = gr.Textbox(label="Cor, textura e atmosfera")
        reference_notes = gr.Textbox(label="Função de cada referência",
                                     placeholder="Ex.: imagem 1 para composição, imagem 2 para paleta")
        make = gr.Button("Montar prompt", variant="primary")
        directed = gr.Textbox(label="Prompt editável", lines=7)
        to_lab = gr.Button("Enviar à Bancada")
        make.click(build_direction, [subject, action, framing, motion, light, look, reference_notes],
                   directed, api_name="direcao_prompt")
        to_lab.click(lambda value: (gr.Tabs(selected="bancada"), value), directed, [main_tabs, prompt],
                     queue=False, api_name=False)

    return open_graph, open_workflow, [pick, state, cpreset, crole]
