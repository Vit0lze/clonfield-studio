// Ctrl/Cmd+K: jump anywhere. Pages, every app (favourites first) and each library category.
import { store } from "./api.js";
import { h, icon, clear, appGlyph } from "./ui.js";
import { isFav } from "./favs.js";

const PAGES = [["#/", "Início", "home"], ["#/chat", "Chat", "comment"], ["#/apps", "Todos os apps", "apps"], ["#/library", "Biblioteca", "cube"],
  ["#/library/lora", "Biblioteca · LoRAs", "layers"], ["#/library/upscaler", "Biblioteca · Upscalers", "upscale"], ["#/library/vae", "Biblioteca · VAEs", "cube"],
  ["#/library/encoder", "Biblioteca · Encoders de texto", "cube"], ["#/history", "Histórico", "clock"], ["#/jobs", "Fila", "clock"], ["#/system", "Sistema e benchmark", "cpu"]];

export function installPalette(navigate) {
  let overlay = null;
  async function open() {
    if (overlay) return;
    const apps = await store.loadApps().catch(() => []);
    const entries = [...PAGES.map(([hash, label, ic]) => ({ hash, label, ic, kind: "Ir para" })),
      ...[...apps].sort((a, b) => Number(isFav("app", b.id)) - Number(isFav("app", a.id))).map(a => ({ hash: `#/apps/${a.id}`, label: a.title, app: a.id, kind: isFav("app", a.id) ? "App ★" : "App", sub: a.tagline }))];
    let active = 0, shown = entries;
    const input = h("input", { class: "pal-input", type: "search", placeholder: "Para onde? Digite um app ou página…", "aria-label": "Busca rápida", oninput: () => { filter(); } });
    const list = h("div", { class: "pal-list", role: "listbox" });
    const close = () => { overlay.classList.add("out"); const gone = overlay; setTimeout(() => gone.remove(), 130); overlay = null; document.removeEventListener("keydown", onKey, true); };
    const go = entry => { close(); navigate(entry.hash); };
    function paint() {
      clear(list);
      shown.slice(0, 40).forEach((e, i) => list.append(h("button", { class: `pal-item${i === active ? " on" : ""}`, type: "button", role: "option", "aria-selected": String(i === active), onclick: () => go(e), onpointermove: () => { active = i; mark(); } },
        e.app ? appGlyph(e.app, "sm") : icon(e.ic, "sm"), h("span", { class: "pal-text" }, h("b", null, e.label), e.sub ? h("small", null, e.sub) : null), h("em", null, e.kind))));
      if (!shown.length) list.append(h("p", { class: "muted pad" }, "Nada encontrado."));
    }
    const mark = () => [...list.children].forEach((el, i) => { el.classList.toggle("on", i === active); el.setAttribute("aria-selected", String(i === active)); if (i === active) el.scrollIntoView({ block: "nearest" }); });
    function filter() { const q = input.value.trim().toLowerCase(); shown = q ? entries.filter(e => (e.label + " " + (e.sub || "")).toLowerCase().includes(q)) : entries; active = 0; paint(); }
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); close(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, Math.min(shown.length, 40) - 1); mark(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); mark(); }
      else if (e.key === "Enter" && shown[active]) { e.preventDefault(); go(shown[active]); }
    }
    overlay = h("div", { class: "pal-overlay", role: "dialog", "aria-modal": "true", "aria-label": "Busca rápida", onpointerdown: e => { if (e.target === overlay) close(); } },
      h("div", { class: "pal-box" }, input, list, h("p", { class: "pal-foot" }, "↑↓ navegar · Enter abrir · Esc fechar")));
    document.body.append(overlay);
    document.addEventListener("keydown", onKey, true);
    paint(); input.focus();
  }
  document.addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); overlay ? null : open(); }
  });
}
