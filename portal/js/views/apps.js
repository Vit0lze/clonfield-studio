import { store } from "../api.js";
import { h, icon, seg, artFor, appGlyph } from "../ui.js";

export function appTile(app, i = 0, wide = false) {
  return h("a", { class: `tile${wide ? " wide" : ""}${app.blocked ? " blocked" : ""}`, href: `#/apps/${app.id}`, style: { "--i": i } },
    h("div", { class: "art" }, artFor("app", app.id, app.art)),
    h("div", { class: "corner" }, appGlyph(app.id, "sm"), h("span", { class: "badge" }, app.group), app.blocked ? h("span", { class: "badge warn" }, `≥ ${app.min_vram} GB`) : null),
    h("div", { class: "copy" }, h("h3", null, app.title), h("p", null, app.tagline)));
}

export async function appsView() {
  const root = h("div", { class: "view" });
  const apps = await store.loadApps();
  const groups = ["Todos", ...new Set(apps.map(a => a.group))];
  let group = "Todos", query = "";
  const grid = h("div", { class: "mosaic" });
  const paint = () => {
    grid.replaceChildren();
    const shown = apps.filter(a => (group === "Todos" || a.group === group) && (a.title + a.tagline).toLowerCase().includes(query));
    shown.forEach((a, i) => grid.append(appTile(a, i, shown.length > 6 && i % 7 === 0)));
    if (!shown.length) grid.append(h("div", { class: "empty" }, h("h3", null, "Nada por aqui"), h("p", null, "Tente outro termo ou categoria.")));
  };
  const search = h("input", { class: "input", type: "search", placeholder: "Buscar app…", "aria-label": "Buscar app", style: { maxWidth: "260px" }, oninput: () => { query = search.value.toLowerCase(); paint(); } });
  root.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Apps"), h("p", null, `${apps.length} ferramentas para imagem, vídeo e acabamento.`))),
    h("div", { class: "libhead" }, seg(groups.map(g => ({ value: g, label: g })), group, v => { group = v; paint(); }), search), grid);
  paint();
  return { el: root };
}
