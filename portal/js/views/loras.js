import { api, store, isFinal } from "../api.js";
import { h, icon, clear, seg, dropdown, posterEl, toast, illustration } from "../ui.js";

const FAMILIES = [
  { value: "qwen21", label: "Qwen Image 2.1", hint: "Edição fiel, texto legível" },
  { value: "krea2", label: "Krea 2", hint: "Estética autoral" },
  { value: "flux2", label: "FLUX.2 Klein 4B", hint: "Rápido e leve" },
  { value: "flux3", label: "FLUX.3 Klein", hint: "Nova geração" },
  { value: "z-image", label: "Z-Image", hint: "Realismo limpo" },
];
const SORTS = [{ value: "downloads", label: "Mais baixados" }, { value: "rated", label: "Mais curtidos" }, { value: "newest", label: "Mais novos" }];
const compact = n => n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}K` : String(n);
const pref = (key, fallback) => { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } };
const setPref = (key, value) => { try { localStorage.setItem(key, value); } catch { /* private mode */ } };

export async function lorasView(navigate) {
  const root = h("div", { class: "view" });
  const followers = [];
  let tab = "civitai", family = pref("cf-lora-family", "qwen21"), sort = "downloads", query = "", cursor = null, loading = false;
  let hideAdult = pref("cf-hide-adult", "0") === "1";
  let cards = [], installed = await api.get("/loras").catch(() => []);
  const grid = h("div", { class: "cvgrid" });
  const more = h("button", { class: "btn", type: "button", hidden: true, onclick: () => load(false) }, "Carregar mais");
  const status = h("p", { class: "hint", role: "status" });

  const useLora = (name, fam) => {
    store.prefill({ app: "create", values: { model: fam, loras: [{ name, strength: 1, clip: 1, on: true }] } });
    navigate("#/apps/create");
  };

  function cover(item) {
    const box = h("div", { class: "cover" });
    if (item.cover && item.cover_kind === "video") box.append(h("video", { src: api.url(item.cover), muted: true, loop: true, autoplay: true, playsinline: true }));
    else if (item.cover) {
      const img = h("img", { src: api.url(item.cover), alt: "", loading: "lazy", decoding: "async" });
      img.addEventListener("error", () => { img.replaceWith(posterEl(item.title || item.name)); });
      box.append(img);
    } else box.append(posterEl(item.title || item.name));
    return box;
  }

  function card(item, i, { fam, install, use, state }) {
    const stats = item.stats;
    const action = h("div", { class: "cvact" });
    const paintAction = () => {
      clear(action);
      if (state.installed) action.append(h("button", { class: "btn sm primary", type: "button", onclick: use }, icon("bolt", "sm"), "Usar"));
      else if (state.busy) action.append(h("span", { class: "cvprog mono" }, state.progress || "Preparando…"));
      else action.append(h("button", { class: "btn sm", type: "button", onclick: install }, icon("download", "sm"), "Baixar",
        item.files?.[0]?.size_mb ? h("small", { class: "mono" }, `${item.files[0].size_mb >= 1024 ? (item.files[0].size_mb / 1024).toFixed(1) + " GB" : Math.round(item.files[0].size_mb) + " MB"}`) : null));
    };
    state.repaint = paintAction;
    paintAction();
    return h("article", { class: `cvcard${item.adult ? " adult" : ""}`, style: { "--i": Math.min(i, 12) } },
      cover(item),
      h("div", { class: "cvtop" }, h("span", { class: "cvbadge" }, "LoRA"), item.badge ? h("span", { class: "cvbadge base" }, item.badge) : null,
        item.page ? h("a", { class: "cvlink", href: item.page, target: "_blank", rel: "noopener noreferrer", "aria-label": "Abrir no Civitai" }, icon("external", "sm")) : null),
      h("div", { class: "cvbody" },
        item.creator ? h("div", { class: "cvby" }, item.avatar ? h("img", { src: item.avatar, alt: "", loading: "lazy" }) : h("i"), h("span", null, item.creator)) : null,
        h("h3", { title: item.title }, item.title),
        stats ? h("div", { class: "cvstats mono" },
          h("span", null, icon("download", "sm"), compact(stats.downloads)), h("span", null, icon("bookmark", "sm"), compact(stats.saves)),
          h("span", null, icon("comment", "sm"), compact(stats.comments)), h("span", { class: "likes" }, icon("thumb", "sm"), compact(stats.likes))) : null,
        action));
  }

  function paintCivitai(fresh) {
    if (fresh) clear(grid);
    const shown = cards.filter(c => !(hideAdult && c.adult));
    if (fresh) shown.forEach((c, i) => addCivitai(c, i));
  }
  function addCivitai(c, i) {
    const state = { installed: c.installed, busy: false, progress: "" };
    grid.append(card(c, i, { fam: family, state,
      install: async () => {
        state.busy = true; state.progress = "Enviando pedido…"; state.repaint();
        try {
          const job = await api.post("/civitai/install", { family, model: c.model, version: c.version, file: c.files[0].file });
          followers.push(api.follow(job.id, async snap => {
            if (!isFinal(snap.status)) { state.progress = snap.desc || "Baixando…"; state.repaint(); return; }
            state.busy = false;
            if (snap.status === "concluído") { state.installed = true; installed = await api.get("/loras").catch(() => installed); }
            else toast(snap.message || "Não foi possível baixar.", "err");
            state.repaint();
          }));
        } catch (error) { state.busy = false; state.repaint(); toast(error.message, "err"); }
      },
      use: () => {
        const found = installed.find(l => l.name.endsWith(`__cv${c.version}.safetensors`));
        if (!found) return toast("Atualize a página para ver a LoRA instalada.", "err");
        useLora(found.name, family);
      } }));
  }

  async function load(fresh) {
    if (loading) return;
    loading = true;
    if (fresh) { cards = []; cursor = null; clear(grid); more.hidden = true; for (let i = 0; i < 8; i++) grid.append(h("div", { class: "cvcard skeleton" })); }
    status.textContent = "";
    more.disabled = true;
    try {
      const params = new URLSearchParams({ family, sort, q: query });
      if (!fresh && cursor) params.set("cursor", cursor);
      const page = await api.get(`/civitai/loras?${params}`);
      if (fresh) clear(grid);
      const start = cards.length;
      cards.push(...page.items);
      page.items.filter(c => !(hideAdult && c.adult)).forEach((c, i) => addCivitai(c, start + i));
      cursor = page.next;
      more.hidden = !cursor;
      if (!cards.length) grid.append(h("div", { class: "empty" }, illustration("empty"), h("h3", null, "Nada encontrado"), h("p", null, "Tente outra busca ou outro modelo.")));
    } catch (error) {
      clear(grid);
      status.textContent = error.message;
      grid.append(h("div", { class: "empty" }, illustration("error"), h("h3", null, "Não deu para falar com o Civitai"), h("p", null, error.message),
        h("button", { class: "btn", type: "button", onclick: () => load(true) }, "Tentar de novo")));
    }
    loading = false; more.disabled = false;
  }

  function paintInstalled() {
    clear(grid); more.hidden = true;
    const mine = installed.filter(l => l.installed && (!l.families.length || l.families.includes(family)) && (l.label || "").toLowerCase().includes(query));
    mine.forEach((l, i) => grid.append(card({ title: l.label, creator: l.creator, cover: l.cover, page: l.page, badge: (l.families[0] || "").toUpperCase(), adult: false, name: l.name, stats: null },
      i, { state: { installed: true }, use: () => useLora(l.name, l.families[0] || family), install: () => {} })));
    if (!mine.length) grid.append(h("div", { class: "empty" }, illustration("empty"), h("h3", null, "Nenhuma LoRA instalada para este modelo"), h("p", null, "Baixe pela aba Civitai ou coloque arquivos .safetensors na pasta loras.")));
  }

  const refresh = () => (tab === "civitai" ? load(true) : paintInstalled());
  const search = h("input", { class: "input", type: "search", placeholder: "Buscar no Civitai…", "aria-label": "Buscar LoRA", onkeydown: e => { if (e.key === "Enter") { query = search.value.trim(); refresh(); } } });
  const adultToggle = h("label", { class: "switch inline" }, h("span", null, "Ocultar adulto"),
    h("input", { type: "checkbox", checked: hideAdult, onchange: e => { hideAdult = e.target.checked; setPref("cf-hide-adult", hideAdult ? "1" : "0"); if (tab === "civitai") { clear(grid); cards.filter(c => !(hideAdult && c.adult)).forEach((c, i) => addCivitai(c, i)); } } }));

  root.append(
    h("div", { class: "section-head" }, h("div", null, h("h2", null, "LoRAs"), h("p", null, "Estilos e personagens do Civitai, prontos para o seu modelo. Ajuste a força direto no app."))),
    h("div", { class: "libhead lora-head" },
      seg([{ value: "civitai", label: "Civitai" }, { value: "installed", label: "Instaladas" }], tab, v => { tab = v; search.placeholder = v === "civitai" ? "Buscar no Civitai…" : "Buscar nas instaladas…"; refresh(); }),
      dropdown(FAMILIES, family, v => { family = v; setPref("cf-lora-family", v); refresh(); }, { label: "Modelo" }),
      dropdown(SORTS, sort, v => { sort = v; if (tab === "civitai") load(true); }, { label: "Ordenar" }),
      search, adultToggle),
    status, grid, h("div", { class: "row center" }, more));
  load(true);
  return { el: root, destroy() { followers.forEach(f => f.stop()); } };
}
