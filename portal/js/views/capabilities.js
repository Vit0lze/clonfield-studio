// Capabilities: what the Studio can DO, independent of which app shows it. Each one has typed inputs/outputs, requirements, an
// honest validation state and the places that use it. Apps are consumers, not owners.
import { api } from "../api.js";
import { h, icon, seg, appGlyph } from "../ui.js";

const KIND = { engine: "Motor compartilhado", step: "Passo de grafo", action: "Ação", mode: "Modo", app: "App completo" };
const STATE_TONE = { "TESTADO CPU": "ok", "TESTADO API REAL": "ok", "TESTADO GPU": "ok", "INTEGRADO E VALIDADO": "ok", "CÓDIGO ESCRITO": "warn", "BLOQUEADO_GPU": "warn", "NÃO INICIADO": "" };
const MODE = { app: "é a tela do app", step: "usa dentro do app", insertion: "pode ser inserida" };

const port = p => h("span", { class: `cap-port t-${p.type}${p.required ? "" : " opt"}`, title: p.note || (p.required ? "obrigatória" : "opcional") }, `${p.name}: ${p.type}${p.many ? "[]" : ""}`);

function card(c, apps, focus) {
  const lane = c.requires.lane === "gpu" ? `GPU ≥ ${c.requires.vram_gb || "?"} GB VRAM` : "roda em CPU";
  const where = [...c.consumers.map(x => ({ app: x.app, text: MODE[x.mode] || x.mode, note: x.note })), ...c.insertable_in.map(x => ({ app: x.app, text: `${MODE.insertion} (${x.point})` }))];
  return h("article", { class: `cap-card${focus === c.id ? " focus" : ""}`, id: `cap-${c.id}`, "data-cap": c.id },
    h("header", null, h("h3", null, c.title), h("span", { class: "badge" }, KIND[c.kind] || c.kind), c.risk !== "low" ? h("span", { class: "badge warn" }, `risco ${c.risk}`) : null),
    h("p", { class: "muted" }, c.tagline),
    h("div", { class: "cap-io" }, h("span", { class: "dim" }, "Entra"), c.inputs.length ? c.inputs.map(port) : h("span", { class: "dim" }, "nada"),
      icon("arrow-right", "sm"), h("span", { class: "dim" }, "Sai"), c.outputs.map(port)),
    Object.keys(c.params).length ? h("p", { class: "cap-params" }, h("span", { class: "dim" }, "Parâmetros: "), Object.entries(c.params).map(([k, v]) => `${k}${v.min != null ? ` (${v.min}–${v.max})` : ""}`).join(" · ")) : null,
    h("p", { class: "cap-req dim" }, `${lane} · ${c.requires.ram_gb} GB de RAM${c.requires.disk_gb ? ` · ${c.requires.disk_gb} GB de disco` : ""} · v${c.version} · ${c.source}`),
    h("p", { class: "cap-state" }, h("span", { class: `badge ${STATE_TONE[c.validation.state] ?? ""}` }, c.validation.state), h("span", { class: "dim" }, ` ${c.validation.evidence}`)),
    where.length ? h("ul", { class: "cap-where" }, where.map(w => h("li", null, apps.get(w.app) ? h("a", { href: `#/apps/${w.app}` }, appGlyph(w.app, "sm"), apps.get(w.app).title) : w.app, h("span", { class: "dim" }, ` · ${w.text}${w.note ? ` — ${w.note}` : ""}`)))) : h("p", { class: "dim" }, "Ainda sem consumidor declarado."));
}

export async function capabilitiesView(focus) {
  const root = h("div", { class: "view" });
  const [list, apps] = await Promise.all([api.get("/capabilities"), api.get("/apps")]);
  const byApp = new Map(apps.map(a => [a.id, a]));
  let kind = "all", query = "";
  const grid = h("div", { class: "cap-grid" });
  const paint = () => {
    grid.replaceChildren();
    const shown = list.filter(c => (kind === "all" || (kind === "shared" ? c.consumers.length > 1 || c.insertable_in.length : c.kind === kind))
      && `${c.id} ${c.title} ${c.tagline} ${c.ops.join(" ")}`.toLowerCase().includes(query));
    shown.forEach(c => grid.append(card(c, byApp, focus)));
    if (!shown.length) grid.append(h("div", { class: "empty" }, h("h3", null, "Nenhuma capacidade com esse filtro")));
    count.textContent = `${shown.length} de ${list.length}`;
  };
  const count = h("span", { class: "dim" });
  const search = h("input", { class: "input", type: "search", placeholder: "Buscar capacidade…", "aria-label": "Buscar capacidade", style: { maxWidth: "260px" }, oninput: () => { query = search.value.toLowerCase(); paint(); } });
  root.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Capacidades"),
      h("p", null, "O que o Studio sabe fazer, separado de qual tela mostra. O agente e os grafos usam este mesmo catálogo."))),
    h("div", { class: "libhead" }, seg([["all", "Todas"], ["shared", "Compartilhadas"], ["step", "Passos"], ["engine", "Motores"], ["app", "Apps"]].map(([value, label]) => ({ value, label })), kind, v => { kind = v; paint(); }), search, count), grid);
  paint();
  if (focus) requestAnimationFrame(() => document.getElementById(`cap-${focus}`)?.scrollIntoView({ block: "center" }));
  return { el: root };
}
