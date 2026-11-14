import { api, store, isFinal, events } from "../api.js";
import { anchorPopover } from "../popover.js";
import { lightEditor } from "../lights.js";
import { boxEditor } from "../boxes.js";
import { openSearch } from "../search.js";
import { favFirst, starButton, isFav } from "../favs.js";
import { hideAdult } from "../adult.js";
import { h, icon, clear, seg, dropdown, actionMenu, appGlyph, reconcile, bareUrl, slider, switchRow, field, toast, illustration, posterEl, artFor, fmtClock, fmtBytes } from "../ui.js";

const SEND_TO = { image: ["upscale", "look", "frame", "animate", "edit", "relight", "compare"], video: ["clip", "still", "board", "seedvr2"] };
const NAME_LIMITS = { image: "imagem", video: "vídeo" };

export async function appView(id, navigate) {
  const [apps, models] = await Promise.all([store.loadApps(), (store.models ||= api.get("/models"))]);
  const app = apps.find(a => a.id === id);
  const root = h("div", { class: "view" });
  if (!app) { root.append(h("div", { class: "empty" }, illustration("error"), h("h3", null, "App não encontrado"), h("a", { class: "btn", href: "#/apps" }, "Ver todos os apps"))); return { el: root }; }

  const prefill = store.takePrefill(app.id);
  const values = {};
  for (const f of app.fields) values[f.id] = structuredClone(prefill[f.id] ?? f.default ?? (f.type === "files" || f.type === "loras" || f.type === "lights" || f.type === "boxes" ? [] : ""));
  const cleanups = [];
  // Capabilities this app uses or lets you insert around its result (shared with other apps and with the agent).
  const usesBar = h("div", { class: "uses-bar", hidden: true });
  api.get(`/capabilities?app=${encodeURIComponent(app.id)}`).then(list => {
    if (!list.length) return;
    usesBar.hidden = false;
    usesBar.append(h("span", { class: "dim" }, "Capacidades:"), ...list.map(c => h("a", { class: "chip-link", href: `#/capabilities/${c.id}`,
      title: `${c.tagline} · ${c.consumers.length} app(s) usam` }, c.title)));
  }).catch(() => {});
  const binders = {};                         // field id -> programmatic update, used when a Conjunto is applied
  const TUNING = new Set(["steps", "cfg"]);   // touching these by hand means the user left the chosen Conjunto
  let setPick = null, setNote = null;
  let markManualHook = () => {};
  const markManual = () => { if (values.set && values.set !== "Manual") { values.set = "Manual"; setPick?.set("Manual"); markManualHook(); } };
  let follower = null, tick = null, current = null;
  // Reframes live per job: kept in memory while the page is open and in localStorage so they survive a reload.
  const reframes = new Map(), hydrated = new Set(), coverSaved = new Set();
  const REFRAME_KEY = id => `cf-reframe-${id}`;
  const stateFor = (job, source = null) => {
    let s = reframes.get(job.id);
    if (!s) { s = { source, reframed: null, resultJobId: null, ratio: null, fit: "Preencher", focus: { x: 0.5, y: 0.5 } }; reframes.set(job.id, s); }
    if (source && !s.source) s.source = source;
    return s;
  };
  const persist = (job, s) => {
    try {
      if (!s.reframed) localStorage.removeItem(REFRAME_KEY(job.id));
      else localStorage.setItem(REFRAME_KEY(job.id), JSON.stringify({ resultJobId: s.resultJobId, sourceId: s.source?.id || null, ratio: s.ratio, fit: s.fit, focus: s.focus }));
    } catch { /* storage unavailable: the reframe still works for this visit */ }
  };
  async function hydrate(job) {
    if (hydrated.has(job.id)) return;
    hydrated.add(job.id);
    let record = null;
    try { record = JSON.parse(localStorage.getItem(REFRAME_KEY(job.id)) || "null"); } catch { /* ignore */ }
    if (!record?.resultJobId) return;
    try {
      const [done, source] = await Promise.all([api.get(`/jobs/${record.resultJobId}`), record.sourceId ? api.get(`/uploads/${record.sourceId}`).catch(() => null) : null]);
      const out = (done.results || []).find(r => r.kind === "image");
      if (!out) return;
      Object.assign(stateFor(job, source), { reframed: out, resultJobId: record.resultJobId, ratio: record.ratio, fit: record.fit || "Preencher", focus: record.focus || { x: 0.5, y: 0.5 } });
      if (current?.id === job.id) finished(job);
    } catch { /* the original result stays on stage */ }
  }

  const stage = h("section", { class: "stage", "aria-live": "polite" });
  const advice = h("div", { class: "advice", hidden: true });
  const missingLine = h("div", { class: "hint" });
  const runButton = h("button", { class: "btn primary lg block", type: "button", onclick: () => run() }, icon("bolt", "sm"), "Gerar");
  const refresh = [];
  const rerun = () => refresh.forEach(fn => fn());

  // ---------- controls ----------
  function control(f) {
    if (f.type === "hidden") return null;
    if (f.type === "textarea" || f.type === "text") {
      const input = h(f.type === "textarea" ? "textarea" : "input", { class: "input", rows: f.rows, value: values[f.id], placeholder: f.placeholder || "",
        oninput: () => { values[f.id] = input.value; rerun(); },
        onkeydown: e => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") run(); } });
      return field(f.label, input, f.help);
    }
    if (f.type === "number") {
      const input = h("input", { class: "input mono", type: "number", value: values[f.id], oninput: () => { values[f.id] = Number(input.value); } });
      binders[f.id] = v => { values[f.id] = v; input.value = v; };
      return field(f.label, input, f.help);
    }
    if (f.type === "chips" || f.type === "select") {
      const options = favFirst(f.options, "upscaler", o => `embutido:${o.value}`).map(o => o.fav_kind ? { ...o, fav: () => starButton(o.fav_kind, `embutido:${o.value}`, { title: o.label }) } : o);
      const pick = dropdown(options, values[f.id], v => { values[f.id] = v; if (TUNING.has(f.id)) markManual(); rerun(); }, { label: f.label });
      binders[f.id] = v => { values[f.id] = v; pick.set(v); };
      return field(f.label, pick, f.help);
    }
    if (f.type === "slider") {
      const out = h("span", { class: "mono dim" });
      const range = slider({ ...f, zero_label: f.min === 0 && f.default === 0 ? "auto" : null }, values[f.id], v => { values[f.id] = v; if (TUNING.has(f.id)) markManual(); });
      binders[f.id] = v => { values[f.id] = v; range.set(v); };
      return field(f.label, range, f.help);
    }
    if (f.type === "switch") return switchRow(f.label, values[f.id], v => { values[f.id] = v; rerun(); });  // rerun refreshes the «Falta:» line and the button
    if (f.type === "set") return setControl(f);
    if (f.type === "model") return modelControl(f);
    if (f.type === "seg") {
      const box = seg(f.options, values[f.id], v => { values[f.id] = v; rerun(); });
      box.classList.add("seg-grid");
      binders[f.id] = v => { values[f.id] = v; [...box.children].forEach((b, i) => b.setAttribute("aria-pressed", String(f.options[i].value === v))); };
      return field(f.label, box, f.help);
    }
    if (f.type === "loras") return loraPanel(f);
    if (f.type === "files") return dropzone(f);
    if (f.type === "lights") {
      const first = () => { const u = (values.refs || [])[0]; return u && !u.pending && u.kind === "image" ? api.url(u.url) : ""; };
      const editor = lightEditor({ lights: values[f.id], max: f.max, getImage: first, onChange: () => rerun() });
      refresh.push(editor.sync);
      return field(f.label, editor.el);
    }
    if (f.type === "boxes") {
      const first = () => { const u = (values.source || values.image || values.refs || [])[0]; return u && !u.pending && u.kind === "image" ? api.url(u.url) : ""; };
      const editor = boxEditor({ boxes: values[f.id], max: f.max, getImage: first, detail: Boolean(f.detail), onChange: () => rerun() });
      refresh.push(editor.sync);
      return field(f.label, editor.el);
    }
    return null;
  }

  function currentModel() { return models.find(m => m.key === values.model); }

  // ---- Conjunto: a whole pipeline (model + encoder + VAE + steps + size). Manual opens every component slot.
  let setField = null, setBox = null, summary = null;
  const slotBox = h("div", { class: "slot-grid" });
  const manualParams = h("div", { class: "manual-params" });
  const manualWrap = h("div", { class: "manual-wrap", hidden: true },
    h("h5", { class: "manual-h" }, "Componentes"), slotBox,
    h("h5", { class: "manual-h" }, "Parâmetros"), manualParams,
    h("p", { class: "manual-note" }, "ControlNet, detectores e VAD ainda não têm workflow conectado neste app, por isso não aparecem."));
  const recipeOf = name => {
    const o = setField?.options.find(x => x.value === name);
    return ((values.refs?.length && o?.recipe_refs) || o?.recipe) || null;  // with reference images the set picks a model that takes them
  };
  const modelTitle = key => models.find(m => m.key === key)?.title || key;

  function paintSummary() {
    if (!summary) return;
    clear(summary);
    const manual = values.set === "Manual";
    manualWrap.hidden = !manual;
    if (manual) {
      summary.append(h("p", { class: "sum-line" }, `${modelTitle(values.model)} · escolha cada componente abaixo`));
      return;
    }
    const r = recipeOf(values.set);
    if (!r) return;
    const bigger = r.gen_factor < 1 ? "gera menor e amplia" : "gera no tamanho do perfil";
    summary.append(...[h("p", { class: "sum-line" }, h("b", null, r.title), ` · ${r.steps} passos · ${bigger}`),
      null,
      h("details", { class: "sum-more" }, h("summary", null, "O que este conjunto usa"),
        h("ul", null, h("li", null, h("span", null, "Por quê"), r.why),
          ...Object.entries(r.components).map(([role, name]) => h("li", null, h("span", null, role), h("code", null, name))),
          h("li", null, h("span", null, "Aviso"), r.note)))].filter(Boolean));
  }
  function applySet() {
    const r = recipeOf(values.set);
    if (!r) { paintSummary(); onModelChange(); loadSlots(); return; }  // Manual: nothing is applied, but model-bound panels (LoRAs, advice) still follow the model
    values.model = r.model;
    binders.model?.(r.model);
    for (const key of ["steps", "cfg", "gen_factor", "sampler", "scheduler"]) {
      values[key] = r[key];
      binders[key]?.(r[key]);
    }
    values.slots = {};
    afterModel();
  }
  function setControl(f) {
    setField = f;
    setBox = seg(f.options, values[f.id], v => { values[f.id] = v; applySet(); rerun(); });
    setBox.classList.add("seg-grid");
    setPick = { set: v => { values.set = v; [...setBox.children].forEach((b, i) => b.setAttribute("aria-pressed", String(f.options[i].value === v))); } };
    summary = h("div", { class: "summary" });
    refresh.push(() => { if (values.set !== "Manual") { const r = recipeOf(values.set); if (r && r.model !== values.model) applySet(); } });
    return field(f.label, h("div", { class: "stack" }, setBox, summary), f.help);
  }
  markManualHook = () => paintSummary();

  let slotSerial = 0;
  async function loadSlots() {
    if (!app.fields.some(f => f.id === "slots")) return;
    const mine = ++slotSerial;
    let slots = [];
    try { slots = await api.get(`/slots?model=${encodeURIComponent(values.model)}`); } catch { /* the panel stays empty */ }
    if (mine !== slotSerial) return;
    clear(slotBox);
    const m = currentModel();
    for (const slot of slots) {
      const isAlgo = slot.kind === "algorithm";
      const current = isAlgo ? (values[slot.id] || "") : (values.slots?.[slot.id] || "");
      const options = slot.options.map(o => ({ value: o.value, label: o.label, star: o.star, installed: o.installed, hint: o.hint,
        badge: o.source === "worker" || o.source === "padrão" ? null : (o.installed ? "instalado" : "baixa ao usar") }));
      if (!options.length) options.push({ value: "", label: "Nenhum", hint: "Escolha no catálogo", installed: false });
      const pick = dropdown(options, current, v => { if (isAlgo) values[slot.id] = v; else (values.slots ||= {})[slot.id] = v; rerun(); },
        { label: slot.label, footer: slot.search ? { label: "Pesquisar…", hint: "No worker, CivitAI e Hugging Face", onclick: () => openSearch({
          role: slot.search.role, label: slot.label, family: slot.search.family, familyTitle: m?.title || slot.search.family,
          onUse: item => { (values.slots ||= {})[slot.id] = item.value; loadSlots(); rerun(); } }) } : null });
      slotBox.append(h("div", { class: "slot" }, h("span", { class: "slot-label" }, slot.label), pick));
    }
    paintSummary();
  }

  function modelControl(f) {
    const options = favFirst(models.filter(m => !f.options || f.options.some(o => o.value === m.key)), "model", m => `receita:${m.key}`).map(m => ({
      value: m.key, label: m.title, hint: m.tagline, installed: m.installed, badge: m.installed ? "instalado" : m.download_bytes ? `baixar ${(m.download_bytes / 1e9).toFixed(1).replace(".", ",")} GB` : "baixa ao usar",
      thumb: () => artFor("model", m.key), fav: () => starButton("model", `receita:${m.key}`, { title: m.title }) }));
    const pick = dropdown(options, values.model, v => { values.model = v; markManual(); afterModel(); rerun(); }, { label: f.label });
    binders[f.id] = v => { values[f.id] = v; pick.set(v); };
    return field(f.label, pick, null, h("a", { href: "#/models", class: "tiny-link" }, "Biblioteca"));
  }

  const modelListeners = [];
  const onModelChange = () => {
    const m = currentModel();
    advice.hidden = !(m && m.advice);
    clear(advice);
    if (m && m.advice) advice.append(icon("alert", "sm"), m.advice);
    modelListeners.forEach(fn => fn());
  };
  const afterModel = () => { onModelChange(); loadSlots(); paintSummary(); };

  function loraPanel(f) {
    const box = h("div", { class: "stack" });
    let dragFrom = null;
    let library = [], counts = {}, familyLabel = "", loaded = false;
    const ui = { query: "", filter: "compat" };  // filter: compat | installed | fav | all
    const paint = () => {
      clear(box);
      values.loras.forEach((item, index) => {
        const entry = library.find(l => l.name === item.name);
        const card = h("div", { class: `lora${item.on === false ? " off" : ""}`, "data-index": String(index) },
          h("div", { class: "head" },
            h("button", { type: "button", class: "grip", draggable: "true", "aria-label": `Mover LoRA ${index + 1}. Arraste ou use Alt e setas.`,
              ondragstart: e => { dragFrom = index; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(index)); card.classList.add("lifting"); },
              ondragend: () => { dragFrom = null; box.querySelectorAll(".lora").forEach(el => el.classList.remove("lifting", "over")); },
              onkeydown: e => {
                if (!e.altKey || !["ArrowUp", "ArrowDown"].includes(e.key)) return;
                e.preventDefault();
                const to = index + (e.key === "ArrowUp" ? -1 : 1);
                if (to < 0 || to >= values.loras.length) return;
                values.loras.splice(to, 0, values.loras.splice(index, 1)[0]); paint();
                box.querySelectorAll(".grip")[to]?.focus();
              } }, icon("grip", "sm")),
            h("div", { class: "po" }, entry?.cover ? h("img", { src: api.url(entry.cover), alt: "", loading: "lazy" }) : posterEl(item.name)),
            h("div", { class: "name", title: item.name }, entry?.label || item.name, entry && !entry.installed ? h("span", { class: "dim" }, " · baixa ao gerar") : null,
              entry && entry.compat === "incompatível" ? h("span", { class: "lora-warn", title: entry.compat_reason }, " · incompatível com o modelo atual") : null,
              entry && entry.compat === "desconhecida" ? h("span", { class: "dim", title: entry.compat_reason }, " · compatibilidade desconhecida") : null),
            h("div", { class: "row" },
              h("label", { class: "switch lora-switch", title: item.on === false ? "Desativada: não entra na geração" : "Ativa: entra na geração" },
                h("input", { type: "checkbox", role: "switch", "aria-label": `Ativar LoRA ${entry?.label || item.name}`, checked: item.on !== false,
                  onchange: e => { item.on = e.target.checked; card.classList.toggle("off", !item.on); refresh.forEach(fn => fn()); } })),
              h("button", { class: "btn ghost sm icon-only", type: "button", "aria-label": "Remover LoRA", onclick: () => { values.loras.splice(index, 1); paint(); } }, icon("x", "sm")))),
          h("div", { class: "field" }, h("label", null, h("span", null, "Força"), h("span", { class: "dim" }, "duplo clique zera")),
            slider({ min: -2, max: 2, step: 0.05, default: 1 }, item.strength ?? 1, v => { item.strength = v; if (item.clipLinked !== false) item.clip = v; })),
          h("details", { class: "more" }, h("summary", null, "Encoder", icon("chevron-down", "sm")),
            h("div", { class: "body" }, slider({ min: -2, max: 2, step: 0.05, default: 1 }, item.clip ?? item.strength ?? 1, v => { item.clip = v; item.clipLinked = false; }))));
        card.addEventListener("dragover", e => { if (dragFrom === null) return; e.preventDefault(); e.dataTransfer.dropEffect = "move"; card.classList.add("over"); });
        card.addEventListener("dragleave", () => card.classList.remove("over"));
        card.addEventListener("drop", e => {
          e.preventDefault();
          if (dragFrom === null || dragFrom === index) return;
          values.loras.splice(index, 0, values.loras.splice(dragFrom, 1)[0]);
          dragFrom = null; paint();
        });
        box.append(card);
      });
      box.append(pickerPanel());
    };
    const COMPAT_TAG = { confirmada: ["ok", "compatível"], provável: ["warn", "provável"], desconhecida: ["dim", "sem informação"], "incompatível": ["bad", "incompatível"] };
    const pickerPanel = () => {
      const chosen = new Set(values.loras.map(v => v.name));
      const hiddenAdult = library.filter(l => l.adult && hideAdult());
      const hiddenMine = hiddenAdult.filter(l => l.installed && (l.compat === "confirmada" || l.compat === "provável")).length;
      const mine = (counts.installed_for_family || 0) - hiddenMine;
      const summary = !loaded ? "Carregando a biblioteca…"
        : `${mine} instalada${mine === 1 ? "" : "s"} para ${familyLabel} · ${counts.installed_other || 0} para outros modelos · ${counts.unknown || 0} sem informação`
          + (hiddenAdult.length ? ` · ${hiddenAdult.length} adulta${hiddenAdult.length > 1 ? "s" : ""} oculta${hiddenAdult.length > 1 ? "s" : ""} (Biblioteca › Ocultar adulto)` : "");
      const match = l => !(l.adult && hideAdult()) && (ui.filter === "all" || (ui.filter === "installed" ? l.installed : ui.filter === "fav" ? isFav("lora", l.fav_id)
        : l.installed && l.compat !== "incompatível") ) && (!ui.query || `${l.label} ${l.name} ${l.creator || ""}`.toLowerCase().includes(ui.query.toLowerCase()));
      const rows = library.filter(l => !chosen.has(l.name) && match(l));
      const search = h("input", { class: "input", type: "search", placeholder: "Buscar LoRA…", "aria-label": "Buscar LoRA", value: ui.query,
        oninput: e => { ui.query = e.target.value; repaintList(); } });
      const chips = h("div", { class: "lora-chips", role: "group", "aria-label": "Filtro" }, [["compat", "Compatíveis"], ["installed", "Instaladas"], ["fav", "Favoritas"], ["all", "Todas"]].map(([key, text]) =>
        h("button", { type: "button", class: `chip${ui.filter === key ? " on" : ""}`, "aria-pressed": String(ui.filter === key), "data-filter": key,
          onclick: () => { ui.filter = key; paint(); } }, text)));
      const list = h("div", { class: "lora-pick", role: "list" });
      const repaintList = () => {
        const shown = library.filter(l => !chosen.has(l.name) && match(l));
        clear(list);
        if (!shown.length) {
          const hidden = library.filter(l => l.installed && l.compat === "incompatível" && !chosen.has(l.name)).length;
          list.append(h("div", { class: "lora-empty", role: "status" },
            ui.filter === "compat" && hidden ? `Nenhuma LoRA instalada serve para ${familyLabel}, mas há ${hidden} instalada${hidden === 1 ? "" : "s"} para outros modelos.`
              : ui.filter === "fav" ? "Nenhuma LoRA favoritada ainda. Use a estrela em qualquer lista." : "Nenhuma LoRA encontrada com este filtro.",
            ui.filter === "compat" && hidden ? h("button", { type: "button", class: "btn sm", onclick: () => { ui.filter = "installed"; paint(); } }, "Ver todas as instaladas") : null,
            h("a", { href: "#/loras", class: "tiny-link" }, "Procurar LoRAs para este modelo")));
          return;
        }
        shown.forEach(l => {
          const [tone, text] = COMPAT_TAG[l.compat] || COMPAT_TAG.desconhecida;
          const blocked = l.compat === "incompatível";
          list.append(h("div", { class: `lora-row${blocked ? " blocked" : ""}`, role: "listitem", "data-name": l.name, "data-compat": l.compat },
            h("div", { class: "po" }, l.cover ? h("img", { src: api.url(l.cover), alt: "", loading: "lazy" }) : posterEl(l.name)),
            h("div", { class: "lr-main" }, h("div", { class: "lr-title", title: l.name }, l.label),
              h("div", { class: "lr-meta" }, h("span", { class: `ltag ${tone}`, title: l.compat_reason }, text), h("span", { class: "dim" }, l.installed ? "instalada" : "baixa ao gerar"),
                blocked ? h("span", { class: "dim" }, l.compat_reason) : null)),
            starButton("lora", l.fav_id, { title: l.label, name: l.name }),
            h("button", { type: "button", class: "btn sm", disabled: blocked, "aria-label": `Adicionar ${l.label}`, title: blocked ? l.compat_reason : "Adicionar ao pedido",
              onclick: () => {
                if (values.loras.length >= (f.max || 4)) return toast(`Use até ${f.max || 4} LoRAs.`, "err");
                values.loras.push({ name: l.name, strength: 1, clip: 1, on: true });  // never auto-activated by the Conjunto or by installing
                paint(); refresh.forEach(fn => fn());
              } }, icon("plus", "sm"), "Adicionar")));
        });
      };
      repaintList();
      return h("div", { class: "addlora lora-browser" }, h("div", { class: "lora-summary", "aria-live": "polite" }, summary), search, chips, list);
    };
    // One source of truth: GET /loras returns every file the worker can see, classified for the model in use.
    let loadSeq = 0;
    const load = () => {
      const mine = ++loadSeq;
      return api.get(`/loras?family=${encodeURIComponent(values.model || "")}`).then(data => {
        if (mine !== loadSeq) return;  // a newer request (model changed) supersedes this one
        library = data.items; counts = data.counts; familyLabel = data.family_label; loaded = true;
        // A LoRA already in the request that does not fit the new model is switched off and flagged, never silently sent.
        values.loras.forEach(item => { const entry = library.find(l => l.name === item.name); if (entry?.compat === "incompatível" && item.on !== false) { item.on = false; item.autoOff = true; } });
        paint(); refresh.forEach(fn => fn());
      }).catch(() => { loaded = true; paint(); });
    };
    modelListeners.push(load);
    // Something finished installing (Library, search, model page): the list updates without reloading the page.
    const onInventory = e => { if (/^install/.test(e.detail?.app || "")) load(); };
    window.addEventListener("cf-job-final", onInventory);
    cleanups.push(() => window.removeEventListener("cf-job-final", onInventory));
    return field(f.label, box, f.help, h("a", { href: "#/loras" }, "Biblioteca"));
  }

  function dropzone(f) {
    const list = values[f.id];
    const thumbs = h("div", { class: "thumbs" });
    const input = h("input", { type: "file", class: "sr", multiple: f.max > 1, accept: f.accept === "image" ? "image/*" : f.accept === "video" ? "video/*" : f.accept.includes(".") ? f.accept : "image/*,video/*,audio/*",
      onchange: () => add([...input.files]) });
    const setDrives = () => f.id === "refs" && setField && values.set !== "Manual";  // the Conjunto will switch to a model that takes references
    const max = () => f.id === "refs" ? (setDrives() && currentModel()?.refs === 0 ? f.max : Math.min(f.max, currentModel()?.refs ?? f.max)) : f.max;
    const zone = h("div", { class: "drop", tabindex: "0", role: "button", onclick: () => input.click(),
      onkeydown: e => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), input.click()),
      ondragover: e => { e.preventDefault(); zone.classList.add("over"); }, ondragleave: () => zone.classList.remove("over"),
      ondrop: e => { e.preventDefault(); zone.classList.remove("over"); add([...e.dataTransfer.files]); } });
    const label = () => {
      clear(zone);
      const limit = max();
      zone.append(icon("upload"), h("div", null, h("strong", null, limit > 1 ? "Solte os arquivos aqui" : "Solte o arquivo aqui"), " ou clique para escolher"),
        h("span", { class: "hint mono" }, setDrives() && currentModel()?.refs === 0 ? "O conjunto troca para um modelo que aceita referências"
          : limit > 1 ? `${list.length}/${limit} · a ordem importa` : (f.accept || "").replace("image", "imagem").replace("video", "vídeo")));
      zone.hidden = limit === 0;
    };
    const paint = () => {
      clear(thumbs);
      list.forEach((u, i) => thumbs.append(h("div", { class: `thumb${u.kind === "image" || u.kind === "video" ? "" : " file"}` },
        u.kind === "image" ? h("img", { src: api.url(u.url), alt: u.name }) : u.kind === "video" ? h("video", { src: api.url(u.url), muted: true, preload: "metadata" }) : u.name,
        f.max > 1 ? h("span", { class: "tag" }, i + 1) : null,
        u.pending ? h("i", { class: "bar", style: { transform: `scaleX(${u.progress || 0.05})` } }) : null,
        h("button", { type: "button", "aria-label": `Remover ${u.name}`, onclick: () => { list.splice(i, 1); paint(); rerun(); } }, icon("x", "sm")))));
      label();
    };
    async function add(files) {
      const limit = max();
      for (const file of files) {
        if (list.length >= limit && limit > 1) { toast(`Máximo de ${limit} arquivo(s) neste modelo.`, "err"); break; }
        if (limit === 1 && list.length) list.length = 0;
        const placeholder = { name: file.name, kind: file.type.startsWith("image") ? "image" : file.type.startsWith("video") ? "video" : "file", url: URL.createObjectURL(file), pending: true, progress: 0 };
        const ref = list.push(placeholder) - 1;
        paint();
        try {
          const done = await api.upload(file, p => { placeholder.progress = p; paint(); });
          list[list.indexOf(placeholder)] = done;
        } catch (error) {
          list.splice(list.indexOf(placeholder), 1);
          toast(error.message, "err");
        }
        paint(); rerun();
      }
      input.value = "";
    }
    modelListeners.push(() => { while (f.id === "refs" && list.length > max() && max() > 0) list.pop(); paint(); });
    paint();
    return field(f.label, h("div", null, input, zone, thumbs), f.help);
  }

  // ---------- stage ----------
  // Plain-language errors; the raw message stays one click away under «Detalhe técnico».
  function friendly(message, status) {
    if (status === "travado") return ["Job interrompido", "O worker parou de responder. Reinicie a célula do Colab e tente de novo."];
    if (/cuda|gpu/i.test(message) && /not compiled|no gpu|not available|cuda is not/i.test(message)) return ["Este ambiente não tem GPU para esse método", "Escolha outro método (o Lanczos roda em qualquer lugar) ou rode no Colab com GPU."];
    if (/out of memory|oom/i.test(message)) return ["A placa ficou sem memória", "Tente um conjunto Rápido, uma resolução menor ou menos variações."];
    if (/worker|comfyui|connection|conex|refused|não responde/i.test(message)) return ["O ComfyUI não está respondendo", "Confira a célula do Colab (ela precisa continuar rodando) e tente de novo."];
    if (/sha-?256|não confere/i.test(message)) return ["O arquivo baixado não confere", "O download foi recusado por segurança. Tente de novo; se repetir, a fonte mudou o arquivo."];
    return ["Não foi dessa vez", message || "Sem detalhes."];
  }
  function idle() {
    clear(stage).append(h("div", { class: "idle" }, illustration("idle"), h("h3", null, app.title),
      h("p", { class: "muted" }, app.note || (setField ? "Descreva abaixo e toque em Gerar. O resultado aparece aqui, e você pode enviá-lo para outro app." : "Ajuste à esquerda e gere. O resultado aparece aqui, e você pode enviá-lo para outro app.")),
      app.blocked ? h("p", { class: "advice" }, icon("alert", "sm"), app.blocked_reason) : null,
      app.slow ? h("p", { class: "advice" }, icon("alert", "sm"), app.slow_reason) : null));
  }
  function running(job) {
    const started = Date.now() - Math.max(0, (job.started ? Date.now() / 1000 - job.started : 0)) * 1000;
    const clock = h("div", { class: "timecode" }, "00:00");
    const line = h("p", { class: "stage-line" }, job.desc);
    const light = h("div", { class: "light" }, h("i"));
    const queued = job.status === "fila";
    clear(stage).append(h("div", { class: "run" },
      h("div", { class: "reel" }, illustration("idle")),
      clock, light, line,
      h("div", { class: "row" }, h("button", { class: "btn danger", type: "button", onclick: () => cancel(job.id) }, icon("stop", "sm"), "Cancelar"))));
    stage._update = j => {
      line.textContent = j.status === "fila" ? `Na fila${j.position ? ` · posição ${j.position}` : ""}` : j.desc;
      const indeterminate = j.status === "fila" || j.fraction <= 0.011;
      light.classList.toggle("indeterminate", indeterminate);
      light.style.setProperty("--p", String(j.fraction || 0));
    };
    stage._update(job);
    clearInterval(tick);
    tick = setInterval(() => { clock.textContent = fmtClock((Date.now() - started) / 1000); }, 500);
  }
  function finished(job) {
    clearInterval(tick);
    stage._update = null;
    if (job.status !== "concluído") {
      const calm = job.status === "cancelado";
      const [title, body] = calm ? ["Cancelado", "Você cancelou este job."] : friendly(job.message || "", job.status);
      clear(stage).append(h("div", { class: `fail${calm ? " soft" : ""}` }, illustration(calm ? "empty" : "error"), h("h3", null, title), h("p", null, body),
        job.message && body !== job.message ? h("details", { class: "tech" }, h("summary", null, "Detalhe técnico"), h("pre", null, job.message)) : null,
        h("div", { class: "row center" }, calm ? null : h("button", { class: "btn primary", type: "button", onclick: () => run() }, icon("bolt", "sm"), "Tentar de novo"),
          h("button", { class: "btn", type: "button", onclick: idle }, "Voltar"))));
      return;
    }
    const results = job.results || [];
    if (!reframes.get(job.id)?.reframed) hydrate(job);
    const reframedNow = reframes.get(job.id)?.reframed;
    const media = results.filter(r => r.kind === "image" || r.kind === "video").map((r, i) => (i === 0 && reframedNow ? { ...reframedNow, original: r } : r));
    const grid = h("div", { class: `grid${media.length === 1 ? " one" : ""}` });
    media.forEach((r, i) => grid.append(h("button", { class: "shot", type: "button", style: { "--i": i }, "aria-label": `Abrir ${r.name}`, onclick: () => lightbox(r.original || r, job) },
      r.kind === "image" ? h("img", { src: api.url(r.url), alt: job.title }) : h("video", { src: api.url(r.url), muted: true, loop: true, autoplay: true, playsinline: true }))));
    const first = media[0];
    const sounds = results.filter(r => r.kind === "audio");
    const files = results.filter(r => r.kind === "file" && !/\.(json|txt)$/i.test(r.name));
    const downloadable = first || sounds[0] || files[0];
    clear(stage).append(h("div", { class: "results" }, media.length ? grid : null,
      sounds.length ? h("div", { class: "audio-list" }, sounds.map(r => h("figure", { class: "audio-card" }, h("audio", { controls: true, preload: "metadata", src: api.url(r.url) }),
        h("figcaption", null, r.name, " · ", h("a", { href: api.url(r.url), download: r.name }, "Baixar"))))) : null,
      files.length ? h("div", { class: "audio-list" }, files.map(r => h("figure", { class: "audio-card" }, h("figcaption", null, icon("cube", "sm"), " ", r.name, " · ", fmtBytes(r.size), " · ",
        h("a", { href: api.url(r.url), download: r.name }, "Baixar"))))) : null,
      job.message ? h("p", { class: "hint" }, job.message) : null,
      h("div", { class: "actions" }, first ? sendMenu(first) : null,
        downloadable ? h("a", { class: "btn sm", href: api.url(downloadable.url), download: downloadable.name }, icon("download", "sm"), "Baixar") : null,
        h("button", { class: "btn sm primary", type: "button", onclick: () => run() }, icon("refresh", "sm"), "Gerar de novo"))));
  }
  const GROUP_ICON = { Imagem: "image", Vídeo: "video", Identidade: "user", Melhorar: "sparkle", Avançado: "sliders" };
  function sendMenu(result) {
    const targets = (SEND_TO[result.kind] || []).filter(t => t !== app.id).map(t => store.apps.find(a => a.id === t)).filter(t => t && !t.blocked);
    if (!targets.length) return null;
    return actionMenu({ label: "Usar em", iconName: "external",
      items: targets.map(t => ({ label: t.title, hint: t.tagline, app: t.id, onclick: () => sendTo(t, result) })) });
  }
  async function sendTo(target, result) {
    try {
      const upload = await api.post("/import", { path: result.path });
      const slot = target.fields.find(f => f.type === "files" && (f.accept || "").includes(result.kind));
      store.prefill({ app: target.id, values: slot ? { [slot.id]: [upload] } : {} });
      navigate(`#/apps/${target.id}`);
    } catch (error) { toast(error.message, "err"); }
  }
  function lightbox(result, job) {
    // With a known uploaded source (Enquadrar imagem) we reframe that file; otherwise the result itself is the base.
    // Reframing always starts from that original, never from a previous reframe.
    const state = stateFor(job), source = state.source;
    const original = source ? { ...source, kind: "image", path: null } : result;
    let view = "original", busy = false, follower = null;
    const { focus } = state;
    let ratio, fit = state.fit;
    const reframedNow = () => state.reframed || (source ? result : null);
    let free = { x: 0, y: 0 };
    const frameApp = store.apps.find(a => a.id === "frame");
    const ratioField = frameApp?.fields.find(f => f.id === "ratio"), fitField = frameApp?.fields.find(f => f.id === "fit");
    ratio = state.ratio || ratioField?.default;
    const shown = () => (view === "result" && reframedNow()) || original;
    const deliver = () => reframedNow() || original;
    const close = () => { follower?.stop(); window.removeEventListener("resize", paintGuide); scrim.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = e => e.key === "Escape" && !document.querySelector(".dd-pop:not(.out)") && close();
    document.addEventListener("keydown", onKey);

    const media = h("div", { class: "media" });
    const side = h("div", { class: "side" });
    const guide = h("div", { class: "guide", hidden: true, tabindex: "0", role: "slider", "aria-label": "Posição do enquadramento. Arraste ou use as setas." });
    let img = null;

    // Crop guide over the original: shows what "Preencher" keeps (or the padded frame for "Inteira").
    function paintGuide() {
      const option = ratioField?.options.find(o => o.value === ratio);
      if (!img || view !== "original" || !option?.ratio || original.kind !== "image" || !img.naturalWidth) { guide.hidden = true; return; }
      const box = media.getBoundingClientRect(), scale = Math.min(box.width / img.naturalWidth, box.height / img.naturalHeight);
      const w = img.naturalWidth * scale, hh = img.naturalHeight * scale, target = option.ratio[0] / option.ratio[1];
      const fill = fit === "Preencher";
      const gw = (fill ? w / hh <= target : w / hh > target) ? w : hh * target, gh = gw / target;
      guide.hidden = false;
      guide.classList.toggle("pad", !fill);
      // "free" is how far the window can travel on each axis; focus 0..1 is where it sits inside that range.
      free = { x: Math.abs(w - gw), y: Math.abs(hh - gh) };
      const sign = fill ? 1 : -1, left0 = (box.width - w) / 2, top0 = (box.height - hh) / 2;
      guide.style.width = `${gw}px`; guide.style.height = `${gh}px`;
      guide.style.left = `${left0 + sign * free.x * focus.x}px`;
      guide.style.top = `${top0 + sign * free.y * focus.y}px`;
      guide.classList.toggle("movable", free.x > 1 || free.y > 1);
    }
    let drag = null;
    const nudge = (dx, dy) => {
      const sign = fit === "Preencher" ? 1 : -1;
      if (free.x > 1) focus.x = Math.min(1, Math.max(0, focus.x + sign * dx / free.x));
      if (free.y > 1) focus.y = Math.min(1, Math.max(0, focus.y + sign * dy / free.y));
      paintGuide();
    };
    guide.addEventListener("pointerdown", e => { e.preventDefault(); guide.setPointerCapture(e.pointerId); drag = { x: e.clientX, y: e.clientY }; guide.classList.add("drag"); });
    guide.addEventListener("pointermove", e => { if (!drag) return; nudge(e.clientX - drag.x, e.clientY - drag.y); drag = { x: e.clientX, y: e.clientY }; });
    const endDrag = () => { drag = null; guide.classList.remove("drag"); };
    guide.addEventListener("pointerup", endDrag); guide.addEventListener("pointercancel", endDrag);
    guide.addEventListener("dblclick", () => { focus.x = focus.y = 0.5; paintGuide(); });
    guide.addEventListener("keydown", e => {
      const step = e.shiftKey ? 24 : 6, move = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
      if (move) { e.preventDefault(); nudge(...move); }
    });
    function paintMedia() {
      clear(media);
      img = null;
      const item = shown();
      if (item.kind === "video") { media.append(h("video", { src: api.url(item.url), controls: true, autoplay: true, loop: true })); return; }
      img = h("img", { src: api.url(item.url), alt: job.title, onload: paintGuide });
      media.append(img, guide);
      paintGuide();
    }
    function setView(next) { view = next; paintMedia(); paintSide(); }
    async function apply() {
      if (busy) return;
      busy = true; paintSide();
      try {
        const upload = source ? source : await api.post("/import", { path: original.path });
        const started = await api.post("/jobs", { app: "frame", params: { image: [upload.id], ratio, fit, focus: [focus.x, focus.y], format: "PNG" } });
        const out = await new Promise((resolve, reject) => {
          follower = api.follow(started.id, snap => {
            if (!isFinal(snap.status)) return;
            follower?.stop();
            const first = (snap.results || []).find(r => r.kind === "image");
            if (snap.status === "concluído" && first) resolve(first);
            else reject(new Error(snap.message || "Não foi possível reenquadrar."));
          });
        });
        state.reframed = out; state.resultJobId = started.id; state.ratio = ratio; state.fit = fit; view = "result"; persist(job, state); finished(job);
        store.refreshJobs().catch(() => {});
      } catch (error) { toast(error.message, "err"); }
      busy = false; paintMedia(); paintSide();
    }
    const picked = () => { view = "original"; paintMedia(); paintSide(); };
    function paintSide() {
      clear(side);
      const item = deliver();
      const canReframe = original.kind === "image" && frameApp && !frameApp.blocked;
      side.append(h("h3", null, job.title), h("p", { class: "mono dim" }, `${item.name} · ${fmtBytes(item.size || 0)}`),
        h("a", { class: "btn primary", href: api.url(item.url), download: item.name }, icon("download", "sm"), reframedNow() ? "Baixar reenquadrada" : "Baixar original"));
      if (canReframe) {
        side.append(h("div", { class: "reframe" },
          h("div", { class: "label" }, h("span", null, "Reenquadrar")),
          dropdown(ratioField.options, ratio, v => { ratio = state.ratio = v; focus.x = focus.y = 0.5; if (view !== "original") picked(); else paintGuide(); }, { label: "Proporção" }),
          dropdown(fitField.options, fit, v => { fit = state.fit = v; if (view !== "original") picked(); else paintGuide(); }, { label: "Encaixe" }),
          h("p", { class: "hint" }, fit === "Preencher" ? "Arraste o contorno sobre a imagem original para escolher o que fica; o resto é cortado. Duplo clique centraliza." : "A imagem original entra inteira. Arraste o contorno para escolher onde ela fica no quadro."),
          h("button", { class: "btn", type: "button", disabled: busy, onclick: apply }, icon(busy ? "refresh" : "crop", "sm"), busy ? "Reenquadrando…" : "Aplicar enquadramento"),
          reframedNow() ? h("div", { class: "seg" }, [["original", "Ver original"], ["result", "Ver reenquadrada"]].map(([v, text]) =>
            h("button", { type: "button", "aria-pressed": String(view === v), onclick: () => setView(v) }, text))) : null,
          state.reframed ? h("button", { class: "btn ghost sm", type: "button", onclick: () => { state.reframed = null; state.resultJobId = null; persist(job, state); finished(job); setView("original"); } }, icon("x", "sm"), "Descartar reenquadramento") : null));
      }
      side.append(sendMenu(item), h("button", { class: "btn ghost", type: "button", onclick: close }, "Fechar"));
    }
    const scrim = h("div", { class: "scrim", onclick: e => e.target === scrim && close() },
      h("div", { class: "lightbox", role: "dialog", "aria-label": job.title }, media, side));
    paintMedia(); paintSide();
    window.addEventListener("resize", paintGuide);
    document.body.append(scrim);
  }

  // ---------- run ----------
  function missing() {
    const list = [];
    for (const f of app.fields) {
      if (f.required && f.type === "switch" ? !values[f.id] : f.required && !String(values[f.id] ?? "").trim()) list.push(f.label);
      if (f.type === "lights" && values[f.id].length < (f.min || 0)) list.push("uma luz");
      if (f.type === "boxes" && !f.detail && !values[f.id].length && !(values.mask || []).some(u => !u.pending)) list.push("uma caixa ou uma máscara");
      if (f.type === "boxes" && f.detail && values.mode !== "edit_instruction" && !values[f.id].length) list.push("pelo menos uma caixa");
      if (f.type === "files") {
        const need = f.id === "refs" ? Math.min(f.min || 0, currentModel()?.refs ?? 9) : f.min || 0;
        const ready = values[f.id].filter(u => !u.pending).length;
        if (ready < need) list.push(`${f.label} (${ready}/${need})`);
        if (values[f.id].some(u => u.pending)) list.push("aguardando envio");
      }
    }
    return list;
  }
  refresh.push(() => {
    const need = missing();
    runButton.disabled = app.blocked || need.length > 0;
    missingLine.textContent = app.blocked ? app.blocked_reason : need.length ? `Falta: ${need.join(", ")}` : "";
  });

  async function run() {
    if (runButton.disabled) return;
    runButton.disabled = true;
    const params = {};
    for (const f of app.fields) {
      if (f.type === "files") params[f.id] = values[f.id].map(u => u.id);
      else params[f.id] = values[f.id];
    }
    try {
      const sourceUpload = app.id === "frame" ? values.image?.[0] : null;
      const job = await api.post("/jobs", { app: app.id, params });
      if (sourceUpload) stateFor(job, sourceUpload);
      store.lastJob(app.id, job.id);
      watch(job);
      store.refreshJobs().catch(() => {});
    } catch (error) { toast(error.message, "err"); }
    rerun();
  }
  function watch(job) {
    follower?.stop();
    current = job;
    isFinal(job.status) ? finished(job) : running(job);
    if (isFinal(job.status)) return;
    follower = api.follow(job.id, snapshot => {
      current = snapshot;
      if (isFinal(snapshot.status)) { finished(snapshot); store.refreshJobs().catch(() => {}); }
      else if (stage._update) stage._update(snapshot);
      else running(snapshot);
    });
  }
  async function cancel(jobId) {
    try { await api.post(`/jobs/${jobId}/cancel`); } catch (error) { toast(error.message, "err"); }
  }

  // ---------- assemble ----------
  const main = app.fields.filter(f => !f.advanced && !f.manual), extra = app.fields.filter(f => f.advanced), manualFields = app.fields.filter(f => f.manual);
  // Parameters that belong to Manual live inside the Manual panel; those tied to specific models hide when the model has no use for them.
  for (const f of manualFields) {
    const node = control(f);
    if (!node) continue;
    const wrap = h("div", { class: "param" }, node);
    if (f.models) modelListeners.push(() => { wrap.hidden = !f.models.includes(values.model); });
    manualParams.append(wrap);
  }
  // Visible fields are grouped by `section` so the panel reads as a few labelled blocks instead of one long list.
  const sections = [];
  for (const f of main) {
    const name = f.section || "";
    if (!sections.length || sections.at(-1).name !== name) sections.push({ name, fields: [] });
    sections.at(-1).fields.push(f);
  }
  const hasSlots = app.fields.some(f => f.id === "slots");
  const sectionNodes = {};
  const blocks = sections.map(sec => {
    const nodes = [];
    for (const f of sec.fields) {
      const node = control(f);
      if (node) nodes.push(node);
      if (f.id === "model" && hasSlots) nodes.push(manualWrap);
    }
    sectionNodes[sec.name] = nodes;
    return h("section", { class: "fsec" }, sec.name ? h("h4", { class: "fsec-title" }, sec.name) : null, ...nodes);
  });
  const extraNodes = extra.map(control).filter(Boolean);

  if (setField) {
    // ---- Dock layout (image apps): one prompt bar at the bottom, settings behind chips, results above.
    // The same controls as the classic panel, moved into popovers, so nothing about the form logic changes.
    const open = { current: null };
    const closeAll = () => { open.current?.close(); };
    const chipDefs = [];
    const pop = (name, glyph, nodes, summary, wide = false) => {
      const panel = h("div", { class: `dock-pop${wide ? " wide" : ""}`, role: "dialog", "aria-label": name, hidden: true }, ...nodes);
      const label = h("span", { class: "chip-sum" });
      const button = h("button", { class: "dock-chip", type: "button", "aria-haspopup": "dialog", "aria-expanded": "false", onclick: () => toggle() }, icon(glyph, "sm"), h("span", { class: "chip-name" }, name), label);
      const wrap = h("div", { class: "dock-chip-wrap" }, button, panel);
      let anchor = null;
      const api2 = { close() { anchor?.destroy(); anchor = null; panel.hidden = true; button.setAttribute("aria-expanded", "false"); if (open.current === api2) open.current = null; } };
      function toggle() {
        if (!panel.hidden) { api2.close(); return button.focus(); }
        closeAll();
        panel.hidden = false; button.setAttribute("aria-expanded", "true"); open.current = api2;
        anchor = anchorPopover(button, panel);
        panel.querySelector("input, select, textarea, button")?.focus({ preventScroll: true });
      }
      cleanups.push(() => api2.close());
      chipDefs.push(() => { label.textContent = summary(); });
      return wrap;
    };
    const optLabel = (id, value) => app.fields.find(f => f.id === id)?.options?.find(o => o.value === value)?.label || value;
    const chips = [
      pop("Modelo", "cube", [...(sectionNodes["Modelo"] || [])], () => `${values.set === "Manual" ? "Manual" : values.set} · ${modelTitle(values.model)}`, true),
      pop("Formato", "frame", [...(sectionNodes["Formato"] || [])], () => `${optLabel("aspect", values.aspect).replace(/ ·.*$/, "")} · ${optLabel("quality", values.quality)} · ${values.variations}×`),
      sectionNodes["Estilo"] ? pop("Estilo", "sparkle", [...sectionNodes["Estilo"]], () => { const on = (values.loras || []).filter(l => l.on !== false).length; return on ? `${on} LoRA${on > 1 ? "s" : ""} ativa${on > 1 ? "s" : ""}` : "nenhuma ativa"; }) : null,
      extraNodes.length ? pop("Mais", "sliders", extraNodes, () => "") : null,
    ].filter(Boolean);
    refresh.push(() => chipDefs.forEach(fn => fn()));
    const outside = e => { if (open.current && !e.target.closest(".dock-chip-wrap, .dock-pop, .dd-pop, .sr-overlay")) closeAll(); };
    document.addEventListener("pointerdown", outside, true);
    cleanups.push(() => document.removeEventListener("pointerdown", outside, true));
    const onEsc = e => { if (e.key === "Escape" && open.current) { closeAll(); e.stopPropagation(); } };
    document.addEventListener("keydown", onEsc);
    cleanups.push(() => document.removeEventListener("keydown", onEsc));

    const pedido = sectionNodes["Pedido"] || [];
    const promptField = pedido[0], refsField = pedido[1];
    const promptArea = promptField?.querySelector("textarea");
    if (promptArea) { promptArea.placeholder = `${app.fields.find(f => f.id === "prompt")?.label || "Descreva a imagem"}…`; promptArea.rows = 1; }
    const fileInput = refsField?.querySelector("input[type=file]");
    const attach = h("button", { class: "dock-attach", type: "button", "aria-label": "Anexar imagens de referência", title: "Anexar referências", onclick: () => fileInput?.click() }, icon("plus"));
    const dock = h("div", { class: "dock" },
      refsField ? h("div", { class: "dock-refs" }, refsField) : null,
      h("div", { class: "dock-bar" }, attach, promptField, runButton),
      h("div", { class: "dock-meta" }, h("div", { class: "dock-chips" }, chips), h("div", { class: "dock-notes" }, advice, missingLine)));
    dock.addEventListener("dragover", e => { e.preventDefault(); dock.classList.add("over"); });
    dock.addEventListener("dragleave", () => dock.classList.remove("over"));
    dock.addEventListener("drop", e => {
      e.preventDefault(); dock.classList.remove("over");
      if (!fileInput || !e.dataTransfer.files.length) return;
      const transfer = new DataTransfer();
      [...e.dataTransfer.files].forEach(f => transfer.items.add(f));
      fileInput.files = transfer.files; fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    // Earlier results of this app, newest first: click to bring one back to the stage.
    const recents = h("div", { class: "recents", "aria-label": "Resultados anteriores" });
    // Keyed by job + file: a poll that changes nothing touches nothing, so thumbnails never remount or flicker.
    const paintRecents = () => {
      const done = (store.jobs || []).filter(j => j.app === app.id && j.status === "concluído").flatMap(j => j.results.filter(r => r.kind === "image").slice(0, 1).map(r => ({ r, j }))).slice(0, 14);
      recents.hidden = !done.length;
      reconcile(recents, done, {
        key: ({ r, j }) => `${j.id}|${bareUrl(r.url)}`,
        sig: ({ r, j }) => `${j.title}|${bareUrl(r.url)}`,
        create: ({ r, j }) => h("button", { class: "recent", type: "button", title: j.title, onclick: () => { api.get(`/jobs/${j.id}`).then(watch); } },
          h("img", { src: api.url(r.url), alt: j.title, loading: "lazy" })),
        update: (node, { j }) => node.classList.toggle("on", current?.id === j.id)
      });
    };
    const onJobs = () => paintRecents();
    events.addEventListener("jobs", onJobs);
    cleanups.push(() => events.removeEventListener("jobs", onJobs));
    (store.jobs?.length ? Promise.resolve() : store.refreshJobs()).then(paintRecents).catch(() => {});

    root.append(h("div", { class: "appview dock-layout" },
      h("div", { class: "dock-top" }, h("a", { class: "crumb", href: "#/apps" }, icon("chevron-left", "sm"), "Apps"),
        h("div", { class: "dock-title" }, appGlyph(app.id, "sm"), h("h2", null, app.title), starButton("app", app.id, { title: app.title })), usesBar),
      stage, recents, dock));
    root.classList.add("dock-view");
  } else {
    root.append(
      h("a", { class: "crumb", href: "#/apps" }, icon("chevron-left", "sm"), "Apps"),
      h("div", { class: "appview" },
        h("section", { class: "panel controls" },
          h("div", { class: "head" }, h("div", { class: "title" }, appGlyph(app.id), h("h2", null, app.title), starButton("app", app.id, { title: app.title })), h("p", { class: "muted" }, app.tagline), usesBar),
          h("div", { class: "scroll" }, blocks, extra.length ? h("details", { class: "more" },
            h("summary", null, h("span", null, "Ajustes avançados"), icon("chevron-down", "sm")), h("div", { class: "body" }, extraNodes)) : null),
          h("div", { class: "foot" }, advice, missingLine, runButton)),
        stage));
  }
  // A model carried in from another app wins over the default Conjunto, so nothing is switched behind the user's back.
  if (setField) {
    const r = recipeOf(values.set);
    if (prefill.model && r && prefill.model !== r.model) { values.set = "Manual"; setPick.set("Manual"); paintSummary(); onModelChange(); loadSlots(); }
    else applySet();
  } else onModelChange();
  rerun();
  idle();
  const last = store.lastJob(app.id);
  if (last) api.get(`/jobs/${last}`).then(job => { if (!current) watch(job); }).catch(() => store.lastJob(app.id, null));
  return { el: root, destroy() { follower?.stop(); clearInterval(tick); } };
}
