# ClonField Studio — changelog honesto do mandato V8.3 até hoje

Gerado em 2026-11-15 a partir do `git log` e dos documentos do repositório. Tudo abaixo está na `main` do GitHub (`f349e71`).

**Janela:** `e5f2382` (12/11, primeiro commit do plano V8.3) até `f349e71` (15/11). Parte de `fa4867a` (changelog V7, 12/11).
**Tamanho:** 42 commits, 142 arquivos mudados, +37.921 / −589 linhas; 106 arquivos novos. Repositório inteiro: 100 commits.
**Máquina de teste:** CPU, 3 GB de RAM, sem GPU. Nada abaixo rodou na T4/Colab, exceto onde dito.

**Como ler os estados** (do mais fraco ao mais forte): `NÃO INICIADO` → `CÓDIGO ESCRITO` → `TESTADO CPU` → `TESTADO API REAL` → `TESTADO GPU` → `INTEGRADO E VALIDADO`. `BLOQUEADO_GPU` = só falta a T4; o código e o grafo existem e foram validados contra o registro/ComfyUI real, mas nenhuma imagem/vídeo foi gerado. Nada aqui é "aprovado para produção".

## Números de hoje

| Medida | Antes (V7, 11/11) | Hoje |
|---|---|---|
| Apps no registro | 20 visíveis | 37 |
| Capabilities (registro tipado) | não existia | 67: 36 apps, 25 passos nativos, 5 ações, 1 motor |
| Receitas de fluxo | não existia | 18 (11 testadas em CPU de verdade, 7 `BLOQUEADO_GPU`) |
| Testes pytest | 102 passed (12/11, fim do Lote 1) | 383 passed, 19 skipped |
| Testes e2e Playwright (Chromium, engine real) | 53 (12/11) | 185 passed |
| Arquivos de teste | — | 48 pytest + 19 specs e2e |

## Linha do tempo por lote do plano

### Lote 1 — P0, correção de regressões (12/11) — `e5f2382`…`92bfdc8`
| Item | O que mudou | Estado |
|---|---|---|
| Infra e2e | Playwright (Node 24, specs CommonJS), engine real, todas as rotas × 4 tamanhos de tela, falha em qualquer erro de console | TESTADO CPU |
| P0-A Home | Home quebrada (`have is not defined`) reproduzida pelo teste e corrigida; anexar mídia volta a preencher o app | TESTADO CPU |
| P0-C Popovers | `popover.js` (vira para cima/baixo, trava na janela, vira bottom sheet no celular); removida a regra de CSS que prendia tudo num canto | TESTADO CPU |
| P0-B LoRA | Uma fonte da verdade (pasta do Studio + ComfyUI + catálogo), classificada por modelo (confirmada/provável/desconhecida/incompatível), busca, interruptor on/off que antes não existia | TESTADO CPU / API real; uso com `LoraLoader` na GPU `BLOQUEADO_GPU` |
| P0-D Capas | Reconciliação por chave (sem piscar), URLs assinadas estáveis, cache persistente de capas com ETag, fim do override por `localStorage` | TESTADO CPU |
| P0-E Variantes | Identidade imutável por arquivo Civitai, verificação antes do download, um cartão por arquivo, MiB × MB corrigido | TESTADO CPU / API real |

Relatório de evidência: `docs/EVIDENCIA_LOTE1.md` (antes/depois, comandos, falhas que restaram).

### Lote 2 — registro de capacidades, DAG e agente (13/11)
- `f4c8b02` **Registro de capabilities + executor DAG tipado** (`cf_capabilities.py`, `cf_dag.py`): cache por hash de conteúdo, reexecução parcial, cancelar/retomar, procedência. TESTADO CPU.
- `b1c0b91` **Agente com tool calling** (`cf_agent.py`), API do DAG, página «Capacidades», trilha do agente no chat. TESTADO CPU; o laço roda com um modelo de verdade só quando há llama-server.
- `b986989` **Chat e agente 100% locais:** Gemma e API do Google removidos; Qwen3.5-9B abliterado via llama.cpp; filtro adulto LIGADO por padrão.
- `5c6b939`, `7e387a3` colibri como backend local; **Jev/TypeSafe removidos**: o agente decide, o roteador é só heurístico.
- Mudança de direção: a camada Gemma + Jev do plano original foi trocada por modelo local único por decisão sua.

### Lote 3 — vídeo (13/11)
- `f9f7ab5` **Wan 2.2 em GGUF**: A14B Q6_K T2V/I2V em dois samplers, 5B Q6/Q8/FP16; controles de duração em segundos, FPS, tamanho livre, variações. Grafos validados contra o ComfyUI real; **nenhum MP4 gerado: BLOQUEADO_GPU**.
- `2b693b4` LTX-Video 2B; `39e01b5` Wan SCAIL-2 e Wan Animate 2 (travados em 24 GB); `081b588` modo rápido do A14B, Qwen 2.1 Turbo, offload.

### Backlog de capacidades/apps (13–14/11)
| Commit | App / capacidade | Estado honesto |
|---|---|---|
| `adaf9fb` | Expandir imagem, Restaurar foto, Trocar roupa (receitas das LoRAs dos autores) + passos de outpaint | CÓDIGO ESCRITO / grafo validado; GPU `BLOQUEADO_GPU` |
| `5a121c2` | Editor de caixas para «Editar região» (caixas → máscara), `bbox_mask` | TESTADO CPU |
| `2c80588` | Fábrica de vídeo com cenas do ComfyUI local; APIs pagas de imagem nunca escolhidas | TESTADO CPU |
| `54c4788` | Troca de rosto com FaceFusion 3.9.2 real, consentimento obrigatório | TESTADO CPU |
| `4191543` | Áudio com Stable Audio 3, expansão de prompt pelo LLM local, player | grafo validado; áudio gerado `BLOQUEADO_GPU` |
| `c517916` | MOSS (nós nativos), Imagem→3D (template oficial), conversor UI→API de workflow | TESTADO API REAL contra ComfyUI; geração `BLOQUEADO_GPU` |
| `41d793b` | Troca de cabeça/corpo (BFS); H3 medido como inviável numa T4 | CÓDIGO ESCRITO |
| `6884614` | Apps acima da VRAM da placa rodam com offload em vez de recusar | CÓDIGO ESCRITO |
| `e8644cf` | Comparar modelos: mesmo pedido em 2–3 modelos com segundos por passo e VRAM medidos | medição só na GPU |
| `c3ddcf9` | Folha de personagem (uma edição por vista) | `BLOQUEADO_GPU`; fidelidade entre vistas não medida |
| `92c3632` | Direção de cinema compilada em prompt de imagem e vídeo | TESTADO CPU |
| `6099d42` | Elenco (@nome), Cobertura de cena, Entre dois quadros com medidor de emenda | medidor TESTADO CPU; geração `BLOQUEADO_GPU` |
| `4889bbe` | Storyboard (modelo local planeja 2–6 planos → imagens → folha + animatic) | parsing/folha/animatic TESTADO CPU; qualidade do plano não medida |
| `6b06103` | Remover fundo (U²-Net ONNX em CPU) | TESTADO CPU |

### Fluxos, agente e receitas (14–15/11) — a maior parte do trabalho recente
| Commit | O que entrou | Estado |
|---|---|---|
| `6d5337d` | Fluxos: fan-out por item com cache por item, condições, parâmetros ligados (`bind`), 10 passos de CPU, 10 receitas, fila de jobs | TESTADO CPU |
| `10c4794` | Encadeamento pelo agente (`compose_chain`), modelo/LoRA como parâmetro, plano em cadeia no chat sem agente, tarefas de avaliação em cadeia | TESTADO CPU; avaliação com Qwen real pendente |
| `755c3a5` | V8.5: 8 passos de CPU (cortar/juntar/filtrar listas, modelo de texto, apresentação, boomerang, mistura), `edit_graph`, linha do tempo por passo | TESTADO CPU |
| `d3dc22c` | **Meus fluxos**: salvar um grafo como receita reutilizável (slots de mídia, campos expostos), `save_flow` | TESTADO CPU / API |
| `20ff54f` | Revisar execução (`revise_run`), botão «Refazer» por passo, id de execução em todo job de grafo | TESTADO CPU |
| `d044ef2` | «Salvar como fluxo» no resultado do agente no chat | TESTADO CPU + e2e |
| `43ca18c` | Varredura de parâmetros (`sweep`), coerção numérica/booleana, receita «Varredura de intensidade» (CPU) e «Melhor de N sementes» (GPU) | CPU testado; GPU `BLOQUEADO_GPU` |
| `3a61ddb` | Se/senão (`when.not`, `first_of`), receita «Conferir e consertar» com os dois ramos testados | TESTADO CPU |
| `ee3262b` | Diálogo «Salvar como fluxo»: nome + escolha de quais ajustes ficam editáveis | TESTADO CPU + e2e |
| `cacfff0` | Receitas `animatic_do_storyboard` (CPU) e `planos_em_filme` (GPU) | animatic TESTADO CPU; filme `BLOQUEADO_GPU` |
| `f349e71` | Ponte «Planos em receita»: imagens do Storyboard viram a entrada de uma receita | TESTADO CPU + e2e |

## O que foi medido de verdade e o que não foi

**Medido nesta máquina (CPU, arquivos e ffmpeg reais):** todos os passos nativos de lista/texto/mídia; as 11 receitas de CPU; cache por item e reexecução parcial; salvar/rodar/apagar fluxo pela tela; se/senão com os dois ramos; ponte do Storyboard até o MP4; recorte U²-Net; FaceFusion; verificação de variantes e de LoRA; navegação de todas as rotas em 4 tamanhos de tela.

**NÃO medido (`BLOQUEADO_GPU` ou sem modelo local aqui):**
- Qualquer imagem, vídeo ou áudio gerado por modelo: as 7 receitas de GPU, Wan 2.2, LTX, MOSS, Stable Audio, Imagem→3D, folha de personagem, Cobertura, BFS.
- O agente com o Qwen3.5-9B real: `tests/agent_eval/run_eval.py --chains` nunca rodou com o modelo; não sei se ele usa bem `edit_graph`, `save_flow` e `revise_run`.
- Qualidade do plano do Storyboard, fidelidade entre vistas do personagem, qualidade de movimento dos clipes.
- Se `force` com semente fixa regenera a mesma saída, e se uma semente por item gera N imagens distintas no ComfyUI.
- Qwen 2.1 padrão × Turbo, Wan «Rápido», apps com offload: tempos e VRAM reais.
- Telas em 375 px dos diálogos e botões recentes (só rodei e2e em desktop nesses).

## Limites e riscos que vale analisar
1. **Volume de código sem GPU:** muita coisa está `CÓDIGO ESCRITO`/`BLOQUEADO_GPU`. Um problema de VRAM ou de nó do ComfyUI só aparece no Colab.
2. **Um flake de e2e** (primeiro teste de Fluxos, 1 falha numa rodada completa; 3 reruns isolados e a rodada seguinte passaram). Causa não identificada.
3. **Conferência técnica** (`cf_refine`, nitidez por variância do Laplaciano, limiar 25) não julga estética.
4. **Ainda NÃO INICIADO** no `docs/BACKLOG_CAPACIDADES_APPS.md`: cerca de 20 itens (referências, workflows Civitai); ideias do OpenField sem implementação: Reshoot, Stage 3D, Mirror.
5. **Legenda automática** não foi feita: precisa de modelo de transcrição/visão que não roda em 3 GB de RAM sem GPU.

## Próximos passos que dependem de você (Colab)
1. Rodar `tests/agent_eval/run_eval.py --chains` com o Qwen real.
2. Rodar as 7 receitas de GPU e olhar os resultados.
3. Comparar Qwen 2.1 × Turbo e testar Wan «Rápido» e os apps com offload.
4. Confirmar o comportamento de `seed` por item e do `force`.

## Documentos relacionados
`docs/HANDOFF.md` (estado técnico por ciclo), `docs/EVIDENCIA_LOTE1.md`, `docs/CHANGELOG_V7.md` (antes de 12/11), `docs/BACKLOG_CAPACIDADES_APPS.md`, `docs/RECONCILIACAO_V7.md`.
