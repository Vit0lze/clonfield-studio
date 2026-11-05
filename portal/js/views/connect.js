import { api, session, studioOrigin } from "../api.js";
import { h, icon } from "../ui.js";

export function connectView(onDone) {
  const same = session.sameOrigin;
  const status = h("p", { class: "hint", role: "status", "aria-live": "polite" });
  const params = new URLSearchParams(location.search);
  const remembered = (() => { try { return localStorage.getItem("cf-last-origin") || ""; } catch { return ""; } })();
  const address = h("input", { class: "input", type: "text", inputmode: "url", placeholder: "https://sua-sessao.gradio.live", required: true, autocomplete: "off", spellcheck: "false",
    value: params.get("api") || session.origin || remembered });
  const password = h("input", { class: "input", type: "password", required: true, autocomplete: "off", placeholder: "Senha impressa no Colab" });
  const submit = h("button", { class: "btn primary lg block", type: "submit" }, "Entrar no Studio");
  const form = h("form", { class: "stack", onsubmit: async e => {
    e.preventDefault();
    let origin = null;
    if (!same) {
      origin = studioOrigin(address.value.trim().replace(/^(?!https?:\/\/)/i, "https://"));
      if (!origin) { status.textContent = "Use o link gradio.live impresso na última célula do Colab."; return; }
    }
    submit.disabled = true; status.textContent = "Conectando…";
    try {
      await api.connect(origin, password.value.trim()); password.value = "";
      try { if (origin) localStorage.setItem("cf-last-origin", origin); } catch { /* private mode */ }
      onDone();
    }
    catch (error) { status.textContent = error.status === 401 ? "Senha inválida. Copie de novo a senha da sessão." : error.message; submit.disabled = false; }
  } },
    same ? null : h("div", { class: "field" }, h("label", { for: "addr" }, "Link da API do Colab"), address, h("span", { class: "hint" }, "O link gradio.live que a última célula imprime.")),
    h("div", { class: "field" }, h("label", null, same ? "Senha da sessão" : "Senha (Bearer)"), password, same ? null : h("span", { class: "hint" }, "Vai como Bearer em cada chamada. Só quem tem o link e a senha controla a GPU.")),
    submit, status,
    same ? null : h("p", { class: "hint" }, "Ainda sem sessão? ", h("a", { href: "https://colab.research.google.com/github/Vit0lze/clonfield-studio/blob/main/ClonField_Colab.ipynb", target: "_blank", rel: "noopener noreferrer" }, "Abra o notebook no Colab"), " e rode a última célula."));
  address.id = "addr";
  return h("div", { class: "gate" },
    h("div", { class: "art" }, h("img", { src: "./assets/art/hero.webp", alt: "" }), h("h1", { class: "tag" }, "Estúdio de ", h("em", null, "imagem"), " e vídeo")),
    h("div", { class: "form" }, h("div", { class: "row" }, icon("logo"), h("strong", null, "ClonField Studio")),
      h("div", { class: "stack" }, h("h2", null, "Conecte sua sessão"), h("p", null, same ? "Digite a senha que a última célula do Colab imprimiu." : "Este painel é público. Ele fala com a GPU do Colab pelo link e pela senha da sua sessão.")), form));
}
