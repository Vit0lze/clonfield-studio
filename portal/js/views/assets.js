// Ativos: mídia publicada com identidade e versões. Usar um ativo em um app passa a VERSÃO escolhida por referência (sem cópia).
import { api, store } from "../api.js";
import { h, icon, clear, toast, actionMenu, fmtBytes } from "../ui.js";
import { sendTargets, prefillAsset } from "./app.js";

const KIND_LABEL = { image: "imagem", video: "vídeo", audio: "áudio", character: "personagem" };
const ACCEPT = { image: "image/*", character: "image/*", video: "video/*", audio: "audio/*" };
const mediaKind = version => (version.mime || "").split("/")[0];  // image | video | audio (a character is an image file)
const when = created => new Date(created * 1000).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });

function thumb(version, cls = "") {
  const src = api.url(version.url), kind = mediaKind(version);
  if (kind === "image") return h("img", { class: cls, src, alt: version.metadata?.title || "Ativo", loading: "lazy" });
  if (kind === "video") return h("video", { class: cls, src, muted: true, preload: "metadata", controls: false });
  return h("div", { class: `cast-noimg ${cls}` }, icon("play"));
}

export async function assetsView(assetId, navigate) {
  const root = h("div", { class: "view" });
  await store.loadApps();
  if (assetId) await detail(root, assetId, navigate); else await list(root, navigate);
  return { el: root };
}

async function list(root, navigate) {
  const items = await api.get("/assets");
  const grid = h("div", { class: "cast-grid" });
  for (const asset of items) {
    const current = asset.current_version;
    grid.append(h("a", { class: "cast-card asset-card", href: `#/assets/${asset.asset_id}`, "data-asset": asset.asset_id, "aria-label": `Abrir ${asset.title}` },
      thumb(current),
      h("div", { class: "cast-body" }, h("h3", null, asset.title),
        h("p", { class: "muted" }, `${KIND_LABEL[asset.kind] || asset.kind} · ${asset.versions.length} ${asset.versions.length === 1 ? "versão" : "versões"}`))));
  }
  root.append(h("div", { class: "section-head" }, h("div", null, h("h2", null, "Ativos"),
    h("p", null, "Mídia publicada com identidade e histórico de versões. Cada versão guarda o arquivo original sem alterar; usar em um app aponta para a versão escolhida, sem cópia."))),
    items.length ? grid : h("div", { class: "empty" }, icon("layers"), h("h3", null, "Nenhum ativo ainda"),
      h("p", null, "Em qualquer resultado, use «Usar em» para publicar a imagem como ativo, ou publique um personagem pelo Elenco."),
      h("a", { class: "btn", href: "#/cast" }, icon("user", "sm"), "Abrir o Elenco")));
}

async function detail(root, assetId, navigate) {
  let data;
  try { data = await api.get(`/assets/${assetId}`); } catch (error) {
    root.append(h("div", { class: "empty" }, icon("alert"), h("h3", null, "Ativo não encontrado"), h("p", null, error.message),
      h("a", { class: "btn", href: "#/assets" }, "Voltar aos ativos")));
    return;
  }
  let selected = data.current;
  const versions = () => data.versions;
  const pickedVersion = () => versions().find(v => v.version_id === selected);
  const stage = h("div", { class: "asset-stage" }), rows = h("div", { class: "asset-versions", role: "group", "aria-label": "Versões" }), actions = h("div", { class: "actions" });

  function paint() {
    const version = pickedVersion();
    clear(stage).append(mediaKind(version) === "video" ? h("video", { src: api.url(version.url), controls: true }) :
      mediaKind(version) === "audio" ? h("audio", { src: api.url(version.url), controls: true }) : thumb(version, "asset-big"),
      h("p", { class: "muted" }, `Versão ${version.number} · ${fmtBytes(version.bytes)}`,
        version.media?.width ? ` · ${version.media.width}×${version.media.height}` : "", version.media?.duration_s != null ? ` · ${version.media.duration_s}s` : "",
        version.metadata?.note ? ` · ${version.metadata.note}` : "",
        version.producer?.app ? ` · de ${version.producer.app}` : ""));
    clear(rows);
    for (const v of [...versions()].reverse()) {
      rows.append(h("button", { type: "button", class: "asset-row", "aria-pressed": String(v.version_id === selected), "data-version": v.version_id,
        onclick: () => { selected = v.version_id; paint(); } },
        h("b", null, `v${v.number}`), h("span", null, when(v.created)), h("code", null, v.sha256.slice(0, 8)),
        v.version_id === data.current ? h("span", { class: "badge ok" }, "atual") : null));
    }
    clear(actions);
    const kind = mediaKind(version);
    const targets = sendTargets(kind);
    if (targets.length) actions.append(actionMenu({ label: `Usar em (v${version.number})`, iconName: "external",
      items: targets.map(t => ({ label: t.title, hint: t.tagline, app: t.id, onclick: () => {
        prefillAsset(t, { id: version.version_id, name: data.title, kind, url: version.url });
        navigate(`#/apps/${t.id}`);
      } })) }));
    actions.append(h("button", { class: "btn sm", type: "button", onclick: async () => {
      try {
        const check = await api.get(`/assets/versions/${version.version_id}`);
        toast(check.verified ? `v${version.number}: o arquivo confere com o SHA-256.` : `v${version.number}: o arquivo NÃO confere com o SHA-256.`, check.verified ? undefined : "err");
      } catch (error) { toast(error.message, "err"); }
    } }, icon("check", "sm"), "Verificar integridade"));
  }

  const file = h("input", { type: "file", accept: ACCEPT[data.kind] || "", hidden: true, "aria-label": "Arquivo da nova versão" });
  const add = h("button", { class: "btn primary", type: "button", onclick: () => file.click() }, icon("plus", "sm"), "Nova versão");
  file.addEventListener("change", async () => {
    const chosen = file.files?.[0];
    if (!chosen) return;
    add.disabled = true;
    try {
      const sent = await api.upload(chosen);
      const made = await api.post(`/assets/${assetId}/versions`, { from: { upload: sent.id } });
      if (made.deduplicated) { toast(`Esse arquivo já é a versão atual (v${made.version.number}).`); return; }
      data = await api.get(`/assets/${assetId}`);
      selected = data.current;
      toast(`Versão ${made.version.number} criada. As anteriores continuam disponíveis.`);
      paint();
    } catch (error) { toast(error.message || "Não consegui criar a versão.", "err"); } finally { add.disabled = false; file.value = ""; }
  });

  root.append(h("div", { class: "section-head" }, h("div", null, h("a", { class: "muted", href: "#/assets" }, "← Ativos"), h("h2", null, data.title),
    h("p", null, `${KIND_LABEL[data.kind] || data.kind} · ${versions().length} ${versions().length === 1 ? "versão" : "versões"}`))),
    h("div", { class: "asset-detail" }, stage, h("div", { class: "asset-side" }, h("div", { class: "row" }, add, file), rows, actions)));
  paint();
}
