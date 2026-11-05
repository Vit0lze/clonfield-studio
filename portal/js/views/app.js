import { api, store, isFinal } from "../api.js";
import { lightEditor } from "../lights.js";
import { h, icon, clear, seg, dropdown, slider, switchRow, field, toast, illustration, posterEl, artFor, fmtClock, fmtBytes } from "../ui.js";

const SEND_TO = { image: ["upscale", "look", "frame", "animate", "edit", "relight", "compare"], video: ["clip", "still", "board", "seedvr2"] };
const NAME_LIMITS = { image: "imagem", video: "vídeo" };

export async function appView(id, navigate) {
  const [apps, models] = await Promise.all([store.loadApps(), (store.models ||= api.get("/models"))]);
  const app = apps.find(a => a.id === id);
  const root = h("div", { class: "view" });
  if (!app) { root.append(h("div", { class: "empty" }, illustration("error"), h("h3", null, "App não encontrado"), h("a", { class: "btn", href: "#/apps" }, "Ver todos os apps"))); return { el: root }; }

  const prefill = store.takePrefill(app.id);
  const values = {};
  for (const f of app.fields) values[f.id] = structuredClone(prefill[f.id] ?? f.default ?? (f.type === "files" || f.type === "loras" || f.type === "lights" ? [] : ""));
  const cleanups = [];
  let follower = null, tick = null, current = null;

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
      return field(f.label, input, f.help);
    }
    if (f.type === "chips" || f.type === "select") {
      const pick = dropdown(f.options, values[f.id], v => { values[f.id] = v; rerun(); }, { label: f.label });
      return field(f.label, pick, f.help);
    }
    if (f.type === "slider") {
      const out = h("span", { class: "mono dim" });
      return field(f.label, slider({ ...f, zero_label: f.min === 0 && f.default === 0 ? "auto" : null }, values[f.id], v => { values[f.id] = v; }), f.help);
    }
    if (f.type === "switch") return switchRow(f.label, values[f.id], v => { values[f.id] = v; });
    if (f.type === "model") return modelPicker(f);
    if (f.type === "loras") return loraPanel(f);
    if (f.type === "files") return dropzone(f);
    if (f.type === "lights") {
      const first = () => { const u = (values.refs || [])[0]; return u && !u.pending && u.kind === "image" ? api.url(u.url) : ""; };
      const editor = lightEditor({ lights: values[f.id], max: f.max, getImage: first, onChange: () => rerun() });
      refresh.push(editor.sync);
      return field(f.label, editor.el);
    }
    return null;
  }

  function currentModel() { return models.find(m => m.key === values.model); }

  function modelPicker(f) {
    const box = h("div", { class: "mpick", role: "group" });
    const paint = () => {
      clear(box);
      for (const m of models.filter(m => !f.options || f.options.some(o => o.value === m.key))) {
        box.append(h("button", { class: "mopt", type: "button", "aria-pressed": String(values.model === m.key),
          onclick: () => { values.model = m.key; paint(); onModelChange(); rerun(); } },
          h("div", { class: "po" }, artFor("model", m.key)),
          h("div", null, h("b", null, m.title), h("span", null, m.tagline),
            h("span", { class: "mono" }, `${m.installed ? "instalado" : "baixa ao usar"}${m.fits ? "" : " · pesado p/ sua GPU"}`))));
      }
    };
    paint();
    return field(f.label, box, null, h("a", { href: "#/models" }, "Ver biblioteca"));
  }
  const modelListeners = [];
  const onModelChange = () => {
    const m = currentModel();
    advice.hidden = !(m && m.advice);
    clear(advice);
    if (m && m.advice) advice.append(icon("alert", "sm"), m.advice);
    modelListeners.forEach(fn => fn());
  };

  function loraPanel(f) {
    const box = h("div", { class: "stack" });
    let library = [];
    const paint = () => {
      clear(box);
      values.loras.forEach((item, index) => {
        const entry = library.find(l => l.name === item.name);
        box.append(h("div", { class: `lora${item.on === false ? " off" : ""}` },
          h("div", { class: "head" },
            h("div", { class: "po" }, posterEl(item.name)),
            h("div", { class: "name", title: item.name }, entry?.label || item.name, entry && !entry.installed ? h("span", { class: "dim" }, " · baixa ao gerar") : null),
            h("div", { class: "row" },
              h("input", { type: "checkbox", "aria-label": "Ativar LoRA", checked: item.on !== false, class: "sr", id: `lora-${index}` }),
              h("button", { class: "btn ghost sm icon-only", type: "button", "aria-label": "Remover LoRA", onclick: () => { values.loras.splice(index, 1); paint(); } }, icon("x", "sm")))),
          h("div", { class: "field" }, h("label", null, h("span", null, "Força"), h("span", { class: "dim" }, "duplo clique zera")),
            slider({ min: -2, max: 2, step: 0.05, default: 1 }, item.strength ?? 1, v => { item.strength = v; if (item.clipLinked !== false) item.clip = v; })),
          h("details", { class: "more" }, h("summary", null, "Encoder", icon("chevron-down", "sm")),
            h("div", { class: "body" }, slider({ min: -2, max: 2, step: 0.05, default: 1 }, item.clip ?? item.strength ?? 1, v => { item.clip = v; item.clipLinked = false; })))));
      });
      const available = library.filter(l => !values.loras.some(v => v.name === l.name));
      const picker = h("select", { class: "input", "aria-label": "Escolher LoRA" }, h("option", { value: "" }, available.length ? "Adicionar LoRA…" : "Nenhuma LoRA compatível"),
        available.map(l => h("option", { value: l.name }, `${l.label}${l.installed ? "" : " (baixar)"}`)));
      picker.addEventListener("change", () => {
        if (!picker.value || values.loras.length >= (f.max || 4)) return picker.value && toast(`Use até ${f.max || 4} LoRAs.`, "err");
        values.loras.push({ name: picker.value, strength: 1, clip: 1, on: true });
        paint();
      });
      box.append(h("div", { class: "addlora" }, picker));
    };
    const load = () => api.get(`/loras?family=${encodeURIComponent(values.model || "")}`).then(items => { library = items; paint(); }).catch(() => paint());
    modelListeners.push(load);
    return field(f.label, box, f.help, h("a", { href: "#/loras" }, "Biblioteca"));
  }

  function dropzone(f) {
    const list = values[f.id];
    const thumbs = h("div", { class: "thumbs" });
    const input = h("input", { type: "file", class: "sr", multiple: f.max > 1, accept: f.accept === "image" ? "image/*" : f.accept === "video" ? "video/*" : f.accept.includes(".") ? f.accept : "image/*,video/*,audio/*",
      onchange: () => add([...input.files]) });
    const max = () => f.id === "refs" ? Math.min(f.max, currentModel()?.refs ?? f.max) : f.max;
    const zone = h("div", { class: "drop", tabindex: "0", role: "button", onclick: () => input.click(),
      onkeydown: e => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), input.click()),
      ondragover: e => { e.preventDefault(); zone.classList.add("over"); }, ondragleave: () => zone.classList.remove("over"),
      ondrop: e => { e.preventDefault(); zone.classList.remove("over"); add([...e.dataTransfer.files]); } });
    const label = () => {
      clear(zone);
      const limit = max();
      zone.append(icon("upload"), h("div", null, h("strong", null, limit > 1 ? "Solte os arquivos aqui" : "Solte o arquivo aqui"), " ou clique para escolher"),
        h("span", { class: "hint mono" }, limit > 1 ? `${list.length}/${limit} · a ordem importa` : (f.accept || "").replace("image", "imagem").replace("video", "vídeo")));
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
  function idle() {
    clear(stage).append(h("div", { class: "idle" }, illustration("idle"), h("h3", null, app.title),
      h("p", { class: "muted" }, app.note || "Ajuste à esquerda e gere. O resultado aparece aqui, e você pode enviá-lo para outro app."),
      app.blocked ? h("p", { class: "advice" }, icon("alert", "sm"), app.blocked_reason) : null));
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
      clear(stage).append(h("div", { class: `fail${calm ? " soft" : ""}` }, illustration(calm ? "empty" : "error"), h("h3", null, calm ? "Cancelado" : job.status === "travado" ? "Job interrompido" : "Não foi dessa vez"),
        h("p", null, job.message || "Sem detalhes."), h("button", { class: "btn", type: "button", onclick: idle }, "Voltar")));
      return;
    }
    const results = job.results || [];
    const media = results.filter(r => r.kind === "image" || r.kind === "video");
    const grid = h("div", { class: `grid${media.length === 1 ? " one" : ""}` });
    media.forEach((r, i) => grid.append(h("button", { class: "shot", type: "button", style: { "--i": i }, "aria-label": `Abrir ${r.name}`, onclick: () => lightbox(r, job) },
      r.kind === "image" ? h("img", { src: api.url(r.url), alt: job.title }) : h("video", { src: api.url(r.url), muted: true, loop: true, autoplay: true, playsinline: true }))));
    const first = media[0];
    clear(stage).append(h("div", { class: "results" }, grid,
      job.message ? h("p", { class: "hint" }, job.message) : null,
      h("div", { class: "row between" },
        h("div", { class: "sendto" }, first ? [h("span", { class: "dim" }, "Usar em"), ...sendButtons(first)] : null),
        h("div", { class: "row" }, first ? h("a", { class: "btn sm", href: api.url(first.url), download: first.name }, icon("download", "sm"), "Baixar") : null,
          h("button", { class: "btn sm primary", type: "button", onclick: () => run() }, icon("refresh", "sm"), "Gerar de novo")))));
  }
  function sendButtons(result) {
    return (SEND_TO[result.kind] || []).filter(t => t !== app.id).map(t => {
      const target = store.apps.find(a => a.id === t);
      return target && !target.blocked ? h("button", { class: "btn sm", type: "button", onclick: () => sendTo(target, result) }, target.title) : null;
    });
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
    const close = () => { scrim.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = e => e.key === "Escape" && close();
    document.addEventListener("keydown", onKey);
    const scrim = h("div", { class: "scrim", onclick: e => e.target === scrim && close() },
      h("div", { class: "lightbox", role: "dialog", "aria-label": job.title },
        h("div", { class: "media" }, result.kind === "video" ? h("video", { src: api.url(result.url), controls: true, autoplay: true, loop: true }) : h("img", { src: api.url(result.url), alt: job.title })),
        h("div", { class: "side" }, h("h3", null, job.title), h("p", { class: "mono dim" }, `${result.name} · ${fmtBytes(result.size)}`),
          h("a", { class: "btn primary", href: api.url(result.url), download: result.name }, icon("download", "sm"), "Baixar original"),
          h("div", { class: "sendto" }, sendButtons(result)), h("button", { class: "btn ghost", type: "button", onclick: close }, "Fechar"))));
    document.body.append(scrim);
  }

  // ---------- run ----------
  function missing() {
    const list = [];
    for (const f of app.fields) {
      if (f.required && !String(values[f.id] ?? "").trim()) list.push(f.label);
      if (f.type === "lights" && values[f.id].length < (f.min || 0)) list.push("uma luz");
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
      const job = await api.post("/jobs", { app: app.id, params });
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
  const main = app.fields.filter(f => !f.advanced), extra = app.fields.filter(f => f.advanced);
  const scroll = h("div", { class: "scroll" }, main.map(control), extra.length ? h("details", { class: "more" },
    h("summary", null, h("span", null, "Ajustes avançados"), icon("chevron-down", "sm")), h("div", { class: "body" }, extra.map(control))) : null);
  root.append(
    h("a", { class: "crumb", href: "#/apps" }, icon("chevron-left", "sm"), "Apps"),
    h("div", { class: "appview" },
      h("section", { class: "panel controls" },
        h("div", { class: "head" }, h("h2", null, app.title), h("p", { class: "muted" }, app.tagline)),
        scroll,
        h("div", { class: "foot" }, advice, missingLine, runButton)),
      stage));
  onModelChange();
  rerun();
  idle();
  const last = store.lastJob(app.id);
  if (last) api.get(`/jobs/${last}`).then(job => { if (!current) watch(job); }).catch(() => store.lastJob(app.id, null));
  return { el: root, destroy() { follower?.stop(); clearInterval(tick); } };
}
