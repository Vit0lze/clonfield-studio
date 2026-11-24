// Cinema: open or start a short, put Library assets on it in order, set durations, swap takes, switch cuts, export and see what
// was re-rendered and what came from the cache. Every edit is saved at once and gets a revision number; every export records the
// revision it rendered, so the screen can always say which version is being edited and which one is being watched.
// Gestures borrowed from the studied projects (docs/V9_CINEMA_TELA.md): cuts as saved variants of one project (ComfyArt),
// takes compared side by side on the shot (Creativefield), the spoken line attached to its shot (Imagination Studio),
// audio as lanes under one time ruler (Panorama Stickers), and after export only what changed is lit (Paint a Plate).
import { api } from "../api.js";
import { h, icon, clear, toast, seg } from "../ui.js";

const LANES = [["voice", "Voz"], ["music", "Música"], ["sfx", "Efeitos"]];
const FINAL = ["concluído", "falhou", "cancelado", "travado"];
const VISUAL = new Set(["video", "image", "character"]);
const TRACKS = { voice: ["Voz", "igual em todos os cortes"], music: ["Música", "só neste corte"], sfx: ["Efeitos", "só neste corte"] };
// Element.append writes null as the text "null": optional pieces are dropped here instead.
const fill = (el, ...kids) => { clear(el).append(...kids.flat().filter(k => k != null && k !== false)); return el; };
const secs = s => `${Number(s).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`;
const exact = s => `${Number(s).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 2 })} s`;  // entry times: 9,25 s, not 9,3 s
const clock = t => new Date(t * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
const stepLabel = step => step.startsWith("video:") ? step.slice(6) : { picture: "junção da imagem", mix: "mix", "stem:voice": "trilha voz", "stem:music": "trilha música", "stem:sfx": "trilha efeitos" }[step] || step;

// The picture as the shot frames it: the shot's crop (fractions of the source) shown in a 16:9 box.
function framed(version, crop, cls) {
  const [x, y, w, hgt] = crop || [0, 0, 1, 1];
  const isImage = (version.mime || "").startsWith("image/");
  const media = isImage ? h("img", { src: api.url(version.url), alt: "", loading: "lazy" }) : h("video", { src: `${api.url(version.url)}#t=1`, muted: true, preload: "metadata" });
  if (crop) Object.assign(media.style, { position: "absolute", width: `${100 / w}%`, height: `${100 / hgt}%`, left: `${-100 * x / w}%`, top: `${-100 * y / hgt}%`, objectFit: "fill" });
  return h("div", { class: `cine-frame ${cls}` }, media);
}

// Clips that overlap go to separate rows; opacity follows the clip gain, so a sound that comes forward reads brighter.
function rows(clips) {
  const ends = [];
  return clips.map(c => {
    let row = ends.findIndex(end => end <= c.at + 0.01);
    if (row < 0) { row = ends.length; ends.push(0); }
    ends[row] = c.at + c.dur;
    return { ...c, row };
  });
}

export async function cinemaView(projectId, navigate) {
  const root = h("div", { class: "view cinema" });
  if (projectId) await editor(root, projectId); else await list(root, navigate);
  return { el: root };
}

async function list(root, navigate) {
  const items = await api.get("/cinema/projects");
  const title = h("input", { type: "text", placeholder: "Nome do novo filme", maxlength: 80, "aria-label": "Nome do novo filme", "data-new-title": "" });
  const create = h("button", { class: "btn primary", type: "submit", "data-act": "create" }, icon("plus", "sm"), "Novo projeto");
  const form = h("form", { class: "cine-new", onsubmit: async event => {
    event.preventDefault();
    create.disabled = true;
    try {
      const made = await api.post("/cinema/projects", { title: title.value });
      if (made.detail) throw new Error(made.detail);
      navigate(`#/cinema/${made.id}`);
    } catch (error) { toast(error.message, "err"); create.disabled = false; }
  } }, title, create);
  root.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Cinema"),
    h("p", null, "Curtas montados a partir de ativos com versão fixada. Trocar uma tomada refaz só aquele plano."))), form,
    items.length ? h("div", { class: "cine-list" }, items.map(p => h("a", { class: "cine-project", href: `#/cinema/${p.id}`, "data-project": p.id },
      icon("film"), h("div", null, h("h3", null, p.title),
        h("p", { class: "muted" }, p.shots ? `${p.shots} planos · ${secs(p.duration_s)} · ${p.cuts.length} ${p.cuts.length === 1 ? "corte" : "cortes"} · revisão ${p.revision}` : "vazio · comece adicionando planos")))))
      : h("div", { class: "empty" }, icon("film"), h("h3", null, "Nenhum projeto de cinema"), h("p", null, "Dê um nome e crie o primeiro.")));
}

async function editor(root, projectId) {
  let project;
  try { project = await api.get(`/cinema/projects/${projectId}`); } catch (error) {
    root.append(h("div", { class: "empty" }, icon("alert"), h("h3", null, "Projeto não encontrado"), h("p", null, error.message), h("a", { class: "btn", href: "#/cinema" }, "Voltar")));
    return;
  }
  let follow = null, running = null;   // the export in flight (job id)
  let watching = null;                   // the last FINISHED export: { entry, films, ab, active }
  let picking = false, video = null;
  const progress = h("progress", { max: 1, value: 0 }), progressLine = h("p", { class: "muted" }, "Na fila de CPU…");

  const head = h("div", { class: "section-head" });
  const bar = h("div", { class: "cine-bar" });
  const ruler = h("div", { class: "cine-ruler", "aria-label": "Linha do tempo" });
  const picker = h("section", { class: "cine-picker" });
  const sound = h("section", { class: "cine-sound", "aria-label": "Som" });
  let soundPicking = false, newCut = false;
  const shots = h("ol", { class: "cine-shots", "aria-label": "Planos na ordem" });
  const exportBox = h("section", { class: "cine-export", "aria-live": "polite" });
  const ab = h("section", { class: "cine-ab" });

  const cut = () => project.cuts_view[project.cut];
  const total = () => Math.max(project.duration_s, 0.001);
  const pct = t => `${(100 * t / total()).toFixed(3)}%`;
  const goodEntry = () => project.exports.find(e => e.job_id === project.last_good) || null;
  const versionNumber = id => { for (const s of project.shots) { const v = (s.versions || []).find(x => x.version_id === id); if (v) return v.number; } return "?"; };

  async function edit(path, body, okMessage) {
    try {
      const next = await api.post(`/cinema/projects/${projectId}${path}`, body);
      if (next.detail) throw new Error(next.detail);
      project = next;
      if (okMessage) toast(okMessage);
    } catch (error) { toast(error.message, "err"); }
    paintAll();
  }

  function paintHead() {
    const last = project.history?.[project.history.length - 1];
    fill(head, h("div", null, h("a", { class: "muted", href: "#/cinema" }, "← Cinema"), h("h2", null, project.title),
      h("p", null, project.shots.length ? `${project.shots.length} planos · ${secs(project.duration_s)}` : "Sem planos ainda"),
      h("p", { class: "cine-rev", "data-revision": project.revision }, h("b", null, `Editando revisão ${project.revision}`),
        ` · salvo às ${clock(project.updated)}`, last ? ` · ${last.what}` : "")));
  }

  function paintBar() {
    const cuts = Object.entries(project.cuts_view);
    const choose = cuts.length > 1 ? seg(cuts.map(([id, c]) => ({ value: id, label: c.label })), project.cut, value => edit("/cut", { cut: value })) : h("b", null, cut().label);
    if (cuts.length > 1) choose.setAttribute("aria-label", "Corte");
    const blocked = !project.shots.length || !!running;
    const add = h("button", { class: "btn", type: "button", "data-act": "add", "aria-expanded": String(picking), onclick: () => { picking = !picking; paintPicker(); paintBar(); } }, icon("plus", "sm"), "Adicionar planos");
    const one = h("button", { class: "btn primary", type: "button", "data-act": "export-one", disabled: blocked, onclick: () => exportCuts([project.cut]) }, icon("download", "sm"), cuts.length > 1 ? "Exportar este corte" : "Exportar");
    const both = cuts.length > 1 ? h("button", { class: "btn", type: "button", "data-act": "export-ab", disabled: blocked, onclick: () => exportCuts(cuts.map(([id]) => id)) }, icon("layers", "sm"), "Exportar A e B") : null;
    fill(bar, h("div", { class: "cine-cut" }, choose, h("p", { class: "muted" }, cut().note || "")), h("div", { class: "row" }, add, one, both));
  }

  async function paintPicker() {
    clear(picker);
    if (!picking) return;
    let assets = [];
    try { assets = (await api.get("/assets")).filter(a => VISUAL.has(a.kind)); } catch (error) { toast(error.message, "err"); }
    fill(picker, h("div", { class: "cine-picker-head" }, h("div", null, h("h3", null, "Ativos"), h("p", { class: "muted" }, "Clique para pôr no fim do filme. Entra a versão atual, fixada no plano.")),
      h("button", { class: "btn sm", type: "button", onclick: () => { picking = false; paintPicker(); paintBar(); } }, "Fechar")),
      assets.length ? h("div", { class: "cine-picker-grid" }, assets.map(a => h("button", { type: "button", class: "cine-pick", "data-asset": a.asset_id,
        onclick: () => edit("/shots", { asset: a.asset_id }, `«${a.title}» entrou no fim do filme.`) },
        framed(a.current_version, null, "cine-pick-frame"), h("b", null, a.title),
        h("small", { class: "muted" }, `${a.kind === "video" ? "vídeo" : "imagem"} · v${a.current_version.number}${a.current_version.media?.duration_s ? ` · ${secs(a.current_version.media.duration_s)}` : ""}`))))
        : h("p", { class: "muted" }, "Nenhuma imagem ou vídeo publicado. Use «Usar em» em um resultado para publicar."));
  }

  // How one shot relates to the export in the player: changed since (other take or new), re-rendered by it, or reused from the cache.
  function shotState(id) {
    const entry = watching?.entry;
    if (!entry) return "";
    const shot = project.shots.find(s => s.id === id);
    const before = entry.shots ? entry.shots[id] : entry.versions?.[id];   // exports since CINEMA-003 keep each shot's render spec
    if (before === undefined || before !== (entry.shots ? shot?.spec : shot?.src)) return "is-edited";
    const done = entry.summary?.[project.cut];
    if (!done) return "";
    return done.rendered.includes(`video:${id}`) ? "is-rendered" : done.reused.includes(`video:${id}`) ? "is-reused" : "";
  }

  function paintRuler() {
    clear(ruler);
    ruler.hidden = !project.shots.length;
    if (ruler.hidden) return;
    const shotRow = h("div", { class: "cine-lane cine-lane-video" }, h("span", { class: "cine-lane-name" }, "Imagem"),
      h("div", { class: "cine-track" }, project.shots.map(s => h("button", {
        type: "button", class: `cine-block ${s.src?.color ? "is-black" : ""} ${shotState(s.id)}`, style: `left:${pct(s.start)};width:${pct(s.end - s.start)}`,
        title: `${s.id} · ${secs(s.start)}–${secs(s.end)}`, onclick: () => document.getElementById(`shot-${s.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })
      }, s.id))));
    const lanes = LANES.filter(([key]) => (cut().lanes[key] || []).length).map(([key, name]) => {
      const placed = rows(cut().lanes[key]);
      const count = Math.max(1, ...placed.map(c => c.row + 1));
      return h("div", { class: "cine-lane" }, h("span", { class: "cine-lane-name" }, name),
        h("div", { class: "cine-track", style: `height:${count * 18 + 2}px` }, placed.map(c => h("span", {
          class: `cine-clip cine-${key}`, "data-gain": c.gain_db,
          style: `left:${pct(c.at)};width:${pct(Math.min(c.dur, total() - c.at))};top:${2 + c.row * 18}px;opacity:${Math.max(0.35, Math.min(1, 1 + (c.gain_db || 0) / 16)).toFixed(2)}`,
          title: `${c.title || ""}${c.note ? " · " + c.note : ""} · ${secs(c.at)} · ${c.gain_db || 0} dB`
        }, key === "voice" ? "" : `${(c.title || "").split(" (")[0]}${c.gain_db ? ` ${c.gain_db > 0 ? "+" : ""}${c.gain_db} dB` : ""}`))));
    });
    const step = total() > 30 ? 10 : total() > 10 ? 5 : 1;
    const ticks = h("div", { class: "cine-ticks", "aria-hidden": "true" }, Array.from({ length: Math.floor(total() / step) + 1 }, (_, i) => h("span", { style: `left:${pct(i * step)}` }, `${i * step}`)));
    ruler.append(ticks, shotRow, ...lanes);
  }

  function lineFor(s) {
    return (cut().lanes.voice || []).filter(c => c.at < s.end && c.at + c.dur > s.start).map(c => c.note).filter(Boolean);
  }

  function paintShots() {
    clear(shots);
    if (!project.shots.length) {
      shots.append(h("li", { class: "empty cine-empty" }, icon("film"), h("h3", null, "Filme vazio"),
        h("p", null, "Adicione imagens ou vídeos dos Ativos. A ordem e a duração de cada plano se ajustam aqui."),
        h("button", { class: "btn primary", type: "button", "data-act": "add-empty", onclick: () => { picking = true; paintPicker(); paintBar(); } }, icon("plus", "sm"), "Adicionar planos")));
      return;
    }
    const [min, max] = project.shot_limits || [0.5, 60];
    project.shots.forEach((s, index) => {
      const takes = s.versions && s.versions.length > 1 ? h("div", { class: "cine-takes", role: "group", "aria-label": `Tomadas do plano ${s.id}` },
        s.versions.map(v => h("button", {
          type: "button", class: "cine-take", "aria-pressed": String(v.version_id === s.src), "data-version": v.version_id,
          onclick: () => v.version_id !== s.src && edit(`/shots/${s.id}`, { version: v.version_id }, `${s.id}: tomada v${v.number}. A anterior continua disponível.`)
        }, framed(v, s.crop, "cine-take-frame"), h("b", null, `v${v.number}`),
          h("small", null, (v.metadata?.note || v.producer?.note || "").replace(/^segunda tomada: /, "").slice(0, 46))))) : null;
      const mark = shotState(s.id);
      const dur = h("input", { type: "number", min, max, step: 0.5, value: s.dur, class: "cine-dur", "aria-label": `Duração do plano ${s.id} em segundos`, "data-dur": s.id });
      dur.addEventListener("change", () => edit(`/shots/${s.id}`, { dur: Number(dur.value) }));
      const move = delta => {
        const order = project.shots.map(x => x.id);
        const [moved] = order.splice(index, 1);
        order.splice(index + delta, 0, moved);
        edit("/order", { order });
      };
      const tools = h("div", { class: "cine-tools" },
        h("label", { class: "cine-dur-label" }, dur, "s"),
        s.kind === "video" && s.natural_s ? h("span", { class: "muted" }, s.loop ? `tomada de ${secs(s.natural_s)}, repete` : `tomada de ${secs(s.natural_s)}`) : null,
        h("span", { class: "grow" }),
        h("button", { class: "btn sm", type: "button", title: "Subir", "aria-label": `Subir ${s.id}`, "data-move": `${s.id}:up`, disabled: index === 0, onclick: () => move(-1) }, "↑"),
        h("button", { class: "btn sm", type: "button", title: "Descer", "aria-label": `Descer ${s.id}`, "data-move": `${s.id}:down`, disabled: index === project.shots.length - 1, onclick: () => move(1) }, "↓"),
        h("button", { class: "btn sm", type: "button", title: "Tirar do filme", "aria-label": `Tirar ${s.id}`, "data-remove": s.id, onclick: () => edit(`/shots/${s.id}`, { remove: true }, `${s.id} saiu do filme.`) }, icon("x", "sm")));
      shots.append(h("li", { class: `cine-shot ${mark}`, id: `shot-${s.id}`, "data-shot": s.id },
        s.src?.color ? h("div", { class: "cine-thumb is-black" }, "preto") : framed(s.version, s.crop, "cine-thumb"),
        h("div", { class: "cine-shot-body" },
          h("div", { class: "cine-shot-head" }, h("b", null, `Plano ${index + 1}`), h("span", { class: "muted" }, `${s.id} · ${secs(s.start)}–${secs(s.end)}`),
            s.version ? h("span", { class: "badge" }, `v${s.version.number}`) : null,
            mark === "is-edited" ? h("span", { class: "badge warn" }, "mudou depois da exportação") : mark === "is-rendered" ? h("span", { class: "badge warn" }, "refeito") : mark === "is-reused" ? h("span", { class: "badge ok" }, "do cache") : null),
          h("p", null, s.asset_title || s.note || ""),
          s.note && s.asset_title && s.note !== s.asset_title ? h("p", { class: "muted" }, s.note) : null,
          lineFor(s).map(text => h("p", { class: "cine-line" }, `«${text}»`)),
          tools, takes)));
    });
  }

  function watch(jobId) {
    running = jobId;
    follow?.stop();
    follow = api.follow(jobId, async snapshot => {
      progress.value = snapshot.progress || 0;
      progressLine.textContent = snapshot.desc || snapshot.status;
      if (!FINAL.includes(snapshot.status)) return;
      running = null;
      project = await api.get(`/cinema/projects/${projectId}`);
      if (snapshot.status === "concluído") await loadWatching();
      else toast(`A exportação ${snapshot.status}. O último par concluído continua no player.`, "err", 8000);
      paintAll();
    });
  }

  async function exportCuts(cuts) {
    try {
      const job = await api.post(`/cinema/projects/${projectId}/export`, { cuts });
      if (job.detail) throw new Error(job.detail);
      progress.value = 0;
      progressLine.textContent = "Na fila de CPU…";
      project = await api.get(`/cinema/projects/${projectId}`);
      watch(job.id);
    } catch (error) { toast(error.message, "err"); }
    paintAll();
  }

  function paintExports() {
    clear(exportBox);
    if (running) exportBox.append(h("div", { class: "cine-live" }, h("h3", null, "Exportando…"), progress, progressLine));
    if (!project.exports.length) return;
    const labelOf = id => project.cuts_view[id]?.label || id;
    exportBox.append(h("h3", null, "Exportações"), h("ol", { class: "cine-history" }, [...project.exports].reverse().slice(0, 6).map(e => {
      const good = e.job_id === project.last_good;
      return h("li", { class: `cine-hist ${good ? "is-good" : ""}`, "data-export": e.job_id, "data-status": e.status },
        h("div", { class: "cine-hist-head" }, h("b", null, `${clock(e.at)} · revisão ${e.revision}`),
          h("span", { class: `badge ${e.status === "concluído" ? "ok" : e.status === "falhou" ? "red" : ""}` }, e.status),
          good ? h("span", { class: "badge" }, "no player") : null),
        e.message && e.status !== "concluído" ? h("p", { class: "muted cine-err" }, e.message.split("\n")[0].slice(0, 160)) : null,
        ...Object.entries(e.summary || {}).map(([cid, r]) => h("div", { class: "cine-steps", "data-cut": cid },
          h("span", { class: "muted" }, `${labelOf(cid)} · ${secs(r.seconds)}:`),
          r.rendered.length ? r.rendered.map(s => h("span", { class: "badge warn", "data-step": s }, `refez ${stepLabel(s)}`)) : h("span", { class: "badge" }, "nada refeito"),
          h("span", { class: "badge ok", title: r.reused.map(stepLabel).join(", ") }, `${r.reused.length} do cache`))));
    })));
  }

  async function loadWatching() {
    const entry = goodEntry();
    if (!entry) { watching = null; return; }
    if (watching?.entry.job_id === entry.job_id) { watching.entry = entry; return; }
    try {
      const job = await api.get(`/jobs/${entry.job_id}`);
      const results = job.results || [];
      const films = entry.cuts.map(cid => ({ cutId: cid, result: results.find(r => r.path.endsWith(`-${cid}.mp4`)) })).filter(f => f.result);
      const abResult = results.find(r => r.path.endsWith(".ab.json"));
      const abRecord = abResult ? await (await fetch(api.url(abResult.url), { cache: "no-store" })).json() : null;
      watching = { entry, films, ab: abRecord, active: Math.max(0, films.findIndex(f => f.cutId === project.cut)) };
    } catch { watching = null; }
  }

  function paintAB() {
    if (!watching || !watching.films.length) { clear(ab); video = null; return; }
    const { entry, films } = watching;
    const film = films[watching.active];
    if (!video) video = h("video", { class: "cine-player", controls: true, preload: "auto" });
    if (video.dataset.src !== film.result.url) {  // switching A/B keeps the instant (and keeps playing)
      const at = video.currentTime || 0, playing = !!video.dataset.src && !video.paused;
      video.src = api.url(film.result.url);
      video.dataset.src = film.result.url;
      if (at) video.addEventListener("loadedmetadata", () => { video.currentTime = at; if (playing) video.play(); }, { once: true });
    }
    const switcher = films.length > 1 ? h("div", { class: "seg", role: "group", "aria-label": "Ouvir o corte" }, films.map((f, i) => h("button", {
      type: "button", "aria-pressed": String(i === watching.active), "data-ab": f.cutId, onclick: () => { watching.active = i; paintAB(); }
    }, `${String.fromCharCode(65 + i)} · ${project.cuts_view[f.cutId]?.label || f.cutId}`))) : null;
    const takes = Object.entries(entry.versions || {}).filter(([id]) => (project.shots.find(s => s.id === id)?.versions || []).length > 1);
    const changed = Object.entries(entry.versions || {}).filter(([id, v]) => project.shots.find(s => s.id === id)?.src !== v);
    const old = entry.signatures?.[film.cutId] !== project.cuts_view[film.cutId]?.signature;
    const watchingLine = h("p", { class: "cine-watching", "data-watching-revision": entry.revision },
      h("b", null, `Assistindo: exportação das ${clock(entry.finished || entry.at)} · revisão ${entry.revision}`),
      takes.length ? ` · ${takes.map(([id, v]) => `${id} v${versionNumber(v)}`).join(" · ")}` : "");
    const staleNote = old ? h("p", { class: "cine-stale", role: "status", "data-stale": "" }, icon("alert", "sm"),
      ` Exportação anterior: a timeline mudou depois deste render (revisão ${entry.revision} → ${project.revision}${changed.length ? `; ${changed.map(([id]) => id).join(", ")} mudou` : ""}). Exporte de novo para ver a mudança.`) : null;
    const voice = cut().lanes.voice || [];
    const longest = [...project.shots].sort((a, b) => (b.end - b.start) - (a.end - a.start))[0];
    const before = longest && voice.filter(c => c.at + c.dur <= longest.start + 0.5).pop();
    const black = [...project.shots].reverse().find(s => s.src?.color);
    const seek = t => () => { video.currentTime = Math.max(0, t); video.play(); };
    const marks = before || black ? h("div", { class: "row" },
      before ? h("button", { class: "btn sm", type: "button", "data-mark": "transicao", onclick: seek(before.at - 1) }, icon("play", "sm"), `Transição · «${(before.note || "").split(". ").pop()}»`) : null,
      black ? h("button", { class: "btn sm", type: "button", "data-mark": "preto", onclick: seek(black.start - 3) }, icon("play", "sm"), `Preto final · ${secs(black.end - black.start)}`) : null) : null;
    const facts = watching.ab ? h("p", { class: "muted", "data-ab-facts": "" },
      watching.ab.picture_identical ? "Imagem idêntica nos dois cortes (mesma junção, mesmo MD5 do vídeo). " : "A imagem difere entre os cortes. ",
      `Volume: ${Object.values(watching.ab.loudness).map(v => `${v.I} LUFS`).join(" e ")} (diferença ${watching.ab.loudness_spread_lu} LU; alvo ${watching.ab.target.I}).`) : null;
    const keep = films.length > 1 ? h("button", { class: "btn primary sm", type: "button", "data-act": "keep", onclick: () => edit("/cut", { cut: films[watching.active].cutId }, `Corte escolhido: «${project.cuts_view[films[watching.active].cutId].label}». O outro continua salvo.`) }, icon("check", "sm"), "Ficar com este corte") : null;
    fill(ab, h("h3", null, films.length > 1 ? "Sessão A/B" : "Assistir"), watchingLine, staleNote, switcher, video, marks, facts, keep);
  }

  // Sound: one row per clip. «Entra em» can be typed or snapped to the start of a shot (sync to a cut); gain in dB;
  // an empty duration plays the whole file. Voice is the project's (every cut); music and effects belong to the chosen cut.
  async function paintSound() {
    if (!project.shots.length) { clear(sound); return; }
    const c = cut();
    const anchors = project.shots.map((s, i) => ({ at: s.start, label: `início do Plano ${i + 1} · ${s.id} (${secs(s.start)})` }));
    const num = (value, attrs, apply) => {
      const input = h("input", { type: "number", class: "cine-num", value: value ?? "", ...attrs });
      input.addEventListener("change", () => apply(input.value === "" ? "" : Number(input.value)));
      return input;
    };
    const update = (track, index, fields) => edit(`/audio/${track}/${index}`, { ...fields, cut: project.cut });
    const tracks = Object.entries(TRACKS).map(([track, [name, scope]]) => {
      const clips = c.lanes[track] || [];
      return h("div", { class: "cine-track-edit", "data-track": track },
        h("h4", null, name, h("span", { class: "muted" }, ` · ${scope}`)),
        clips.length ? clips.map(clip => {
          const anchor = h("select", { class: "cine-anchor", "aria-label": `Encaixar ${clip.title} no início de um plano`, "data-anchor": `${track}:${clip.index}` },
            h("option", { value: "" }, "encaixar no início de…"), anchors.map(a => h("option", { value: a.at }, a.label)));
          anchor.addEventListener("change", () => anchor.value !== "" && update(track, clip.index, { at: Number(anchor.value) }));
          const player = h("audio", { src: api.url(clip.url), preload: "none", controls: true, class: "cine-audio" });
          return h("div", { class: "cine-clip-row", "data-clip": `${track}:${clip.index}` },
            h("div", { class: "cine-clip-title" }, h("b", null, clip.title || clip.src), h("span", { class: "muted" }, ` v${clip.version} · ${exact(clip.at)}–${secs(Math.min(clip.at + clip.dur, project.duration_s))}`)),
            h("div", { class: "cine-clip-fields" },
              h("label", null, "entra em", num(clip.at, { step: 0.1, min: 0, "data-field": "at", "aria-label": "Entra em (s)" }, v => update(track, clip.index, { at: v })), "s"),
              anchor,
              h("label", null, "ganho", num(clip.gain_db, { step: 0.5, min: -40, max: 12, "data-field": "gain_db", "aria-label": "Ganho (dB)" }, v => update(track, clip.index, { gain_db: v === "" ? 0 : v })), "dB"),
              h("label", null, "dura", num(clip.set_dur, { step: 0.1, min: 0.1, placeholder: clip.natural_s ? secs(clip.natural_s) : "inteira", "data-field": "dur", "aria-label": "Duração (s, vazio = o arquivo inteiro)" }, v => update(track, clip.index, { dur: v })), "s"),
              h("label", null, "fade", num(clip.fade_in, { step: 0.1, min: 0, placeholder: "0", "data-field": "fade_in", "aria-label": "Fade de entrada (s)" }, v => update(track, clip.index, { fade_in: v })),
                "/", num(clip.fade_out, { step: 0.1, min: 0, placeholder: "0", "data-field": "fade_out", "aria-label": "Fade de saída (s)" }, v => update(track, clip.index, { fade_out: v })), "s"),
              h("button", { class: "btn sm", type: "button", "aria-label": `Tirar ${clip.title}`, "data-clip-remove": `${track}:${clip.index}`, onclick: () => update(track, clip.index, { remove: true }) }, icon("x", "sm"))),
            player);
        }) : h("p", { class: "muted" }, "vazio"));
    });
    const label = h("input", { type: "text", placeholder: "Nome do corte novo", maxlength: 40, "aria-label": "Nome do corte novo", "data-new-cut": "" });
    const cutForm = newCut ? h("form", { class: "cine-new", onsubmit: event => { event.preventDefault(); newCut = false; edit("/cuts", { label: label.value, from: project.cut }, "Corte novo criado a partir deste; a voz e a imagem são as mesmas."); } },
      label, h("button", { class: "btn primary sm", type: "submit" }, "Criar corte"), h("button", { class: "btn sm", type: "button", onclick: () => { newCut = false; paintSound(); } }, "Cancelar")) : null;
    const pickList = soundPicking ? h("div", { class: "cine-sound-picker" }, (audioAssets || []).map(a => h("div", { class: "cine-sound-pick", "data-audio": a.asset_id },
      h("div", null, h("b", null, a.title), h("small", { class: "muted" }, ` · v${a.current_version.number}${a.current_version.media?.duration_s ? ` · ${secs(a.current_version.media.duration_s)}` : ""}`)),
      h("audio", { src: api.url(a.current_version.url), preload: "none", controls: true, class: "cine-audio" }),
      h("div", { class: "row" }, Object.entries(TRACKS).map(([track, [name]]) => h("button", { class: "btn sm", type: "button", "data-add-to": track,
        onclick: () => { soundPicking = false; edit("/audio", { track, asset: a.asset_id, at: 0, cut: project.cut }, `«${a.title}» entrou em ${name.toLowerCase()} no início; ajuste a entrada.`); } }, `→ ${name}`)))))) : null;
    fill(sound, h("div", { class: "cine-sound-head" }, h("div", null, h("h3", null, `Som · ${c.label}`),
      h("p", { class: "muted" }, "Mudar só o som reaproveita a imagem inteira na próxima exportação.")),
      h("div", { class: "row" },
        h("button", { class: "btn sm", type: "button", "data-act": "add-sound", "aria-expanded": String(soundPicking), onclick: async () => { soundPicking = !soundPicking; if (soundPicking) await loadAudio(); paintSound(); } }, icon("plus", "sm"), "Adicionar som"),
        h("button", { class: "btn sm", type: "button", "data-act": "new-cut", onclick: () => { newCut = true; paintSound(); } }, icon("layers", "sm"), "Novo corte a partir deste"))),
      cutForm, pickList, tracks);
  }

  let audioAssets = null;
  async function loadAudio() {
    try { audioAssets = (await api.get("/assets")).filter(a => a.kind === "audio"); } catch (error) { toast(error.message, "err"); audioAssets = []; }
  }

  function paintAll() { paintHead(); paintBar(); paintRuler(); paintSound(); paintShots(); paintExports(); paintAB(); }

  root.append(head, bar, ruler, sound, picker, h("div", { class: "cine-grid" }, shots, h("div", { class: "cine-side" }, exportBox, ab)));
  await Promise.all([loadWatching(), loadAudio()]);
  const inFlight = project.exports.find(e => e.job_id === project.last_export && !FINAL.includes(e.status));
  if (inFlight) watch(inFlight.job_id);  // reopened while an export runs: follow it
  paintAll();
}
