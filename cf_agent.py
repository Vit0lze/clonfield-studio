"""ONE operational agent with real tool calling.

It replaces "an LLM writes text + a router picks + the user clicks every step". The model sees the capability catalog through
tools, builds a typed DAG, validates it (and fixes it from the reasons it gets back), executes it, looks at the result and may
repeat steps. Nothing here parses free text for decisions: every decision is a tool call with arguments.

Providers are interchangeable behind one method, `step(system, messages, tools) -> {text, calls}`:
  * GeminiProvider      Gemma 4 through the Google AI Studio API (native function calling). Testable today.
  * OpenAICompatProvider llama.cpp `llama-server` (OpenAI-style `tools`), meant for Qwen3.5-9B GGUF on the Colab GPU.
                         CÓDIGO ESCRITO: no GPU here, so it has not been run against a real Qwen.
JEV / TypeSafe is NOT in this path; the router keeps it behind a feature flag.

Policy: low-risk graphs run without asking. A graph that needs a high-risk capability is returned as `needs_confirmation`
and only runs when the user has confirmed it (the `confirm` argument is set by the application, never trusted from the model
alone: see `Toolbox.allow_confirm`).
"""

import json
import os
import time
from pathlib import Path

import requests

import cf_capabilities as caps
import cf_dag as dag
import cf_env
import cf_llm

MAX_STEPS = 10
RESULT_LIMIT = 6000

SYSTEM = """Você é o operador do ClonField Studio, um estúdio de imagem, vídeo e áudio. Você age SOMENTE chamando ferramentas.
Regras:
- Descubra o que existe com list_capabilities (filtre por texto, por tipo de entrada com accepts, por saída com produces) e inspect_capability. Nunca invente o id de uma capacidade, de uma mídia ou de um parâmetro.
- As mídias do usuário vêm de list_media; use o campo id delas em {"media": "<id>"}.
- Monte um grafo JSON: {"nodes":[{"id":"a","cap":"<capacidade>","inputs":{"<entrada>":{"media":"<id>"} ou {"from":"<no>.<saida>"}},"params":{...}}]}. Passos podem se repetir (por exemplo duas ampliações) e podem usar a saída de qualquer passo anterior.
- Antes de executar, rode validate_graph. Se houver erros, corrija o grafo usando os motivos devolvidos e valide de novo.
- Execute com execute_graph. Depois confira o resultado com inspect_artifact; se a conferência técnica falhar, ajuste e execute de novo.
- Apps de GPU e passos de risco alto: se execute_graph responder needs_confirmation, pare e peça ao usuário para confirmar; não tente contornar.
- Não faça o que não foi pedido. Se faltar uma mídia ou a informação for ambígua, pergunte em uma frase.
- Responda ao usuário em português, curto, dizendo o que foi feito e o que saiu (nomes de arquivos e medidas reais, sem inventar)."""


class AgentError(Exception):
    pass


# ---------------------------------------------------------------- providers
class GeminiProvider:
    """Gemma 4 via generativelanguage.googleapis.com with native `functionDeclarations`."""

    name = "gemma-api"

    def __init__(self, key=None, models=None, timeout=70):
        self.key = key or cf_env.secret("gemma")
        self.models = models or cf_llm.models()
        self.timeout = timeout
        if not self.key:
            raise AgentError("Sem chave do Gemma neste ambiente.")

    @staticmethod
    def contents(messages):
        out = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "parts": [{"text": m["text"]}]})
            elif m["role"] == "assistant":
                parts = m.get("raw_parts") or ([{"text": m["text"]}] if m.get("text") else []) + [{"functionCall": {"name": c["name"], "args": c["args"]}} for c in m.get("calls", [])]
                out.append({"role": "model", "parts": parts})
            elif m["role"] == "tool":
                response = m["result"] if isinstance(m["result"], dict) else {"result": m["result"]}
                out.append({"role": "user", "parts": [{"functionResponse": {"name": m["name"], "response": response}}]})
        return out

    @staticmethod
    def declarations(tools):
        return [{"functionDeclarations": [dict(name=t["name"], description=t["description"], parameters=t["parameters"]) for t in tools]}]

    def step(self, system, messages, tools):
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": self.contents(messages), "tools": self.declarations(tools),
                "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}}, "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1500}}
        last = "sem resposta"
        for model in self.models:
            for attempt in range(3):
                try:
                    response = requests.post(cf_llm.API.format(model=model), headers={"x-goog-api-key": self.key}, json=body, timeout=self.timeout)
                except requests.RequestException as exc:
                    last = type(exc).__name__
                    time.sleep(2)
                    continue
                if response.status_code in cf_llm.RETRY_CODES:
                    last = f"HTTP {response.status_code}"
                    time.sleep(2 + attempt)
                    continue
                if response.status_code != 200:
                    raise AgentError(f"O Gemma recusou o pedido (HTTP {response.status_code}): {response.text[:160]}")
                candidate = (response.json().get("candidates") or [{}])[0]
                parts = [p for p in (candidate.get("content") or {}).get("parts", []) if not p.get("thought")]
                text = "".join(p.get("text", "") for p in parts).strip()
                calls = [dict(id=p["functionCall"].get("id") or f"call_{i}", name=p["functionCall"]["name"], args=p["functionCall"].get("args") or {})
                         for i, p in enumerate(parts) if "functionCall" in p]
                if not text and not calls:
                    last = "resposta vazia"
                    continue
                return dict(text=text, calls=calls, raw_parts=parts, model=model)
        raise AgentError(f"O Gemma não respondeu ({last}).")


class OpenAICompatProvider:
    """llama.cpp llama-server (or any OpenAI-compatible endpoint) with native tool calls. Meant for Qwen3.5-9B GGUF on the T4."""

    name = "llama-server"

    def __init__(self, base_url=None, model="qwen", timeout=180):
        self.base = (base_url or os.environ.get("CLONFIELD_LLAMA_URL") or "http://127.0.0.1:8080").rstrip("/")
        self.model, self.timeout = model, timeout

    @staticmethod
    def wire(system, messages):
        out = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                entry = {"role": "assistant", "content": m.get("text") or ""}
                if m.get("calls"):
                    entry["tool_calls"] = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}} for c in m["calls"]]
                out.append(entry)
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["id"], "content": json.dumps(m["result"], ensure_ascii=False)[:RESULT_LIMIT]})
        return out

    def step(self, system, messages, tools):
        body = {"model": self.model, "messages": self.wire(system, messages), "temperature": 0.2, "max_tokens": 1500,
                "tools": [{"type": "function", "function": dict(name=t["name"], description=t["description"], parameters=t["parameters"])} for t in tools]}
        try:
            response = requests.post(f"{self.base}/v1/chat/completions", json=body, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AgentError(f"O llama-server não respondeu: {exc}") from None
        message = response.json()["choices"][0]["message"]
        calls = []
        for i, c in enumerate(message.get("tool_calls") or []):
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            calls.append(dict(id=c.get("id") or f"call_{i}", name=c["function"]["name"], args=args))
        return dict(text=(message.get("content") or "").strip(), calls=calls, model=self.model)


def choose_provider():
    """llama-server when one is configured and answering, else the Gemma API when a key exists, else None (the chat keeps its old path)."""
    url = os.environ.get("CLONFIELD_LLAMA_URL")
    if url:
        try:
            if requests.get(url.rstrip("/") + "/health", timeout=2).status_code == 200:
                return OpenAICompatProvider(url)
        except requests.RequestException:
            pass
    if cf_env.secret("gemma"):
        return GeminiProvider()
    return None


# ---------------------------------------------------------------- tools
def schema(**props):
    return {"type": "object", "properties": props, "required": [k for k, v in props.items() if v.pop("_required", False)]}


def S(description, required=False, **extra):
    return dict(type="string", description=description, **({"_required": True} if required else {}), **extra)


class Toolbox:
    """The tools the agent may call. `host` supplies the outside world (media of the conversation, job submission, job state)."""

    def __init__(self, registry, env, host, allow_confirm=False):
        self.registry, self.env, self.host, self.allow_confirm = registry, env, host, allow_confirm
        self.tools = [
            dict(name="list_capabilities", description="Lista capacidades do Studio (compacto). Filtre por texto (query), tipo de entrada (accepts: image|video|audio|mask|text|json|file) ou de saída (produces).",
                 parameters=schema(query=S("palavras-chave"), accepts=S("tipo de mídia que a capacidade recebe"), produces=S("tipo de mídia que a capacidade gera"), kind=S("engine|step|action|mode|app")), fn=self.list_capabilities),
            dict(name="inspect_capability", description="Detalhes de uma capacidade: entradas e saídas tipadas, parâmetros com faixas, requisitos, estado de validação e onde é usada.",
                 parameters=schema(id=S("id da capacidade", True)), fn=self.inspect_capability),
            dict(name="list_media", description="Mídias disponíveis nesta conversa (id, nome, tipo, origem).", parameters=schema(), fn=self.list_media),
            dict(name="validate_graph", description="Valida um grafo sem executar. Devolve erros com o motivo de cada incompatibilidade, a ordem de execução e os recursos.",
                 parameters=schema(graph_json=S("o grafo como texto JSON: {\"nodes\":[...]}", True)), fn=self.validate_graph),
            dict(name="estimate_resources", description="VRAM, RAM, disco, faixa (cpu/gpu) e risco que o grafo exige, e quais nós já estão em cache.",
                 parameters=schema(graph_json=S("o grafo como texto JSON", True)), fn=self.estimate_resources),
            dict(name="execute_graph", description="Executa o grafo (valida antes). Passos de CPU terminam aqui e devolvem os arquivos; passos de GPU devolvem job_id para acompanhar com job_status.",
                 parameters=schema(graph_json=S("o grafo como texto JSON", True), force=S("ids de nós separados por vírgula para recalcular ignorando o cache")), fn=self.execute_graph),
            dict(name="job_status", description="Estado de um job iniciado antes.", parameters=schema(job_id=S("id do job", True)), fn=self.job_status),
            dict(name="inspect_artifact", description="Mede um arquivo: dimensões, nitidez, exposição (imagem) ou tamanho. Use depois de executar para conferir o resultado.",
                 parameters=schema(ref=S("id de mídia ou caminho de resultado devolvido por execute_graph", True)), fn=self.inspect_artifact),
        ]
        self.by_name = {t["name"]: t for t in self.tools}

    # -- helpers
    def graph(self, text):
        try:
            graph = json.loads(text) if isinstance(text, str) else text
        except ValueError as exc:
            raise ValueError(f"graph_json não é JSON válido: {exc}") from None
        if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
            raise ValueError('o grafo precisa ser {"nodes":[...]}')
        return graph

    def compact(self, d):
        return dict(id=d["id"], title=d["title"], what=d["tagline"], kind=d["kind"], inputs=[f'{p["name"]}:{p["type"]}' + ("" if p["required"] else "?") for p in d["inputs"]],
                    outputs=[f'{p["name"]}:{p["type"]}' for p in d["outputs"]], params=list(d["params"]), lane=d["requires"]["lane"], risk=d["risk"], state=d["validation"]["state"])

    # -- tools
    def list_capabilities(self, query=None, accepts=None, produces=None, kind=None):
        found = self.registry.catalog(kind=kind or None, query=query or None, produces=produces or None, accepts=accepts or None)
        return dict(count=len(found), capabilities=[self.compact(d) for d in found[:40]], truncated=len(found) > 40)

    def inspect_capability(self, id):
        try:
            return self.registry.describe(id)
        except KeyError:
            raise ValueError(f"«{id}» não existe. Use list_capabilities.") from None

    def list_media(self):
        return dict(media=self.host.media())

    def validate_graph(self, graph_json):
        report = dag.validate(self.graph(graph_json), self.registry, self.env.tier, self.env.resolve_media)
        return dict(ok=report["ok"], errors=[e["message"] for e in report["errors"]], order=report["order"], resources=report["resources"])

    def estimate_resources(self, graph_json):
        graph = self.graph(graph_json)
        report = dag.validate(graph, self.registry, self.env.tier, self.env.resolve_media)
        if not report["ok"]:
            return dict(ok=False, errors=[e["message"] for e in report["errors"]])
        return dict(ok=True, **{k: v for k, v in report["resources"].items()}, nodes=len(report["order"]))

    def execute_graph(self, graph_json, force=None):
        graph = self.graph(graph_json)
        report = dag.validate(graph, self.registry, self.env.tier, self.env.resolve_media)
        if not report["ok"]:
            return dict(status="invalid", errors=[e["message"] for e in report["errors"]])
        if report["resources"]["risk"] != "low" and not self.allow_confirm:
            return dict(status="needs_confirmation", reason=f"o grafo usa uma capacidade de risco {report['resources']['risk']}; peça ao usuário para confirmar antes de executar")
        return self.host.run(graph, [f.strip() for f in str(force or "").split(",") if f.strip()], report["resources"])

    def job_status(self, job_id):
        return self.host.job(job_id)

    def inspect_artifact(self, ref):
        return self.host.inspect(ref)


# ---------------------------------------------------------------- the loop
def run_agent(provider, toolbox, user_text, history=(), max_steps=MAX_STEPS, on_step=None):
    """Tool-calling loop. Returns dict(final, trace, steps, stop, provider). Never raises for a tool failure: the error goes back
    to the model as the tool result so it can correct itself."""
    messages = [dict(role="user", text=t["text"]) if t["role"] == "user" else dict(role="assistant", text=t["text"]) for t in history]
    messages.append(dict(role="user", text=user_text))
    trace, stop, final = [], "limite de passos", ""
    for step in range(1, max_steps + 1):
        started = time.monotonic()
        reply = provider.step(SYSTEM, messages, toolbox.tools)
        messages.append(dict(role="assistant", text=reply["text"], calls=reply["calls"], raw_parts=reply.get("raw_parts")))
        if not reply["calls"]:
            final, stop = reply["text"], "resposta final"
            break
        for call in reply["calls"]:
            tool = toolbox.by_name.get(call["name"])
            began = time.monotonic()
            if tool is None:
                result = dict(error=f"ferramenta «{call['name']}» não existe; use: {', '.join(toolbox.by_name)}")
            else:
                try:
                    result = tool["fn"](**{k: v for k, v in (call["args"] or {}).items() if k in tool["parameters"]["properties"]})
                except Exception as exc:  # the model gets the reason and may try again
                    result = dict(error=f"{type(exc).__name__}: {exc}"[:600])
            text = json.dumps(result, ensure_ascii=False, default=str)
            if len(text) > RESULT_LIMIT:
                result = dict(truncated=True, preview=text[:RESULT_LIMIT])
            messages.append(dict(role="tool", id=call["id"], name=call["name"], result=result))
            entry = dict(step=step, tool=call["name"], args=call["args"], ok="error" not in result and result.get("status") not in ("invalid",), ms=round((time.monotonic() - began) * 1000),
                         result=text[:700])
            trace.append(entry)
            if on_step:
                on_step(entry)
        if time.monotonic() - started > 600:
            stop = "tempo"
            break
    return dict(final=final, trace=trace, steps=len(trace), stop=stop, provider=getattr(provider, "name", "custom"), model=getattr(provider, "models", [None])[0] if hasattr(provider, "models") else getattr(provider, "model", None))


# ---------------------------------------------------------------- the real host (jobs, media, artifacts)
class LocalHost:
    """Connects the tools to the real job manager: a graph becomes a real job, CPU jobs are awaited, results become files the
    agent can inspect. `media_list()` returns the conversation's media ([{id, name, kind, origin}]); `on_result(files, job)`
    lets the application attach results to the conversation."""

    def __init__(self, registry, env, manager, media_list, on_result=None, wait=150, on_job=None):
        self.registry, self.env, self.manager, self.media_list, self.on_result, self.wait, self.on_job = registry, env, manager, media_list, on_result, wait, on_job
        self.runs = {}

    def media(self):
        return self.media_list()

    def run(self, graph, force, resources):
        box = {}

        def runner(ctx):
            box["run"] = dag.execute(graph, self.registry, self.env, ctx, force=force)
            files = dag.final_files(box["run"])
            if self.on_result:
                self.on_result(files, ctx.job)
            return files

        lane = resources["lane"]
        job = self.manager.submit("dag", "Agente · " + ", ".join(n["cap"] for n in graph["nodes"])[:60], {}, lane, runner)
        self.runs[job.id] = box
        if self.on_job:
            self.on_job(job)
        if lane != "cpu":
            return dict(status="queued", job_id=job.id, lane=lane, note="job de GPU em andamento; acompanhe com job_status")
        deadline = time.monotonic() + self.wait
        while job.status not in ("concluído", "falhou", "cancelado", "travado") and time.monotonic() < deadline:
            time.sleep(0.15)
        return self.describe(job)

    def describe(self, job):
        out = dict(status=job.status, job_id=job.id, message=job.message or None)
        run = self.runs.get(job.id, {}).get("run")
        if job.status == "concluído" and run:
            out["recomputed"], out["cached"] = run["recomputed"], run["cached"]
            out["outputs"] = [dict(node=nid, port=port, type=o["type"], ref=Path(o["path"]).resolve().relative_to(self.env.out_dir.resolve()).as_posix() if o.get("path") else None,
                                   value=o.get("value") if not o.get("path") else None, sha256=o["sha256"][:12])
                              for nid, outputs in run["final"].items() for port, o in outputs.items()]
        return {k: v for k, v in out.items() if v is not None}

    def job(self, job_id):
        job = self.manager.get(str(job_id))
        if job is None:
            raise ValueError("job desconhecido")
        return dict(self.describe(job), progress=round(job.fraction, 2), desc=job.desc)

    def path_of(self, ref):
        found = self.env.resolve_media(ref)
        if found:
            return Path(found["path"]), found["type"]
        target = (self.env.out_dir / str(ref)).resolve()
        if not target.is_relative_to(self.env.out_dir.resolve()) or not target.is_file():
            raise ValueError("arquivo desconhecido; use um id de list_media ou um ref devolvido por execute_graph")
        return target, None

    def inspect(self, ref):
        path, kind = self.path_of(ref)
        info = dict(name=path.name, bytes=path.stat().st_size)
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
            import cf_refine
            from PIL import Image
            with Image.open(path) as image:
                info.update(width=image.width, height=image.height, mode=image.mode)
            info["technical_gate"] = [dict(line=v.line, status=v.status, reason=v.reason) for v in cf_refine.judge(path, {}, ["not_blank", "sharp", "exposure"])]
        return info


def history_from_session(session, limit=8):
    out = []
    for m in session["messages"][-limit:]:
        if m["role"] == "user" and m.get("text"):
            out.append(dict(role="user", text=m["text"][:400]))
        elif m["role"] == "assistant" and m.get("text") and not m.get("pending"):
            out.append(dict(role="assistant", text=m["text"][:400]))
    return out
