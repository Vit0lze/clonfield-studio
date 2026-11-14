import { api, store } from "../api.js";
import { h, icon, clear, toast, artFor, illustration, appGlyph } from "../ui.js";
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
  const uploads = [];
  const media = { get size() { return new Set(uploads.map(u => u.kind)).size; }, kinds: () => [...new Set(uploads.filter(u => !u.pending).map(u => u.kind))] };
  const thumbs = h("div", { class: "home-thumbs" });
  const picker = h("input", { type: "file", class: "sr", multiple: true, accept: "image/*,video/*", onchange: () => attach([...picker.files]) });
  const paintThumbs = () => { clear(thumbs); uploads.forEach((u, i) => thumbs.append(h("span", { class: "home-thumb" }, u.kind === "image" && u.url ? h("img", { src: api.url(u.url), alt: u.name }) : h("span", null, u.name.slice(0, 10)),
    u.pending ? h("i", { class: "bar", style: { transform: `scaleX(${u.progress || 0.05})` } }) : null,
    h("button", { type: "button", "aria-label": `Remover ${u.name}`, onclick: () => { uploads.splice(i, 1); paintThumbs(); } }, icon("x", "sm"))))); };
  async function attach(files) {
    for (const file of files) {
      const item = { name: file.name, kind: file.type.startsWith("video") ? "video" : "image", pending: true, progress: 0 };
      uploads.push(item); paintThumbs();
      try { Object.assign(item, await api.upload(file, p => { item.progress = p; paintThumbs(); }), { pending: false }); }
      catch (error) { uploads.splice(uploads.indexOf(item), 1); toast(error.message, "err"); }
      paintThumbs();
    }
    picker.value = "";
  }
  const attachButton = h("button", { class: "btn sm", type: "button", onclick: () => picker.click() }, icon("plus", "sm"), "Anexar imagem ou vídeo");
  const plan = h("div", { class: "plan", "aria-live": "polite" });
  // Fields an attached file can fill in the opened app, by kind.
  const FILL = { image: ["refs", "image", "source", "before", "media"], video: ["video", "videos", "media"] };
  const fillFor = () => { const values = {}; for (const kind of ["image", "video"]) { const list = uploads.filter(u => !u.pending && u.kind === kind); if (list.length) FILL[kind].forEach(k => { values[k] = list; }); } return values; };
  const suggest = async button => {
    if (!input.value.trim()) return input.focus();
    if (uploads.some(u => u.pending)) return toast("Aguarde o envio terminar.", "err");
    button.disabled = true; plan.replaceChildren(h("span", { class: "muted" }, "Montando o caminho…"));
    try {
      const result = await api.post("/plan", { request: input.value.trim(), media: media.kinds() });
      const steps = result.steps.filter(s => s.app);
      plan.replaceChildren(...(steps.length ? steps.flatMap((s, i) => [i ? icon("chevron-right", "sm") : null, h("a", { class: "plan-step", href: `#/apps/${s.app}`,
        title: `Confiança ${Math.round(s.probability * 100)}%`, onclick: () => store.prefill({ app: s.app, values: { prompt: input.value.trim(), ...fillFor() } }) },
        appGlyph(s.app, "sm"), s.title)]).filter(Boolean) : [h("span", { class: "muted" }, result.conversation ? "Isso parece uma pergunta, não um pedido. Abra o Chat para conversar." : "Nenhum app disponível para este pedido com o que você anexou.")]));
    } catch (error) {
      plan.replaceChildren(h("span", { class: "muted" }, error.message || "Não consegui planejar agora."));
    } finally { button.disabled = false; }
  };
  const suggestButton = h("button", { class: "btn lg", type: "button", onclick: e => suggest(e.currentTarget) }, icon("sparkle", "sm"), "Sugerir");
  root.append(h("section", { class: "hero" },
    h("div", { class: "art" }, h("img", { src: "./assets/art/hero.webp", alt: "" })),
    h("h1", null, "A sala está ", h("em", null, "escura"), ". O que projetamos hoje?"),
    h("div", { class: "quick" }, input, h("div", { class: "quick-actions" }, suggestButton, h("button", { class: "btn primary lg", type: "button", onclick: go }, icon("sparkle", "sm"), "Criar"))),
    h("div", { class: "plan-have" }, attachButton, picker, thumbs), plan));

  const recent = h("div");
  const featured = h("div", { class: "mosaic" });
  root.append(recent, h("div", { class: "section-head" }, h("div", null, h("h2", null, "Apps"), h("p", null, "Cada ferramenta tem sua própria página, com controles que se ajustam à sua placa."))
    , h("a", { class: "btn", href: "#/apps" }, "Ver todos", icon("arrow-right", "sm"))), featured);

  const [apps, jobs] = await Promise.all([store.loadApps(), api.get("/jobs?limit=40").catch(() => [])]);
  store.jobs = jobs;
  const shots = jobs.filter(j => j.status === "concluído" && j.app !== "benchmark").flatMap(j => j.results.map(r => ({ r, j }))).filter(x => x.r.kind !== "audio" && x.r.kind !== "file").slice(0, 12);
  if (shots.length) {
    recent.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Continue de onde parou")), h("a", { class: "btn ghost", href: "#/history" }, "Histórico", icon("chevron-right", "sm"))),
      h("div", { class: "strip" }, shots.map(({ r, j }, i) => h("a", { class: "shot", href: "#/history", style: { "--i": i }, title: j.title },
        r.kind === "image" ? h("img", { src: api.url(r.url), alt: j.title, loading: "lazy" }) : h("video", { src: api.url(r.url), muted: true, preload: "metadata" })))));
  }
  const pick = ["create", "animate", "edit", "seedvr2", "portrait", "upscale"].map(id => apps.find(a => a.id === id)).filter(Boolean);
  pick.forEach((app, i) => featured.append(appTile(app, i, i === 0 || i === 3)));
  return { el: root };
}
