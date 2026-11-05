import { api, session, store, events, isFinal } from "./api.js";
import { h, icon, clear, toast } from "./ui.js";
import { connectView } from "./views/connect.js";
import { homeView } from "./views/home.js";
import { appsView } from "./views/apps.js";
import { appView } from "./views/app.js";
import { modelsView, modelDetail } from "./views/models.js";
import { lorasView } from "./views/loras.js";
import { historyView } from "./views/history.js";
import { jobsView } from "./views/jobs.js";
import { systemView } from "./views/system.js";

const root = document.getElementById("root");
const NAV = [["", "Início", "home"], ["apps", "Apps", "apps"], ["models", "Modelos", "cube"], ["history", "Histórico", "clock"], ["system", "Sistema", "cpu"]];
const TITLES = { "": "Início", apps: "Apps", models: "Modelos", loras: "LoRAs", history: "Histórico", jobs: "Fila", system: "Sistema" };
let page = null, shell = null, token = 0, poll = null, offline = null;

const navigate = hash => { location.hash = hash.replace(/^#/, ""); };

function mountShell() {
  const tray = h("a", { class: "pill", href: "#/jobs", "aria-label": "Fila de jobs" }, h("i", { class: "dot" }), h("span", null, "Fila vazia"));
  const tier = h("span", { class: "pill", title: "Perfil detectado" }, icon("cpu", "sm"), h("span", null, "…"));
  const outlet = h("main");
  const title = h("div", { class: "title" });
  const rail = h("nav", { class: "rail", "aria-label": "Principal" }, h("a", { class: "brand", href: "#/", "aria-label": "ClonField Studio" }, icon("logo", "")),
    NAV.map(([path, label, ic]) => h("a", { class: "nav", href: `#/${path}`, "data-path": path }, icon(ic), label)), h("div", { class: "grow" }));
  const banner = h("div", { class: "banner", role: "alert", hidden: true }, icon("alert", "sm"), h("span", null, "Conexão com o Colab perdida. Seus jobs continuam rodando lá."),
    h("button", { class: "btn sm", type: "button", onclick: () => { banner.hidden = true; route(); } }, "Tentar de novo"));
  const column = h("div", { style: { minWidth: 0 } }, banner, h("header", { class: "top" }, title, tray, tier), outlet);
  clear(root).append(h("div", { class: "shell" }, rail, column));
  shell = { outlet, tray, tier, rail, banner, title };
  api.get("/system").then(info => { store.system = info; tier.lastChild.textContent = info.tier.vram_gb ? `${info.tier.label} · ${info.tier.vram_gb.toFixed(0)} GB` : "Sem GPU"; }).catch(() => {});
}

function paintTray() {
  if (!shell) return;
  const active = store.jobs.filter(j => !isFinal(j.status));
  const dot = shell.tray.querySelector(".dot"), text = shell.tray.lastChild;
  dot.className = "dot" + (active.length ? " live" : " ok");
  text.textContent = active.length ? `${active.length} em andamento` : "Fila vazia";
}
events.addEventListener("jobs", paintTray);
events.addEventListener("offline", () => { if (shell) shell.banner.hidden = false; });
events.addEventListener("online", () => { if (shell) shell.banner.hidden = true; });
events.addEventListener("unauthorized", () => start());

function startPolling() {
  clearInterval(poll);
  const tick = () => { if (!document.hidden && session.ready) store.refreshJobs().catch(() => {}); };
  tick();
  poll = setInterval(tick, 4000);
}

async function route() {
  if (!session.ready || !shell) return;
  const mine = ++token;
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [head = "", arg] = parts;
  shell.rail.querySelectorAll("a.nav").forEach(a => a.removeAttribute("aria-current"));
  const section = head === "loras" ? "models" : head === "jobs" ? "" : head;
  shell.rail.querySelector(`a.nav[data-path="${section}"]`)?.setAttribute("aria-current", "page");
  shell.title.textContent = TITLES[head] || (head === "apps" && arg ? "App" : "");
  page?.destroy?.();
  page = null;
  clear(shell.outlet).append(h("div", { class: "view" }, h("div", { class: "skeleton", style: { height: "300px", marginTop: "24px" } })));
  try {
    let next;
    if (head === "") next = await homeView(navigate);
    else if (head === "apps") next = arg ? await appView(arg, navigate) : await appsView();
    else if (head === "models") next = arg ? await modelDetail(arg, navigate) : await modelsView();
    else if (head === "loras") next = await lorasView(navigate);
    else if (head === "history") next = await historyView(navigate);
    else if (head === "jobs") next = await jobsView(navigate);
    else if (head === "system") next = await systemView();
    else next = await homeView(navigate);
    if (mine !== token) return next.destroy?.();
    page = next;
    clear(shell.outlet).append(next.el);
    window.scrollTo({ top: 0 });
  } catch (error) {
    if (mine !== token) return;
    clear(shell.outlet).append(h("div", { class: "view" }, h("div", { class: "empty" }, icon("alert"), h("h3", null, "Não consegui abrir esta página"), h("p", null, error.message),
      h("button", { class: "btn", type: "button", onclick: route }, "Tentar de novo"))));
  }
}

function start() {
  clearInterval(poll);
  if (!session.ready) {
    shell = null;
    clear(root).append(connectView(() => start()));
    return;
  }
  mountShell();
  startPolling();
  route();
}
window.addEventListener("hashchange", route);
document.addEventListener("visibilitychange", () => !document.hidden && session.ready && store.refreshJobs().catch(() => {}));
start();
