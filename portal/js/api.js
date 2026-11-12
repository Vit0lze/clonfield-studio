// Session, REST calls, uploads with progress, and a job follower that survives dropped connections.
const FINAL = ["concluído", "falhou", "cancelado", "travado"];
export const isFinal = status => FINAL.includes(status);

export function studioOrigin(value) {
  let url;
  try { url = new URL(value.trim()); } catch { return null; }
  const live = url.protocol === "https:" && /^[a-z0-9-]+\.gradio\.live$/i.test(url.hostname) && !url.port;
  const local = ["localhost", "127.0.0.1"].includes(url.hostname) && url.protocol === "http:";
  return (live || local) && !url.username && !url.password ? url.origin : null;
}

const saved = key => { try { return sessionStorage.getItem(key); } catch { return null; } };
const save = (key, value) => { try { value == null ? sessionStorage.removeItem(key) : sessionStorage.setItem(key, value); } catch { /* private mode */ } };

export const session = {
  origin: saved("cf-origin"), token: saved("cf-token"),
  get sameOrigin() { return location.pathname.startsWith("/studio"); },
  get ready() { return Boolean(this.token && (this.origin || this.sameOrigin)); },
  base() { return this.sameOrigin ? location.origin : this.origin; },
  set(origin, token) { this.origin = origin; this.token = token; save("cf-origin", origin); save("cf-token", token); },
  clear() { this.token = null; save("cf-token", null); }
};

export class ApiError extends Error { constructor(message, status) { super(message); this.status = status; } }
export const events = new EventTarget();

async function request(path, options = {}, secret = session.token) {
  const headers = new Headers(options.headers);
  if (secret) headers.set("Authorization", `Bearer ${secret}`);
  let response;
  try {
    response = await fetch(new URL(path, session.base()), { ...options, headers, credentials: "omit" });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    events.dispatchEvent(new CustomEvent("offline"));
    throw new ApiError("Sem conexão com o Colab. Confira se a célula do Studio continua rodando.", 0);
  }
  events.dispatchEvent(new CustomEvent("online"));
  if (response.status === 401 && secret === session.token) {
    session.clear();
    events.dispatchEvent(new CustomEvent("unauthorized"));
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(typeof body.detail === "string" ? body.detail : `O Studio respondeu HTTP ${response.status}.`, response.status);
  }
  return response;
}

export const api = {
  async connect(origin, password) {
    if (origin) session.origin = origin;
    const response = await request("/clonfield/connect", { method: "POST" }, password);
    const { token } = await response.json();
    if (typeof token !== "string") throw new ApiError("Atualize e reinicie a sessão do ClonField no Colab.", 0);
    session.set(session.sameOrigin ? null : origin, token);
  },
  get: path => request(`/clonfield/api${path}`).then(r => r.json()),
  post: (path, body) => request(`/clonfield/api${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {})
  }).then(r => r.json()),
  url: rel => rel && new URL(rel, session.base()).href,

  // XHR so the dropzone can show real upload progress
  upload(file, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const body = new FormData();
      body.append("files", file);
      xhr.open("POST", new URL("/clonfield/api/upload", session.base()));
      xhr.setRequestHeader("Authorization", `Bearer ${session.token}`);
      xhr.upload.onprogress = e => e.lengthComputable && onProgress?.(e.loaded / e.total);
      xhr.onerror = () => reject(new ApiError("O envio falhou. Confira a conexão com o Colab.", 0));
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch { /* html error page */ }
        xhr.status < 300 ? resolve(data[0]) : reject(new ApiError(data.detail || `Envio recusado (HTTP ${xhr.status}).`, xhr.status));
      };
      xhr.send(body);
    });
  },

  // Follow one job over SSE. The server keeps the job when the page reloads or the tunnel drops,
  // so a silent stream is reopened instead of waited on forever.
  follow(jobId, onUpdate, onLink) {
    let stopped = false, controller = null, attempt = 0;
    const loop = async () => {
      while (!stopped) {
        controller = new AbortController();
        let timer;
        const arm = () => { clearTimeout(timer); timer = setTimeout(() => controller.abort(), 30000); };
        try {
          arm();
          const response = await request(`/clonfield/api/jobs/${jobId}/events`, { signal: controller.signal });
          onLink?.(true);
          attempt = 0;
          const reader = response.body.getReader(), decoder = new TextDecoder();
          let buffer = "";
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            arm();
            buffer += decoder.decode(value, { stream: true });
            let cut;
            while ((cut = buffer.indexOf("\n\n")) >= 0) {
              const chunk = buffer.slice(0, cut);
              buffer = buffer.slice(cut + 2);
              const line = chunk.split("\n").find(l => l.startsWith("data: "));
              if (!line) continue;
              const snapshot = JSON.parse(line.slice(6));
              onUpdate(snapshot);
              if (isFinal(snapshot.status)) { stopped = true; clearTimeout(timer); window.dispatchEvent(new CustomEvent("cf-job-final", { detail: snapshot })); return; }
            }
          }
        } catch (error) {
          if (error.status === 404) { stopped = true; return; }
        } finally { clearTimeout(timer); }
        if (stopped) return;
        onLink?.(false);
        await new Promise(r => setTimeout(r, Math.min(8000, 1500 * ++attempt)));
      }
    };
    loop();
    return { stop() { stopped = true; controller?.abort(); } };
  }
};

// state shared by views
export const store = {
  system: null, apps: null, jobs: [],
  async loadApps() { return this.apps ||= await api.get("/apps"); },
  async refreshJobs() { this.jobs = await api.get("/jobs?limit=80"); events.dispatchEvent(new CustomEvent("jobs")); return this.jobs; },
  prefill(value) { save("cf-prefill", JSON.stringify(value)); },
  takePrefill(app) {
    try {
      const data = JSON.parse(saved("cf-prefill") || "null");
      if (data && data.app === app) { save("cf-prefill", null); return data.values || {}; }
    } catch { /* ignore */ }
    return {};
  },
  lastJob(app, id) { return id === undefined ? saved(`cf-last-${app}`) : save(`cf-last-${app}`, id); }
};
