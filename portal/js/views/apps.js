import { store } from "../api.js";
import { h, icon, seg, artFor, appGlyph } from "../ui.js";
import { favFirst, isFav, onFavs, starButton } from "../favs.js";

export function appTile(app, i = 0, wide = false) {
  const tile = appTileLink(app, i, wide);
  return h("div", { class: `tile-wrap${wide ? " wide" : ""}` }, tile, starButton("app", app.id, { title: app.title }));
}

function appTileLink(app, i = 0, wide = false) {
  return h("a", { class: `tile${wide ? " wide" : ""}${app.blocked ? " blocked" : ""}`, href: `#/apps/${app.id}`, style: { "--i": i } },
    h("div", { class: "art" }, artFor("app", app.id, app.art)),
    h("div", { class: "corner" }, appGlyph(app.id, "sm"), h("span", { class: "badge" }, app.group), app.blocked ? h("span", { class: "badge warn" }, `≥ ${app.min_vram} GB`) : null),
    h("div", { class: "copy" }, h("h3", null, app.title), h("p", null, app.tagline)));
}

export async function appsView() {
  const root = h("div", { class: "view" });
  const apps = await store.loadApps();
  const groups = ["Todos", "Favoritos", ...new Set(apps.map(a => a.group))];
  let group = "Todos", query = "";
  const grid = h("div", { class: "mosaic" });
  const paint = () => {
    grid.replaceChildren();
    const shown = favFirst(apps, "app", a => a.id).filter(a => (group === "Todos" || (group === "Favoritos" ? isFav("app", a.id) : a.group === group)) && (a.title + a.tagline).toLowerCase().includes(query));
    shown.forEach((a, i) => grid.append(appTile(a, i, shown.length > 6 && i % 7 === 0)));
    if (!shown.length) grid.append(h("div", { class: "empty" }, h("h3", null, group === "Favoritos" ? "Nenhum app favorito ainda" : "Nada por aqui"),
      h("p", null, group === "Favoritos" ? "Toque na estrela de um app para fixá-lo aqui e no topo da lista." : "Tente outro termo ou categoria.")));
  };
  const search = h("input", { class: "input", type: "search", placeholder: "Buscar app…", "aria-label": "Buscar app", style: { maxWidth: "260px" }, oninput: () => { query = search.value.toLowerCase(); paint(); } });
  root.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Apps"), h("p", null, `${apps.length} ferramentas para imagem, vídeo e acabamento.`)), h("a", { class: "btn", href: "#/capabilities" }, icon("cube", "sm"), "Capacidades")),
    h("div", { class: "libhead" }, seg(groups.map(g => ({ value: g, label: g })), group, v => { group = v; paint(); }), search), grid);
  paint();
  const off = onFavs(paint);
  return { el: root, destroy: off };
}
