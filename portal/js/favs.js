// Favourites: the yellow star. Not the red ★ of default compatibility. Stored on the server, mirrored here for instant UI.
import { api } from "./api.js";
import { h, icon, toast } from "./ui.js";

export const favs = { items: [] };
const listeners = new Set();
/** Subscribe to favourite changes (views re-sort themselves). Returns the unsubscribe function. */
export const onFavs = fn => { listeners.add(fn); return () => listeners.delete(fn); };
const notify = () => listeners.forEach(fn => { try { fn(); } catch { /* a view that is gone */ } });
export async function loadFavs() { favs.items = await api.get("/favorites").catch(() => []); }
export const keyOf = (kind, id) => `${kind}|${id}`;
export const isFav = (kind, id) => favs.items.some(i => i.kind === kind && i.id === id);
export const ofKind = kind => favs.items.filter(i => i.kind === kind);
/** Stable sort: favourites first, everything else keeps its order. */
export const favFirst = (list, kind, idOf) => [...list].sort((a, b) => Number(isFav(kind, idOf(b))) - Number(isFav(kind, idOf(a))));

function paintAll(kind, id, on) {
  document.querySelectorAll(`button.fav-star[data-fav="${CSS.escape(keyOf(kind, id))}"]`).forEach(b => {
    b.setAttribute("aria-pressed", String(on));
    b.title = on ? "Remover dos favoritos" : "Favoritar";
    b.setAttribute("aria-label", b.title);
  });
}

export async function toggleFav(kind, id, meta = {}) {
  const was = isFav(kind, id);
  // optimistic: the star flips at once, then the server confirms (or we roll back)
  favs.items = was ? favs.items.filter(i => !(i.kind === kind && i.id === id)) : [...favs.items, { kind, id, meta, time: Date.now() / 1000 }];
  paintAll(kind, id, !was);
  try {
    const result = await api.post("/favorites/toggle", { kind, id, meta });
    if (result.favorite !== !was) { await loadFavs(); paintAll(kind, id, isFav(kind, id)); }
    notify();
  } catch (error) {
    favs.items = was ? [...favs.items, { kind, id, meta, time: Date.now() / 1000 }] : favs.items.filter(i => !(i.kind === kind && i.id === id));
    paintAll(kind, id, was);
    toast(error.message || "Não foi possível salvar o favorito.", "err");
  }
}

export function starButton(kind, id, meta = {}, { cls = "" } = {}) {
  const on = isFav(kind, id);
  return h("button", { class: `fav-star ${cls}`.trim(), type: "button", "data-fav": keyOf(kind, id), "aria-pressed": String(on),
    title: on ? "Remover dos favoritos" : "Favoritar", "aria-label": on ? "Remover dos favoritos" : "Favoritar",
    onclick: e => { e.preventDefault(); e.stopPropagation(); toggleFav(kind, id, meta); } }, icon("star", "sm"));
}
