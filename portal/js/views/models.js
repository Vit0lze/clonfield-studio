import { api, store, isFinal } from "../api.js";
import { h, icon, clear, seg, dropdown, artFor, posterEl, toast, field } from "../ui.js";
import { favFirst, isFav, starButton } from "../favs.js";
import { resultRow } from "../search.js";

const meter = n => h("div", { class: "meter", "aria-label": `${n} de 5` }, [1, 2, 3, 4, 5].map(i => h("i", { class: i <= n ? "on" : "" })));

const gb = bytes => bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1).replace(".", ",")} GB` : `${Math.round(bytes / 1e6)} MB`;
const TYPES = [
  { value: "upscalers", label: "Upscalers", hint: "Ampliação de imagem" },
  { value: "Checkpoint", label: "Checkpoints", hint: "Modelos completos (SDXL, SD 1.5…)" },
  { value: "Difusão", label: "Modelos de difusão", hint: "Transformer/UNet separado" },
  { value: "VAE", label: "VAEs", hint: "Codificador de imagem" },
  { value: "Encoder", label: "Encoders de texto", hint: "CLIP, Qwen-VL…" },
  { value: "lora", label: "LoRAs →", hint: "Abre a biblioteca de LoRAs" },
];
const pref = (key, fallback) => { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } };
const setPref = (key, value) => { try { localStorage.setItem(key, value); } catch { /* private mode */ } };

export async function modelsView(navigate) {
  const root = h("div", { class: "view" });
  const [models, families] = await Promise.all([(store.models = api.get("/models")), api.get("/lora-families").catch(() => [])]);
  let tab = pref("cf-models-tab", "catalogo"), filter = "all";
  let kind = "upscalers", family = pref("cf-explore-family", "qwen21"), source = "civitai", query = "";
  const body = h("div");
  const grid = h("div", { class: "mosaic" });
  const followers = [];

  // ---------------- Catálogo: what ships with the Studio
  const paintCatalog = () => {
    clear(grid);
    const shown = favFirst(models, "model", m => m.key).filter(m => filter === "all" || (filter === "installed" ? m.installed : isFav("model", m.key)));
    shown.forEach((m, i) => {
      const note = m.installed ? "instalado" : m.download_bytes ? `baixar ${m.size_known ? "" : "≥ "}${gb(m.download_bytes)}` : "tamanho indisponível";
      grid.append(h("div", { class: "tile-wrap", style: { "--i": i } }, h("a", { class: "tile", href: `#/models/${m.key}` },
        h("div", { class: "art" }, artFor("model", m.key)),
        h("div", { class: "corner" }, h("span", { class: `badge ${m.installed ? "ok" : ""}` }, note), h("span", { class: `badge ${m.fits ? "" : "warn"}` }, m.weight)),
        h("div", { class: "copy" }, h("h3", null, m.title), h("p", null, m.tagline))), starButton("model", m.key, { title: m.title })));
    });
    if (!shown.length) grid.append(h("div", { class: "empty" }, illustration("empty"),
      h("h3", null, filter === "favorites" ? "Nenhum modelo favorito" : "Nenhum modelo instalado ainda"),
      h("p", null, filter === "favorites" ? "Toque na estrela de um modelo para fixá-lo no topo." : "Abra um modelo e instale com um clique, ou deixe baixar na primeira geração. Em Explorar você acha checkpoints, VAEs, encoders e upscalers.")));
  };
  const catalog = () => h("div", null,
    h("div", { class: "libhead" }, seg([{ value: "all", label: "Todos" }, { value: "installed", label: "Instalados" }, { value: "favorites", label: "Favoritos" }], filter, v => { filter = v; paintCatalog(); })), grid);

  // ---------------- Explorar: what can be downloaded
  const results = h("div", { class: "sr-list explore-results", role: "list" });
  const note = h("p", { class: "hint" });
  let serial = 0;
  async function explore() {
    const mine = ++serial;
    clear(results); note.textContent = "";
    if (kind === "lora") return navigate("#/loras");
    results.append(h("p", { class: "muted pad" }, "Buscando…"));
    try {
      if (kind === "upscalers") {
        const list = await api.get("/upscalers");
        if (mine !== serial) return;
        clear(results);
        favFirst(list, "upscaler", u => u.name).filter(u => (u.name + u.use).toLowerCase().includes(query)).forEach(u => results.append(upscalerRow(u)));
        note.textContent = "Já inclusos no Studio, com SHA-256 conferido. Licença dos pesos ≠ licença do código: NC é só uso não comercial.";
        return;
      }
      const params = new URLSearchParams({ role: kind, family, source, q: query });
      const out = await api.get(`/search?${params}`);
      if (mine !== serial) return;
      clear(results);
      if (!out.items.length) results.append(h("p", { class: "muted pad" }, "Nada encontrado para essa combinação. Tente outro termo, outra fonte ou outro modelo compatível."));
      else favFirst(out.items, "component", i => `${kind}|${i.source}|${i.id}`).forEach(item => results.append(resultRow(item, { family, role: kind, label: TYPES.find(t => t.value === kind)?.label || kind, onChange: explore })));
      note.textContent = source === "huggingface" ? "Hugging Face: descoberto não é validado. O Studio não baixa nada daqui sozinho." : source === "civitai" ? "CivitAI: só aparecem arquivos da mesma base do modelo escolhido, com SHA-256 na instalação." : "";
    } catch (error) { if (mine === serial) { clear(results); results.append(h("p", { class: "advice pad" }, error.message || "A fonte não respondeu.")); } }
  }
  function upscalerRow(u) {
    const button = h("button", { class: "btn sm", type: "button", onclick: async () => {
      button.disabled = true; button.textContent = "Baixando…";
      try {
        const job = await api.post("/upscalers/install", { name: u.name });
        followers.push(api.follow(job.id, snap => {
          button.textContent = isFinal(snap.status) ? (snap.status === "concluído" ? "Instalado" : "Falhou") : (snap.desc || "Baixando…").slice(0, 26);
          if (isFinal(snap.status)) { if (snap.status === "concluído") { toast(`${u.short} instalado.`); explore(); } else { toast(snap.message || "Falhou.", "err"); button.disabled = false; button.textContent = "Baixar"; } }
        }));
      } catch (error) { toast(error.message, "err"); button.disabled = false; button.textContent = "Baixar"; }
    } }, icon("download", "sm"), `Baixar ${u.mb} MB`);
    return h("div", { class: "sr-row", role: "listitem" },
      h("div", { class: "sr-main" }, h("b", null, u.short), h("span", { class: "muted" }, `${u.use} · ${u.mb} MB · ${u.source}`), h("span", { class: "sr-compat" }, `Licença dos pesos: ${u.license}`)),
      h("span", { class: `sr-chip ${u.installed ? "ok" : ""}` }, u.installed ? "instalado" : "no catálogo"),
      h("div", { class: "sr-actions" }, starButton("upscaler", u.name, { title: u.short }), u.installed ? h("a", { class: "btn primary sm", href: "#/apps/upscale" }, "Usar") : button));
  }
  const search = h("input", { class: "input", type: "search", placeholder: "Buscar…", "aria-label": "Buscar", onkeydown: e => { if (e.key === "Enter") { query = search.value.trim().toLowerCase(); explore(); } } });
  const familyOptions = favFirst(families, "model", f => f.key).map(f => ({ value: f.key, label: f.title, hint: f.tagline, badge: f.installed ? "instalado" : null, installed: f.installed,
    fav: () => starButton("model", f.key, { title: f.title }) }));
  const explorer = () => {
    const sourceSeg = seg([{ value: "civitai", label: "CivitAI" }, { value: "huggingface", label: "Hugging Face" }, { value: "local", label: "No worker" }], source, v => { source = v; explore(); });
    const bar = h("div", { class: "libhead explore-bar" },
      dropdown(TYPES, kind, v => { kind = v; paintExplorerBar(); explore(); }, { label: "O que baixar" }),
      dropdown(familyOptions, family, v => { family = v; setPref("cf-explore-family", v); explore(); }, { label: "Compatível com" }), sourceSeg, search);
    const paintExplorerBar = () => { const hide = kind === "upscalers"; bar.children[1].hidden = hide; sourceSeg.hidden = hide; };
    paintExplorerBar();
    explore();
    return h("div", null, bar, note, results);
  };

  const tabs = seg([{ value: "catalogo", label: "Catálogo" }, { value: "explorar", label: "Explorar" }], tab, v => { tab = v; setPref("cf-models-tab", v); paintBody(); });
  function paintBody() { clear(body); body.append(tab === "catalogo" ? catalog() : explorer()); if (tab === "catalogo") paintCatalog(); }
  root.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Modelos"), h("p", null, "O catálogo traz as receitas prontas. Em Explorar você acha o que mais dá para baixar: checkpoints, VAEs, encoders e upscalers."))),
    h("div", { class: "libhead" }, tabs, h("a", { class: "btn", href: "#/loras" }, icon("layers", "sm"), "LoRAs")), body);
  paintBody();
  return { el: root, destroy() { followers.forEach(f => f.stop()); } };
}
import { illustration } from "../ui.js";
const illustrationEmpty = () => illustration("empty");

export async function modelDetail(key, navigate) {
  const root = h("div", { class: "view" });
  const m = await api.get(`/models/${key}`).catch(() => null);
  if (!m) return { el: h("div", { class: "view" }, h("div", { class: "empty" }, h("h3", null, "Modelo não encontrado"), h("a", { class: "btn", href: "#/models" }, "Voltar"))) };
  let follower = null;
  const files = h("tbody");
  const action = h("div", { class: "stack" });
  const paint = (job) => {
    clear(files);
    m.files.forEach(f => files.append(h("tr", null, h("td", null, f.role), h("td", null, h("div", null, f.name), h("div", { class: "mono" }, `${f.repo}${f.size ? " · " + gb(f.size) : ""}`)),
      h("td", { style: { textAlign: "right" } }, h("span", { class: `badge ${f.installed ? "ok" : ""}` }, f.installed ? "instalado" : "falta")))));
    clear(action);
    if (job && !isFinal(job.status)) {
      action.append(h("div", { class: "light" + (job.fraction ? "" : " indeterminate"), style: { "--p": job.fraction } }, h("i")), h("p", { class: "hint mono" }, job.desc),
        h("button", { class: "btn danger sm", type: "button", onclick: () => api.post(`/jobs/${job.id}/cancel`) }, "Cancelar download"));
      return;
    }
    if (job && job.status === "falhou") action.append(h("p", { class: "advice" }, icon("alert", "sm"), job.message));
    if (!m.installed) action.append(h("button", { class: "btn primary lg block", type: "button", onclick: install }, icon("download", "sm"), m.download_bytes ? `Instalar agora · ${m.size_known ? "" : "≥ "}${gb(m.download_bytes)}` : "Instalar agora"),
      h("p", { class: "hint" }, "Opcional: o Studio também baixa sozinho na primeira geração."));
    action.append(h("button", { class: `btn ${m.installed ? "primary lg" : ""} block`, type: "button", onclick: use }, icon("sparkle", "sm"), "Criar com este modelo"));
  };
  async function install() {
    try {
      const job = await api.post(`/models/${key}/install`);
      paint(job);
      follower?.stop();
      follower = api.follow(job.id, async snap => {
        if (isFinal(snap.status)) { Object.assign(m, await api.get(`/models/${key}`)); store.models = null; }
        paint(snap);
      });
    } catch (error) { toast(error.message, "err"); }
  }
  const use = () => { store.prefill({ app: "create", values: { model: key } }); navigate("#/apps/create"); };
  root.append(h("a", { class: "crumb", href: "#/models" }, icon("chevron-left", "sm"), "Modelos"),
    h("div", { class: "detail" },
      h("div", { class: "stack" }, h("div", { class: "mcover" }, artFor("model", key), h("h1", null, m.title), starButton("model", key, { title: m.title })),
        h("div", { class: "panel", style: { padding: "20px 22px" } }, h("h3", null, "Arquivos"), h("table", { class: "filetable" }, files))),
      h("aside", { class: "panel stack", style: { padding: "22px" } },
        h("p", { class: "muted" }, m.tagline),
        h("div", { class: "facts" },
          h("div", { class: "fact" }, "Velocidade", meter(m.speed)), h("div", { class: "fact" }, "Qualidade", meter(m.quality)),
          h("div", { class: "fact" }, "VRAM recomendada", h("span", { class: "mono" }, `≥ ${m.min_vram} GB`)),
          h("div", { class: "fact" }, "Referências", h("span", { class: "mono" }, m.refs || "nenhuma")),
          h("div", { class: "fact" }, "Passos / CFG", h("span", { class: "mono" }, `${m.steps} / ${m.cfg}`))),
        m.advice ? h("p", { class: "advice" }, icon("alert", "sm"), m.advice) : h("p", { class: "advice", style: { color: "var(--ok)" } }, icon("check", "sm"), "Cabe na sua placa."),
        action,
        h("a", { class: "btn ghost sm", href: m.page, target: "_blank", rel: "noreferrer noopener" }, "Página do modelo", icon("external", "sm")))));
  paint();
  return { el: root, destroy() { follower?.stop(); } };
}
