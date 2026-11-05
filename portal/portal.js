"use strict";

const form = document.querySelector("#connect");
const address = document.querySelector("#address");
const password = document.querySelector("#password");
const reveal = document.querySelector("#reveal");
const button = document.querySelector("#submit");
const status = document.querySelector("#status");

function publicOrigin(value) {
  try {
    const url = new URL(value.trim());
    if (url.protocol === "https:" && /^[a-z0-9-]+\.gradio\.live$/i.test(url.hostname) &&
        !url.username && !url.password && !url.port && url.pathname === "/" && !url.search && !url.hash) {
      return url.origin;
    }
  } catch {
    return null;
  }
  return null;
}

reveal.addEventListener("click", () => {
  const visible = password.type === "password";
  password.type = visible ? "text" : "password";
  reveal.textContent = visible ? "Ocultar" : "Mostrar";
  reveal.setAttribute("aria-pressed", String(visible));
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const origin = publicOrigin(address.value);
  if (!origin) {
    status.textContent = "Cole o link HTTPS do Gradio que aparece no Colab.";
    address.focus();
    return;
  }
  const secret = password.value.trim();
  if (!secret) {
    status.textContent = "Informe a senha da sessão.";
    password.focus();
    return;
  }

  const handoff = document.createElement("form");
  handoff.id = "portal-handoff";
  handoff.method = "post";
  handoff.action = new URL("/clonfield/connect", origin);
  handoff.hidden = true;
  for (const [name, value] of [["username", "clonfield"], ["password", secret]]) {
    const field = document.createElement("input");
    field.type = "hidden";
    field.name = name;
    field.value = value;
    handoff.append(field);
  }
  document.body.append(handoff);
  button.disabled = true;
  status.textContent = "Abrindo o Studio…";
  password.value = "";
  handoff.submit();
});

window.addEventListener("pageshow", () => {
  document.querySelector("#portal-handoff")?.remove();
  password.value = "";
  button.disabled = false;
  status.textContent = "";
});
