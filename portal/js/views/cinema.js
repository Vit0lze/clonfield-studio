// Cinema: open a saved short, see its shots in order, swap the take of a shot, switch between cuts, export and see what was
// re-rendered and what came from the cache. A/B: both cuts side by side on the same player, same reference loudness.
// Gestures borrowed from the studied projects (docs/V9_CINEMA_TELA.md): cuts as saved variants of one project (ComfyArt),
// takes compared side by side on the shot (Creativefield), the spoken line attached to its shot (Imagination Studio),
// audio as lanes under one time ruler (Panorama Stickers), and after export only what changed is lit (Paint a Plate).
import { api } from "../api.js";
import { h, icon, clear, toast, seg } from "../ui.js";

const LANES = [["voice", "Voz"], ["music", "Música"], ["sfx", "Efeitos"]];
const secs = s => `${Number(s).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`;
const stepLabel = step => step.startsWith("video:") ? step.slice(6) : { picture: "junção da imagem", mix: "mix", "stem:voice": "trilha voz", "stem:music": "trilha música", "stem:sfx": "trilha efeitos" }[step] || step;

// The picture as the shot frames it: the shot's crop (fractions of the source) shown in a 16:9 box.
function framed(url, crop, cls) {
  const [x, y, w, hgt] = crop || [0, 0, 1, 1];
  const video = h("video", { src: `${api.url(url)}#t=1`, muted: true, preload: "metadata" });
  if (crop) Object.assign(video.style, { position: "absolute", width: `${100 / w}%`, height: `${100 / hgt}%`, left: `${-100 * x / w}%`, top: `${-100 * y / hgt}%`, objectFit: "fill" });
  return h("div", { class: `cine-frame ${cls}` }, video);
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
  if (projectId) await editor(root, projectId, navigate); else await list(root);
  return { el: root };
}

async function list(root) {
  const items = await api.get("/cinema/projects");
  root.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Cinema"),
    h("p", null, "Curtas montados a partir de ativos com versão fixada. Trocar uma tomada refaz só aquele plano."))),
    items.length ? h("div", { class: "cine-list" }, items.map(p => h("a", { class: "cine-project", href: `#/cinema/${p.id}`, "data-project": p.id },
      icon("film"), h("div", null, h("h3", null, p.title), h("p", { class: "muted" }, `${p.shots} planos · ${secs(p.duration_s)} · ${p.cuts.length} cortes`)))))
      : h("div", { class: "empty" }, icon("film"), h("h3", null, "Nenhum projeto de cinema"), h("p", null, "Um projeto é salvo pela API (POST /cinema/projects).")));
}

async function editor(root, projectId, navigate) {
  let project;
  try { project = await api.get(`/cinema/projects/${projectId}`); } catch (error) {
    root.append(h("div", { class: "empty" }, icon("alert"), h("h3", null, "Projeto não encontrado"), h("p", null, error.message), h("a", { class: "btn", href: "#/cinema" }, "Voltar")));
    return;
  }
  let lastRecords = {};   // shot id -> "rendered" | "reused" from the last export, per cut
  let edited = new Set(); // shots changed since that export
  let follow = null;
  const total = project.duration_s;

  const head = h("div", { class: "section-head" });
  const bar = h("div", { class: "cine-bar" });
  const ruler = h("div", { class: "cine-ruler", "aria-label": "Linha do tempo" });
  const shots = h("ol", { class: "cine-shots", "aria-label": "Planos na ordem" });
  const exportBox = h("section", { class: "cine-export", "aria-live": "polite" });
  const ab = h("section", { class: "cine-ab" });

  const cut = () => project.cuts_view[project.cut];
  const pct = t => `${(100 * t / total).toFixed(3)}%`;

  function paintHead() {
    clear(head).append(h("div", null, h("a", { class: "muted", href: "#/cinema" }, "← Cinema"), h("h2", null, project.title),
      h("p", null, `${project.shots.length} planos · ${secs(total)} · imagem e voz iguais em todos os cortes`)));
  }

  function paintBar() {
    const choose = seg(Object.entries(project.cuts_view).map(([id, c]) => ({ value: id, label: c.label })), project.cut, async value => {
      try { project = await api.post(`/cinema/projects/${projectId}/cut`, { cut: value }); paintAll(); } catch (error) { toast(error.message, "err"); }
    });
    choose.setAttribute("aria-label", "Corte");
    const one = h("button", { class: "btn primary", type: "button", "data-act": "export-one", onclick: () => exportCuts([project.cut]) }, icon("download", "sm"), "Exportar este corte");
    const both = h("button", { class: "btn", type: "button", "data-act": "export-ab", onclick: () => exportCuts(Object.keys(project.cuts)) }, icon("layers", "sm"), "Exportar A e B");
    clear(bar).append(h("div", { class: "cine-cut" }, choose, h("p", { class: "muted" }, cut().note || "")), h("div", { class: "row" }, one, both));
  }

  function paintRuler() {
    const shotRow = h("div", { class: "cine-lane cine-lane-video" }, h("span", { class: "cine-lane-name" }, "Imagem"),
      h("div", { class: "cine-track" }, project.shots.map(s => h("button", {
        type: "button", class: `cine-block ${s.src?.color ? "is-black" : ""} ${state(s.id)}`, style: `left:${pct(s.start)};width:${pct(s.end - s.start)}`,
        title: `${s.id} · ${secs(s.start)}–${secs(s.end)}`, onclick: () => document.getElementById(`shot-${s.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })
      }, s.id))));
    const lanes = LANES.map(([key, name]) => {
      const placed = rows(cut().lanes[key] || []);
      const count = Math.max(1, ...placed.map(c => c.row + 1));
      return h("div", { class: "cine-lane" }, h("span", { class: "cine-lane-name" }, name),
        h("div", { class: "cine-track", style: `height:${count * 18 + 2}px` }, placed.map(c => h("span", {
          class: `cine-clip cine-${key}`, "data-gain": c.gain_db,
          style: `left:${pct(c.at)};width:${pct(Math.min(c.dur, total - c.at))};top:${2 + c.row * 18}px;opacity:${Math.max(0.35, Math.min(1, 1 + (c.gain_db || 0) / 16)).toFixed(2)}`,
          title: `${c.title || ""}${c.note ? " · " + c.note : ""} · ${secs(c.at)} · ${c.gain_db || 0} dB`
        }, key === "voice" ? "" : `${(c.title || "").split(" (")[0]}${c.gain_db ? ` ${c.gain_db > 0 ? "+" : ""}${c.gain_db} dB` : ""}`))));
    });
    const ticks = h("div", { class: "cine-ticks", "aria-hidden": "true" }, Array.from({ length: Math.floor(total / 10) + 1 }, (_, i) => h("span", { style: `left:${pct(i * 10)}` }, `${i * 10}`)));
    clear(ruler).append(ticks, shotRow, ...lanes);
  }

  function state(shotId) {
    if (edited.has(shotId)) return "is-edited";
    return lastRecords[shotId] ? `is-${lastRecords[shotId]}` : "";
  }

  function lineFor(s) {
    return (cut().lanes.voice || []).filter(c => c.at < s.end && c.at + c.dur > s.start).map(c => c.note).filter(Boolean);
  }

  function paintShots() {
    clear(shots);
    for (const s of project.shots) {
      const lines = lineFor(s);
      const takes = s.versions && s.versions.length > 1 ? h("div", { class: "cine-takes", role: "group", "aria-label": `Tomadas do plano ${s.id}` },
        s.versions.map(v => h("button", {
          type: "button", class: "cine-take", "aria-pressed": String(v.version_id === s.src), "data-version": v.version_id,
          onclick: () => v.version_id !== s.src && swap(s, v)
        }, framed(v.url, s.crop, "cine-take-frame"), h("b", null, `v${v.number}`),
          h("small", null, (v.metadata?.note || v.producer?.note || "").replace(/^segunda tomada: /, "").slice(0, 46))))) : null;
      const mark = state(s.id);
      shots.append(h("li", { class: `cine-shot ${mark}`, id: `shot-${s.id}`, "data-shot": s.id },
        s.src?.color ? h("div", { class: "cine-thumb is-black" }, "preto") : framed(s.version.url, s.crop, "cine-thumb"),
        h("div", { class: "cine-shot-body" },
          h("div", { class: "cine-shot-head" }, h("b", null, s.id), h("span", { class: "muted" }, `${secs(s.start)}–${secs(s.end)}`),
            s.version ? h("span", { class: "badge" }, `v${s.version.number}`) : null,
            mark === "is-edited" ? h("span", { class: "badge warn" }, "alterado") : mark === "is-rendered" ? h("span", { class: "badge warn" }, "refeito") : mark === "is-reused" ? h("span", { class: "badge ok" }, "do cache") : null),
          h("p", null, s.asset_title || s.note || ""),
          s.note && s.asset_title ? h("p", { class: "muted" }, s.note) : null,
          lines.map(text => h("p", { class: "cine-line" }, `«${text}»`)),
          takes)));
    }
  }

  async function swap(shot, version) {
    try {
      project = await api.post(`/cinema/projects/${projectId}/shots/${shot.id}`, { version: version.version_id });
      edited.add(shot.id);
      toast(`${shot.id}: tomada v${version.number}. A anterior continua disponível.`);
      paintAll();
    } catch (error) { toast(error.message, "err"); }
  }

  async function exportCuts(cuts) {
    bar.querySelectorAll("button[data-act]").forEach(b => { b.disabled = true; });
    const progress = h("progress", { max: 1, value: 0 }), line = h("p", { class: "muted" }, "Na fila de CPU…");
    clear(exportBox).append(h("h3", null, cuts.length > 1 ? "Exportando A e B" : `Exportando «${project.cuts_view[cuts[0]].label}»`), progress, line);
    try {
      const job = await api.post(`/cinema/projects/${projectId}/export`, { cuts });
      if (job.detail) throw new Error(job.detail);
      follow?.stop();
      follow = api.follow(job.id, async snapshot => {
        progress.value = snapshot.progress || 0;
        line.textContent = snapshot.desc || snapshot.status;
        if (snapshot.status === "concluído") { edited = new Set(); await showExport(snapshot); }
        else if (["falhou", "cancelado", "travado"].includes(snapshot.status)) { line.textContent = snapshot.message || snapshot.status; done(); }
      });
    } catch (error) { line.textContent = error.message; done(); }
  }

  function done() { bar.querySelectorAll("button[data-act]").forEach(b => { b.disabled = false; }); }

  async function readJson(result) { return (await fetch(api.url(result.url), { cache: "no-store" })).json(); }

  async function showExport(job) {
    done();
    const results = job.results || [];
    const renders = await Promise.all(results.filter(r => r.path.endsWith(".render.json")).map(readJson));
    const abResult = results.find(r => r.path.endsWith(".ab.json"));
    const abRecord = abResult ? await readJson(abResult) : null;
    lastRecords = {};
    const current = renders.find(r => r.timeline.name.endsWith(`-${project.cut}`)) || renders[0];
    for (const step of current?.steps || []) if (step.step.startsWith("video:")) lastRecords[step.step.slice(6)] = step.status;
    clear(exportBox).append(h("h3", null, "Última exportação"),
      h("p", { class: "muted" }, new Date((job.finished || Date.now() / 1000) * 1000).toLocaleString("pt-BR"), ` · job ${job.id.slice(0, 8)}`),
      ...renders.map(r => {
        const label = Object.entries(project.cuts_view).find(([id]) => r.timeline.name.endsWith(`-${id}`))?.[1].label || r.timeline.name;
        return h("div", { class: "cine-report", "data-cut": r.timeline.name },
          h("h4", null, label, h("span", { class: "muted" }, ` · ${secs(r.seconds)} de render · ${r.film.loudness.I} LUFS`)),
          h("div", { class: "cine-steps" }, h("span", { class: "muted" }, "Refeito:"), r.rendered.length ? r.rendered.map(s => h("span", { class: "badge warn", "data-step": s }, stepLabel(s))) : h("span", { class: "badge" }, "nada")),
          h("div", { class: "cine-steps" }, h("span", { class: "muted" }, "Do cache:"), r.reused.map(s => h("span", { class: "badge ok", "data-step": s }, stepLabel(s)))));
      }));
    paintRuler();
    paintShots();
    paintAB(renders, results, abRecord);
  }

  function paintAB(renders, results, abRecord) {
    clear(ab);
    const films = renders.map(r => ({ record: r, result: results.find(x => x.path.endsWith(r.film.file)),
      cutId: Object.keys(project.cuts_view).find(id => r.timeline.name.endsWith(`-${id}`)) })).filter(f => f.result);
    if (!films.length) return;
    let active = films.findIndex(f => f.cutId === project.cut);
    if (active < 0) active = 0;
    const video = h("video", { class: "cine-player", controls: true, preload: "auto", src: api.url(films[active].result.url) });
    const pick = index => {
      const at = video.currentTime, playing = !video.paused;
      active = index;
      video.src = api.url(films[index].result.url);
      video.addEventListener("loadedmetadata", () => { video.currentTime = at; if (playing) video.play(); }, { once: true });
      paintSwitch();
    };
    const switcher = h("div", { class: "seg", role: "group", "aria-label": "Ouvir o corte" });
    const paintSwitch = () => {
      clear(switcher).append(...films.map((f, i) => h("button", { type: "button", "aria-pressed": String(i === active), "data-ab": f.cutId, onclick: () => pick(i) },
        `${String.fromCharCode(65 + i)} · ${project.cuts_view[f.cutId]?.label || f.cutId}`)));
    };
    paintSwitch();
    const voice = project.cuts_view[project.cut].lanes.voice || [];
    const longest = [...project.shots].sort((a, b) => (b.end - b.start) - (a.end - a.start))[0];
    const before = voice.filter(c => c.at + c.dur <= longest.start + 0.5).pop();
    const black = [...project.shots].reverse().find(s => s.src?.color);
    const seek = t => () => { video.currentTime = Math.max(0, t); video.play(); };
    const marks = h("div", { class: "row" },
      before ? h("button", { class: "btn sm", type: "button", "data-mark": "transicao", onclick: seek(before.at - 1) }, icon("play", "sm"), `Transição · «${(before.note || "").split(". ").pop()}»`) : null,
      black ? h("button", { class: "btn sm", type: "button", "data-mark": "preto", onclick: seek(black.start - 3) }, icon("play", "sm"), `Preto final · ${secs(black.end - black.start)}`) : null);
    const facts = abRecord ? h("p", { class: "muted", "data-ab-facts": "" },
      abRecord.picture_identical ? "Imagem idêntica nos dois cortes (mesma junção, mesmo MD5 do vídeo). " : "A imagem difere entre os cortes. ",
      `Volume: ${Object.values(abRecord.loudness).map(v => `${v.I} LUFS`).join(" e ")} (diferença ${abRecord.loudness_spread_lu} LU; alvo ${abRecord.target.I}).`) : null;
    const keep = h("button", { class: "btn primary sm", type: "button", "data-act": "keep", onclick: async () => {
      const id = films[active].cutId;
      project = await api.post(`/cinema/projects/${projectId}/cut`, { cut: id });
      toast(`Corte escolhido: «${project.cuts_view[id].label}». O outro continua salvo.`);
      paintAll();
    } }, icon("check", "sm"), "Ficar com este corte");
    ab.append(h("h3", null, films.length > 1 ? "Sessão A/B" : "Assistir"), switcher, video, marks, facts, films.length > 1 ? keep : null);
  }

  function paintAll() { paintHead(); paintBar(); paintRuler(); paintShots(); }  // the A/B player is left as it is

  root.append(head, bar, ruler, h("div", { class: "cine-grid" }, shots, h("div", { class: "cine-side" }, exportBox, ab)));
  paintAll();
  if (project.last_export) {
    try {
      const job = await api.get(`/jobs/${project.last_export}`);
      if (job.status === "concluído") await showExport(job);
    } catch { /* the job record may be gone: nothing to show */ }
  }
}
