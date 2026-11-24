# V9 — estado (atualizado por entrega)

Base: `64998ff` (= `origin/main`, auditoria pré-Opus). P0 em `c314f6a`, P1 Asset em `7b6f043`, ambos em `origin/v9/integration` (main não tocada).
Máquina de teste desta sessão: PC local, CPU, 3,7 GB de RAM (≈0,8 GB livres), sem GPU. Um pytest por vez, nunca a suíte inteira.

## Mapa curto de dependências e donos

| Fila | Item | Depende de | Dono (nesta sessão) | Estado |
|---|---|---|---|---|
| P0 | V9-P0-001 dono único do worker (lock global) | — | Opus (serial; sem Sonnet: RAM local não comporta 2 pytest) | TESTADO CPU |
| P0 | V9-P0-002 job «concluído» sem arquivo | — | Opus | TESTADO CPU |
| P0 | V9-P0-003 reinício falho / RAM desconhecida / fallback silencioso | 001 | Opus | TESTADO CPU |
| P0 | V9-P0-004 `plan` pela rota HTTP `/jobs/{id}` | — | Opus | TESTADO CPU |
| P0 | V9-P0-005 recibos das 15 fontes aprovadas | — | Haiku (subagente, só leitura web); pins conferidos por Opus com `curl` | FONTE LIDA / LICENÇA AVALIADA (ver `docs/sources/INDEX.md`) |
| P0 | V9-P0-006 docs com números corrigidos (`/free`, Turbo, 408/19, sementes) | auditoria | Opus | feito em `docs/VALIDACAO_GPU.md`, `CLAUDE.md` |
| P0 | V9-P0-007 linha de base do agente (`plan_eval.py`) | LLM no Colab | humano + Sonnet | **BLOQUEADO**: `plan_eval.py` sumiu do `/tmp`; só `agent_full.py` foi recuperado (`tests/agent_eval/agent_full.py`) |
| P0 | Delta da revisão do dono (4 itens) | P0 | Opus | TESTADO CPU (`7c303a0`); patch anexo não chegou, itens refeitos pela descrição |
| P0 | Suíte completa no HEAD | máquina ≥ 8 GB (Colab CPU) | humano/Colab | NÃO EXECUTADO |
| P1 | Asset Graph (V9-P1-ASSET-001) | P0 aceito | Sonnet + Opus | TESTADO CPU / API real / navegador real |
| P1 | Cinema alfa (60 s) V9-P1-CINEMA-001 | Asset Graph | Opus (motor, direção) + Haiku (fontes) | TESTADO CPU / API real; exibição humana do corte PENDENTE; T4 PENDENTE |
| P1 | Cinema na tela V9-P1-CINEMA-002 | CINEMA-001 | Opus | TESTADO CPU / API real / navegador real; decisão A/B do dono PENDENTE |
| P1 | Matriz das 93 reconciliada (12 fora da matriz) | — | Haiku | NÃO INICIADO |

## V9-P0-001..004 — prestação de contas

```text
V9-P0-001 — dois chamadores de cf_workflows.run não reiniciam o worker um sob o prompt do outro
HEAD/commit: árvore sobre 64998ff, sem commit
Mudança: cf_worker.py (hold/busy/WorkerUnavailable; restart sob o lock), cf_workflows.py (run segura o worker do início ao fim),
         cf_seedvr2.py (run sob o lock: posta /prompt próprio), cf_apps.py (A14B: 2 estágios + reinício como uma unidade),
         cf_api.py (guarda do LLM também vê o lock, cobre o modo clássico)
Fonte externa: nenhuma
Testes: antes — test_worker_lock.py::test_a_second_caller... 1 failed (pid 1545183→1545196 com A esperando);
        depois — test_worker_lock.py 9 passed; test_worker_restart 5; test_llm_release 14; test_wan 40; test_dag 10;
        test_agent 16 (+2 skip); test_agent_api 5 (+1 skip); test_seethrough 2 (+3 skip); test_upscalers 1 skip;
        test_comfy_real -k latent 1 passed (ComfyUI 0.44 REAL em CPU, novo run())
GPU: NÃO TESTADO
Riscos: um job longo do modo clássico agora faz o job do Studio ESPERAR (com aviso «Aguardando outro job do ComfyUI terminar»),
        em vez de morrer. cf_comfy_check.py ainda posta /prompt sem o lock (ferramenta de checagem, fora dos jobs).
Estado: TESTADO CPU (worker falso rotulado + ComfyUI real em CPU para o caminho do latente)
```

```text
V9-P0-002 — job sem arquivo não vira «concluído»
Mudança: cf_jobs.py (Effect(note) para efeito sem mídia; lista vazia/None → falhou; arquivo fora da pasta ou inexistente → descartado e dito),
         cf_apps.py (6 instaladores devolvem Effect)
Testes: test_worker_lock.py (4 casos de cf_jobs) + test_llm_release/test_dag/test_agent_api sem regressão
Limite: um grafo do DAG cujo resultado final é só texto (sem arquivo) agora FALHA; nenhuma receita atual é assim, mas é escolha a revisar
Estado: TESTADO CPU
```

```text
V9-P0-003 — falhas explícitas
Mudança: restart_if_bloated levanta WorkerUnavailable quando o reinício era necessário e o worker não voltou (antes: False ambíguo e ignorado);
         run falha com motivo se o worker está fora e nunca foi visto; A14B entre estágios: worker morto → JobError,
         reinício impossível com worker vivo → segue com /free e DIZ isso no progresso; cf_wan.memory_problem recusa o Q6_K com RAM ilegível
Testes: test_worker_lock (reinício falho, worker nunca visto), test_wan (dois ramos do A14B, RAM 0)
Não feito: cf_api.py:84-90 `except Exception: pass` na captura do worker; cf_llama.gpu_loaded sem nvidia-smi; os `except: pass` antigos de cf_workflows/cf_civitai/cf_diagnose
Estado: TESTADO CPU
```

```text
V9-P0-004 — `plan` exposto em /jobs/{id}
Teste: test_agent_api.py::test_an_agent_job_exposes_its_plan_on_the_http_job_route — chat → agente → LocalHost → Manager → GET /jobs/{id},
       com um PROVEDOR ROTEIRIZADO rotulado (sem llama-server); o modelo real continua coberto pelo teste live (skip aqui)
Estado: TESTADO CPU (API real via TestClient)
```

## Revisão pré-commit (23/11) — achados corrigidos no próprio patch P0

```text
V9-P0-R1 — cancelar um job que ainda espera a trava não interrompe o prompt do dono
Achado: o job na espera não tem prompt_id; Manager.cancel/Control.cancel mandavam /interrupt sem id, que no ComfyUI 0.44
        (server.py post_interrupt) interrompe QUALQUER prompt em execução. A trava tornou esse caso alcançável.
Mudança: cf_jobs.cancel e cf_workflows.Control.cancel só interrompem com prompt_id
Testes: test_worker_lock::test_cancelling_a_job_that_waits... — com a guarda revertida: 1 failed (interrupts.log criado); com a guarda: passed
Estado: TESTADO CPU (worker falso rotulado)
```

```text
V9-P0-R2 — grafo cujo passo final é só texto/JSON não vira falha
Achado: o patch P0 marcava como «falhou» um DAG cujo resultado é `value` sem `path` (text_list, resolution_plan): regressão.
Mudança: cf_jobs.Effect(note, kind="effect"|"text"|"json") e campo `outcome` ("media" ou o kind) no snapshot/HTTP;
         cf_dag.job_result(run) = arquivos, senão Effect text/json, senão [] (falha); usado pelos 3 runners de cf_api e pelo do agente
Testes: test_worker_lock::test_a_dag_whose_sinks...; test_agent_api::test_a_text_only_graph... (API real, text_list → outcome "text")
Contrato: mídia válida = arquivo dentro da pasta de saída; texto/JSON = valor no registro da execução (ou arquivo .txt/.json, kind "file");
          efeito = Effect("effect") só em runners que conferem o efeito (instaladores com SHA-256). Nada mais conclui vazio.
Estado: TESTADO CPU
```

## V9-P1-ASSET-001 — AssetRef.v1 ponta a ponta (24/11)

```text
V9-P1-ASSET-001 — uma versão de ativo atravessa dois apps sem reupload; v2 refaz só o ramo afetado; v1 segue selecionável
HEAD/commit: sobre c314f6a
Mudança: cf_asset_graph.py (novo: blobs sha256 imutáveis 0444, index atômico, publish/add_version/resolve/verify, dedup),
         cf_api.py (media_file único: uploads + v_/a_; rotas /assets; asset_versions no job; /uploads/{v_} hidrata),
         portal: «Usar em» publica e passa a referência (sem /import), tela #/assets (versões, seletor, Usar em, nova versão,
         verificar integridade), Elenco «Publicar como ativo»
Contrato: docs/V9_ASSET_GRAPH_CONTRACT.md (+ campo HTTP `asset_versions` no job)
Fonte externa: nenhuma no código (recibos em docs/sources/V9-P1-ASSET-001-recibos.md)
Divisão: Opus contrato + revisão (2 defeitos corrigidos: job_producer quebrava em job DAG; procedência invisível na API);
         Sonnet implementação (parou antes de testar; testes rodados por Opus); Haiku pesquisa de fontes
Testes (PC local CPU, um por vez): test_asset_graph 11 passed; test_agent_api 6 (+1 skip: sem llama-server); test_dag 10;
         test_cast 8; test_recipes_api 4; test_myflows 8; test_worker_lock 11
Demo API (engine real local): tests/demo/asset_graph_demo.py → docs/evidence/V9-P1-ASSET-001-api.txt
Demo navegador (portal /studio no engine local): Ativos → v1 → Usar em → Cor e contraste e → Enquadrar imagem; os dois jobs
         registram asset_versions = v1; nenhum POST /upload ou /import na rede; uploads/ sem cópia; 375 px sem rolagem lateral
GPU: NÃO TESTADO (não é necessário para esta entrega)
Limites: lock do índice é por processo; blob 0444 não impede root (Colab roda como root) — o verify() detecta;
         dedup compara só com a versão atual; sem apagar ativo, sem backup/exportação; vídeo/áudio sem ffprobe ficam sem duração
Estado: TESTADO CPU / API real / navegador real (engine local)
```

**Delta da revisão do dono** — o arquivo anexo não chegou a esta máquina; os quatro itens descritos foram corrigidos em `7c303a0`:

```text
V9-P0-R3 — cancelar enquanto o POST /prompt está em voo: collect interrompe o próprio prompt pelo id antes de dar «cancelado»
V9-P0-R4 — cf_seedvr2.reopen segura cf_worker.hold() (pode postar o fallback 3B)
V9-P0-R5 — DAG só JSON pela rota HTTP: outcome "json", valor lido de /dag/runs
V9-P0-R6 — animatic com duração exata (antes 3 × 1,5 s = 109 quadros / 4,54 s; 3 × 0,7 s = 52 quadros)
Testes: test_worker_lock 13 (R3/R4 falham com a correção revertida); test_agent_api 7 (+1 skip); test_storyboard 11
Pendente: A14B e SeedVR2 na T4
```

```text
V9-P1-CINEMA-001 — curta editável de 60 s, trilhas separadas, troca de tomada que reaproveita o resto
Mudança: cf_cinema.py (Timeline.v1, cache por plano com digest/fresh/mark do Content Factory, concat sem recodificar,
         3 trilhas WAV float, mix com ducking e loudness em 2 passadas, MP4 com 4 áudios nomeados),
         cf_api.py (POST /cinema/validate, POST /cinema/render na fila de CPU, asset_versions no job)
Contrato e direção: docs/V9_CINEMA_ALFA.md · recibos: docs/sources/V9-P1-CINEMA-001-recibos.md
Testes (PC local CPU, um por vez): test_cinema 6 passed; test_asset_graph 11; test_agent_api 7 (+1 skip); test_recipes_api 4
Demo (tests/demo/cinema_alfa_demo.py, tomadas reais do Studio na T4): render morto por SIGKILL após 3 planos → retomada reaproveita
         s01–s03 → troca de s04 (v1→v2) refaz só s04 e a junção; 8 segmentos com os mesmos bytes; trilhas e mix reaproveitados
Medido: 46,9 s de parede para as 3 rodadas; pico 232 MB (processo) / 227 MB (filhos); filme −15,9 LUFS, −1,5 dBTP; 1440 quadros, 60,000 s
Evidência: docs/evidence/V9-P1-CINEMA-001/
GPU: NÃO TESTADO (montagem é CPU; geração de novas tomadas e Stable Audio ficam para a T4)
Pendente: exibição humana do corte inteiro; tela no portal; OpenTimelineIO
Estado: TESTADO CPU / API real
```

```text
V9-P1-CINEMA-002 — abrir, editar e exportar «A última luz» pela tela, com sessão A/B
Mudança: cf_cinema.py (CinemaProject.v1: cortes que só mudam música/efeitos/mix; troca de tomada só dentro do mesmo ativo;
         export_project com registro A/B: imagem idêntica por MD5 e volume de cada corte), cf_api.py (rotas /cinema/projects…,
         uma pasta por exportação), portal/js/views/cinema.js (#/cinema), menu «Cinema»
Doc: docs/V9_CINEMA_TELA.md · evidência: docs/evidence/V9-P1-CINEMA-002/
Testes: test_cinema 7 passed (novo: projeto → troca → A/B duas vezes, pares antigos intactos); test_asset_graph 11; test_agent_api 7 (+1 skip)
Navegador (engine local, cache vazio): exportar A e B → A refaz tudo, B só música/efeitos/mix; trocar s04 → A refaz s04 + junção, B nada;
         imagem idêntica, −15,9/−15,9 LUFS; segmentos iguais byte a byte aos da prova pela API; 375 px sem rolagem lateral
Achados corrigidos na prova: exportações sobrescreviam a anterior (mesma pasta e nomes); relatório lido do cache do navegador;
         miniatura mostrava o quadro cru, não o enquadramento; menu de 8 itens estourava 375 px
Estado: TESTADO CPU / API real / navegador real
```

## Pendências que dependem do humano
1. Assistir aos dois cortes de «A última luz» na tela Cinema (Sessão A/B) e escolher.
2. Suíte completa no Colab em CPU (`pytest tests -q --ignore=...`, ver `CLAUDE.md`) para cobrir o HEAD inteiro.
3. Linha de base do agente: reescrever `plan_eval.py` (perdido) e rodar com o LLM no ar — 6 pedidos, sem GPU de vídeo.
