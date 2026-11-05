// Tiny DOM helpers, an authored icon set, generative posters and the form controls shared by every view.
export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "style" && typeof value === "object") for (const [k, v] of Object.entries(value)) k.startsWith("--") ? el.style.setProperty(k, v) : (el.style[k] = v);
    else if (key.startsWith("on")) el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "value" || key === "checked" || key === "disabled" || key === "hidden") el[key] = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  append(el, kids);
  return el;
}
export function append(el, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
export const clear = el => { el.replaceChildren(); return el; };

const NS = "http://www.w3.org/2000/svg";
function svgFrom(markup, cls, viewBox = "0 0 24 24") {
  const wrap = document.createElement("div");
  wrap.innerHTML = `<svg xmlns="${NS}" viewBox="${viewBox}" aria-hidden="true">${markup}</svg>`;
  const el = wrap.firstChild;
  if (cls) el.setAttribute("class", cls);
  return el;
}

const ICONS = {
  home: '<path d="M4 11l8-7 8 7"/><path d="M6 10v9h12v-9"/><path d="M10 19v-5h4v5"/>',
  apps: '<rect x="4" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.6"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.6"/>',
  cube: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12L4 7.5M12 12v9"/>',
  layers: '<path d="M12 4l9 5-9 5-9-5z"/><path d="M3 14l9 5 9-5"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r=".9"/><circle cx="4.5" cy="12" r=".9"/><circle cx="4.5" cy="18" r=".9"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx=".8"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>',
  image: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.6"/><path d="M4 17l5-4.5 4 3.5 3-2.5 4.5 4"/>',
  video: '<rect x="3" y="6" width="13" height="12" rx="2.5"/><path d="M16 10.5l5-3v9l-5-3z"/>',
  user: '<circle cx="12" cy="8.5" r="3.6"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"/>',
  sparkle: '<path d="M11 3.5l1.9 5.1 5.1 1.9-5.1 1.9L11 17.5l-1.9-5.1L4 10.5l5.1-1.9z"/><path d="M18.5 16l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
  wand: '<path d="M5 19L16 8"/><path d="M14.5 6.5l3 3"/><path d="M18 3l.7 1.8 1.8.7-1.8.7L18 8l-.7-1.8-1.8-.7 1.8-.7z"/>',
  crop: '<path d="M7 3v14h14"/><path d="M3 7h14v14"/>',
  scissors: '<circle cx="6" cy="7" r="2.5"/><circle cx="6" cy="17" r="2.5"/><path d="M8 8.5L20 18M8 15.5L20 6"/>',
  film: '<rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M8 3.5v17M16 3.5v17M4 8h4M16 8h4M4 12h4M16 12h4M4 16h4M16 16h4"/>',
  upload: '<path d="M12 16V5"/><path d="M7.5 9.5L12 5l4.5 4.5"/><path d="M5 15v3.5A1.5 1.5 0 006.5 20h11a1.5 1.5 0 001.5-1.5V15"/>',
  download: '<path d="M12 5v11"/><path d="M7.5 11.5L12 16l4.5-4.5"/><path d="M5 19.5h14"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  play: '<path d="M8 5.5v13l11-6.5z"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  "chevron-right": '<path d="M9 6l6 6-6 6"/>',
  "chevron-left": '<path d="M15 6l-6 6 6 6"/>',
  "chevron-down": '<path d="M6 9l6 6 6-6"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>',
  alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/>',
  refresh: '<path d="M19 8a7.5 7.5 0 00-13-1.5L4 9"/><path d="M4 4v5h5"/><path d="M5 16a7.5 7.5 0 0013 1.5L20 15"/><path d="M20 20v-5h-5"/>',
  link: '<path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1"/>',
  external: '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v4.5a1.5 1.5 0 01-1.5 1.5h-11A1.5 1.5 0 014 18.5v-11A1.5 1.5 0 015.5 6H10"/>',
  sliders: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  "arrow-right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
  trash: '<path d="M5 7h14M10 7V4.5h4V7"/><path d="M6.5 7l1 12.5h9l1-12.5"/>',
  power: '<path d="M12 4v8"/><path d="M7 7a7.5 7.5 0 1010 0"/>',
  thumb: '<path d="M7 11v9H4v-9z"/><path d="M7 11l4-7c1.6 0 2.6 1.2 2.3 2.8L12.8 9H19a2 2 0 0 1 2 2.4l-1.3 6.4A2.6 2.6 0 0 1 17.2 20H7"/>',
  comment: '<path d="M4 5h16v11H9l-5 4z"/>',
  bookmark: '<path d="M6 4h12v16l-6-4-6 4z"/>',
  grip: '<circle cx="9" cy="6" r="1.2"/><circle cx="15" cy="6" r="1.2"/><circle cx="9" cy="12" r="1.2"/><circle cx="15" cy="12" r="1.2"/><circle cx="9" cy="18" r="1.2"/><circle cx="15" cy="18" r="1.2"/>',
  bulb: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1 2V16h5.2v-.2c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z"/>',
  bolt: '<path d="M13 3L5 13.5h6L10 21l8-10.5h-6z"/>',
  logo: '<rect x="3" y="3" width="30" height="30" rx="9" fill="none"/><circle cx="18" cy="18" r="7.5" fill="none"/><path d="M16 14.2v7.6l6.2-3.8z" fill="currentColor" stroke="none"/>'
};
const APP_ICONS = {
  create: '<path d="M12 3.5l1.9 5.1 5.1 1.9-5.1 1.9L12 17.5l-1.9-5.1L5 10.5l5.1-1.9z"/><path d="M5 18.5h4M7 16.5v4"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
  portrait: '<circle cx="12" cy="9" r="3.4"/><path d="M5.5 19.5c1-3.6 3.5-5.3 6.5-5.3s5.5 1.7 6.5 5.3"/>',
  region: '<rect x="4" y="4" width="16" height="16" rx="2.5" stroke-dasharray="3 3"/><circle cx="12" cy="12" r="3"/>',
  relight: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1 2V16h5.2v-.2c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z"/>',
  animate: '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M10 9.5l5 2.5-5 2.5z"/>',
  text2video: '<path d="M4 10h16v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><path d="M4 10l1.6-4.6 14.2 3.6-.6 1M9 6.7l-1.5 3M14 8l-1.5 2.4"/>',
  upscale: '<path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/>',
  seedvr2: '<path d="M12 20v-7"/><path d="M12 13c0-3.5-2.5-5.5-6-5.5 0 3.5 2.5 5.5 6 5.5zM12 11c0-3 2-5 5.5-5 0 3-2 5-5.5 5z"/>',
  look: '<circle cx="12" cy="12" r="8"/><path d="M12 4v16"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/>',
  frame: '<path d="M7 3v14h14M3 7h14v14"/>',
  clip: '<circle cx="6.5" cy="7" r="2.5"/><circle cx="6.5" cy="17" r="2.5"/><path d="M8.7 8.3L20 15M8.7 15.7L20 9"/>',
  still: '<rect x="3.5" y="7" width="17" height="12" rx="2.5"/><circle cx="12" cy="13" r="3.2"/><path d="M9 7l1.2-2h3.6L15 7"/>',
  board: '<rect x="3.5" y="5" width="7" height="6" rx="1.5"/><rect x="13.5" y="5" width="7" height="6" rx="1.5"/><rect x="3.5" y="13" width="7" height="6" rx="1.5"/><rect x="13.5" y="13" width="7" height="6" rx="1.5"/>',
  sequence: '<rect x="3" y="8" width="7.5" height="8" rx="2"/><rect x="13.5" y="8" width="7.5" height="8" rx="2"/><path d="M10.5 12h3"/>',
  compare: '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M12 5v14"/><path d="M9 10l-2 2 2 2M15 10l2 2-2 2"/>',
  openjutsu: '<circle cx="8" cy="8" r="2.5"/><circle cx="16" cy="16" r="2.5"/><path d="M13 7h6l-2-2M11 17H5l2 2"/>',
  workflow: '<circle cx="5.5" cy="7" r="2"/><circle cx="5.5" cy="17" r="2"/><circle cx="18.5" cy="12" r="2"/><path d="M7.5 7h2c3.5 0 3.5 5 7 5M7.5 17h2c3.5 0 3.5-5 7-5"/>',
  speedtest: '<path d="M4.5 16a8 8 0 1 1 15 0"/><path d="M12 14l4-4"/><circle cx="12" cy="14" r="1.2"/>'
};
// One tile for every app: same shape and weight everywhere (menu, gallery, app header), a different glyph for each app.
export function appGlyph(id, size = "") {
  const tile = h("span", { class: `glyph ${size}`.trim(), "aria-hidden": "true" });
  tile.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" class="icon">${APP_ICONS[id] || ICONS.cube}</svg>`;
  return tile;
}

export function icon(name, cls = "") {
  if (name === "logo") return svgFrom(ICONS.logo, `icon ${cls}`, "0 0 36 36");
  return svgFrom(ICONS[name] || ICONS.cube, `icon ${cls}`);
}

// ----- generative posters: deterministic art for models and LoRAs that have no cover -----
let posterCount = 0;
function seeded(text) {
  let a = 2166136261;
  for (const c of text) a = Math.imul(a ^ c.charCodeAt(0), 16777619);
  return () => ((a = Math.imul(a ^ (a >>> 15), 2246822507) ^ Math.imul(a ^ (a >>> 13), 3266489909)) >>> 0) / 4294967296;
}
export function poster(id) {
  const rnd = seeded(id), n = ++posterCount;
  const hue = Math.round(348 + rnd() * 30) % 360;
  const shapes = [];
  const count = 3 + Math.floor(rnd() * 3);
  for (let i = 0; i < count; i++) {
    const cx = Math.round(rnd() * 100), cy = Math.round(rnd() * 100), r = Math.round(18 + rnd() * 44);
    const light = Math.round(28 + rnd() * 32), alpha = (0.3 + rnd() * 0.5).toFixed(2);
    shapes.push(i % 3 === 0
      ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="hsl(${hue + i * 6} 80% ${light}%)" opacity="${alpha}" filter="url(#b${n})"/>`
      : i % 3 === 1
        ? `<path d="M${-10} ${cy} C ${30} ${cy - r} ${70} ${cy + r} ${110} ${cy}" fill="none" stroke="hsl(${hue} 90% ${light + 22}%)" stroke-width="${(0.3 + rnd()).toFixed(2)}" opacity="${alpha}"/>`
        : `<ellipse cx="${cx}" cy="${cy}" rx="${r}" ry="${Math.round(r / 3)}" fill="none" stroke="hsl(${hue} 90% ${light + 20}%)" stroke-width=".4" opacity="${alpha}" transform="rotate(${Math.round(rnd() * 180)} ${cx} ${cy})"/>`);
  }
  const lines = Array.from({ length: 6 }, (_, i) => `<path d="M${i * 20 - 10} 0 L${i * 20 + 30} 100" stroke="hsl(${hue} 70% 55%)" stroke-width=".18" opacity=".25"/>`).join("");
  return svgFrom(`<defs><linearGradient id="g${n}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="hsl(${hue} 55% 15%)"/><stop offset="1" stop-color="hsl(${hue + 8} 60% 6%)"/></linearGradient>
    <filter id="b${n}" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="9"/></filter></defs>
    <rect width="100" height="100" fill="url(#g${n})"/>${lines}${shapes.join("")}`, "poster", "0 0 100 100");
}
export function posterEl(id) { const el = poster(id); el.setAttribute("preserveAspectRatio", "xMidYMid slice"); return el; }

const APP_ART = { image: "app-image", video: "app-video", identity: "app-identity", upscale: "app-upscale" };
const ART_BY_ID = { relight: "app-image", text2video: "model-wan", portrait: "app-identity", seedvr2: "model-flux" };
const MODEL_ART = { qwen21: "model-qwen21", flux2: "model-flux2", flux3: "model-flux3", krea2: "model-krea2", "krea2-turbo": "model-krea2-turbo", "z-image": "model-zimage", "z-image-turbo": "model-zimage-turbo" };
export function artFor(kind, id, art) {
  const file = kind === "model" ? MODEL_ART[id] : (ART_BY_ID[id] || APP_ART[art]);
  if (kind === "model") {
    let mine = null;
    try { mine = localStorage.getItem(`cf-cover-${id}`); } catch { /* private mode */ }
    if (mine) return h("img", { src: mine, alt: "", loading: "lazy", decoding: "async", class: "mine" });
  }
  if (!file) return posterEl(kind + id);
  return h("img", { src: `./assets/art/${file}.webp`, alt: "", loading: "lazy", decoding: "async" });
}

// ----- illustrations for empty / idle / error states -----
export function illustration(kind) {
  const beam = '<path d="M62 70 L170 28 L170 112 Z" fill="url(#beam)" opacity=".9"/>';
  const reel = (x, y, r) => `<circle cx="${x}" cy="${y}" r="${r}" fill="none" stroke="#e2343f" stroke-width="2"/><circle cx="${x}" cy="${y}" r="${r * 0.28}" fill="#e2343f"/>` +
    [0, 60, 120, 180, 240, 300].map(a => `<circle cx="${x + Math.cos(a * Math.PI / 180) * r * 0.62}" cy="${y + Math.sin(a * Math.PI / 180) * r * 0.62}" r="${r * 0.14}" fill="#0b0708" stroke="#e2343f" stroke-width="1.2"/>`).join("");
  const defs = '<defs><linearGradient id="beam" x1="0" x2="1"><stop offset="0" stop-color="#ff5a65" stop-opacity=".55"/><stop offset="1" stop-color="#ff5a65" stop-opacity="0"/></linearGradient></defs>';
  const bodies = {
    idle: `${defs}${beam}<rect x="20" y="58" width="52" height="34" rx="8" fill="#1d1013" stroke="#e2343f" stroke-width="2"/><circle cx="62" cy="75" r="9" fill="#0b0708" stroke="#ff5a65" stroke-width="2"/>${reel(36, 42, 17)}${reel(66, 38, 13)}<rect x="176" y="22" width="4" height="96" rx="2" fill="#43303a"/>`,
    empty: `${defs}<rect x="40" y="30" width="120" height="80" rx="10" fill="#130d0f" stroke="#43303a" stroke-width="2" stroke-dasharray="6 6"/><path d="M70 82l22-24 18 18 12-12 18 18" fill="none" stroke="#e2343f" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="82" cy="50" r="6" fill="#e2343f"/>`,
    error: `${defs}<circle cx="100" cy="70" r="42" fill="#1d1013" stroke="#ff6b6b" stroke-width="2"/><path d="M100 48v26" stroke="#ff6b6b" stroke-width="4" stroke-linecap="round"/><circle cx="100" cy="90" r="3.4" fill="#ff6b6b"/>`
  };
  return svgFrom(bodies[kind] || bodies.idle, "ill", "0 0 200 140");
}

// ----- toasts -----
export function toast(message, kind = "ok", ms = 4200) {
  let box = document.querySelector(".toasts");
  if (!box) { box = h("div", { class: "toasts", role: "status", "aria-live": "polite" }); document.body.append(box); }
  const node = h("div", { class: `toast ${kind}` }, icon(kind === "err" ? "alert" : "check", "sm"), h("span", null, message));
  box.append(node);
  const close = () => { node.classList.add("out"); setTimeout(() => node.remove(), 200); };
  setTimeout(close, kind === "err" ? Math.max(ms, 7000) : ms);
  node.addEventListener("click", close);
}

// ----- formatting -----
export const fmtBytes = n => n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`;
export function fmtClock(seconds) {
  seconds = Math.max(0, Math.floor(seconds));
  const m = String(Math.floor(seconds / 60)).padStart(2, "0"), s = String(seconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}
export const ago = t => {
  const s = Date.now() / 1000 - t;
  return s < 60 ? "agora" : s < 3600 ? `${Math.floor(s / 60)} min` : s < 86400 ? `${Math.floor(s / 3600)} h` : `${Math.floor(s / 86400)} d`;
};

// ----- shared form controls -----
let fieldCount = 0;
export function field(label, control, hint, extra) {
  const id = `f${++fieldCount}`;
  const target = control.matches?.("input,textarea,select") ? control : control.querySelector?.("input:not([type=file]),textarea,select");
  if (target) target.id = id;
  const tag = target ? h("label", { for: id }, h("span", null, label), extra) : h("div", { class: "label" }, h("span", null, label), extra);
  if (!target) control.setAttribute("aria-label", label);
  return h("div", { class: "field" }, tag, control, hint ? h("div", { class: "hint" }, hint) : null);
}

export function ratioGlyph([w, hgt]) {
  const glyph = h("i", { class: `ar${w ? "" : " auto"}`, "aria-hidden": "true" });
  const ratio = w ? w / hgt : 1;
  glyph.style.width = `${ratio >= 1 ? 16 : 16 * ratio}px`;
  glyph.style.height = `${ratio >= 1 ? 16 / ratio : 16}px`;
  return glyph;
}

export function seg(options, value, onChange) {
  const box = h("div", { class: "seg", role: "group" });
  const paint = () => [...box.children].forEach((b, i) => b.setAttribute("aria-pressed", String(options[i].value === value)));
  options.forEach(o => box.append(h("button", {
    type: "button", disabled: o.disabled, title: o.reason || o.hint || "", "aria-pressed": "false",
    onclick: () => { value = o.value; paint(); onChange(value); }
  }, o.ratio ? ratioGlyph(o.ratio) : null, o.label, o.hint && o.label.length < 12 ? h("small", null, o.hint) : null)));
  paint();
  return box;
}

// Button that opens a menu of actions (same popover look as the dropdown).
export function actionMenu({ label, iconName = "external", items, cls = "btn sm" }) {
  const button = h("button", { type: "button", class: cls, "aria-haspopup": "menu", "aria-expanded": "false" }, icon(iconName, "sm"), label, icon("chevron-down", "sm"));
  let pop = null;
  const close = (focus = true) => {
    if (!pop) return;
    pop.classList.add("out"); const gone = pop; setTimeout(() => gone.remove(), 120); pop = null;
    document.removeEventListener("pointerdown", outside, true); window.removeEventListener("resize", close); window.removeEventListener("scroll", onScroll, true);
    button.setAttribute("aria-expanded", "false"); if (focus) button.focus();
  };
  const outside = e => { if (pop && !pop.contains(e.target) && !button.contains(e.target)) close(false); };
  const onScroll = e => { if (pop && !pop.contains(e.target)) close(false); };
  button.addEventListener("click", () => {
    if (pop) return close();
    pop = h("div", { class: "dd-pop menu", role: "menu" }, items.map(item => h("button", { type: "button", class: "dd-opt", role: "menuitem",
      onclick: () => { close(false); item.onclick(); } }, appGlyph(item.app, "sm"), h("span", { class: "dd-text" }, h("b", null, item.label), item.hint ? h("small", null, item.hint) : null))));
    document.body.append(pop);
    const rect = button.getBoundingClientRect(), room = window.innerHeight - rect.bottom - 12, above = rect.top - 12, up = room < 280 && above > room;
    pop.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 300))}px`;
    pop.style.minWidth = "280px"; pop.style.maxHeight = `${Math.min(420, up ? above : room)}px`;
    if (up) { pop.style.bottom = `${window.innerHeight - rect.top + 6}px`; pop.classList.add("up"); } else pop.style.top = `${rect.bottom + 6}px`;
    button.setAttribute("aria-expanded", "true");
    document.addEventListener("pointerdown", outside, true); window.addEventListener("resize", close); window.addEventListener("scroll", onScroll, true);
    pop.querySelector(".dd-opt")?.focus();
  });
  button.addEventListener("keydown", e => { if (e.key === "Escape") close(); });
  return button;
}

// Dropdown for every "pick one" field: glyph, label, hint, optional groups, keyboard and screen-reader support.
export function dropdown(options, value, onChange, { label = "" } = {}) {
  const chevron = icon("chevron-down", "sm");
  const current = () => options.find(o => o.value === value) || options[0];
  const face = h("span", { class: "dd-face" });
  const button = h("button", { type: "button", class: "dd-btn", "aria-haspopup": "listbox", "aria-expanded": "false", "aria-label": label }, face, chevron);
  const root = h("div", { class: "dd" }, button);
  let pop = null, active = -1;

  const row = o => [o.ratio ? ratioGlyph(o.ratio) : null, h("span", { class: "dd-text" }, h("b", null, o.label), o.hint ? h("small", null, o.hint) : null)];
  const paintFace = () => { clear(face); face.append(...row(current()).filter(Boolean)); };

  function close(focus = true) {
    if (!pop) return;
    pop.classList.add("out");
    const gone = pop;
    setTimeout(() => gone.remove(), 120);
    pop = null;
    document.removeEventListener("pointerdown", outside, true);
    window.removeEventListener("resize", close);
    window.removeEventListener("scroll", onScroll, true);
    button.setAttribute("aria-expanded", "false");
    if (focus) button.focus();
  }
  function onScroll(e) { if (pop && !pop.contains(e.target)) close(false); }
  function outside(e) { if (pop && !pop.contains(e.target) && !root.contains(e.target)) close(false); }
  function choose(o) {
    if (o.disabled) return;
    value = o.value; paintFace(); close(); onChange(value);
  }
  function mark(index) {
    active = index;
    [...pop.querySelectorAll("[role=option]")].forEach((el, i) => { el.classList.toggle("act", i === index); if (i === index) el.scrollIntoView({ block: "nearest" }); });
  }
  function open() {
    if (pop) return close();
    pop = h("div", { class: "dd-pop", role: "listbox", tabindex: "-1", "aria-label": label });
    let lastGroup = null;
    options.forEach((o, i) => {
      if (o.group && o.group !== lastGroup) { pop.append(h("div", { class: "dd-group", role: "presentation" }, o.group)); lastGroup = o.group; }
      pop.append(h("button", { type: "button", class: `dd-opt${o.value === value ? " sel" : ""}`, role: "option", "aria-selected": String(o.value === value), disabled: o.disabled, title: o.reason || "",
        onclick: () => choose(o), onpointermove: () => mark(i) }, ...row(o), o.value === value ? icon("check", "sm") : null));
    });
    document.body.append(pop);
    const rect = button.getBoundingClientRect();
    const room = window.innerHeight - rect.bottom - 12, above = rect.top - 12;
    const up = room < 260 && above > room;
    pop.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - Math.max(rect.width, 280) - 8))}px`;
    pop.style.minWidth = `${rect.width}px`;
    pop.style.maxHeight = `${Math.min(380, up ? above : room)}px`;
    if (up) { pop.style.bottom = `${window.innerHeight - rect.top + 6}px`; pop.classList.add("up"); } else pop.style.top = `${rect.bottom + 6}px`;
    button.setAttribute("aria-expanded", "true");
    mark(Math.max(0, options.findIndex(o => o.value === value)));
    document.addEventListener("pointerdown", outside, true);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", onScroll, true);
  }
  const step = d => {
    let i = active;
    do { i = (i + d + options.length) % options.length; } while (options[i].disabled && i !== active);
    mark(i);
  };
  button.addEventListener("click", open);
  button.addEventListener("keydown", e => {
    if (!pop && (e.key === "ArrowDown" || e.key === "ArrowUp")) { e.preventDefault(); open(); return; }
    if (!pop) return;
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); step(-1); }
    else if (e.key === "Home") { e.preventDefault(); mark(0); }
    else if (e.key === "End") { e.preventDefault(); mark(options.length - 1); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(options[active]); }
    else if (e.key === "Tab") close(false);
  });
  paintFace();
  return root;
}

export function slider(f, value, onChange) {
  const input = h("input", { type: "range", min: f.min, max: f.max, step: f.step || 1, value });
  const out = h("output", null);
  const paint = () => {
    const v = Number(input.value);
    input.style.setProperty("--pct", `${((v - f.min) / (f.max - f.min)) * 100}%`);
    out.textContent = f.zero_label && v === 0 ? f.zero_label : (Number.isInteger(f.step || 1) ? v : v.toFixed(2).replace(/0$/, ""));
  };
  input.addEventListener("input", () => { paint(); onChange(Number(input.value)); });
  input.addEventListener("dblclick", () => { input.value = f.default ?? f.min; paint(); onChange(Number(input.value)); });
  paint();
  return h("div", { class: "range" }, input, out);
}

export function switchRow(label, value, onChange) {
  const box = h("input", { type: "checkbox", checked: !!value, onchange: () => onChange(box.checked) });
  return h("label", { class: "switch" }, h("span", null, label), box);
}

// Remember the latest result of each model as its cover (a small JPEG kept in this browser only).
export function rememberCover(modelKey, url) {
  if (!modelKey || !url) return;
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.onload = () => {
    try {
      const scale = Math.min(1, 480 / Math.max(img.naturalWidth, img.naturalHeight));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.naturalWidth * scale); canvas.height = Math.round(img.naturalHeight * scale);
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      localStorage.setItem(`cf-cover-${modelKey}`, canvas.toDataURL("image/jpeg", 0.8));
    } catch { /* tainted canvas or storage full: keep the authored cover */ }
  };
  img.src = url;
}
export function forgetCover(modelKey) { try { localStorage.removeItem(`cf-cover-${modelKey}`); } catch { /* ignore */ } }
