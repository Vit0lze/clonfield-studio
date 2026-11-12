# Evidência — Lote 1 (P0 do mandato V8.3)

Data: 2026-11-12. Máquina: CPU, 3 GB de RAM, sem GPU. **Nada neste lote foi testado na T4/Colab.** O que depende de GPU está marcado `BLOQUEADO_GPU`.
Commits locais (nenhum enviado ao GitHub): `e5f2382`, `bb2ab98`, `158f61c`, `a4e5c83`, `92bfdc8` (sobre `fa4867a`).

## Como reproduzir

```bash
# Python (engine + pytest) e Node 24 (Playwright 1.49 trava em ESM no Node 25: por isso as specs são CommonJS)
cd clonfield-studio && python -m pytest tests -q --ignore=tests/test_live.py --ignore=tests/test_jev_live.py \
  --ignore=tests/test_civitai_live.py --ignore=tests/test_download_live.py --ignore=tests/test_resilience_live.py
cd tests/e2e && npm install && npx playwright install chromium
CF_PY=/caminho/do/python ./run.sh      # semeia LoRAs/jobs reais mínimos, sobe cf_engine.py real, roda 53 testes
```

`CLONFIELD_FAKE_VRAM=15` só libera os apps na UI desta máquina. Não é medida de GPU e nenhum resultado abaixo a usa como tal.

## Resumo

| Item | Estado | Antes (falhava) | Depois |
|---|---|---|---|
| Infra e2e Playwright | TESTADO CPU | — | 53 testes, engine real |
| P0-A Home `have is not defined` | TESTADO CPU (navegador real) | Home mostrava «Não consegui abrir esta página»; 1 de 10 rotas falhava | 40 combinações rota×viewport + fluxo de anexo passam |
| P0-B LoRAs baixadas em Criar | TESTADO CPU / API real; GPU `BLOQUEADO_GPU` | 7 testes pytest falhavam (não existia `available`); lista vazia com Manual | 7 pytest + 4 e2e |
| P0-C popovers | TESTADO CPU (navegador real) | gap 76–90 px entre chip e painel em 768/1366/1920 | 4 viewports ancorados, dentro da janela |
| P0-D capas/imagens | TESTADO CPU (navegador real) | 182 remontagens de nós, URLs diferentes a cada leitura, 7/7 cartas recriadas, override `cf-cover-*` ativo | 0 remontagens, URL estável, ETag/304, cache em disco |
| P0-E variantes | TESTADO CPU + TESTADO API REAL (Civitai) | 20 testes falhavam | 21 testes (inclui 2 contra o Civitai real) |

## P0-A — Home

- **Causa:** `portal/js/views/home.js` ainda chamava `have("image")`/`have("video")` depois que removi essa função ao trocar por anexo real. `node --check` não pega isso.
- **Correção:** `h("div", {class:"plan-have"}, attachButton, picker, thumbs)`; CSS `.plan-have` com wrap.
- **Teste:** `tests/e2e/smoke.spec.cjs` abre 10 rotas em 375/768/1366/1920 px, falha em `pageerror`, `console.error`, no cartão «Não consegui abrir esta página» (o roteador captura exceções e as mostra como cartão: só o console não bastaria) e em overflow horizontal. `tests/e2e/home.spec.cjs`: anexa PNG + MP4, chama `/plan`, clica no passo e confere que a foto chegou ao app aberto.
- **Evidência antes:** saída em `/tmp/smoke1366.txt` na época: `✘ rota #/ sem erros em 1366px`, 9 de 10 passando.

## P0-B — LoRAs

- **Fonte única:** `cf_loras.available(base, comfy_root, family)` junta `base/loras` (com sidecar), `ComfyUI/models/loras` (arquivos soltos, nível raiz) e o catálogo fixado. Classes: `confirmada` (família declarada pelo catálogo/sidecar), `provável` (cabeçalho safetensors ou nome sugere a família), `desconhecida`, `incompatível` (com motivo). **Família vazia nunca é `confirmada`** (teste dedicado).
- **Contagens que explicam o vazio:** `installed_for_family`, `installed_other`, `unknown`, `by_family`. A UI diz «1 instalada para Z-Image · 2 para outros modelos · 1 sem informação» e, quando só há LoRAs de outros modelos, oferece «Ver todas as instaladas».
- **UI (popover Estilo):** busca, filtros Compatíveis/Instaladas/Favoritas/Todas, estrela, miniatura, etiqueta de compatibilidade, «Adicionar» desabilitado para incompatíveis (com o motivo), **interruptor `role=switch` visível ligado a `item.on`** (antes: checkbox `sr` sem handler). Nada é ativado sozinho; ao trocar de modelo, uma LoRA já escolhida que não serve é desligada e marcada.
- **Atualização sem recarregar:** `api.follow` emite `cf-job-final`; o seletor recarrega quando termina qualquer job `install*`.
- **Bug extra achado pelo teste:** com Conjunto «Manual» (ex.: vindo da Biblioteca), `applySet` não chamava `onModelChange`, então a lista de LoRAs nunca carregava. Corrigido.
- **Testes:** `tests/test_loras.py` (7, falhavam antes) com `.safetensors` reais mínimos (um com cabeçalho SDXL); `tests/e2e/lora.spec.cjs` (4): aparece sem prefill, troca de modelo muda a lista, o corpo real do `POST /jobs` leva `on:true`/`on:false` (a requisição é abortada para não disparar download de 14 GB), arquivo novo + job de instalação real passando pelo SSE atualiza a lista.
- **Limites:** só arquivos no nível raiz de `ComfyUI/models/loras`; `LoraLoader` no grafo real não foi executado (`BLOQUEADO_GPU`).

## P0-C — Popovers

- **Causa:** `views.css` linhas 614–615 (`.dock-chip-wrap{position:static}`, `.dock-pop{left:12px}`) que eu tinha acrescentado; todos os painéis ficavam na mesma origem do dock.
- **Correção:** `portal/js/popover.js::anchorPopover`: painel movido para `<body>` ao abrir (o `.dock` tem `backdrop-filter`, que quebraria `position:fixed`), prefere cima, vira para baixo se houver mais espaço, trava no eixo X dentro da janela, `max-height` pelo espaço real, reposiciona em resize/scroll/ResizeObserver, bottom sheet em ≤600 px acima da navegação. Foco no primeiro controle, Esc, clique fora, `aria-expanded`.
- **Teste:** `tests/e2e/popovers.spec.cjs` mede retângulos de cada chip e painel (Modelo, Formato, Estilo, Mais) em 4 viewports: dentro da janela, gap vertical ≤16 px, esquerda alinhada ao chip, origens distintas, sem overflow.
- Captura visual conferida a 1366×768 (painel Formato colado ao chip Formato).

## P0-D — Capas e imagens

- **Causas medidas:** (1) `sign()` usava `time.time()+ttl`: cada leitura da fila gerava URL nova por imagem, então o navegador rebaixava e repintava tudo; (2) `paintRecents`, `paintGrid` e a lista de jobs faziam `clear()` + recriação; (3) `rememberCover` gravava o último resultado em `localStorage cf-cover-*` e `artFor` o preferia à capa autoral; (4) capas do Civitai só em memória (sumiam no reinício → 404 «Atualize a busca») e falhas 403 eram repetidas a cada repintura.
- **Correção:** `sign()` arredonda a expiração a uma janela fixa (mesma URL entre leituras); `ui.reconcile()` (nós por chave, reconstruídos só se a assinatura de dados muda) em Recentes, Biblioteca e Fila; `artFor` só usa arte autoral e `purgeLegacyCovers()` remove `cf-cover-*`; `cf_civitai` guarda capas em `base/cache/covers`, restaura o registro após reinício, lembra 403/falha por 10 min/1 min, `/cover` envia `ETag` e responde `304`.
- **Testes:** `tests/test_covers.py` (5, todos falhavam antes) e `tests/e2e/covers.spec.cjs` (4). O de Recentes aplica 10 repintagens forçadas pelo mesmo evento do poller + 2 ciclos reais de 4 s com `MutationObserver` e contagem de requisições `/files/`. **Antes: 182 mutações, URLs diferentes, 7/7 cartas recriadas, resíduo do localStorage mantido. Depois: 0 / iguais / 7 preservadas / removido.**
- **Limite:** a capa «da última geração» deixou de existir (era o bug). Se você quiser uma miniatura separada do último resultado, é tarefa nova.

## P0-E — Integridade da variante

- **Reprodução do relato (Qwen 2.1, ~3 GB NVFP4 vs 6,6 GB INT8):** o **mecanismo foi reproduzido com dados reais do Civitai**, a **entrega errada não foi**.
  - Modelo 3034876 / versão 3448331: 10 arquivos na mesma versão: NVFP4 (4003 MiB), Q4_0, **FP8 (6787 MiB, marcado como principal pela página)**, Q4_K_M, Q8_0, Q5_K_M, **INT8-ConvRot (6921 MiB)**, Q6_K, BF16… O app mostrava um cartão por modelo com `files[0]`, sem dizer qual arquivo nem a quantização, enquanto a página do Civitai destaca outro arquivo. Quem comparava o cartão com a página via números e tipos diferentes. Mesmo padrão no modelo 2958896 (int4 4361 MB, int8 6921 MB, fp8, bf16, fp16).
  - O download em si já usava `?fileId=` e conferia SHA-256, então não encontrei um caminho que entregue INT8 quando o cartão diz NVFP4. **NÃO REPRODUZIDO como download trocado.** O defeito comprovado é a escolha silenciosa e a ausência de identidade/aviso.
- **Bug adicional comprovado:** `sizeKB` do Civitai é KiB; o app fazia MiB×1e6 e mostrava 4,0 GB para um arquivo de 4,2 GB (−4,9 %). Agora o tamanho vem de bytes reais.
- **Correção:**
  - `cf_civitai`: `quant_of` (NVFP4, MXFP8, INT8/ConvRot, INT6, INT4, FP8, BF16, FP16, FP32), `variant_of`, `matching_files` com `quant`, `size_bytes`, `primary`.
  - `check_delivery`: antes de baixar, compara `Content-Disposition` (nome) e tamanho total (`Content-Range`/`Content-Length`) com o arquivo anunciado; divergência vira `ValueError` «anunciou NVFP4 (4,2 GB) … entrega INT8 (7,3 GB). Nada foi baixado».
  - `entry_for(expect=…)`: o pedido de instalação leva o que a lista mostrou (nome, quantização, tamanho, sha256); se o registro mudou, recusa.
  - `sniff_quant`/`verify_variant`: depois de baixar, compara os dtypes dos tensores com a quantização anunciada (NVFP4/INT8/FP8/BF16/FP16/FP32; INT4/INT6 não são comparados porque o empacotamento é ambíguo).
  - `cf_search`/`cf_library`: **um cartão por arquivo** (até 6 por versão, do menor ao maior), título com a quantização, fatos «Arquivo», «Quantização», «Na página do Civitai: arquivo principal / outro arquivo da mesma versão», link com `modelVersionId`; LoRAs com vários arquivos também (nome local por arquivo, `linked_name`).
  - `cf_contracts.CatalogItem.variant` obrigatório com `provider, model_id, version_id, file_id, sha256, quant, size_bytes, file_name`; variante parcial é rejeitada.
- **Testes:** `tests/test_variants.py` (21; 20 falhavam antes). Usa um registro **real** gravado do Civitai (`tests/fixtures/civitai_3034876.json`), `.safetensors` reais com dtypes I8/F16/U8+`weight_scale_2`, e dois testes ao vivo: cabeçalhos reais de entrega (`Content-Disposition`/`Content-Range` de um arquivo real) aceitos e uma troca forçada recusada; e `/library` real listando NVFP4 e INT8 como cartas separadas.
- **Limites:** não validei que NVFP4 rode numa T4 (sem Blackwell, depende da emulação do ComfyUI): a UI não promete isso. Não baixei os 4–7 GB: o fluxo completo de instalação com arquivo grande ficou para o Colab.

## O que NÃO foi feito neste lote

- Nada de GPU/T4: `LoraLoader` real, geração com LoRA, qualquer medida de VRAM/RAM.
- Capas dos apps novos (Camadas de anime, Fábrica) continuam sem arte própria.
- Cobertura e2e do modal «Pesquisar» no navegador (só API real).
- Push para o GitHub (aguarda sua autorização).

## Pronto para continuar

Estado: branch `main` local, 5 commits à frente de `6648b3d` (o último enviado). Próximo lote: registro de capacidades + DAG + agente com tool calling (plano em `~/.claude/plans/…`), depois vídeo Wan GGUF.
