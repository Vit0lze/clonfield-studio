import { api, store, isFinal } from "../api.js";
import { h, icon, clear, seg, posterEl, toast, illustration } from "../ui.js";

const FAMILY = { qwen21: "Qwen 2.1", krea2: "Krea 2", "krea2-turbo": "Krea 2 Turbo" };

export async function lorasView(navigate) {
  const root = h("div", { class: "view" });
  let items = await api.get("/loras");
  let family = "all", query = "";
  const list = h("div", { class: "lora-list" });
  const followers = [];
  const paint = () => {
    clear(list);
    const shown = items.filter(l => (family === "all" || l.families.includes(family) || !l.families.length) && l.label.toLowerCase().includes(query));
    shown.forEach((l, i) => {
      const status = h("div", { class: "hint mono" });
      const install = h("button", { class: "btn sm", type: "button", onclick: async () => {
        install.disabled = true;
        try {
          const job = await api.post("/loras/install", { name: l.name });
          followers.push(api.follow(job.id, snap => {
            status.textContent = isFinal(snap.status) ? (snap.status === "concluído" ? "" : snap.message) : snap.desc;
            if (snap.status === "concluído") { l.installed = true; paint(); }
            if (isFinal(snap.status)) install.disabled = false;
          }));
        } catch (error) { toast(error.message, "err"); install.disabled = false; }
      } }, icon("download", "sm"), "Baixar");
      list.append(h("div", { class: "lorarow", style: { "--i": i } }, h("div", { class: "po" }, posterEl(l.name)),
        h("div", null, h("h3", null, l.label), h("div", { class: "row", style: { gap: "6px", marginTop: "4px", flexWrap: "wrap" } },
          l.families.map(f => h("span", { class: "badge red" }, FAMILY[f] || f)), h("span", { class: `badge ${l.installed ? "ok" : ""}` }, l.installed ? "instalada" : l.source)), status),
        h("div", { class: "actions" }, l.installed ? null : install,
          h("button", { class: "btn sm primary", type: "button", onclick: () => {
            store.prefill({ app: "create", values: { model: l.families[0] || "qwen21", loras: [{ name: l.name, strength: 1, clip: 1, on: true }] } });
            navigate("#/apps/create");
          } }, "Usar"))));
    });
    if (!shown.length) list.append(h("div", { class: "empty" }, illustration("empty"), h("h3", null, "Nenhuma LoRA aqui"), h("p", null, "Coloque arquivos .safetensors na pasta loras do Studio ou escolha outra família.")));
  };
  const search = h("input", { class: "input", type: "search", placeholder: "Buscar LoRA…", "aria-label": "Buscar LoRA", style: { maxWidth: "260px" }, oninput: () => { query = search.value.toLowerCase(); paint(); } });
  const families = ["all", ...new Set(items.flatMap(i => i.families))];
  root.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "LoRAs"), h("p", null, "Estilos e personagens que se encaixam no modelo. Ajuste a força direto no app."))),
    h("div", { class: "libhead" }, seg(families.map(f => ({ value: f, label: f === "all" ? "Todas" : FAMILY[f] || f })), family, v => { family = v; paint(); }), search), list);
  paint();
  return { el: root, destroy() { followers.forEach(f => f.stop()); } };
}
