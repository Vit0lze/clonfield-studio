// «Pesquisar…» from any slot: one modal over local files, Civitai (filtered by slot and base model) and Hugging Face.
// Discovery is not installation and installation is not execution: every row says which one it is.
import { api, isFinal } from "./api.js";
import { h, icon, clear, toast } from "./ui.js";
import { starButton } from "./favs.js";

const SOURCES = [["local", "No worker"], ["civitai", "CivitAI"], ["huggingface", "Hugging Face"]];

export function openSearch({ role, label, family, familyTitle, onUse }) {
  let source = "local", timer = null, serial = 0;
  const input = h("input", { class: "input", type: "search", placeholder: `Buscar ${label.toLowerCase()}…`, "aria-label": "Buscar",
    oninput: () => { clearTimeout(timer); timer = setTimeout(load, 350); } });
  const list = h("div", { class: "sr-list", role: "list" });
  const tabs = h("div", { class: "seg sr-tabs" }, SOURCES.map(([id, text]) => h("button", { type: "button", "aria-pressed": String(id === source),
    onclick: e => { source = id; [...tabs.children].forEach(b => b.setAttribute("aria-pressed", String(b === e.currentTarget))); load(); } }, text)));
  const close = () => { overlay.classList.add("out"); setTimeout(() => overlay.remove(), 140); document.removeEventListener("keydown", onKey); };
  const onKey = e => { if (e.key === "Escape") close(); };
  const overlay = h("div", { class: "sr-overlay", role: "dialog", "aria-modal": "true", "aria-label": `Pesquisar ${label}`, onpointerdown: e => { if (e.target === overlay) close(); } },
    h("div", { class: "sr-box" },
      h("div", { class: "sr-head" }, h("div", null, h("h3", null, `Pesquisar ${label}`), h("p", { class: "muted" }, `para ${familyTitle}`)),
        h("button", { class: "btn ghost", type: "button", "aria-label": "Fechar", onclick: close }, icon("x", "sm"))),
      tabs, input, list));
  document.body.append(overlay);
  document.addEventListener("keydown", onKey);
  input.focus();

  const row = item => resultRow(item, { family, role, label, onUse: picked => { onUse(picked); close(); }, onChange: () => load() });

  async function load() {
    const mine = ++serial;
    clear(list); list.append(h("p", { class: "muted pad" }, "Buscando…"));
    try {
      const result = await api.get(`/search?role=${encodeURIComponent(role)}&family=${encodeURIComponent(family)}&source=${source}&q=${encodeURIComponent(input.value)}`);
      if (mine !== serial) return;
      clear(list);
      if (!result.items.length) list.append(h("p", { class: "muted pad" }, source === "local" ? "Nada instalado neste slot com esse nome." : "Nada encontrado. Tente outro termo."));
      else list.append(...result.items.map(row));
      if (source === "huggingface" && result.items.length) list.append(h("p", { class: "muted pad" }, "Hugging Face: descoberto não é validado. Confirme arquitetura e loader antes de usar; o Studio não baixa nada daqui automaticamente."));
    } catch (error) { if (mine === serial) { clear(list); list.append(h("p", { class: "advice pad" }, error.message || "A fonte não respondeu.")); } }
  }
  load();
}

/** One search result: title, honest status, compatibility, ⭐ favourite, and the actions that really exist for it. */
export function resultRow(item, { family, role, label, onUse, onChange }) {
  async function install(button) {
    button.disabled = true; button.textContent = "Baixando…";
    try {
      const job = await api.post("/components/install", { family, role, ...item.install });
      api.follow(job.id, snap => {
        button.textContent = isFinal(snap.status) ? (snap.status === "concluído" ? "Instalado" : "Falhou") : (snap.desc || "Baixando…").slice(0, 28);
        if (isFinal(snap.status)) {
          if (snap.status === "concluído") { toast(`${label} instalado. Já aparece na lista do slot.`); onChange?.(); }
          else { toast(snap.message || "A instalação falhou.", "err"); button.disabled = false; button.textContent = "Instalar"; }
        }
      });
    } catch (error) { toast(error.message, "err"); button.disabled = false; button.textContent = "Instalar"; }
  }
  const chip = h("span", { class: `sr-chip ${item.status === "instalado" ? "ok" : item.status === "compatível" ? "good" : ""}` }, item.status);
  const actions = [];
  if (item.url) actions.push(h("a", { class: "btn ghost sm", href: item.url, target: "_blank", rel: "noopener noreferrer" }, "Página"));
  if (item.install) actions.push(h("button", { class: "btn sm", type: "button", onclick: e => install(e.currentTarget) }, "Instalar"));
  if (item.status === "instalado" && item.value !== undefined && onUse) actions.push(h("button", { class: "btn primary sm", type: "button", onclick: () => onUse(item) }, "Usar aqui"));
  return h("div", { class: "sr-row", role: "listitem" },
    h("div", { class: "sr-main" }, h("b", null, item.title), h("span", { class: "muted" }, [item.author, item.size_mb ? (item.size_mb >= 1000 ? `${(item.size_mb / 1000).toFixed(1).replace(".", ",")} GB` : `${item.size_mb} MB`) : "", item.downloads ? `${item.downloads.toLocaleString("pt-BR")} downloads` : ""].filter(Boolean).join(" · ")),
      item.file_name ? h("span", { class: "sr-file mono", title: "O arquivo exato que será baixado e conferido (nome, tamanho e SHA-256) antes de entrar na pasta" },
        item.quant_label ? h("b", { class: "sr-quant" }, item.quant_label) : null, ` ${item.file_name}`, item.primary === false ? " · não é o arquivo principal da página" : "") : null,
      h("span", { class: "sr-compat" }, `Compatibilidade: ${item.compatible}`)),
    chip, h("div", { class: "sr-actions" }, starButton(({ Difusão: "model", Checkpoint: "model", VAE: "vae", Encoder: "encoder", Upscaler: "upscaler", LoRA: "lora" })[role] || "model", `${item.source}:${item.id}`, { title: item.title, role, family, source: item.source, url: item.url || "" }), actions));
}
