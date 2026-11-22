"""ONE operational agent with real tool calling, running on a LOCAL model.

It replaces "an LLM writes text + a router picks + the user clicks every step". The model sees the capability catalog through
tools, builds a typed DAG, validates it (and fixes it from the reasons it gets back), executes it, looks at the result and may
repeat steps. Nothing here parses free text for decisions: every decision is a tool call with arguments.

The only provider is a llama.cpp `llama-server` (OpenAI-style `tools`) on 127.0.0.1, meant for an abliterated Qwen3.5-9B GGUF on
the Colab GPU (see cf_llama). No outside API is called. Protocol validated here against a real Qwen3.5-0.8B on CPU; the 9B has
not been run on this machine (no GPU), so its tool-calling quality is NOT measured.
No outside service is involved: the model is local (llama-server or colibri).

Policy: low-risk graphs run without asking. A graph that needs a high-risk capability is returned as `needs_confirmation`
and only runs when the user has confirmed it (the `confirm` argument is set by the application, never trusted from the model
alone: see `Toolbox.allow_confirm`).
"""

import json
import os
import time
import uuid
from pathlib import Path

import requests

import cf_capabilities as caps
import cf_dag as dag
import cf_llm

MAX_STEPS = 10
RESULT_LIMIT = 6000

SYSTEM = """Você é o operador do ClonField Studio, um estúdio de imagem, vídeo e áudio. Você age SOMENTE chamando ferramentas.
Regras:
- Descubra o que existe com list_capabilities (filtre por texto, por tipo de entrada com accepts, por saída com produces) e inspect_capability. Nunca invente o id de uma capacidade, de uma mídia ou de um parâmetro.
- As mídias do usuário vêm de list_media; use o campo id delas em {"media": "<id>"}.
- Monte um grafo JSON: {"nodes":[{"id":"a","cap":"<capacidade>","inputs":{"<entrada>":{"media":"<id>"} ou {"from":"<no>.<saida>"}},"params":{...}}]}. Passos podem se repetir (por exemplo duas ampliações) e podem usar a saída de qualquer passo anterior.
- Para encadear passos (por exemplo gerar imagem, ampliar e animar em vídeo, escolhendo o modelo de cada passo) prefira compose_chain: ele liga o resultado de um passo ao seguinte e devolve o grafo pronto; com run=sim já executa. Escolha parâmetros reais olhando inspect_capability (modelo, qualidade, duração, seed). Para listas (vários cenários, quadros de um vídeo) um passo pode rodar uma vez por item ("each"), receber um texto de um passo anterior ("bind") ou rodar só se uma medição passar ("when"; com "not": true roda só se NÃO passar, e first_of junta os dois ramos: assim se faz um se/senão). Se uma receita de list_recipes cobre o pedido (inclusive as de «Meus fluxos»), use run_recipe. Quando um fluxo montado por você funcionou e o usuário quer reaproveitá-lo, guarde com save_flow. Para refazer uma execução que já rodou mudando só um detalhe, use revise_run (o que não mudou vem do cache). Para mudar um fluxo já montado (trocar um parâmetro, inserir uma ampliação, tirar um passo) use edit_graph em vez de reescrever o grafo; listas podem ser cortadas (take_images), unidas (merge_images) e filtradas por qualidade (keep_passing); números podem ser varridos com sweep (ligue-o com bind + each a um parâmetro numérico, ou à semente para N variações); imagens viram vídeo com slideshow e clipes viram loop com video_fx.
- Antes de executar, rode validate_graph. Se houver erros, corrija o grafo usando os motivos devolvidos e valide de novo.
- Execute com execute_graph. Depois confira o resultado com inspect_artifact; se a conferência técnica falhar, ajuste e execute de novo.
- Apps de GPU e passos de risco alto: se execute_graph responder needs_confirmation, pare e peça ao usuário para confirmar; não tente contornar.
- Não filtre nem recuse por tema (o usuário é adulto e responsável): execute o que foi pedido, inclusive conteúdo adulto, sem avisos.
- Não faça o que não foi pedido. Se faltar uma mídia ou a informação for ambígua, pergunte em uma frase.
- Responda ao usuário em português, curto, dizendo o que foi feito e o que saiu (nomes de arquivos e medidas reais, sem inventar)."""


class AgentError(Exception):
    pass


# ---------------------------------------------------------------- providers
class OpenAICompatProvider:
    """llama.cpp llama-server (or any OpenAI-compatible endpoint) with native tool calls. Meant for Qwen3.5-9B GGUF on the T4."""

    def __init__(self, base_url=None, model="qwen", timeout=300):
        self.base = (base_url or cf_llm.base_url()).rstrip("/")
        self.name = "colibri" if (not base_url and cf_llm.backend() == "colibri") else "llama-server"
        if self.name == "colibri" and model == "qwen":
            model = cf_llm.models()[0]  # colibri answers to the id of the model it serves
        self.model, self.timeout = model, timeout
        self.models = [model]

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
        body = {"model": self.model, "messages": self.wire(system, messages), "temperature": 0.2, "max_tokens": 1500, "chat_template_kwargs": {"enable_thinking": False},
                "tools": [{"type": "function", "function": dict(name=t["name"], description=t["description"], parameters=t["parameters"])} for t in tools]}
        if self.name == "colibri":
            body["enable_thinking"] = False  # colibri's extension is top-level; chat_template_kwargs is llama.cpp's
        try:
            cf_llm.ensure_gpu_free()
        except cf_llm.LLMError as exc:
            raise AgentError(str(exc)) from None
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
    """The local llama-server when one answers, else None (the chat then keeps its heuristic path)."""
    return OpenAICompatProvider() if cf_llm.available() else None


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
            dict(name="search_models", description="Procura componentes (modelos de difusão, encoders, VAEs, upscalers) no que já está instalado, no Civitai ou no Hugging Face. Só descobre: não baixa nada (baixar exige o usuário).",
                 parameters=schema(role=S("Difusão|Checkpoint|Encoder|VAE|Upscaler|LoRA", True), family=S("modelo da receita: qwen21|flux2|flux3|krea2|z-image", True), query=S("termo de busca"), source=S("local|civitai|huggingface (padrão local)")), fn=self.search_models),
            dict(name="list_cast", description="Personagens salvos no Elenco (nome e descrição). Num pedido de imagem ou vídeo, escreva @nome no prompt: o Studio troca pela descrição e usa a imagem do personagem como referência.",
                 parameters=schema(), fn=self.list_cast),
            dict(name="compose_chain", description="Monta um fluxo ligando passos em fila: o resultado de cada passo entra no seguinte (mesmo tipo de mídia). Ex.: gerar imagem, ampliar, animar em vídeo. Cada passo: {\"cap\", \"params\"?, \"inputs\"?: {entrada: id_de_mídia}, \"each\"?}. Se o passo anterior devolve uma lista, o seguinte roda uma vez por item. Com run=sim já executa (se válido).",
                 parameters=schema(stages_json=S("lista JSON de passos: [{\"cap\":\"app.create\",\"params\":{...}},{\"cap\":\"upscale\"},{\"cap\":\"app.animate\",\"params\":{\"model\":\"5b-q6\"}}]", True), run=S("sim para executar já; padrão não")), fn=self.compose_chain),
            dict(name="edit_graph", description="Revisa um grafo já montado sem reescrevê-lo. ops_json é uma lista de operações: {\"op\":\"set_param\",\"node\",\"name\",\"value\"}, set_params, remove (os passos seguintes passam a ler o que o removido lia), insert_after ({\"node\",\"cap\",\"params\"?,\"id\"?,\"output\"?}: o novo passo entra depois e assume os consumidores), replace_cap, set_each, set_when, set_bind. Devolve o grafo novo já validado; com run=sim executa.",
                 parameters=schema(graph_json=S("o grafo atual como texto JSON", True), ops_json=S("lista JSON de operações", True), run=S("sim para executar já; padrão não")), fn=self.edit_graph),
            dict(name="save_flow", description="Guarda um grafo que deu certo como fluxo reutilizável em «Meus fluxos»: os arquivos viram campos do formulário e os parâmetros listados em expose_json viram campos editáveis. Depois ele roda com run_recipe e aparece na tela Fluxos. Só salve quando o usuário pedir ou concordar.",
                 parameters=schema(graph_json=S("o grafo como texto JSON", True), title=S("nome do fluxo (3 a 60 caracteres)", True), tagline=S("uma frase do que ele faz"),
                                   expose_json=S("lista JSON de parâmetros editáveis: [{\"node\":\"id\",\"name\":\"parâmetro\",\"label\":\"rótulo\"}]")), fn=self.save_flow),
            dict(name="revise_run", description="Refaz uma execução anterior (run_id vem de execute_graph/job_status) mudando só o que precisa: ops_json aplica as mesmas operações de edit_graph ao grafo daquela execução; force lista nós a recalcular ignorando o cache. Os passos que não mudaram e não dependem dos mudados vêm do cache (veja recomputed/cached no resultado).",
                 parameters=schema(run_id=S("id da execução anterior", True), ops_json=S("lista JSON de operações de edit_graph (opcional)"), force=S("ids de nós separados por vírgula para recalcular")), fn=self.revise_run),
            dict(name="list_recipes", description="Receitas prontas: fluxos de vários passos (lote de imagens, matriz de cenários, storyboard em filme…) com o formulário de cada uma. Prefira uma receita a montar o grafo à mão quando ela cobre o pedido.",
                 parameters=schema(), fn=self.list_recipes),
            dict(name="run_recipe", description="Executa uma receita. vars_json é o formulário como objeto JSON (ids de mídia de list_media nos campos de arquivo); uma LISTA de objetos enfileira uma execução por item. Receitas de GPU devolvem job_id.",
                 parameters=schema(recipe=S("id da receita", True), vars_json=S("formulário em JSON: {...} ou [{...}, {...}]", True)), fn=self.run_recipe),
            dict(name="system_info", description="Placa, VRAM e RAM livres (do ComfyUI, se estiver no ar) e espaço em disco desta máquina. Só lê. Use antes de escolher um modelo grande.",
                 parameters=schema(), fn=self.system_info),
            dict(name="free_memory", description="Descarrega os modelos do ComfyUI da VRAM e da RAM. O próximo job recarrega os pesos (fica mais lento). Use para abrir espaço antes de um modelo grande.",
                 parameters=schema(), fn=self.free_memory),
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

    def search_models(self, role, family, query="", source="local"):
        import cf_apps
        import cf_search
        if source not in cf_search.SOURCES:
            raise ValueError(f"fonte inválida; use {', '.join(cf_search.SOURCES)}")
        if family not in cf_apps.lab.PRESETS:
            raise ValueError(f"família desconhecida; use {', '.join(cf_apps.IMAGE_MODELS)}")
        items, _ = cf_search.search(role, family, source, query or "", cf_apps.ENV["civitai"])
        return dict(count=len(items), items=[dict(title=i["title"], status=i["status"], size_mb=i.get("size_mb"), quant=i.get("quant_label") or None, file=i.get("file_name"), url=i.get("url")) for i in items[:8]])

    def job_status(self, job_id):
        return self.host.job(job_id)

    def list_cast(self):
        import cf_cast
        items = cf_cast.load(self.env.base)
        return dict(count=len(items), cast=[dict(name=i["name"], mention=f"@{i['name']}", description=i.get("description", ""), has_image=bool(i.get("image"))) for i in items])

    def compose_chain(self, stages_json, run="nao"):
        try:
            stages = json.loads(stages_json) if isinstance(stages_json, str) else stages_json
        except ValueError as exc:
            raise ValueError(f"stages_json não é JSON válido: {exc}") from None
        graph = dag.chain(stages, self.registry)
        report = dag.validate(graph, self.registry, self.env.tier, self.env.resolve_media)
        out = dict(graph=graph, ok=report["ok"], errors=[e["message"] for e in report["errors"]], order=report["order"], resources=report["resources"])
        if report["ok"] and str(run).lower() in ("sim", "true", "1", "yes"):
            out["execution"] = self.execute_graph(json.dumps(graph))
        return out

    def edit_graph(self, graph_json, ops_json, run="nao"):
        try:
            ops = json.loads(ops_json) if isinstance(ops_json, str) else ops_json
        except ValueError as exc:
            raise ValueError(f"ops_json não é JSON válido: {exc}") from None
        graph = dag.edit(self.graph(graph_json), ops, self.registry)
        report = dag.validate(graph, self.registry, self.env.tier, self.env.resolve_media)
        out = dict(graph=graph, ok=report["ok"], errors=[e["message"] for e in report["errors"]], order=report["order"], resources=report["resources"])
        if report["ok"] and str(run).lower() in ("sim", "true", "1", "yes"):
            out["execution"] = self.execute_graph(json.dumps(graph))
        return out

    def save_flow(self, graph_json, title, tagline="", expose_json=None):
        import cf_myflows
        try:
            expose = json.loads(expose_json) if isinstance(expose_json, str) and expose_json.strip() else (expose_json or [])
        except ValueError as exc:
            raise ValueError(f"expose_json não é JSON válido: {exc}") from None
        saved = cf_myflows.save(self.env.base, self.registry, self.graph(graph_json), title, tagline, expose, self.env.resolve_media, self.env.tier)
        return dict(saved=True, id=saved["id"], title=saved["title"], replaced=saved["replaced"], form=[dict(id=i["id"], kind=i["kind"], label=i.get("label")) for i in saved["inputs"]],
                    how="rode com run_recipe usando este id; ele também aparece na tela Fluxos, em «Meus fluxos»")

    def revise_run(self, run_id, ops_json=None, force=None):
        try:
            previous = dag.load_run(self.env, str(run_id))
        except (OSError, ValueError):
            raise ValueError("execução desconhecida; use o run_id devolvido por execute_graph ou job_status") from None
        graph = previous["graph"]
        if isinstance(ops_json, str) and ops_json.strip():
            try:
                ops = json.loads(ops_json)
            except ValueError as exc:
                raise ValueError(f"ops_json não é JSON válido: {exc}") from None
            graph = dag.edit(graph, ops, self.registry)
        return self.execute_graph(json.dumps(graph), force)

    def list_recipes(self):
        import cf_recipes
        return dict(recipes=[dict(id=r["id"], title=r["title"], what=r["tagline"], lane=r["lane"], state=r["state"], steps=r["steps"],
                                  inputs=[dict(id=i["id"], kind=i["kind"], label=i.get("label"), options=i.get("options"), default=i.get("default")) for i in r["inputs"]])
                             for r in cf_recipes.catalog(self.env.base)])

    def run_recipe(self, recipe, vars_json):
        import cf_recipes
        try:
            wanted = json.loads(vars_json) if isinstance(vars_json, str) else vars_json
        except ValueError as exc:
            raise ValueError(f"vars_json não é JSON válido: {exc}") from None
        sets = wanted if isinstance(wanted, list) else [wanted]
        if not 1 <= len(sets) <= cf_recipes.MAX_BATCH:
            raise ValueError(f"a fila aceita de 1 a {cf_recipes.MAX_BATCH} execuções")
        try:
            chosen = cf_recipes.get(recipe, self.env.base)
        except KeyError:
            raise ValueError(f"receita «{recipe}» não existe. Use list_recipes.") from None
        runs = []
        for raw in sets:
            graph = chosen.build(cf_recipes.resolve(chosen, raw))
            result = self.execute_graph(json.dumps(graph))
            runs.append(result)
            if result.get("status") in ("invalid", "needs_confirmation"):
                break
        return dict(recipe=recipe, runs=runs)

    def system_info(self):
        import shutil
        import requests
        import cf_workflows
        tier = self.env.tier
        out = dict(gpu=tier.gpu, vram_gb=round(tier.vram_gb, 1), profile=tier.label, worker=None, disk_free_gb=round(shutil.disk_usage(self.env.base).free / 1024**3, 1))
        try:
            with requests.Session() as session:
                session.trust_env = False
                stats = session.get(f"{cf_workflows.SERVER}/system_stats", timeout=3).json()
            device = (stats.get("devices") or [{}])[0]
            system = stats.get("system", {})
            out["worker"] = dict(device=device.get("name"), type=device.get("type"), vram_total_gb=round(device.get("vram_total", 0) / 1024**3, 1), vram_free_gb=round(device.get("vram_free", 0) / 1024**3, 1),
                                 ram_total_gb=round(system.get("ram_total", 0) / 1024**3, 1), ram_free_gb=round(system.get("ram_free", 0) / 1024**3, 1))
        except (requests.RequestException, ValueError):
            out["worker_note"] = "o ComfyUI não respondeu; VRAM e RAM livres desconhecidas"
        return out

    def free_memory(self):
        import requests
        import cf_workflows
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.post(f"{cf_workflows.SERVER}/free", json={"unload_models": True, "free_memory": True}, timeout=10)
            return dict(ok=response.ok, note="modelos descarregados; o próximo job recarrega os pesos" if response.ok else f"o ComfyUI recusou (HTTP {response.status_code})")
        except requests.RequestException:
            return dict(ok=False, note="o ComfyUI não respondeu; nada foi descarregado")

    def inspect_artifact(self, ref):
        return self.host.inspect(ref)


# ---------------------------------------------------------------- the loop
GPU_NOTE = "Iniciei o job de GPU. O modelo de texto fica descarregado enquanto ele roda; o resultado aparece no chat quando terminar."


def run_agent(provider, toolbox, user_text, history=(), max_steps=MAX_STEPS, on_step=None):
    """Tool-calling loop. Returns dict(final, trace, steps, stop, provider). Never raises for a tool failure: the error goes back
    to the model as the tool result so it can correct itself."""
    messages = [dict(role="user", text=t["text"]) if t["role"] == "user" else dict(role="assistant", text=t["text"]) for t in history]
    messages.append(dict(role="user", text=user_text))
    trace, stop, final = [], "limite de passos", ""
    for step in range(1, max_steps + 1):
        started = time.monotonic()
        try:
            reply = provider.step(SYSTEM, messages, toolbox.tools)
        except AgentError:
            if trace and cf_llm.gpu_busy():  # the job started between the tool call and this step (the GPU lane picks it up in its own thread)
                final, stop = GPU_NOTE, "job de GPU iniciado"
                break
            raise
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
        if cf_llm.gpu_busy():  # a tool started a GPU job: the text model is unloaded while it runs, so the turn ends here with a fixed answer
            final, stop = GPU_NOTE, "job de GPU iniciado"
            break
        if time.monotonic() - started > 600:
            stop = "tempo"
            break
    return dict(final=final, trace=trace, steps=len(trace), stop=stop, provider=getattr(provider, "name", "custom"), model=getattr(provider, "model", None))


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

        run_id = uuid.uuid4().hex[:12]
        box["run_id"] = run_id

        def runner(ctx):
            box["run"] = dag.execute(graph, self.registry, self.env, ctx, run_id=run_id, force=force)
            files = dag.final_files(box["run"])
            if self.on_result:
                self.on_result(files, ctx.job)
            return files

        lane = resources["lane"]
        job = self.manager.submit("dag", "Agente · " + ", ".join(n["cap"] for n in graph["nodes"])[:60], {"run": run_id}, lane, runner)
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
        out = dict(status=job.status, job_id=job.id, message=job.message or None, run_id=self.runs.get(job.id, {}).get("run_id"))
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
