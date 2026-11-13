import { h, icon, clear } from "./ui.js";

// Box editor: drag over the picture to mark what changes. Boxes are fractions of the image (x, y, w, h in 0..1), so they survive any
// preview size; the server turns them into the mask. Click a box to select it, Delete (or the × in the list) removes it, arrows nudge it.
const MIN = 0.02;

export function boxEditor({ boxes, getImage, onChange, max = 16, detail = false }) {
  let selected = -1, drawing = null;
  const img = h("img", { alt: "", draggable: "false" });
  const empty = h("div", { class: "lempty" }, icon("frame"), h("b", null, "Envie a imagem"), h("span", null, "Depois arraste sobre ela para desenhar as caixas."));
  const layer = h("div", { class: "blayer", role: "application", "aria-label": "Área para desenhar caixas sobre a imagem" });
  const surface = h("div", { class: "bsurface" }, img, layer);
  const stage = h("div", { class: "lstage" }, empty, surface);
  const list = h("ul", { class: "blist" });
  const form = h("div", { class: "bform" });  // detail mode: what goes inside the selected box
  const hint = h("p", { class: "dim bhint" }, "Arraste sobre a imagem para criar uma caixa. Clique numa caixa para selecionar; Delete a remove.");
  const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
  const emit = () => onChange(boxes);

  const place = (el, b) => { el.style.left = `${b.x * 100}%`; el.style.top = `${b.y * 100}%`; el.style.width = `${b.w * 100}%`; el.style.height = `${b.h * 100}%`; };
  function paintForm() {
    clear(form);
    const b = boxes[selected];
    if (!detail || !b) return;
    b.kind = b.kind || "obj";
    form.append(h("div", { class: "bform-head" }, h("b", null, `Caixa ${selected + 1}`),
        h("div", { class: "seg" }, [["obj", "Objeto"], ["text", "Texto"]].map(([value, label]) => h("button", { type: "button", "aria-pressed": String(b.kind === value),
          onclick: () => { b.kind = value; paintForm(); emit(); } }, label)))),
      b.kind === "text" ? h("label", { class: "field" }, h("span", { class: "label" }, "Palavras exatas que aparecem"),
        h("input", { class: "input", type: "text", value: b.text || "", maxlength: 200, "aria-label": `Texto da caixa ${selected + 1}`, oninput: e => { b.text = e.target.value; emit(); } })) : null,
      h("label", { class: "field" }, h("span", { class: "label" }, b.kind === "text" ? "Onde está o texto e como ele é (fonte, cor, em que superfície)" : "O que aparece nesta caixa"),
        h("textarea", { class: "input", rows: 2, maxlength: 600, "aria-label": `Descrição da caixa ${selected + 1}`, oninput: e => { b.desc = e.target.value; emit(); } }, b.desc || "")));
  }
  function paint() {
    clear(layer); clear(list);
    boxes.forEach((b, i) => {
      const el = h("button", { type: "button", class: `bbox${i === selected ? " on" : ""}`, "data-index": String(i), "aria-label": `Caixa ${i + 1}: ${Math.round(b.w * 100)}% × ${Math.round(b.h * 100)}%`,
        onclick: e => { e.stopPropagation(); selected = i; paint(); },
        onkeydown: e => {
          const step = e.shiftKey ? 0.05 : 0.01;
          if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); remove(i); }
          else if (e.key.startsWith("Arrow")) {
            e.preventDefault();
            if (e.key === "ArrowLeft") b.x = clamp(b.x - step, 0, 1 - b.w); if (e.key === "ArrowRight") b.x = clamp(b.x + step, 0, 1 - b.w);
            if (e.key === "ArrowUp") b.y = clamp(b.y - step, 0, 1 - b.h); if (e.key === "ArrowDown") b.y = clamp(b.y + step, 0, 1 - b.h);
            place(el, b); emit();
          }
        } }, h("span", null, i + 1));
      place(el, b);
      layer.append(el);
      list.append(h("li", { class: i === selected ? "on" : "" }, h("button", { type: "button", class: "blink", onclick: () => { selected = i; paint(); } }, `Caixa ${i + 1}`),
        h("span", { class: "dim" }, `${Math.round(b.w * 100)}% × ${Math.round(b.h * 100)}%`),
        h("button", { type: "button", class: "btn ghost sm icon-only", "aria-label": `Remover caixa ${i + 1}`, onclick: () => remove(i) }, icon("x", "sm"))));
    });
    if (drawing) { const ghost = h("i", { class: "bghost" }); place(ghost, drawing.box); layer.append(ghost); }
    paintForm();
  }
  function remove(i) { boxes.splice(i, 1); selected = -1; paint(); emit(); }

  layer.addEventListener("pointerdown", e => {
    if (e.target !== layer || boxes.length >= max) return;
    e.preventDefault();
    layer.setPointerCapture(e.pointerId);
    const rect = layer.getBoundingClientRect();
    const x = clamp((e.clientX - rect.left) / rect.width), y = clamp((e.clientY - rect.top) / rect.height);
    drawing = { rect, x0: x, y0: y, box: { x, y, w: 0, h: 0 } };
  });
  layer.addEventListener("pointermove", e => {
    if (!drawing) return;
    const x = clamp((e.clientX - drawing.rect.left) / drawing.rect.width), y = clamp((e.clientY - drawing.rect.top) / drawing.rect.height);
    drawing.box = { x: Math.min(x, drawing.x0), y: Math.min(y, drawing.y0), w: Math.abs(x - drawing.x0), h: Math.abs(y - drawing.y0) };
    paint();
  });
  const finish = () => {
    if (!drawing) return;
    const box = drawing.box;
    drawing = null;
    if (box.w >= MIN && box.h >= MIN) { boxes.push({ x: +box.x.toFixed(4), y: +box.y.toFixed(4), w: +box.w.toFixed(4), h: +box.h.toFixed(4) }); selected = boxes.length - 1; emit(); }
    paint();
  };
  layer.addEventListener("pointerup", finish);
  layer.addEventListener("pointercancel", () => { drawing = null; paint(); });

  function sync() {
    const src = getImage();
    empty.hidden = Boolean(src);
    surface.hidden = !src;
    if (src && img.getAttribute("src") !== src) img.src = src;
    hint.hidden = !src;
  }
  paint(); sync();
  return { el: h("div", { class: "boxeditor" }, stage, hint, list, form), sync };
}
