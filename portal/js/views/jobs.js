import { api, store, isFinal, events } from "../api.js";
import { h, icon, clear, illustration, ago, toast } from "../ui.js";

const STATE = { fila: ["Na fila", ""], executando: ["Executando", "red"], concluído: ["Concluído", "ok"], falhou: ["Falhou", "warn"], cancelado: ["Cancelado", ""], travado: ["Interrompido", "warn"] };

export async function jobsView(navigate) {
  const root = h("div", { class: "view" });
  const list = h("div", { class: "joblist" });
  const paint = () => {
    clear(list);
    store.jobs.forEach(j => {
      const [label, tone] = STATE[j.status] || [j.status, ""];
      const first = j.results.find(r => r.kind === "image" || r.kind === "video");
      const active = !isFinal(j.status);
      list.append(h("a", { class: "job", href: `#/apps/${j.app}`, onclick: () => store.lastJob(j.app, j.id) },
        h("div", { class: "thumbj" }, first ? (first.kind === "image" ? h("img", { src: api.url(first.url), alt: "", loading: "lazy" }) : h("video", { src: api.url(first.url), muted: true, preload: "metadata" })) : icon(active ? "bolt" : "alert")),
        h("div", { style: { minWidth: 0 } }, h("h3", null, j.title), h("div", { class: "meta" }, h("span", { class: `badge ${tone}` }, label), active ? j.desc : (j.message || `há ${ago(j.created)}`)),
          active ? h("div", { class: "light" + (j.fraction ? "" : " indeterminate"), style: { "--p": j.fraction } }, h("i")) : null),
        active ? h("button", { class: "btn sm danger", type: "button", onclick: e => { e.preventDefault(); api.post(`/jobs/${j.id}/cancel`).then(() => store.refreshJobs()); } }, icon("stop", "sm"), "Cancelar") : h("span", { class: "dim mono" }, icon("chevron-right", "sm"))));
    });
    if (!store.jobs.length) list.append(h("div", { class: "empty" }, illustration("idle"), h("h3", null, "Fila vazia"), h("p", null, "Quando você gerar algo, o andamento aparece aqui.")));
  };
  const clearAll = h("button", { class: "btn", type: "button", onclick: async () => {
    const { cancelled } = await api.post("/queue/clear").catch(e => (toast(e.message, "err"), { cancelled: 0 }));
    toast(cancelled ? `${cancelled} job(s) cancelado(s).` : "Nada para cancelar.");
    store.refreshJobs();
  } }, icon("stop", "sm"), "Limpar fila");
  root.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Fila e jobs"), h("p", null, "Tudo que está rodando ou já rodou. Um job continua no Colab mesmo se você fechar esta aba.")), clearAll), list);
  await store.refreshJobs().catch(() => {});
  paint();
  const onJobs = () => paint();
  events.addEventListener("jobs", onJobs);
  return { el: root, destroy() { events.removeEventListener("jobs", onJobs); } };
}
