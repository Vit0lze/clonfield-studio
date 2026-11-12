import { api, store, isFinal } from "../api.js";
import { h, icon, clear, artFor, toast } from "../ui.js";
import { starButton } from "../favs.js";

const meter = n => h("div", { class: "meter", "aria-label": `${n} de 5` }, [1, 2, 3, 4, 5].map(i => h("i", { class: i <= n ? "on" : "" })));

const gb = bytes => bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1).replace(".", ",")} GB` : `${Math.round(bytes / 1e6)} MB`;
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
  root.append(h("a", { class: "crumb", href: "#/library" }, icon("chevron-left", "sm"), "Biblioteca"),
    h("div", { class: "detail" },
      h("div", { class: "stack" }, h("div", { class: "mcover" }, artFor("model", key), h("h1", null, m.title), starButton("model", `receita:${key}`, { title: m.title })),
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
