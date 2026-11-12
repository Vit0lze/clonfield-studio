// Chat: persistent sessions. A message becomes a plan (the router proposes, you press «Executar» per step); every original,
// job and result stays inside the session, so projects never mix references.
import { api, store, isFinal } from "../api.js";
import { h, icon, clear, toast, appGlyph, fmtClock } from "../ui.js";

const when = ts => new Date(ts * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

export async function chatView(navigate, sessionId) {
  const root = h("div", { class: "view chatview" });
  let sessions = await api.get("/sessions");
  let session = null, pending = [], followers = new Map(), sending = false, armedDelete = null;
  const snaps = new Map(), updaters = new Map();  // last snapshot per job + the card currently showing it
  const unmount = () => followers.forEach(f => f.stop());

  const list = h("div", { class: "chat-list", role: "list" });
  const thread = h("div", { class: "chat-thread", "aria-live": "polite" });
  const strip = h("div", { class: "media-strip" });
  const chips = h("div", { class: "composer-chips" });
  const input = h("textarea", { class: "input", rows: 2, placeholder: "Descreva o que quer fazer. Anexe imagens ou vídeos com o clipe.", "aria-label": "Mensagem",
    onkeydown: e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } } });
  const picker = h("input", { type: "file", class: "sr", multiple: true, accept: "image/*,video/*,audio/*", onchange: () => attach([...picker.files]) });
  const sendButton = h("button", { class: "btn primary", type: "button", onclick: () => send() }, icon("bolt", "sm"), "Enviar");

  // ------------------------------------------------------------------ sessions list
  function paintList() {
    clear(list);
    list.append(h("button", { class: "btn block", type: "button", onclick: newSession }, icon("plus", "sm"), "Nova conversa"));
    if (!sessions.length) list.append(h("p", { class: "muted pad" }, "Nenhuma conversa ainda. Cada uma guarda suas próprias mídias."));
    for (const s of sessions) {
      const confirming = armedDelete === s.id;
      list.append(h("div", { class: `chat-item${session?.id === s.id ? " on" : ""}`, role: "listitem" },
        h("button", { class: "chat-open", type: "button", onclick: () => openSession(s.id) }, h("b", null, s.title), h("span", null, `${when(s.updated)} · ${s.media} mídia(s)`)),
        h("button", { class: `btn ghost sm${confirming ? " danger" : ""}`, type: "button", "aria-label": confirming ? "Confirmar exclusão" : `Excluir ${s.title}`,
          onclick: () => confirming ? remove(s.id) : (armedDelete = s.id, paintList(), setTimeout(() => { if (armedDelete === s.id) { armedDelete = null; paintList(); } }, 4000)) },
          confirming ? "Excluir de vez?" : icon("trash", "sm"))));
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
  async function openSession(id) { navigate(`#/chat/${id}`); }

  // ------------------------------------------------------------------ thread
  const media = id => session.media.find(m => m.id === id);
  const thumb = m => !m || m.gone || !m.url ? h("span", { class: "thumb file" }, m?.gone ? "expirou" : "?")
    : m.kind === "image" ? h("a", { class: "thumb", href: api.url(m.url), target: "_blank", rel: "noopener" }, h("img", { src: api.url(m.url), alt: m.name, loading: "lazy" }))
    : m.kind === "video" ? h("video", { class: "thumb", src: api.url(m.url), controls: true, muted: true, preload: "metadata" }) : h("span", { class: "thumb file" }, m.name);

  const stepState = (messageIndex, step) => {
    const job = session.messages.slice(messageIndex + 1).find(m => m.role === "job" && m.app === step.app);
    return job ? { ...job, status: snaps.get(job.job)?.status || "enviado" } : null;
  };

  function planCard(message, index) {
    const plan = message.plan;
    const label = plan.provider === "jev" ? "Plano do Jev" : "Plano (heurística local)";
    const box = h("div", { class: "plan-card" }, h("div", { class: "plan-head" }, h("b", null, label), h("span", { class: "muted" }, "Decisão só sugere: você aprova cada passo.")),
      plan.note ? h("p", { class: "sum-warn" }, icon("alert", "sm"), plan.note) : null);
    if (!plan.steps.length) box.append(h("p", { class: "muted" }, "Nenhum app disponível para isto com as mídias e a placa atuais. Anexe a mídia certa ou descreva de outro jeito."));
    plan.steps.forEach((step, i) => {
      const ran = stepState(index, step);
      const blocked = step.missing?.length && !ran;
      const waits = blocked && i > 0;
      box.append(h("div", { class: "plan-row" },
        h("span", { class: "plan-n" }, i + 1),
        appGlyph(step.app, "sm"),
        h("div", { class: "plan-main" }, h("b", null, step.title),
          blocked ? h("span", { class: "muted" }, waits ? "usa o resultado do passo anterior" : `Falta: ${step.missing.join(", ")}`)
            : step.probability != null ? h("span", { class: "muted mono" }, `${Math.round(step.probability * 100)}% de confiança`) : null),
        h("div", { class: "plan-actions" },
          ran ? h("span", { class: `sr-chip ${ran.status === "concluído" ? "ok" : ""}` }, ran.status || "enviado")
            : h("button", { class: "btn primary sm", type: "button", disabled: blocked && !waits, title: blocked && !waits ? `Falta: ${step.missing.join(", ")}` : "",
              onclick: e => run(plan.text, step, e.currentTarget) }, icon("bolt", "sm"), "Executar"),
          h("a", { class: "btn ghost sm", href: `#/apps/${step.app}`, onclick: () => store.prefill({ app: step.app, values: { prompt: plan.text } }) }, "Abrir no app"))));
    });
    return box;
  }

  function jobCard(message) {
    const state = h("span", { class: "muted mono" }, "…");
    const bar = h("i", { style: { transform: "scaleX(0.02)" } });
    const results = h("div", { class: "job-results" });
    const card = h("div", { class: "job-card" }, h("div", { class: "plan-head" }, appGlyph(message.app, "sm"), h("b", null, message.title), state), h("div", { class: "bar" }, bar), results);
    const paintResults = () => {
      clear(results);
      session.media.filter(m => m.job === message.job).forEach(m => results.append(thumb(m)));
    };
    const apply = snap => {
      state.textContent = isFinal(snap.status) ? (snap.status === "concluído" ? (snap.message || "pronto") : snap.message || snap.status) : (snap.desc || "").slice(0, 70);
      bar.style.transform = `scaleX(${isFinal(snap.status) ? 1 : Math.max(0.02, Math.min(1, snap.fraction || 0))})`;
      card.classList.toggle("fail", isFinal(snap.status) && snap.status !== "concluído");
    };
    paintResults();
    updaters.set(message.job, apply);
    if (snaps.has(message.job)) apply(snaps.get(message.job));
    if (!followers.has(message.job)) {
      followers.set(message.job, api.follow(message.job, async snap => {
        snaps.set(message.job, snap);
        updaters.get(message.job)?.(snap);
        if (isFinal(snap.status)) {
          session = await api.get(`/sessions/${session.id}`);
          paintAll();
        }
      }));
    }
    return card;
  }

  function paintThread() {
    clear(thread);
    if (!session.messages.length) {
      thread.append(h("div", { class: "empty" }, h("h3", null, "Conte o que quer criar"), h("p", null, "Ex.: «troca a roupa dessa foto, amplia 2x e recorta pra story». Eu proponho o caminho e você aprova cada passo.")));
    }
    session.messages.forEach((m, i) => {
      if (m.role === "user") thread.append(h("div", { class: "bubble user" }, m.text ? h("p", null, m.text) : null,
        m.media?.length ? h("div", { class: "bubble-media" }, m.media.map(id => thumb(media(id)))) : null));
      else if (m.role === "assistant" && m.plan) thread.append(h("div", { class: "bubble bot" }, planCard(m, i)));
      else if (m.role === "job") thread.append(h("div", { class: "bubble bot" }, jobCard(m)));
    });
    thread.scrollTop = thread.scrollHeight;
  }
  function paintStrip() {
    clear(strip);
    if (!session.media.length) return;
    strip.append(h("span", { class: "strip-title" }, "Mídia da sessão"),
      ...session.media.map(m => h("div", { class: "strip-item", title: m.name }, thumb(m), h("small", null, m.origin === "result" ? "resultado" : "original"))));
  }
  const paintAll = () => { paintList(); paintThread(); paintStrip(); };

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
    pending.forEach((m, i) => chips.append(h("span", { class: "chip-file" }, m.name, m.pending ? ` ${Math.round((m.progress || 0) * 100)}%` : "",
      h("button", { type: "button", "aria-label": `Remover ${m.name}`, onclick: () => { pending.splice(i, 1); paintChips(); } }, icon("x", "sm")))));
  }
  async function send() {
    if (sending || !session) return;
    const text = input.value.trim();
    const ready = pending.filter(m => !m.pending);
    if (pending.some(m => m.pending)) return toast("Aguarde o envio dos anexos terminar.", "err");
    if (!text && !ready.length) return input.focus();
    sending = true; sendButton.disabled = true; sendButton.textContent = "Pensando…";
    try {
      session = await api.post(`/sessions/${session.id}/message`, { text, media: ready.map(({ id, name, kind }) => ({ id, name, kind })) });
      input.value = ""; pending = []; paintChips();
      paintAll(); refreshList();
    } catch (error) { toast(error.message, "err"); }
    finally { sending = false; sendButton.disabled = false; clear(sendButton).append(icon("bolt", "sm"), "Enviar"); }
  }
  async function run(text, step, button) {
    button.disabled = true;
    try {
      await api.post(`/sessions/${session.id}/run`, { app: step.app, text });
      session = await api.get(`/sessions/${session.id}`);
      store.refreshJobs().catch(() => {});
      paintAll();
    } catch (error) {
      button.disabled = false;
      toast(error.message, "err");
    }
  }

  // ------------------------------------------------------------------ assemble
  const composer = h("div", { class: "composer" }, chips, h("div", { class: "composer-row" }, input,
    h("div", { class: "composer-actions" }, h("button", { class: "btn", type: "button", "aria-label": "Anexar mídia", onclick: () => picker.click() }, icon("upload", "sm"), "Anexar"), picker, sendButton)));
  root.append(h("div", { class: "chat" }, h("aside", { class: "chat-side" }, list),
    h("section", { class: "chat-main" }, thread, strip, composer)));

  if (sessionId) {
    try { session = await api.get(`/sessions/${sessionId}`); }
    catch { toast("Essa conversa não existe mais.", "err"); sessionId = null; }
  }
  if (!session) {
    if (sessions.length) { navigate(`#/chat/${sessions[0].id}`); }
    else { const created = await api.post("/sessions", {}); sessions = await api.get("/sessions"); session = created; }
  }
  if (session) paintAll(); else paintList();
  if (session && !session.messages.length) input.focus();
  return { el: root, destroy: unmount };
}
