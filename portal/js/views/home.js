import { api, store } from "../api.js";
import { h, icon, artFor, illustration } from "../ui.js";
import { appTile } from "./apps.js";

export async function homeView(navigate) {
  const root = h("div", { class: "view" });
  const input = h("textarea", { placeholder: "Descreva uma imagem… ex.: retrato de uma capivara astronauta, luz de estúdio, 85mm", rows: 2,
    onkeydown: e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(); } } });
  const go = () => {
    if (!input.value.trim()) return input.focus();
    store.prefill({ app: "create", values: { prompt: input.value.trim() } });
    navigate("#/apps/create");
  };
  root.append(h("section", { class: "hero" },
    h("div", { class: "art" }, h("img", { src: "./assets/art/hero.webp", alt: "" })),
    h("h1", null, "A sala está ", h("em", null, "escura"), ". O que projetamos hoje?"),
    h("div", { class: "quick" }, input, h("button", { class: "btn primary lg", type: "button", onclick: go }, icon("sparkle", "sm"), "Criar"))));

  const recent = h("div");
  const featured = h("div", { class: "mosaic" });
  root.append(recent, h("div", { class: "section-head" }, h("div", null, h("h2", null, "Apps"), h("p", null, "Cada ferramenta tem sua própria página, com controles que se ajustam à sua placa."))
    , h("a", { class: "btn", href: "#/apps" }, "Ver todos", icon("arrow-right", "sm"))), featured);

  const [apps, jobs] = await Promise.all([store.loadApps(), api.get("/jobs?limit=40").catch(() => [])]);
  store.jobs = jobs;
  const shots = jobs.filter(j => j.status === "concluído").flatMap(j => j.results.map(r => ({ r, j }))).filter(x => x.r.kind !== "audio" && x.r.kind !== "file").slice(0, 12);
  if (shots.length) {
    recent.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Continue de onde parou")), h("a", { class: "btn ghost", href: "#/history" }, "Histórico", icon("chevron-right", "sm"))),
      h("div", { class: "strip" }, shots.map(({ r, j }, i) => h("a", { class: "shot", href: "#/history", style: { "--i": i }, title: j.title },
        r.kind === "image" ? h("img", { src: api.url(r.url), alt: j.title, loading: "lazy" }) : h("video", { src: api.url(r.url), muted: true, preload: "metadata" })))));
  }
  const pick = ["create", "animate", "edit", "seedvr2", "portrait", "upscale"].map(id => apps.find(a => a.id === id)).filter(Boolean);
  pick.forEach((app, i) => featured.append(appTile(app, i, i === 0 || i === 3)));
  return { el: root };
}
