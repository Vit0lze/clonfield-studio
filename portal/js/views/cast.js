// Elenco: characters saved once (name, short description, optional picture) and called by @name in any prompt.
import { api } from "../api.js";
import { h, icon, toast, clear } from "../ui.js";

export async function castView() {
  const root = h("div", { class: "view" });
  const grid = h("div", { class: "cast-grid" });
  let items = await api.get("/cast");
  let picked = null;  // the uploaded picture for the form: { id, name }

  const name = h("input", { class: "input", id: "cast-name", placeholder: "Marina", maxlength: 24, "aria-label": "Nome do personagem", autocomplete: "off" });
  const about = h("textarea", { class: "input", rows: 3, maxlength: 400, "aria-label": "Descrição do personagem", placeholder: "Mulher de 30 anos, cabelo ruivo curto, jaqueta jeans, sardas." });
  const file = h("input", { type: "file", accept: "image/*", hidden: true, "aria-label": "Imagem do personagem" });
  const status = h("span", { class: "muted" }, "Sem imagem: só a descrição entra no pedido.");
  const save = h("button", { class: "btn primary", type: "button", onclick: async () => {
    save.disabled = true;
    try {
      const made = await api.post("/cast/create", { name: name.value, description: about.value, upload: picked?.id || "" });
      items = [...items, made];
      name.value = about.value = ""; picked = null; file.value = "";
      status.textContent = "Sem imagem: só a descrição entra no pedido.";
      toast(`@${made.name} entrou no elenco.`);
      paint();
    } catch (error) { toast(error.message || "Não consegui salvar.", "err"); } finally { save.disabled = false; }
  } }, icon("plus", "sm"), "Adicionar ao elenco");
  const pick = h("button", { class: "btn", type: "button", onclick: () => file.click() }, icon("image", "sm"), "Escolher imagem");
  file.addEventListener("change", async () => {
    const chosen = file.files?.[0];
    if (!chosen) return;
    status.textContent = "Enviando…";
    try { picked = await api.upload(chosen); status.textContent = `Imagem: ${picked.name}`; } catch (error) { picked = null; status.textContent = error.message; }
  });

  function paint() {
    clear(grid);
    if (!items.length) grid.append(h("div", { class: "empty" }, icon("user"), h("h3", null, "O elenco está vazio"), h("p", null, "Cadastre um personagem e use @nome em qualquer pedido de imagem ou vídeo.")));
    for (const item of items) {
      grid.append(h("article", { class: "cast-card", "data-name": item.name },
        item.image ? h("img", { src: api.url(item.image), alt: `Imagem de ${item.name}`, loading: "lazy" }) : h("div", { class: "cast-noimg" }, icon("user")),
        h("div", { class: "cast-body" }, h("h3", null, `@${item.name}`), h("p", { class: "muted" }, item.description || "Sem descrição."),
          h("button", { class: "btn sm", type: "button", "aria-label": `Remover ${item.name}`, onclick: async () => {
            if (!confirm(`Remover @${item.name} do elenco?`)) return;
            try { await api.del(`/cast/${item.id}`); items = items.filter(x => x.id !== item.id); paint(); } catch (error) { toast(error.message, "err"); }
          } }, icon("x", "sm"), "Remover"))));
    }
  }
  paint();
  root.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Elenco"), h("p", null, "Personagens salvos. Escreva @nome no pedido: a descrição entra no texto e a imagem vira referência quando o modelo aceita."))),
    h("section", { class: "cast-form" }, h("label", { for: "cast-name" }, "Nome"), name, h("label", null, "Descrição"), about, h("div", { class: "row" }, pick, file, status), save), grid);
  return { el: root };
}
