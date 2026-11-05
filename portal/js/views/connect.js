import { api, session, studioOrigin } from "../api.js";
import { h, icon } from "../ui.js";

export function connectView(onDone) {
  const same = session.sameOrigin;
  const status = h("p", { class: "hint", role: "status", "aria-live": "polite" });
  const address = h("input", { class: "input", type: "url", inputmode: "url", placeholder: "https://sua-sessao.gradio.live", required: true, autocomplete: "off", value: session.origin || "" });
  const password = h("input", { class: "input", type: "password", required: true, autocomplete: "off", placeholder: "Senha impressa no Colab" });
  const submit = h("button", { class: "btn primary lg block", type: "submit" }, "Entrar no Studio");
  const form = h("form", { class: "stack", onsubmit: async e => {
    e.preventDefault();
    let origin = null;
    if (!same) {
      origin = studioOrigin(address.value);
      if (!origin) { status.textContent = "Use o link gradio.live impresso na última célula do Colab."; return; }
    }
    submit.disabled = true; status.textContent = "Conectando…";
    try { await api.connect(origin, password.value); password.value = ""; onDone(); }
    catch (error) { status.textContent = error.status === 401 ? "Senha inválida. Copie de novo a senha da sessão." : error.message; submit.disabled = false; }
  } },
    same ? null : h("div", { class: "field" }, h("label", { for: "addr" }, "Link do Studio"), address),
    h("div", { class: "field" }, h("label", null, "Senha da sessão"), password),
    submit, status);
  address.id = "addr";
  return h("div", { class: "gate" },
    h("div", { class: "art" }, h("img", { src: "./assets/art/hero.webp", alt: "" }), h("h1", { class: "tag" }, "Estúdio de ", h("em", null, "imagem"), " e vídeo")),
    h("div", { class: "form" }, h("div", { class: "row" }, icon("logo"), h("strong", null, "ClonField Studio")),
      h("div", { class: "stack" }, h("h2", null, "Conecte sua sessão"), h("p", null, same ? "Digite a senha que a última célula do Colab imprimiu." : "Cole o link público e a senha que a última célula do Colab imprimiu.")), form));
}
