import { h, icon, clear, slider } from "./ui.js";

const KINDS = [
  { value: "point", label: "Pontual", hint: "lâmpada, vela, neon" },
  { value: "softbox", label: "Softbox", hint: "luz grande e macia" },
  { value: "rim", label: "Contorno", hint: "recorta o assunto" },
  { value: "spot", label: "Spot", hint: "feixe focado" },
];
const SWATCHES = ["#ff9a4d", "#ffd7a1", "#ffffff", "#7cc4ff", "#8a7bff", "#ff4fa3", "#e2343f", "#5dffb0"];
const MAX = 8;

// Light editor: drag orbs over the photo (x, y), set depth with the slider or the wheel, tune colour and
// strength. The glow on the photo is only a preview; the model does the real relighting.
export function lightEditor({ lights, getImage, onChange, max = MAX }) {
  let selected = lights.length ? 0 : -1;
  let dragging = null;

  const img = h("img", { alt: "", draggable: "false" });
  const empty = h("div", { class: "lempty" }, icon("bulb"), h("b", null, "Envie a imagem base"), h("span", null, "As luzes aparecem sobre ela."));
  const glows = h("div", { class: "lglows" });
  const orbs = h("div", { class: "lorbs" });
  const surface = h("div", { class: "lsurface" }, img, glows, orbs);
  const stage = h("div", { class: "lstage" }, empty, surface);
  const inspector = h("div", { class: "linspect" });
  const list = h("div", { class: "llist", role: "tablist" });
  const adders = h("div", { class: "ladd" });

  const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
  const emit = () => onChange(lights);

  function paintGlows() {
    clear(glows);
    lights.forEach((l, i) => {
      const size = 28 + (l.size ?? 50) * 0.9;
      const glow = h("i", { class: `lglow${l.kind === "rim" ? " rim" : ""}${l.kind === "spot" ? " spot" : ""}` });
      glow.style.left = `${l.x * 100}%`;
      glow.style.top = `${l.y * 100}%`;
      glow.style.width = glow.style.height = `${size}%`;
      glow.style.setProperty("--c", l.color);
      glow.style.opacity = String(0.15 + (l.intensity / 100) * 0.8);
      glows.append(glow);
    });
  }

  function orbEl(l, i) {
    const scale = 0.72 + l.z * 0.7;
    const orb = h("button", { type: "button", class: `lorb${i === selected ? " on" : ""}`, role: "tab", "aria-selected": String(i === selected),
      "aria-label": `Luz ${i + 1}: arraste para mover, setas ajustam, roda do mouse muda a profundidade` });
    orb.style.left = `${l.x * 100}%`;
    orb.style.top = `${l.y * 100}%`;
    orb.style.setProperty("--c", l.color);
    orb.style.setProperty("--s", String(scale));
    orb.append(h("span", null, i + 1));
    orb.addEventListener("pointerdown", e => {
      e.preventDefault();
      orb.setPointerCapture(e.pointerId);
      dragging = { i, rect: surface.getBoundingClientRect() };
      select(i, false);
      orb.classList.add("drag");
    });
    orb.addEventListener("pointermove", e => {
      if (!dragging || dragging.i !== i) return;
      l.x = clamp((e.clientX - dragging.rect.left) / dragging.rect.width);
      l.y = clamp((e.clientY - dragging.rect.top) / dragging.rect.height);
      orb.style.left = `${l.x * 100}%`;
      orb.style.top = `${l.y * 100}%`;
      paintGlows();
    });
    const end = () => { if (dragging?.i === i) { dragging = null; orb.classList.remove("drag"); emit(); } };
    orb.addEventListener("pointerup", end);
    orb.addEventListener("pointercancel", end);
    orb.addEventListener("wheel", e => {
      e.preventDefault();
      l.z = clamp(l.z - Math.sign(e.deltaY) * 0.05);
      paint(); emit();
    }, { passive: false });
    orb.addEventListener("keydown", e => {
      const step = e.shiftKey ? 0.05 : 0.01;
      const move = { ArrowLeft: ["x", -step], ArrowRight: ["x", step], ArrowUp: ["y", -step], ArrowDown: ["y", step] }[e.key];
      if (move) { e.preventDefault(); l[move[0]] = clamp(l[move[0]] + move[1]); paint(); emit(); orbs.children[i]?.focus(); }
      if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); remove(i); }
    });
    return orb;
  }

  function select(i, repaint = true) {
    selected = i;
    if (repaint) paint(); else { paintList(); paintInspector(); [...orbs.children].forEach((o, n) => { o.classList.toggle("on", n === i); o.setAttribute("aria-selected", String(n === i)); }); }
  }

  function add(kind) {
    if (lights.length >= max) return;
    const n = lights.length;
    lights.push({ x: [0.22, 0.78, 0.5, 0.15, 0.85, 0.5, 0.3, 0.7][n % 8], y: [0.25, 0.3, 0.12, 0.65, 0.7, 0.85, 0.5, 0.5][n % 8], z: kind === "rim" ? 0.1 : 0.7,
      color: SWATCHES[n % 3], intensity: 70, size: kind === "softbox" ? 75 : kind === "spot" ? 25 : 45, kind });
    selected = lights.length - 1;
    paint(); emit();
  }
  function remove(i) {
    lights.splice(i, 1);
    selected = Math.min(selected, lights.length - 1);
    paint(); emit();
  }

  function paintList() {
    clear(list);
    lights.forEach((l, i) => {
      const chip = h("button", { type: "button", class: `lchip${i === selected ? " on" : ""}`, role: "tab", "aria-selected": String(i === selected), onclick: () => select(i) },
        h("i", { class: "dot" }), `Luz ${i + 1}`);
      chip.firstChild.style.background = l.color;
      list.append(chip);
    });
  }

  function paintInspector() {
    clear(inspector);
    const l = lights[selected];
    if (!l) {
      inspector.append(h("p", { class: "hint" }, lights.length ? "" : "Adicione uma luz abaixo e arraste sobre a foto para posicioná-la."));
      return;
    }
    const color = h("input", { type: "color", class: "lcolor", value: l.color, "aria-label": "Cor da luz",
      oninput: () => { l.color = color.value; paintGlows(); paintList(); orbs.children[selected]?.style.setProperty("--c", l.color); emit(); } });
    const swatches = h("div", { class: "swatches" }, SWATCHES.map(c => {
      const b = h("button", { type: "button", class: "sw", "aria-label": `Cor ${c}`, onclick: () => { l.color = c; color.value = c; color.dispatchEvent(new Event("input")); } });
      b.style.background = c;
      return b;
    }));
    const row = (label, node) => h("div", { class: "field" }, h("label", null, h("span", null, label)), node);
    inspector.append(
      h("div", { class: "lhead" }, h("b", null, `Luz ${selected + 1}`),
        h("button", { type: "button", class: "btn ghost sm", onclick: () => remove(selected) }, icon("x", "sm"), "Remover")),
      h("div", { class: "lcolors" }, color, swatches),
      row("Intensidade", slider({ min: 5, max: 100, step: 1, default: 70 }, l.intensity, v => { l.intensity = v; paintGlows(); emit(); })),
      row("Maciez", slider({ min: 0, max: 100, step: 1, default: 50 }, l.size, v => { l.size = v; paintGlows(); emit(); })),
      row("Profundidade · atrás ↔ à frente", slider({ min: 0, max: 1, step: 0.01, default: 0.7 }, l.z, v => { l.z = v; orbs.children[selected]?.style.setProperty("--s", String(0.72 + v * 0.7)); emit(); })),
      h("div", { class: "kinds" }, KINDS.map(k => h("button", { type: "button", class: "kind", "aria-pressed": String(l.kind === k.value),
        onclick: () => { l.kind = k.value; paint(); emit(); } }, h("b", null, k.label), h("span", null, k.hint)))));
  }

  function paintOrbs() {
    clear(orbs);
    lights.forEach((l, i) => orbs.append(orbEl(l, i)));
  }

  function paint() { paintGlows(); paintOrbs(); paintList(); paintInspector(); adders.querySelectorAll("button").forEach(b => { b.disabled = lights.length >= max; }); }

  KINDS.forEach(k => adders.append(h("button", { type: "button", class: "btn sm", onclick: () => add(k.value) }, icon("plus", "sm"), k.label)));

  function syncImage() {
    const src = getImage();
    empty.hidden = !!src;
    surface.hidden = !src;
    if (src && img.getAttribute("src") !== src) img.setAttribute("src", src);
    if (!src) img.removeAttribute("src");
  }

  const el = h("div", { class: "lights" }, stage, h("div", { class: "lbar" }, list, adders), inspector,
    h("p", { class: "hint" }, "A prévia é aproximada. A IA recalcula sombras, reflexos e cor na foto de verdade."));
  paint();
  syncImage();
  return { el, sync: syncImage };
}
