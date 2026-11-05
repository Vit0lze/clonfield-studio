export function studioOrigin(value) {
  let url;
  try { url = new URL(value.trim()); } catch { return null; }
  const live = url.protocol === "https:" && /^[a-z0-9-]+\.gradio\.live$/i.test(url.hostname) && !url.port;
  const local = ["localhost", "127.0.0.1"].includes(location.hostname) &&
    ["localhost", "127.0.0.1"].includes(url.hostname) && url.protocol === "http:";
  return (live || local) && !url.username && !url.password && url.pathname === "/" && !url.search && !url.hash
    ? url.origin : null;
}

export class StudioAPI {
  constructor(origin) {
    this.origin = origin;
    this.session = crypto.randomUUID().replaceAll("-", "");
    this.token = null;
    this.controller = new AbortController();
  }

  async request(path, options = {}, secret = this.token) {
    const headers = new Headers(options.headers);
    if (secret) headers.set("Authorization", `Bearer ${secret}`);
    const response = await fetch(new URL(path, this.origin), {
      ...options, headers, credentials: "omit", redirect: "error", signal: this.controller.signal
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" ? body.detail : `O Studio retornou HTTP ${response.status}.`);
    }
    return response;
  }

  async connect(password) {
    const response = await this.request("/clonfield/connect", { method: "POST" }, password);
    const { token } = await response.json();
    if (typeof token !== "string") throw new Error("Atualize e reinicie a sessão do ClonField no Colab.");
    this.token = token;
    return this.request("/config").then(response => response.json());
  }

  disconnect() {
    this.controller.abort();
    this.token = null;
  }

  async upload(file) {
    const body = new FormData();
    body.append("files", file);
    const [path] = await this.request("/gradio_api/upload", { method: "POST", body }).then(r => r.json());
    return { path, orig_name: file.name, size: file.size, mime_type: file.type, meta: { _type: "gradio.FileData" } };
  }

  async submit(dependency, data, progress) {
    const body = JSON.stringify({ fn_index: dependency.id, session_hash: this.session, data });
    const { event_id } = await this.request("/gradio_api/queue/join", {
      method: "POST", headers: { "Content-Type": "application/json" }, body
    }).then(r => r.json());
    const response = await this.request(`/gradio_api/queue/data?session_hash=${this.session}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        for (;;) {
          const boundary = /\r?\n\r?\n/.exec(buffer);
          if (!boundary) break;
          const message = buffer.slice(0, boundary.index);
          buffer = buffer.slice(boundary.index + boundary[0].length);
          const data = message.split(/\r?\n/).filter(line => line.startsWith("data:"))
            .map(line => line.slice(5).trimStart()).join("\n");
          if (!data) continue;
          const event = JSON.parse(data);
          if (event.event_id && event.event_id !== event_id) continue;
          if (event.msg === "process_completed") {
            if (!event.success || event.output?.error) {
              throw new Error(event.output?.error || "A execução falhou no Studio. Consulte o log do Colab.");
            }
            return event.output.data;
          }
          if (event.msg === "unexpected_error") throw new Error(event.message || "A sessão do Studio foi interrompida.");
          progress(event);
        }
      }
    } finally {
      await reader.cancel().catch(() => {});
    }
    throw new Error("A conexão encerrou antes do resultado. Confira o Colab antes de enviar novamente.");
  }

  async file(payload) {
    // Resolve media against the connected worker, never send Authorization to a URL in the result.
    const path = `/gradio_api/file=${payload.path.split("/").map(encodeURIComponent).join("/")}`;
    return this.request(path).then(response => response.blob());
  }
}
