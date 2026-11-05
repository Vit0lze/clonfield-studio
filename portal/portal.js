import { StudioAPI, studioOrigin } from "./api.js";

const byId = id => document.getElementById(id);
const tools = [
  ["Imagem", "Bancada de modelos", "bancada_gerar", "Gerar imagem"],
  ["Imagem", "Criar com Qwen", "gerar", "Gerar imagem"],
  ["Imagem", "Editar região", "editar_regiao", "Editar região"],
  ["Imagem", "Direção de cena", "direcao_prompt", "Montar prompt"],
  ["Imagem", "Acabamento", "acabamento_imagem", "Aplicar"],
  ["Imagem", "Comparar imagens", "comparar_imagens", "Comparar"],
  ["Vídeo", "Criar vídeo", "gerar_video", "Gerar vídeo"],
  ["Vídeo", "OpenJutsu", "openjutsu", "Executar"],
  ["Vídeo", "Montagem", "montagem_video", "Processar"],
  ["Vídeo", "Sequência", "montar_sequencia", "Montar sequência"],
  ["Melhorar", "Upscale SeedVR2", "seedvr2", "Aplicar upscale"],
  ["Recursos", "Catálogo Civitai", "catalogo_buscar", "Buscar compatíveis"],
  ["Recursos", "Histórico", "historico_listar", "Buscar resultados"],
  ["Avançado", "Workflows ComfyUI", "executar_workflow", "Executar workflow"]
];
const modelSlots = new Set(["Difusão", "Checkpoint", "Encoder", "VAE", "LoRA", "Upscaler"]);
const mainFields = /^(Preset|Prompt|Instrução|Assunto|Referências|Imagem|Vídeo|Mídia|Ferramenta|Busca|Proporção|Largura|Altura|Modo|LoRA|Checkpoint|Difusão|VAE|Encoder|Upscaler|Passos|CFG|Seed|Componente|Antes|Depois|Máscara|Workflow)/i;
const state = { api: null, current: null, busy: false, epoch: 0, components: new Map(), endpoints: new Map(),
  values: new Map(), parents: new Map(), urls: [], catalog: null, history: null };
const inputTypes = new Set(["textbox", "dropdown", "radio", "number", "slider", "checkbox", "file", "image", "video", "audio"]);

function element(type, text, classes) {
  const el = document.createElement(type);
  if (text != null) el.textContent = text;
  if (classes) el.className = classes;
  return el;
}
function button(label, callback, primary = false) {
  const node = element("button", label, primary ? "primary" : "");
  node.type = "button";
  node.disabled = state.busy;
  node.addEventListener("click", callback);
  return node;
}
function currentValue(id) {
  return state.values.has(id) ? state.values.get(id) : state.components.get(id)?.props.value ?? null;
}
function visibility(id) {
  for (let node = id; node != null; node = state.parents.get(node)) {
    if (state.components.get(node)?.props.visible === false) return false;
  }
  return true;
}
function configure(config) {
  state.components = new Map(config.components.map(c => [c.id, c]));
  state.endpoints = new Map(config.dependencies.filter(d => typeof d.api_name === "string").map(d => [d.api_name, d]));
  state.parents.clear();
  const visit = (node, parent) => {
    if (parent != null) state.parents.set(node.id, parent);
    for (const child of node.children || []) visit(child, node.id);
  };
  visit(config.layout);
  if (!state.endpoints.has("bancada_gerar")) throw new Error("Atualize o ClonField no Colab para usar este frontend.");
}
function apply(dependency, output) {
  output.forEach((value, index) => {
    const id = dependency.outputs[index];
    const component = state.components.get(id);
    if (!component || component.type === "state") return;
    if (value?.__type__ === "update") {
      const { __type__, value: selected, ...props } = value;
      Object.assign(component.props, props);
      if (Object.hasOwn(value, "value")) state.values.set(id, selected);
    } else if (inputTypes.has(component.type)) {
      state.values.set(id, value);
    }
  });
}
function clearResults() {
  state.urls.forEach(URL.revokeObjectURL);
  state.urls = [];
  byId("result").replaceChildren();
}
function status(message) { byId("job-status").textContent = message; }

function navigate(tool, { searchCatalog = true } = {}) {
  if (state.busy) return;
  state.current = tool;
  clearResults();
  status("Pronto para executar.");
  byId("elapsed").textContent = "";
  byId("result").append(element("p", "Os arquivos da execução aparecem aqui."));
  render();
  if (tool[2] === "bancada_gerar" && state.endpoints.has("bancada_atualizar")) {
    run("bancada_atualizar", { update: true });
  } else if (tool[2] === "catalogo_buscar" && searchCatalog && !state.catalog) {
    run("catalogo_buscar");
  }
}
function toolName() { return state.current?.[2]; }
function endpointInput(name, label) {
  return state.endpoints.get(name)?.inputs.find(id => state.components.get(id)?.props.label === label);
}
function render() {
  const [group, title, name, action] = state.current;
  const inCatalog = name === "catalogo_buscar";
  byId("stage").classList.toggle("catalog-mode", inCatalog);
  byId("catalog-grid").hidden = !inCatalog;
  byId("tool-group").textContent = group;
  byId("tool-title").textContent = title;
  byId("tools").replaceChildren(...tools.filter(t => state.endpoints.has(t[2])).map(tool => {
    const entry = button(tool[1], () => navigate(tool));
    if (tool === state.current) entry.setAttribute("aria-current", "page");
    return entry;
  }));
  const dependency = state.endpoints.get(name);
  const fields = byId("fields");
  fields.replaceChildren();
  const advanced = element("details");
  advanced.append(element("summary", "Mais parâmetros"));
  for (const id of dependency.inputs) {
    const c = state.components.get(id);
    if (!c || !inputTypes.has(c.type) || c.props.interactive === false || !visibility(id)) continue;
    const label = c.props.label || "Entrada";
    const target = mainFields.test(label) ? fields : advanced;
    if (name === "bancada_gerar" && /^LoRA \d/.test(label)) {
      const index = Number(label.match(/^LoRA (\d+)/)[1]) - 1;
      const adapter = currentValue(endpointInput(name, "LoRA"))?.[index];
      if (!adapter) continue;
      let panel = fields.querySelector(`[data-lora="${index}"]`);
      if (!panel) {
        panel = element("details", null, "lora-options");
        panel.dataset.lora = index;
        const choices = state.components.get(endpointInput(name, "LoRA")).props.choices || [];
        const title = choices.find(choice => choice[1] === adapter)?.[0] || `LoRA ${index + 1}`;
        panel.append(element("summary", title));
        fields.append(panel);
      }
      panel.append(field(c));
    } else {
      target.append(field(c));
    }
  }
  if (advanced.childElementCount > 1) fields.append(advanced);
  const actions = byId("actions");
  actions.replaceChildren(button(action, () => run(name), true));
  if (name === "bancada_gerar" && state.endpoints.has("checar_conjunto")) {
    actions.append(button("Checar conjunto", () => run("checar_conjunto")));
  }
  if (inCatalog) renderCatalog();
  if (name === "historico_listar") renderHistory(fields, actions);
  fields.inert = state.busy;
}

function field(component) {
  const { id, type, props } = component;
  const value = currentValue(id);
  const wrap = element("div");
  const label = element("label", props.label || "Entrada");
  label.htmlFor = `field-${id}`;
  wrap.append(label);
  let input;
  if (["dropdown", "radio"].includes(type)) {
    input = element("select");
    input.multiple = Boolean(props.multiselect);
    if (input.multiple) input.size = Math.min(4, Math.max(2, (props.choices || []).length));
    if (!input.multiple && value == null) input.append(new Option("Selecione", "", true, true));
    for (const entry of props.choices || []) {
      const [text, option] = Array.isArray(entry) ? entry : [entry, entry];
      const selected = input.multiple ? (value || []).includes(option) : value === option;
      input.append(new Option(String(text), JSON.stringify(option), false, selected));
    }
    input.addEventListener("change", () => {
      const decode = option => option.value ? JSON.parse(option.value) : null;
      let next = input.multiple ? [...input.selectedOptions].map(decode) : decode(input);
      if (input.multiple && props.max_choices && next.length > props.max_choices) {
        next = next.slice(0, props.max_choices);
        for (const option of input.options) option.selected = next.includes(decode(option));
      }
      state.values.set(id, next);
      onSelection(id);
    });
  } else if (["file", "image", "video", "audio"].includes(type)) {
    input = element("input");
    input.type = "file";
    input.multiple = props.file_count === "multiple";
    const types = props.file_types || (type === "file" ? [] : [type]);
    input.accept = types.map(type => ["image", "audio", "video"].includes(type) ? `${type}/*` : type).join(",");
    const labelFiles = element("p", null, "help");
    const updateLabel = files => { labelFiles.textContent = files.map(f => f.name || f.orig_name).filter(Boolean).join(", "); };
    updateLabel(Array.isArray(value) ? value : value ? [value] : []);
    input.addEventListener("change", () => {
      const files = [...input.files];
      state.values.set(id, input.multiple ? files : files[0] || null);
      updateLabel(files);
    });
    wrap.append(labelFiles);
  } else if (type === "checkbox") {
    input = element("input");
    input.type = "checkbox";
    input.checked = Boolean(value);
    input.addEventListener("change", () => state.values.set(id, input.checked));
    label.prepend(input);
  } else {
    input = element(type === "textbox" && (props.lines || 1) > 1 ? "textarea" : "input");
    if (type !== "textbox") {
      input.type = "number";
      input.min = props.minimum ?? "";
      input.max = props.maximum ?? "";
      input.step = props.step ?? (props.precision === 0 ? 1 : "any");
    }
    input.value = value ?? "";
    input.placeholder = props.placeholder || "";
    input.addEventListener("input", () => state.values.set(id,
      input.type === "number" ? (Number.isFinite(input.valueAsNumber) ? input.valueAsNumber : null) : input.value));
  }
  input.id = label.htmlFor;
  if (type !== "checkbox") wrap.append(input);
  if (props.info) wrap.append(element("p", props.info, "help"));
  if (toolName() === "bancada_gerar" && modelSlots.has(props.label) && state.endpoints.has("catalogo_buscar")) {
    wrap.append(button("Procurar mais", async () => {
      if (state.busy) return;
      const [catalogPreset, catalogRole, catalogQuery] = state.endpoints.get("catalogo_buscar").inputs;
      state.values.set(catalogPreset, currentValue(state.endpoints.get("bancada_gerar").inputs[0]));
      state.values.set(catalogQuery, "");
      state.catalog = null;
      navigate(tools.find(tool => tool[2] === "catalogo_buscar"), { searchCatalog: false });
      await run("catalogo_tipos", { update: true, hide: true });
      const roles = state.components.get(catalogRole).props.choices || [];
      if (roles.some(choice => (Array.isArray(choice) ? choice[1] : choice) === props.label)) {
        state.values.set(catalogRole, props.label);
      }
      run("catalogo_buscar");
    }));
  }
  return wrap;
}

function onSelection(id) {
  if (id === state.endpoints.get("bancada_preset")?.inputs[0]) {
    run("bancada_preset", { update: true, hide: true });
  } else if (id === endpointInput("bancada_gerar", "LoRA")) {
    run("bancada_loras", { update: true });
  } else if (id === state.endpoints.get("catalogo_buscar")?.inputs[0]) {
    state.catalog = null;
    run("catalogo_tipos", { update: true, hide: true });
  } else if (id === state.endpoints.get("catalogo_buscar")?.inputs[1]) {
    state.catalog = null;
    render();
  } else {
    for (const name of ["video_opcoes", "acabamento_opcoes", "montagem_opcoes"]) {
      if (id === state.endpoints.get(name)?.inputs[0]) {
        run(name, { update: true, hide: true });
        break;
      }
    }
  }
}

function selection(target, id, choices, onChange) {
  const c = state.components.get(id);
  c.props.choices = choices;
  target.append(field(c));
  const control = target.querySelector(`#field-${id}`);
  control.addEventListener("change", onChange);
}
function catalogCover(card) {
  const cover = element("div", null, "catalog-cover");
  const missing = element("span", "Sem capa disponível");
  if (!card.cover) {
    cover.append(missing);
    return cover;
  }
  let url;
  try { url = new URL(card.cover.url); } catch { cover.append(missing); return cover; }
  if (url.origin !== "https://image.civitai.com" || url.username || url.password) {
    cover.append(missing);
    return cover;
  }
  const video = card.cover.type === "video";
  const media = element(video ? "video" : "img");
  media.addEventListener("error", () => cover.replaceChildren(missing), { once: true });
  if (video) {
    media.controls = true;
    media.preload = "metadata";
    media.playsInline = true;
  } else {
    media.alt = card.title;
    media.loading = "lazy";
    media.decoding = "async";
  }
  media.src = url.href;
  cover.append(media);
  return cover;
}
function renderCatalog() {
  const grid = byId("catalog-grid");
  grid.replaceChildren();
  const results = state.catalog;
  if (!results) return;
  for (const card of results.cards) {
    const block = element("article", null, "catalog-card");
    block.setAttribute("aria-label", card.title);
    block.append(catalogCover(card));
    const footer = element("div", null, "catalog-actions");
    const link = element("a", "Civitai");
    const page = new URL(card.page);
    if (page.origin === "https://civitai.com" && /^\/models\/\d+$/.test(page.pathname)) {
      link.href = page.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.setAttribute("aria-label", `Abrir ${card.title} no Civitai`);
      footer.append(link);
    }
    const download = button(card.installed ? "Instalado" : "Baixar", () => {
      state.values.set(state.endpoints.get("catalogo_buscar").outputs[0], card.key);
      run("catalogo_instalar", { card });
    }, true);
    download.setAttribute("aria-label", `${download.textContent} ${card.title}`);
    download.disabled ||= card.installed;
    footer.append(download);
    block.append(footer);
    grid.append(block);
  }
  if (results.next) {
    const next = element("div", null, "catalog-next");
    next.append(button("Carregar mais", () => run("catalogo_proxima")));
    grid.append(next);
  }
}
function renderHistory(fields, actions) {
  if (!state.history?.length) return;
  const picker = state.endpoints.get("historico_listar").outputs[0];
  selection(fields, picker, state.history, render);
  if (currentValue(picker)) actions.append(button("Abrir resultado", () => run("historico_abrir")));
}
async function encodeInput(api, id) {
  const c = state.components.get(id);
  if (!c || c.type === "state") return null;
  const value = currentValue(id);
  if (Array.isArray(value) && value.some(item => item instanceof File)) {
    return Promise.all(value.map(item => item instanceof File ? api.upload(item) : item));
  }
  if (value instanceof File) {
    const file = await api.upload(value);
    return c.type === "video" ? { video: file, subtitles: null } : file;
  }
  return value;
}
function jobEvent(event) {
  if (event.msg === "progress") {
    const stage = event.progress_data?.at(-1);
    if (!stage) return;
    if (stage.desc) status(stage.desc);
    if (typeof stage.progress === "number") byId("job-progress").value = stage.progress;
    else if (stage.length) byId("job-progress").value = stage.index / stage.length;
  } else if (event.msg === "estimation") {
    status(event.rank == null ? "Na fila do Studio…" : `Na fila · posição ${event.rank + 1}`);
  } else if (event.msg === "process_starts") {
    status("Executando no Colab…");
  }
}

async function run(name, options = {}) {
  if (state.busy) return;
  const dependency = state.endpoints.get(name);
  if (!dependency) return;
  if (name === "catalogo_buscar" && dependency.outputs.length < 6) {
    status("Atualize e reinicie o ClonField no Colab para carregar as capas do catálogo.");
    return;
  }
  const api = state.api;
  const epoch = state.epoch;
  state.busy = true;
  render();
  byId("fields").hidden = !!options.hide;
  const progress = byId("job-progress");
  progress.removeAttribute("value");
  progress.hidden = false;
  status("Preparando a solicitação…");
  const start = Date.now();
  const timer = setInterval(() => {
    if (epoch === state.epoch) byId("elapsed").textContent = `${Math.floor((Date.now() - start) / 1000)} s`;
  }, 1000);
  try {
    const data = await Promise.all(dependency.inputs.map(id => encodeInput(api, id)));
    status("Solicitação enviada à fila…");
    const output = await api.submit(dependency, data, event => { if (epoch === state.epoch) jobEvent(event); });
    if (epoch !== state.epoch) return;
    if (options.update || ["catalogo_buscar", "catalogo_proxima", "historico_listar"].includes(name)) apply(dependency, output);
    if (["catalogo_buscar", "catalogo_proxima"].includes(name)) {
      state.catalog = { cards: Array.isArray(output[5]) ? output[5] : [], next: output[4]?.interactive === true };
      status(output[3] || "Busca concluída.");
    } else if (name === "catalogo_instalar") {
      status(output[0] || "Arquivo baixado.");
      if (options.card) options.card.installed = true;
      const refresh = state.endpoints.get("bancada_atualizar");
      if (refresh) {
        try {
          const inputs = await Promise.all(refresh.inputs.map(id => encodeInput(api, id)));
          const updated = await api.submit(refresh, inputs, () => {});
          if (epoch === state.epoch) apply(refresh, updated);
        } catch {
          if (epoch === state.epoch) status("Arquivo baixado. Reabra a Bancada para atualizar a lista.");
        }
      }
    } else if (name === "historico_listar") {
      state.history = output[0]?.choices || [];
      status(output[1] || "Busca concluída.");
    } else if (options.update) {
      status(name === "bancada_atualizar" ? "Componentes instalados atualizados." : "Opções atualizadas.");
    } else {
      await showOutputs(api, dependency, output);
    }
  } catch (error) {
    if (epoch === state.epoch) status(error.message || "Falha na comunicação com o Colab.");
  } finally {
    clearInterval(timer);
    if (epoch === state.epoch) {
      state.busy = false;
      progress.hidden = true;
      byId("fields").hidden = false;
      render();
    }
  }
}

function gatherFiles(value, files, label) {
  if (!value || typeof value !== "object") return;
  if (typeof value.path === "string" && value.meta?._type === "gradio.FileData") {
    if (!files.has(value.path)) files.set(value.path, { ...value, label });
    return;
  }
  if (Array.isArray(value)) value.forEach(item => gatherFiles(item, files, label));
  else Object.values(value).forEach(item => gatherFiles(item, files, label));
}
async function showOutputs(api, dependency, output) {
  clearResults();
  const target = byId("result");
  const files = new Map();
  const messages = [];
  output.forEach((value, index) => {
    const c = state.components.get(dependency.outputs[index]);
    if (!c || c.type === "state") return;
    gatherFiles(value, files, c.props.label);
    if (typeof value === "string" && value.trim()) messages.push(value);
    if (c.type === "json" && value && value.__type__ !== "update") {
      const info = element("details");
      info.append(element("summary", c.props.label || "Detalhes"), element("pre", JSON.stringify(value, null, 2)));
      target.append(info);
    }
  });
  status(messages.find(message => /^(falh|conclu|aguard|erro|envio)/i.test(message))?.split("\n")[0] || "Resposta recebida.");
  for (const message of messages) target.append(element("p", message));
  for (const file of files.values()) {
    const figure = element("figure");
    const filename = file.orig_name || file.path.split("/").at(-1);
    const type = /\.(png|jpe?g|webp|gif|avif)$/i.test(filename) ? "img" :
      /\.(mp4|webm|mov)$/i.test(filename) ? "video" : /\.(mp3|wav|ogg|flac)$/i.test(filename) ? "audio" : null;
    const link = element("a", `Baixar ${filename}`);
    figure.append(element("figcaption", file.label || filename));
    target.append(figure);
    try {
      const blob = await api.file(file);
      if (api !== state.api) return;
      const url = URL.createObjectURL(blob);
      state.urls.push(url);
      if (type) {
        const media = element(type);
        media.src = url;
        if (type === "img") media.alt = file.label || filename;
        else media.controls = true;
        figure.append(media);
      }
      link.href = url;
      link.download = filename;
      figure.append(link);
    } catch {
      figure.append(element("p", "O arquivo ficou indisponível para download."));
    }
  }
  if (!target.childElementCount) target.append(element("p", "A operação não devolveu arquivos."));
}

byId("job-form").addEventListener("submit", event => {
  event.preventDefault();
  if (toolName()) run(toolName());
});

const password = byId("password");
byId("reveal").addEventListener("click", () => {
  const visible = password.type === "password";
  password.type = visible ? "text" : "password";
  byId("reveal").textContent = visible ? "Ocultar" : "Mostrar";
  byId("reveal").setAttribute("aria-pressed", String(visible));
});
byId("connect").addEventListener("submit", async event => {
  event.preventDefault();
  const origin = studioOrigin(byId("address").value);
  const message = byId("connection-status");
  if (!origin) {
    message.textContent = "Cole o link público HTTPS exibido no Colab.";
    return;
  }
  byId("submit").disabled = true;
  message.textContent = "Conectando ao Studio…";
  const api = new StudioAPI(origin);
  try {
    configure(await api.connect(password.value.trim()));
    state.api = api;
    state.epoch++;
    password.value = "";
    byId("access").hidden = true;
    byId("workspace").hidden = false;
    byId("session").hidden = false;
    byId("worker").textContent = new URL(origin).host;
    navigate(tools[0]);
  } catch (error) {
    api.disconnect();
    message.textContent = error instanceof TypeError
      ? "A sessão não respondeu. Confira o link e se o Colab continua rodando."
      : error.message;
  } finally {
    byId("submit").disabled = false;
  }
});
byId("disconnect").addEventListener("click", () => {
  state.api?.disconnect();
  state.epoch++;
  state.api = null;
  state.busy = false;
  state.values.clear();
  state.catalog = null;
  state.history = null;
  clearResults();
  byId("workspace").hidden = true;
  byId("session").hidden = true;
  byId("access").hidden = false;
  byId("connection-status").textContent = "";
  byId("address").focus();
});
