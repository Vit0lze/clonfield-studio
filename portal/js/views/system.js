import { api, store, isFinal } from "../api.js";
import { h, icon, clear, toast } from "../ui.js";

export async function systemView() {
  const root = h("div", { class: "view" });
  const [info, logs] = await Promise.all([api.get("/system"), api.get("/logs").catch(() => ({ worker: "" }))]);
  const t = info.tier;
  const bar = (p) => h("div", { class: "bar" }, h("i", { style: { "--p": Math.min(1, Math.max(0, p)) } }));
  const speed = h("div", { class: "hint mono" });
  const speedBtn = h("button", { class: "btn", type: "button", onclick: async () => {
    speedBtn.disabled = true; speed.textContent = "Enviando…";
    try {
      const job = await api.post("/jobs", { app: "speedtest", params: {} });
      api.follow(job.id, snap => {
        speed.textContent = isFinal(snap.status) ? (snap.message || snap.desc) : snap.desc;
        if (isFinal(snap.status)) speedBtn.disabled = false;
      });
    } catch (error) { toast(error.message, "err"); speedBtn.disabled = false; speed.textContent = ""; }
  } }, icon("bolt", "sm"), "Medir velocidade");
  const logBox = h("pre", { class: "log" }, logs.worker || "Sem log do ComfyUI neste ambiente.");
  const worker = info.worker;
  root.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Sistema"), h("p", null, "O Studio ajusta resolução, qualidade e flags do ComfyUI ao que sua placa aguenta."))),
    h("div", { class: "sysgrid" },
      h("section", { class: "panel" }, h("div", { class: "row between" }, h("h3", null, "Placa de vídeo"), h("span", { class: "badge red" }, `perfil ${t.label}`)),
        h("div", { class: "bigstat" }, t.vram_gb ? `${t.vram_gb.toFixed(0)} GB` : "Sem GPU"), h("p", { class: "muted" }, t.gpu),
        h("div", { class: "facts" },
          h("div", { class: "fact" }, "Lado padrão", h("span", { class: "mono" }, `${t.default_side} px`)), h("div", { class: "fact" }, "Lado máximo", h("span", { class: "mono" }, `${t.max_side} px`)),
          h("div", { class: "fact" }, "Variações", h("span", { class: "mono" }, `até ${t.max_variations}`)), h("div", { class: "fact" }, "SeedVR2", h("span", { class: "mono" }, t.seedvr2)),
          h("div", { class: "fact" }, "OpenJutsu", h("span", { class: `badge ${t.openjutsu ? "ok" : ""}` }, t.openjutsu ? "liberado" : "precisa ~96 GB")))),
      h("section", { class: "panel" }, h("h3", null, "Memória e disco"),
        h("div", { class: "stack" }, h("div", null, h("div", { class: "fact" }, "RAM livre", h("span", { class: "mono" }, `${info.ram_free_gb} / ${info.ram_gb} GB`)), bar(1 - info.ram_free_gb / (info.ram_gb || 1))),
          h("div", { class: "fact" }, "Disco livre", h("span", { class: "mono" }, `${info.disk_free_gb} GB`))),
        h("div", { class: "fact" }, "Hugging Face", h("span", { class: `badge ${info.credentials.hf ? "ok" : "warn"}` }, info.credentials.hf ? "token ativo" : "sem token")),
        h("div", { class: "fact" }, "Civitai", h("span", { class: `badge ${info.credentials.civitai ? "ok" : "warn"}` }, info.credentials.civitai ? "token ativo" : "sem token"))),
      h("section", { class: "panel" }, h("div", { class: "row between" }, h("h3", null, "Worker ComfyUI"), h("span", { class: `badge ${worker.ok ? "ok" : "warn"}` }, worker.ok ? `v${worker.version || "?"}` : "parado")),
        worker.ok ? h("p", { class: "muted" }, `${worker.running} executando · ${worker.pending} na fila`) : h("p", { class: "advice" }, icon("alert", "sm"), "O worker não responde. Rode a célula do ComfyUI no Colab."),
        h("div", { class: "row" }, speedBtn, h("button", { class: "btn ghost", type: "button", onclick: async () => { const r = await api.post("/queue/clear"); toast(`${r.cancelled} job(s) cancelado(s).`); } }, "Limpar fila")), speed),
      h("section", { class: "panel", style: { gridColumn: "1 / -1" } }, h("h3", null, "Log do worker"), logBox)));
  logBox.scrollTop = logBox.scrollHeight;
  return { el: root };
}
