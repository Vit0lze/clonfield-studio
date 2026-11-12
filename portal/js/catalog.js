// One card for every catalogue item (contract: cf_contracts.CatalogItem). Same layout, same star position, same actions
// whatever the item is: a recipe model, a LoRA, a VAE, an upscaler, a Civitai file.
import { api, isFinal, store } from "./api.js";
import { h, icon, clear, toast, artFor, posterEl } from "./ui.js";
import { starButton } from "./favs.js";

const gb = n => n >= 1e9 ? `${(n / 1e9).toFixed(1).replace(".", ",")} GB` : `${Math.round(n / 1e6)} MB`;

function cover(item) {
  const box = h("div", { class: "cc-cover" });
  if (item.art) { const [kind, key] = item.art.split(":"); box.append(artFor(kind, key)); }
  else if (item.cover) {
    const img = h("img", { src: api.url(item.cover), alt: "", loading: "lazy", decoding: "async" });
    img.addEventListener("error", () => img.replaceWith(posterEl(item.title)));
    box.append(img);
  } else box.append(posterEl(item.title));
  return box;
}

/** «Falta baixar X» from the parts that are not on disk yet, and a breakdown that names what is shared. */
function sizeBlock(item) {
  if (!item.size_parts.length) return item.size != null ? h("p", { class: "cc-size" }, gb(item.size)) : h("p", { class: "cc-size dim" }, "tamanho não informado");
  const missing = item.size_parts.filter(p => !p.installed);
  const known = item.size_parts.every(p => p.size != null);
  if (!item.size_parts.some(p => p.size != null)) return h("p", { class: "cc-size dim" }, "tamanho não informado (repositório restrito)");
  const total = missing.reduce((a, p) => a + (p.size || 0), 0);
  const head = !missing.length ? "Tudo instalado" : `Falta baixar ${known ? "" : "≥ "}${gb(total)}`;
  const shared = item.size_parts.filter(p => p.shared_with.length && !p.installed);
  return h("details", { class: "cc-parts" }, h("summary", null, head),
    h("ul", null, item.size_parts.map(p => h("li", null, h("span", null, p.label), h("b", null, p.size != null ? gb(p.size) : "indisponível"),
      p.installed ? h("small", null, "já instalado") : null, p.shared_with.length ? h("small", { class: "shared" }, `também usado por ${p.shared_with.join(", ")}`) : null))),
    shared.length ? h("p", { class: "cc-note" }, "Arquivos compartilhados são baixados uma vez: se você já tem um dos modelos que os usam, o download real é menor.") : null);
}

export function catalogCard(item, { navigate, onChange }) {
  const actions = h("div", { class: "cc-actions" });
  const status = h("span", { class: `cc-status s-${item.status.replace(/[^a-z]/gi, "")}` }, item.status);
  let busy = false;

  async function perform(a, button) {
    if (a.href) return window.open(a.href, "_blank", "noopener");
    if (a.prefill) { store.prefill({ app: a.prefill.app, values: a.prefill.values }); return navigate(`#/apps/${a.prefill.app}`); }
    if (!a.call || busy) return;
    busy = true; button.disabled = true; button.textContent = "Enviando…";
    try {
      const job = await api.post(a.call.path, a.call.body || {});
      api.follow(job.id, snap => {
        button.textContent = isFinal(snap.status) ? (snap.status === "concluído" ? "Instalado" : "Falhou") : (snap.desc || "Baixando…").slice(0, 30);
        if (isFinal(snap.status)) {
          busy = false;
          if (snap.status === "concluído") { toast(`${item.title} instalado.`); onChange?.(); }
          else { toast(snap.message || "A instalação falhou.", "err"); button.disabled = false; button.textContent = a.label; }
        }
      });
    } catch (error) { busy = false; button.disabled = false; button.textContent = a.label; toast(error.message, "err"); }
  }

  const ordered = [...item.actions].sort((x, y) => (y.id === "install") - (x.id === "install") || (y.id === "use") - (x.id === "use"));
  ordered.forEach((a, i) => {
    const primary = i === 0 && a.enabled;
    if (a.id === "open" && a.href) actions.append(h("a", { class: "btn ghost sm", href: a.href, target: "_blank", rel: "noopener noreferrer" }, a.label, icon("external", "sm")));
    else actions.append(h("button", { class: `btn sm${primary ? " primary" : ""}`, type: "button", disabled: !a.enabled, title: a.enabled ? "" : a.reason, onclick: e => perform(a, e.currentTarget) }, a.label));
  });
  item.links.filter(l => !item.actions.some(a => a.href === l.url)).forEach(l => actions.append(h("a", { class: "btn ghost sm", href: l.url, target: "_blank", rel: "noopener noreferrer" }, l.label, icon("external", "sm"))));

  return h("article", { class: `ccard${item.adult ? " adult" : ""}` },
    cover(item), starButton(item.favorite.kind, item.favorite.id, item.favorite.meta),
    h("div", { class: "cc-top" }, status, ...item.badges.map(b => h("span", { class: "cc-badge" }, b))),
    h("div", { class: "cc-body" },
      h("h3", { title: item.title }, item.title),
      item.subtitle ? h("p", { class: "cc-sub" }, item.subtitle) : null,
      item.facts.length ? h("dl", { class: "cc-facts" }, item.facts.slice(0, 4).flatMap(f => [h("dt", null, f.label), h("dd", null, f.value)])) : null,
      sizeBlock(item),
      item.compat?.note ? h("p", { class: "cc-compat" }, item.compat.note) : null),
    actions);
}
