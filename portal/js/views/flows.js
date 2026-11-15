// Fluxos: ready-made multi-step recipes. One form, a preview of the steps, and a queue: every queued set of values is its own job.
import { api, isFinal } from "../api.js";
import { h, icon, toast, clear, field, switchRow } from "../ui.js";

const KIND_MEDIA = { image: "image/*", images: "image/*", video: "video/*", videos: "video/*" };
const STATE_CLASS = { "BLOQUEADO_GPU": "gpu", "TESTADO CPU": "ok" };

export async function flowsView(id, navigate) {
  const recipes = await api.get("/recipes");
  const root = h("div", { class: "view" });
  const followers = [];
  const recipe = id && recipes.find(r => r.id === id);
  if (id && !recipe) {
    root.append(h("div", { class: "empty" }, icon("alert"), h("h3", null, "Esta receita não existe"), h("a", { class: "btn", href: "#/flows" }, "Ver todas")));
    return { el: root };
  }
  recipe ? detail(recipe) : list();
  return { el: root, destroy() { followers.forEach(f => f.stop()); } };

  function list() {
    const groups = [...new Set(recipes.map(r => r.group))];
    root.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Fluxos"), h("p", null, "Receitas com vários passos: cada passo roda uma vez por item, e só o que mudou é refeito."))));
    if (!recipes.some(r => r.custom)) root.append(h("p", { class: "muted flow-hint" }, "Peça ao agente do chat para montar um fluxo e guardá-lo: ele aparece aqui, em «Meus fluxos», pronto para rodar com outros arquivos."));
    for (const group of groups) {
      root.append(h("h3", { class: "flow-group" }, group), h("div", { class: "flow-grid" }, recipes.filter(r => r.group === group).map(r =>
        h("a", { class: "flow-card", href: `#/flows/${r.id}`, "data-recipe": r.id },
          h("div", { class: "flow-top" }, h("strong", null, r.title), h("span", { class: `sr-chip ${r.lane}` }, r.lane === "gpu" ? "GPU" : "CPU")),
          h("p", { class: "muted" }, r.tagline),
          h("div", { class: "flow-meta" }, r.custom ? h("span", { class: "sr-chip" }, "seu fluxo") : null, h("span", { class: "sr-chip" }, `${r.steps} passos`), h("span", { class: `sr-chip ${STATE_CLASS[r.state] || ""}`, title: r.evidence }, r.state))))));
    }
  }

  function detail(rec) {
    const values = {};
    const queue = [];
    const controls = h("div", { class: "flow-form" });
    const steps = h("ol", { class: "flow-steps", "aria-label": "Passos da receita" });
    const queueBox = h("div", { class: "flow-queue" });
    const jobsBox = h("div", { class: "flow-jobs", "aria-live": "polite" });
    const note = h("p", { class: "muted flow-note" });

    for (const spec of rec.inputs) controls.append(control(spec));

    function control(spec) {
      const key = spec.id;
      const label = spec.label || key;
      if (KIND_MEDIA[spec.kind]) {
        const many = spec.kind.endsWith("s");
        const status = h("span", { class: "muted" }, many ? `Escolha de ${spec.min || 1} a ${spec.max || 8} arquivos.` : "Escolha um arquivo.");
        const input = h("input", { type: "file", accept: KIND_MEDIA[spec.kind], multiple: many, "aria-label": label, onchange: async () => {
          const files = [...(input.files || [])].slice(0, spec.max || 8);
          if (!files.length) return;
          status.textContent = "Enviando…";
          try {
            const sent = [];
            for (const file of files) sent.push(await api.upload(file));
            values[key] = many ? sent.map(s => s.id) : sent[0].id;
            status.textContent = sent.map(s => s.name).join(", ");
          } catch (error) { delete values[key]; status.textContent = error.message; }
          refresh();
        } });
        return field(label, h("div", { class: "row" }, input, status));
      }
      values[key] = spec.default ?? (spec.kind === "bool" ? false : "");
      if (spec.kind === "enumlist") {
        values[key] = [...(spec.default || [])];
        return field(label, h("div", { class: "flow-checks", role: "group", "aria-label": label }, spec.options.map(o => h("label", { class: "flow-check" },
          h("input", { type: "checkbox", checked: values[key].includes(o), "data-option": o, onchange: e => {
            values[key] = e.target.checked ? [...values[key], o] : values[key].filter(x => x !== o);
            refresh();
          } }), h("span", null, o)))));
      }
      if (spec.kind === "bool") return switchRow(label, values[key], v => { values[key] = v; refresh(); });
      if (spec.kind === "enum") {
        const select = h("select", { class: "input", onchange: () => { values[key] = select.value; refresh(); } }, spec.options.map(o => h("option", { value: o, selected: o === values[key] }, o)));
        return field(label, select);
      }
      if (spec.kind === "number") {
        const input = h("input", { class: "input", type: "number", min: spec.min, max: spec.max, step: "any", value: values[key], oninput: () => { values[key] = input.value === "" ? "" : Number(input.value); refresh(); } });
        return field(label, input);
      }
      const area = h(spec.kind === "lines" ? "textarea" : "input", { class: "input", rows: spec.kind === "lines" ? 5 : undefined, value: values[key], oninput: () => { values[key] = area.value; refresh(); } });
      return field(label, area);
    }

    let timer = null;
    function refresh() {
      clearTimeout(timer);
      timer = setTimeout(preview, 250);
    }
    async function preview() {
      try {
        const out = await api.post(`/recipes/${rec.id}/preview`, { vars: values });
        if (!out.ok) throw new Error(out.detail);
        clear(steps).append(...out.steps.map(s => h("li", { "data-step": s.id }, h("span", null, s.label),
          s.each ? h("small", { class: "sr-chip" }, "um por item") : null, s.when ? h("small", { class: "sr-chip" }, s.when_not ? "só se reprovar" : "só se passar") : null)));
        note.textContent = out.resources.slow?.length ? "Alguns passos usam offload (mais lentos)." : "";
        run.disabled = add.disabled = false;
        steps.dataset.ok = "1";
      } catch (error) {
        steps.dataset.ok = "0";
        clear(steps).append(h("li", { class: "bad" }, error.message));
        run.disabled = add.disabled = true;
      }
    }

    const add = h("button", { class: "btn", type: "button", disabled: true, onclick: () => {
      if (queue.length >= 12) return toast("A fila aceita até 12 execuções.", "err");
      queue.push(JSON.parse(JSON.stringify(values)));
      paintQueue();
    } }, icon("plus", "sm"), "Colocar na fila");
    const run = h("button", { class: "btn primary", type: "button", disabled: true, onclick: () => submit(queue.length ? queue : [values]) }, icon("bolt", "sm"), "Rodar");

    function paintQueue() {
      clear(queueBox);
      if (!queue.length) return void (run.lastChild.textContent = "Rodar");
      queue.forEach((q, i) => queueBox.append(h("div", { class: "flow-q" }, h("span", null, `Execução ${i + 1}`), h("button", { class: "btn sm", type: "button", "aria-label": `Tirar a execução ${i + 1} da fila`,
        onclick: () => { queue.splice(i, 1); paintQueue(); } }, icon("x", "sm")))));
      run.lastChild.textContent = `Rodar a fila (${queue.length})`;
    }

    async function submit(sets) {
      run.disabled = true;
      try {
        const out = await api.post(`/recipes/${rec.id}/run`, { batch: sets.map(s => ({ ...s })) });
        queue.length = 0; paintQueue();
        out.jobs.forEach(watch);
        toast(out.jobs.length > 1 ? `${out.jobs.length} execuções na fila.` : "Receita iniciada.");
      } catch (error) { toast(error.message, "err"); } finally { run.disabled = false; }
    }

    async function removeFlow() {
      if (!confirm(`Apagar o fluxo «${rec.title}»? Os resultados já gerados ficam na Biblioteca.`)) return;
      try { await api.del(`/recipes/${rec.id}`); toast("Fluxo apagado."); navigate("#/flows"); } catch (error) { toast(error.message, "err"); }
    }

    async function redo(job, stepId) {
      try {
        const next = await api.post(`/dag/runs/${job.run}/revise`, { force: [stepId], title: `${job.title.replace(/ · refeito$/, "")} · refeito` });
        watch(next);
        toast("Refazendo deste passo; o que não mudou vem do cache.");
      } catch (error) { toast(error.message, "err"); }
    }

    function watch(job) {
      const bar = h("div", { class: "light" }, h("i"));
      const line = h("p", { class: "stage-line" }, job.desc || "Na fila");
      const out = h("div", { class: "flow-out" });
      const timeline = h("ol", { class: "flow-timeline", "aria-label": "Andamento por passo" });
      const card = h("article", { class: "flow-job", "data-job": job.id }, h("strong", null, job.title), bar, line, timeline, out);
      let seq = 0;
      const readRun = async j => {
        if (!j.run) return;
        const mine = ++seq;  // only the newest read paints, so a slow early read can never hide the Refazer buttons of the final one
        try {
          const run = await api.get(`/dag/runs/${j.run}`);
          if (mine === seq) paintTimeline(timeline, run, isFinal(j.status) ? id => redo(j, id) : null);
        } catch { /* the record appears once the first step starts */ }
      };
      jobsBox.prepend(card);
      const paint = j => {
        bar.style.setProperty("--p", String(j.fraction || 0));
        bar.classList.toggle("indeterminate", j.status === "fila" || (j.fraction || 0) <= 0.011);
        line.textContent = j.status === "fila" ? `Na fila${j.position ? ` · posição ${j.position}` : ""}` : j.status === "concluído" ? `Concluído · ${(j.results || []).length} arquivo(s)` : (j.desc || j.message || j.status);
        card.dataset.status = j.status;
        readRun(j);
        if (!isFinal(j.status)) return;
        clear(out);
        for (const r of j.results || []) {
          if (r.kind === "image") out.append(h("a", { href: api.url(r.url), target: "_blank", rel: "noopener" }, h("img", { src: api.url(r.url), alt: r.name, loading: "lazy" })));
          else if (r.kind === "video") out.append(h("video", { src: api.url(r.url), controls: true, muted: true, playsinline: true }));
          else out.append(h("a", { class: "btn sm", href: api.url(r.url), download: r.name }, icon("download", "sm"), r.name));
        }
        if (j.status === "falhou") line.textContent = j.message || "Falhou.";
      };
      paint(job);
      if (!isFinal(job.status)) followers.push(api.follow(job.id, paint));
    }

    root.append(h("div", { class: "section-head" }, h("div", null, h("a", { class: "muted", href: "#/flows" }, "← Fluxos"), h("h2", null, rec.title), h("p", null, rec.tagline))),
      h("div", { class: "flow-layout" }, h("section", null, controls, h("div", { class: "row flow-actions" }, add, run), queueBox, note),
        h("section", null, h("h3", null, "Passos"), steps, h("span", { class: `sr-chip ${STATE_CLASS[rec.state] || ""}`, title: rec.evidence }, rec.state),
          rec.custom ? h("p", null, h("button", { class: "btn sm", type: "button", "data-action": "delete-flow", onclick: removeFlow }, icon("trash", "sm"), "Apagar este fluxo")) : null)),
      jobsBox);
    refresh();
  }
}

const RUN_LABEL = { pendente: "espera", executando: "rodando", "concluído": "feito", "em cache": "em cache", ignorado: "ignorado", falhou: "falhou", cancelado: "cancelado" };

// One line per step of the run record: what it is, its state, how many items, how many came from the cache.
export function paintTimeline(list, run, redo) {
  const labels = Object.fromEntries((run.graph?.nodes || []).map(n => [n.id, n.label || n.id]));
  clear(list).append(...(run.order || []).map(id => {
    const n = run.nodes?.[id] || {};
    const state = n.status || "pendente";
    const detail = n.status === "ignorado" ? (n.reason || "condição não atendida")
      : n.items ? `${n.items} itens${n.cached_items ? ` · ${n.cached_items} em cache` : ""}`
      : n.status === "falhou" ? (n.error || "falhou") : "";
    return h("li", { "data-step": id, "data-state": state }, h("span", { class: "tl-name" }, labels[id] || id),
      h("span", { class: `sr-chip tl-${state.replace(/\s+/g, "-")}` }, RUN_LABEL[state] || state), detail ? h("small", { class: "muted" }, detail) : null,
      redo && state !== "ignorado" ? h("button", { class: "btn sm", type: "button", "data-action": "redo", "aria-label": `Refazer a partir de «${labels[id] || id}»`, onclick: () => redo(id) }, icon("refresh", "sm"), "Refazer") : null);
  }));
}
