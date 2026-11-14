// Chat: persistent sessions. A message becomes a path (the router proposes, you press «Executar» per step); every original,
// job and result stays inside the session, so projects never mix references.
// Layout: a quiet transcript. Your lines are pills, the assistant writes plain text, the path is a rail of steps, a result is a
// framed picture. Session media lives in a drawer instead of repeating every image under the thread.
import { api, store, isFinal } from "../api.js";
import { h, icon, clear, toast, appGlyph } from "../ui.js";

const when = ts => {
  const d = new Date(ts * 1000), today = new Date();
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
};
const WEAK = 0.6;  // below this, extra steps are tucked under «Outros caminhos» instead of competing with the main one

export async function chatView(navigate, sessionId) {
  const root = h("div", { class: "view chatview" });
  let sessions = await api.get("/sessions");
  const llm = await api.get("/llm").catch(() => ({ available: false }));
  let session = null, pending = [], sending = false, armedDelete = null, drawerOpen = false, poller = null;
  const followers = new Map(), snaps = new Map(), updaters = new Map(), drafts = new Map();
  const unmount = () => { followers.forEach(f => f.stop()); clearInterval(poller); };

  const pref = (key, value) => { try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch { /* storage unavailable */ } return null; };
  let collapsed = pref("cf-chat-side") === "1";
  const list = h("nav", { class: "chat-list", "aria-label": "Conversas" });
  const sideToggle = h("button", { class: "side-toggle", type: "button", onclick: () => setCollapsed(!collapsed) });
  const side = h("aside", { class: "chat-side" });
  const shell = h("div", { class: "chat" });
  function setCollapsed(value) {
    collapsed = value; pref("cf-chat-side", value ? "1" : "0");
    shell.classList.toggle("side-collapsed", collapsed);
    sideToggle.setAttribute("aria-expanded", String(!collapsed));
    sideToggle.setAttribute("aria-label", collapsed ? "Mostrar conversas" : "Recolher conversas");
    sideToggle.title = collapsed ? "Mostrar conversas" : "Recolher conversas";
  }
  const head = h("header", { class: "chat-head" });
  const drawer = h("div", { class: "media-drawer", hidden: true });
  const thread = h("div", { class: "chat-thread", role: "log", "aria-live": "polite" });
  const chips = h("div", { class: "composer-chips" });
  const input = h("textarea", { class: "composer-input", rows: 1, placeholder: "O que vamos criar?", "aria-label": "Mensagem",
    oninput: () => grow(), onkeydown: e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } } });
  const grow = () => { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 160)}px`; };
  const picker = h("input", { type: "file", class: "sr", multiple: true, accept: "image/*,video/*,audio/*", onchange: () => attach([...picker.files]) });
  const sendButton = h("button", { class: "send", type: "button", "aria-label": "Enviar", onclick: () => send() }, icon("arrow-right"));

  // ------------------------------------------------------------------ sessions
  function paintList() {
    clear(list);
    list.append(h("button", { class: "new-chat", type: "button", title: "Nova conversa", "aria-label": "Nova conversa", onclick: newSession }, icon("plus", "sm"), h("span", null, "Nova conversa")));
    for (const s of sessions) {
      const confirming = armedDelete === s.id;
      list.append(h("div", { class: `chat-item${session?.id === s.id ? " on" : ""}` },
        h("button", { class: "chat-open", type: "button", "aria-current": session?.id === s.id ? "true" : null, onclick: () => navigate(`#/chat/${s.id}`) },
          h("b", null, s.title), h("span", null, when(s.updated))),
        h("button", { class: `chat-del${confirming ? " armed" : ""}`, type: "button", "aria-label": confirming ? "Confirmar exclusão" : `Excluir ${s.title}`,
          onclick: () => confirming ? remove(s.id) : (armedDelete = s.id, paintList(), setTimeout(() => { if (armedDelete === s.id) { armedDelete = null; paintList(); } }, 4000)) },
          confirming ? "Excluir?" : icon("trash", "sm"))));
    }
  }
  async function refreshList() { sessions = await api.get("/sessions"); paintList(); }
  async function newSession() { const created = await api.post("/sessions", {}); await refreshList(); navigate(`#/chat/${created.id}`); }
  async function remove(id) {
    armedDelete = null;
    await api.post(`/sessions/${id}/delete`, {});
    toast("Conversa excluída. Os arquivos gerados continuam no Histórico.");
    await refreshList();
    if (session?.id === id) navigate("#/chat");
  }

  // ------------------------------------------------------------------ header + media drawer
  function paintHead() {
    clear(head);
    const count = session.media.length;
    const title = h("h2", { class: "chat-title", tabindex: "0", title: "Clique para renomear", onclick: () => rename(title) }, session.title);
    head.append(title, h("div", { class: "chat-head-actions" },
      llm.available ? h("span", { class: "tip", tabindex: "0", role: "img", title: `Modelo local (${llm.model}), rodando no seu Colab. Nada do que você escreve ou anexa sai do seu ambiente.`,
        "aria-label": "Respostas escritas por um modelo local" }, "i") : null,
      h("button", { class: "chip-btn", type: "button", "aria-expanded": String(drawerOpen), disabled: !count, onclick: () => { drawerOpen = !drawerOpen; paintHead(); paintDrawer(); } },
        icon("image", "sm"), `${count} ${count === 1 ? "mídia" : "mídias"}`)));
  }
  function rename(node) {
    const field = h("input", { class: "chat-title edit", value: session.title, maxlength: 80, "aria-label": "Nome da conversa" });
    const done = async save => {
      if (save && field.value.trim() && field.value.trim() !== session.title) {
        session.title = field.value.trim();
        await api.post(`/sessions/${session.id}/rename`, { title: session.title }).catch(error => toast(error.message, "err"));
        refreshList();
      }
      paintHead();
    };
    field.addEventListener("keydown", e => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
    field.addEventListener("blur", () => done(true));
    node.replaceWith(field); field.focus(); field.select();
  }
  function paintDrawer() {
    drawer.hidden = !drawerOpen || !session.media.length;
    clear(drawer);
    if (drawer.hidden) return;
    drawer.append(...session.media.map(m => h("figure", { class: "drawer-item" }, thumb(m, "sm"), h("figcaption", null, m.origin === "result" ? "resultado" : "original"))));
  }

  // ------------------------------------------------------------------ thread
  const media = id => session.media.find(m => m.id === id);
  const thumb = (m, size = "md") => {
    if (!m || m.gone || !m.url) return h("span", { class: `thumb ${size} file` }, m?.gone ? "expirou" : "?");
    if (m.kind === "image") return h("a", { class: `thumb ${size}`, href: api.url(m.url), target: "_blank", rel: "noopener", "aria-label": `Abrir ${m.name}` }, h("img", { src: api.url(m.url), alt: m.name, loading: "lazy" }));
    if (m.kind === "video") return h("video", { class: `thumb ${size}`, src: api.url(m.url), controls: true, muted: true, preload: "metadata" });
    return h("span", { class: `thumb ${size} file` }, m.name);
  };
  const stepRun = (index, step) => {
    const job = session.messages.slice(index + 1).find(m => m.role === "job" && m.app === step.app);
    return job ? { ...job, status: snaps.get(job.job)?.status || "enviado" } : null;
  };

  function pathBlock(message, index) {
    const plan = message.plan;
    const promptBox = h("textarea", { class: "path-prompt", rows: 1, "aria-label": "Prompt usado nos passos", value: drafts.get(message.id) ?? plan.prompt ?? plan.text,
      oninput: () => { drafts.set(message.id, promptBox.value); autogrow(promptBox); } });
    const autogrow = el => { el.style.height = "auto"; el.style.height = `${el.scrollHeight}px`; };
    requestAnimationFrame(() => autogrow(promptBox));

    const strong = plan.steps.filter((s, i) => i === 0 || (s.probability ?? 1) >= WEAK);
    const weak = plan.steps.filter(s => !strong.includes(s));
    const nextIndex = strong.findIndex(s => !stepRun(index, s) && !s.missing?.length);

    const row = (step, i, primary) => {
      const ran = stepRun(index, step);
      const blocked = step.missing?.length && !ran;
      const waits = blocked && i > 0;
      return h("li", { class: `step${ran ? " done" : ""}${blocked && !waits ? " blocked" : ""}` },
        h("span", { class: "step-dot", "aria-hidden": "true" }, ran?.status === "concluído" ? icon("check", "sm") : String(i + 1)),
        h("div", { class: "step-main" },
          h("span", { class: "step-title" }, appGlyph(step.app, "sm"), h("b", null, step.title)),
          h("small", null, ran ? (ran.status === "concluído" ? "pronto" : ran.status) : blocked ? (waits ? "usa o resultado do passo anterior" : `falta ${step.missing.join(", ").toLowerCase()}`)
            : step.probability != null ? `${Math.round(step.probability * 100)}% de certeza` : "")),
        h("div", { class: "step-actions" },
          ran ? null : h("button", { class: `btn sm${primary ? " primary" : ""}`, type: "button", disabled: blocked && !waits, title: blocked && !waits ? `Falta ${step.missing.join(", ")}` : "",
            onclick: e => run(promptBox.value, step, e.currentTarget) }, "Executar"),
          h("a", { class: "step-open", href: `#/apps/${step.app}`, title: "Abrir no app com este prompt", onclick: () => store.prefill({ app: step.app, values: { prompt: promptBox.value } }) }, icon("external", "sm"))));
    };

    return h("div", { class: "path" },
      h("p", { class: "path-label" }, plan.provider !== "local" ? "Caminho sugerido" : "Caminho (heurística local)", h("span", null, " · você aprova cada passo")),
      plan.note ? h("p", { class: "path-note" }, icon("alert", "sm"), plan.note) : null,
      plan.steps.length ? h("div", { class: "path-prompt-wrap" }, h("span", { class: "path-prompt-tag" }, "Prompt"), promptBox) : null,
      !plan.steps.length ? h("p", { class: "muted" }, "Nenhum app serve para isso com as mídias e a placa atuais. Anexe a mídia certa ou descreva de outro jeito.") : null,
      h("ol", { class: "steps" }, strong.map((s, i) => row(s, plan.steps.indexOf(s), i === nextIndex))),
      weak.length ? h("details", { class: "weak" }, h("summary", null, `Outros caminhos (${weak.length})`), h("ol", { class: "steps" }, weak.map(s => row(s, plan.steps.indexOf(s), false)))) : null);
  }

  function resultBlock(message) {
    const status = h("span", { class: "result-status" }, "enviado");
    const bar = h("i", { style: { transform: "scaleX(0.02)" } });
    const track = h("div", { class: "result-bar", role: "progressbar" }, bar);
    const frames = h("div", { class: "result-frames" });
    const card = h("div", { class: "result" }, h("div", { class: "result-head" }, appGlyph(message.app, "sm"), h("b", null, message.title), status), track, frames);
    const paintFrames = () => {
      clear(frames);
      session.media.filter(m => m.job === message.job).forEach(m => frames.append(h("figure", { class: "frame" }, thumb(m, "lg"),
        h("figcaption", null, h("a", { href: api.url(m.url), download: m.name }, "Baixar")))));
    };
    const apply = snap => {
      const final = isFinal(snap.status);
      status.textContent = final ? (snap.status === "concluído" ? (snap.message ? snap.message.slice(0, 90) : "pronto") : snap.message || snap.status) : (snap.desc || "").slice(0, 70);
      bar.style.transform = `scaleX(${final ? 1 : Math.max(0.02, Math.min(1, snap.fraction || 0))})`;
      track.hidden = final;
      card.classList.toggle("fail", final && snap.status !== "concluído");
    };
    paintFrames();
    updaters.set(message.job, apply);
    if (snaps.has(message.job)) apply(snaps.get(message.job));
    if (!followers.has(message.job)) {
      followers.set(message.job, api.follow(message.job, async snap => {
        snaps.set(message.job, snap);
        updaters.get(message.job)?.(snap);
        if (isFinal(snap.status)) { session = await api.get(`/sessions/${session.id}`); paintAll(); }
      }));
    }
    return card;
  }

  // The agent's real tool calls, as they happen: what it asked for, whether it worked, how long it took.
  const TOOL_LABEL = { list_capabilities: "Procurou capacidades", inspect_capability: "Leu uma capacidade", list_media: "Viu as mídias", validate_graph: "Validou o grafo",
    estimate_resources: "Estimou recursos", execute_graph: "Executou o grafo", job_status: "Consultou o job", inspect_artifact: "Mediu o resultado" };
  function traceBlock(m, open) {
    const trace = m.agent?.trace || [];
    if (!trace.length) return null;
    const meta = [m.agent.provider, m.agent.model].filter(Boolean).join(" · ");
    return h("details", { class: "agent-trace", open: open || undefined },
      h("summary", null, `Passos do agente (${trace.length})`, meta ? h("span", { class: "dim" }, ` · ${meta}`) : null),
      h("ol", null, trace.map(t => h("li", { class: t.ok ? "ok" : "bad", title: t.result },
        h("b", null, TOOL_LABEL[t.tool] || t.tool), h("code", null, ` ${String(t.args || "").slice(0, 90)}`), h("small", { class: "dim" }, ` ${t.ok ? "ok" : "recusado"} · ${t.ms} ms`)))));
  }

  function paintThread() {
    clear(thread);
    if (!session.messages.length) {
      thread.append(h("div", { class: "chat-empty" }, h("h3", null, "O que vamos criar?"),
        h("p", null, "Descreva o resultado e anexe as mídias. O agente monta e executa os passos; você vê cada ferramenta que ele usa."),
        h("ul", { class: "try" }, ["troca a roupa dessa foto, amplia 2x e recorta pra story", "um clipe de drone sobre uma floresta", "separa esse desenho anime em camadas"].map(t =>
          h("li", null, h("button", { type: "button", onclick: () => { input.value = t; grow(); input.focus(); } }, t))))));
    }
    session.messages.forEach((m, i) => {
      if (m.role === "user") {
        thread.append(h("div", { class: "msg user" }, m.media?.length ? h("div", { class: "msg-media" }, m.media.map(id => thumb(media(id), "sm"))) : null, m.text ? h("p", null, m.text) : null));
      } else if (m.role === "assistant" && m.plan) {
        thread.append(h("div", { class: "msg bot" }, pathBlock(m, i)));
      } else if (m.role === "assistant" && m.kind === "text") {
        if (m.pending) thread.append(h("div", { class: "msg bot typing", "aria-label": m.agent ? "O agente está trabalhando" : "O modelo local está escrevendo" },
          h("span", { class: "dots" }, h("i"), h("i"), h("i")), traceBlock(m, true)));
        else if (m.text) thread.append(h("div", { class: `msg bot${m.error ? " warn" : ""}` }, h("p", null, m.text), m.question ? h("p", { class: "ask" }, m.question) : null, traceBlock(m, false)));
      } else if (m.role === "job") {
        thread.append(h("div", { class: "msg bot" }, resultBlock(m)));
      }
    });
    thread.scrollTop = thread.scrollHeight;
  }
  const paintAll = () => { paintList(); paintHead(); paintDrawer(); paintThread(); watchPending(); };

  // The path is instant; the local model's text arrives seconds later, so poll while a reply is pending.
  function watchPending() {
    const waiting = session?.messages.some(m => m.pending);
    if (!waiting) { clearInterval(poller); poller = null; return; }
    if (poller) return;
    let tries = 0;
    poller = setInterval(async () => {
      if (++tries > 400) { clearInterval(poller); poller = null; return; }
      try {
        const fresh = await api.get(`/sessions/${session.id}`);
        const key = s => JSON.stringify([s.messages.length, s.media.length, s.messages.map(m => [m.id, m.pending, m.text, m.agent?.trace?.length])]);
        if (key(fresh) !== key(session)) { session = fresh; paintAll(); }
      } catch { /* keep polling */ }
    }, 2500);
  }

  // ------------------------------------------------------------------ actions
  async function attach(files) {
    for (const file of files) {
      const item = { name: file.name, pending: true, progress: 0 };
      pending.push(item); paintChips();
      try { Object.assign(item, await api.upload(file, p => { item.progress = p; paintChips(); }), { pending: false }); }
      catch (error) { pending.splice(pending.indexOf(item), 1); toast(error.message, "err"); }
      paintChips();
    }
    picker.value = "";
  }
  function paintChips() {
    clear(chips);
    pending.forEach((m, i) => chips.append(h("span", { class: "chip-file" }, m.pending ? h("i", { class: "chip-bar", style: { transform: `scaleX(${m.progress || 0.05})` } }) : null,
      h("span", null, m.name), h("button", { type: "button", "aria-label": `Remover ${m.name}`, onclick: () => { pending.splice(i, 1); paintChips(); } }, icon("x", "sm")))));
  }
  async function send() {
    if (sending || !session) return;
    const text = input.value.trim();
    const ready = pending.filter(m => !m.pending);
    if (pending.some(m => m.pending)) return toast("Aguarde o envio dos anexos terminar.", "err");
    if (!text && !ready.length) return input.focus();
    sending = true; sendButton.disabled = true;
    try {
      session = await api.post(`/sessions/${session.id}/message`, { text, media: ready.map(({ id, name, kind }) => ({ id, name, kind })) });
      input.value = ""; grow(); pending = []; paintChips();
      paintAll(); refreshList();
    } catch (error) { toast(error.message, "err"); }
    finally { sending = false; sendButton.disabled = false; input.focus(); }
  }
  async function run(text, step, button) {
    button.disabled = true;
    try {
      await api.post(`/sessions/${session.id}/run`, { app: step.app, text });
      session = await api.get(`/sessions/${session.id}`);
      store.refreshJobs().catch(() => {});
      paintAll();
    } catch (error) { button.disabled = false; toast(error.message, "err"); }
  }

  // ------------------------------------------------------------------ assemble
  const composer = h("div", { class: "composer" }, chips,
    h("div", { class: "composer-bar" },
      h("button", { class: "attach", type: "button", "aria-label": "Anexar imagem, vídeo ou áudio", title: "Anexar", onclick: () => picker.click() }, icon("plus")),
      picker, input, sendButton));
  side.append(h("div", { class: "side-head" }, h("span", { class: "side-title" }, icon("comment", "sm"), "Conversas"), sideToggle), list);
  shell.append(side, h("section", { class: "chat-main" }, head, drawer, thread, composer));
  root.append(shell);
  setCollapsed(collapsed);

  if (sessionId) {
    try { session = await api.get(`/sessions/${sessionId}`); }
    catch { toast("Essa conversa não existe mais.", "err"); sessionId = null; }
  }
  if (!session) {
    if (sessions.length) navigate(`#/chat/${sessions[0].id}`);
    else { session = await api.post("/sessions", {}); sessions = await api.get("/sessions"); }
  }
  if (session) { paintAll(); if (!session.messages.length) input.focus(); } else paintList();
  return { el: root, destroy: unmount };
}
