// Library: ONE page for every kind of component, with the same three views (Recomendados / Instalados / Explorar) and the same card.
import { api } from "../api.js";
import { h, icon, clear, seg, dropdown, illustration } from "../ui.js";
import { favFirst, onFavs, starButton } from "../favs.js";
import { catalogCard } from "../catalog.js";

const pref = (key, fallback) => { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } };
const setPref = (key, value) => { try { localStorage.setItem(key, value); } catch { /* private mode */ } };
const VIEW_LABEL = { recommended: "Recomendados", installed: "Instalados", explore: "Explorar" };
const SOURCE_LABEL = { civitai: "CivitAI", huggingface: "Hugging Face", worker: "No worker", embutido: "Já no Studio" };

export async function libraryView(navigate, wanted) {
  const root = h("div", { class: "view" });
  const [categories, families] = await Promise.all([api.get("/library/categories"), api.get("/lora-families").catch(() => [])]);
  let kind = categories.some(c => c.id === wanted) ? wanted : pref("cf-lib-kind", "model");
  let view = pref("cf-lib-view", "recommended"), family = pref("cf-lib-family", "qwen21"), source = pref("cf-lib-source", "civitai");
  let query = "", cursor = null, loading = false, serial = 0, items = [];
  let hideAdult = pref("cf-hide-adult", "0") === "1";
  const category = () => categories.find(c => c.id === kind);

  const grid = h("div", { class: "ccgrid" });
  const status = h("p", { class: "hint", role: "status" });
  const more = h("button", { class: "btn", type: "button", hidden: true, onclick: () => load(false) }, "Carregar mais");
  const head = h("div");
  const bar = h("div", { class: "libhead explore-bar" });

  const familyOptions = () => favFirst(families, "model", f => `receita:${f.key}`).map(f => ({ value: f.key, label: f.title, hint: f.tagline,
    badge: f.installed ? "modelo instalado" : null, installed: f.installed, fav: () => starButton("model", `receita:${f.key}`, { title: f.title }) }));

  function paintBar() {
    clear(bar);
    const c = category();
    bar.append(seg(c.views.map(v => ({ value: v, label: VIEW_LABEL[v] })), view, v => { view = v; setPref("cf-lib-view", v); paintBar(); load(true); }));
    if (view === "explore") {
      if (c.family_filter) bar.append(dropdown(familyOptions(), family, v => { family = v; setPref("cf-lib-family", v); load(true); }, { label: "Compatível com o modelo" }));
      const sources = c.id === "upscaler" ? ["embutido", ...c.sources.filter(s => s !== "worker")] : c.sources;
      if (!sources.includes(source)) source = sources[0];
      if (sources.length > 1) bar.append(seg(sources.map(s => ({ value: s, label: SOURCE_LABEL[s] || s })), source, v => { source = v; setPref("cf-lib-source", v); load(true); }));
    }
    let typing;
    bar.append(h("input", { class: "input", type: "search", placeholder: "Buscar…", "aria-label": "Buscar", value: query,
      oninput: e => { clearTimeout(typing); typing = setTimeout(() => { query = e.target.value.trim(); load(true); }, 400); } }));
    if (view === "explore" && ["model", "lora", "vae", "encoder", "upscaler"].includes(kind)) {
      bar.append(h("label", { class: "switch inline" }, h("span", null, "Ocultar adulto"),
        h("input", { type: "checkbox", checked: hideAdult, onchange: e => { hideAdult = e.target.checked; setPref("cf-hide-adult", hideAdult ? "1" : "0"); paintGrid(); } })));
    }
  }

  function paintHead() {
    clear(head);
    head.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Biblioteca"), h("p", null, category().hint + ". Tudo aqui segue o mesmo formato: o que é, de onde vem, quanto pesa e o que você pode fazer."))),
      h("div", { class: "libhead" }, seg(categories.map(c => ({ value: c.id, label: c.title })), kind, v => { kind = v; setPref("cf-lib-kind", v); query = ""; source = "civitai"; view = category().views.includes(view) ? view : "recommended"; paintHead(); paintBar(); load(true); })));
  }

  function paintGrid() {
    clear(grid);
    const shown = favFirst(items.filter(i => !(hideAdult && i.adult)), kind, i => i.favorite.id);
    const ordered = shown;
    ordered.forEach(i => grid.append(catalogCard(i, { navigate, onChange: () => load(true) })));
    if (!ordered.length && !loading) grid.append(h("div", { class: "empty" }, illustration("empty"), h("h3", null, emptyTitle()), h("p", null, emptyBody())));
  }
  const emptyTitle = () => view === "installed" ? `Nenhum item instalado em ${category().title}` : view === "explore" ? "Nada encontrado" : "Nada recomendado aqui ainda";
  const emptyBody = () => view === "installed" ? "Instale algo em Recomendados ou Explorar. Arquivos já na pasta de modelos do worker também aparecem aqui."
    : view === "explore" ? "Tente outro termo, outra fonte ou outro modelo compatível. A fonte «No worker» só lista o que já está na pasta do ComfyUI." : "Use Explorar para buscar no CivitAI e no Hugging Face.";

  async function load(fresh) {
    if (loading && !fresh) return;
    const mine = ++serial;
    loading = true;
    if (fresh) { items = []; cursor = null; clear(grid); more.hidden = true; for (let i = 0; i < 6; i++) grid.append(h("div", { class: "ccard skeleton" })); }
    status.textContent = ""; more.disabled = true;
    try {
      const params = new URLSearchParams({ kind, view, family, source, q: query });
      if (!fresh && cursor) params.set("cursor", cursor);
      const out = await api.get(`/library?${params}`);
      if (mine !== serial) return;
      items = fresh ? out.items : [...items, ...out.items];
      cursor = out.next || null;
      more.hidden = !cursor;
    } catch (error) {
      if (mine !== serial) return;
      items = []; clear(grid);
      grid.append(h("div", { class: "empty" }, illustration("error"), h("h3", null, "Não deu para carregar"), h("p", null, error.message),
        h("button", { class: "btn", type: "button", onclick: () => load(true) }, "Tentar de novo")));
      loading = false; more.disabled = false; return;
    }
    loading = false; more.disabled = false;
    paintGrid();
  }

  root.append(head, bar, status, grid, h("div", { class: "row center" }, more));
  paintHead(); paintBar(); load(true);
  const off = onFavs(() => paintGrid());
  return { el: root, destroy: off };
}
