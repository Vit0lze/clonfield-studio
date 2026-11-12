import { api, store } from "../api.js";
import { h, icon, clear, seg, illustration, fmtBytes, ago } from "../ui.js";

export async function historyView(navigate) {
  const root = h("div", { class: "view" });
  const jobs = await api.get("/jobs?limit=200");
  let kind = "all";
  const gallery = h("div", { class: "gallery" });
  const entries = jobs.filter(j => j.status === "concluído" && j.app !== "benchmark").flatMap(j => j.results.map(r => ({ r, j }))).filter(x => x.r.kind === "image" || x.r.kind === "video");
  const paint = () => {
    clear(gallery);
    const shown = entries.filter(x => kind === "all" || x.r.kind === kind);
    shown.forEach(({ r, j }, i) => gallery.append(h("button", { class: "shot", type: "button", style: { "--i": Math.min(i, 20) }, "aria-label": j.title, onclick: () => open(r, j) },
      r.kind === "image" ? h("img", { src: api.url(r.url), alt: j.title, loading: "lazy" }) : h("video", { src: api.url(r.url), muted: true, preload: "metadata" }),
      r.kind === "video" ? h("span", { class: "kind" }, icon("play", "sm"), "vídeo") : null)));
    if (!shown.length) gallery.replaceChildren(h("div", { class: "empty" }, illustration("empty"), h("h3", null, "Ainda não há resultados"), h("a", { class: "btn primary", href: "#/apps" }, "Criar algo agora")));
  };
  function open(r, j) {
    const close = () => { scrim.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = e => e.key === "Escape" && close();
    document.addEventListener("keydown", onKey);
    const scrim = h("div", { class: "scrim", onclick: e => e.target === scrim && close() },
      h("div", { class: "lightbox", role: "dialog", "aria-label": j.title },
        h("div", { class: "media" }, r.kind === "video" ? h("video", { src: api.url(r.url), controls: true, autoplay: true, loop: true }) : h("img", { src: api.url(r.url), alt: j.title })),
        h("div", { class: "side" }, h("h3", null, j.title), h("p", { class: "mono dim" }, `${r.name} · ${fmtBytes(r.size)} · há ${ago(j.created)}`),
          h("a", { class: "btn primary", href: api.url(r.url), download: r.name }, icon("download", "sm"), "Baixar"),
          h("button", { class: "btn", type: "button", onclick: () => { close(); navigate(`#/apps/${j.app}`); store.lastJob(j.app, j.id); } }, "Abrir no app"),
          h("button", { class: "btn ghost", type: "button", onclick: close }, "Fechar"))));
    document.body.append(scrim);
  }
  root.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Histórico"), h("p", null, `${entries.length} resultados guardados nesta sessão do Studio.`))),
    h("div", { class: "libhead" }, seg([{ value: "all", label: "Tudo" }, { value: "image", label: "Imagens" }, { value: "video", label: "Vídeos" }], kind, v => { kind = v; paint(); })), gallery);
  paint();
  return { el: root };
}
