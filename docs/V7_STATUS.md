# V7.1 — status por fonte (estados: encontrado → examinado → baixado → sandbox → executado → comparado → produção)

Ambiente desta rodada: CPU, 4 núcleos, 3 GB RAM, sem GPU, sem T4. Nada abaixo foi medido em GPU.

## See-through V3 — camadas de anime → PSD
| Item | Estado | Evidência |
|---|---|---|
| shitagaki-lab/see-through `df019de` | examinado, baixado | Apache-2.0 (LICENSE). README: BF16 ~12-16 GB; group offload ~10 GB; NF4 ~8 GB; block swap ~8 GB (alegações do autor, não medidas aqui) |
| jtydhr88/ComfyUI-See-through `98d754b` (0.5.0) | baixado, instalado em sandbox, **executado até o loader** | MIT só em `pyproject.toml` (sem arquivo LICENSE; registrar). Carrega no ComfyUI 0.44 CPU: 7 nós `SeeThrough_*` em `/object_info` |
| Pesos `layerdifforg/seethroughv0.0.2_layerdiff3d` (~10 GB) | examinado (API do HF) | **OpenRAIL++** — restrições de uso valem para pesos, distinto da licença do código |
| Integração ClonField | integrado | `cf_seethrough.py` (grafo, perfis, pacote PSD/ZIP), `prepare_seethrough.py` (clone fixado), app `seethrough`, passo no notebook (`PREPARE_SEETHROUGH`), ícone |
| Testes | 5 passam | grafo por perfil aceito pelo ComfyUI 0.44 real (validação de tipos/links/combos); PSD gerado com psd-tools e relido (ordem, tamanho, pixel); job completo via API real chega ao loader e falha com "No GPU found" no NF4 (esperado sem CUDA) |
| Camadas reais geradas / PSD do modelo / VRAM / tempo / fidelidade | **NÃO TESTADO** | exige GPU; perfis NF4, BF16+offload, BF16 e block swap seguem pendentes na T4 |
| Block swap | não integrado | só os 3 perfis acima; block swap existe no repo upstream (CLI), não no wrapper ComfyUI |

Observação: o nó `SeeThrough_SavePSD` só grava PNGs + `layers.json` (o PSD vem do navegador via ag-psd);
o ClonField monta o PSD no servidor com psd-tools a partir desses arquivos. Número de camadas varia por imagem.

## Outras fontes
Clonados e licenças lidas: JevRouter `b1cdf80` (MIT), scenario-labs/skills `b96506d` (MIT).
Restante dos 93 links: **encontrado apenas**, nada examinado em profundidade nesta rodada.

## JEV / Scenario (rodada 2)
| Item | Estado | Evidência / limite |
|---|---|---|
| scenario-labs/skills `b96506d` (MIT) — quality-gate, refine-loop | lidos; **método adaptado** em `cf_refine.py` | Copiado o método: rubrica fixa antes de julgar, veredito por linha, correção mais barata primeiro (filtro determinístico → nova seed), 1 variável por rodada, regenerar da base, teto de rodadas, parar se a mesma linha falha sob 2 correções, manter a melhor. **Sem Scenario MCP/pago** |
| Gate | só propriedades **medidas** (vazio, nitidez, exposição, tamanho, estrutura vs. referência) | NÃO há avaliador de IA: linhas de texto livre ficam "não avaliado" e nenhuma nota numérica é inventada. Limites do próprio Scenario valem aqui, em dobro: não detecta anatomia/identidade |
| Refino automático | integrado como opção avançada em Criar/Editar/etc. (`refine`) | Testado com imagens PIL reais e `refine_outputs`; **não testado com geração real** (sem GPU/pesos) |
| JevRouter `b1cdf80` (MIT) | lido; **contrato adaptado** em `cf_router.py` + `POST /route` | Probabilidades do provedor intocadas; disponibilidade em `router`; sem renormalizar; só decide, não executa |
| Provedor Jev remoto (`api.typesafe.ai/v1/systemone`) | **integrado e testado ao vivo** | token de `TYPESAFE_API_TOKEN` (também `TYPESAFE_API_KEY`/`JEV_API_KEY`). Uma pergunta Choice; só texto do pedido e nomes dos tipos de mídia são enviados. 4 pedidos reais roteados corretamente; falha/token ruim cai no heurístico local e a resposta traz `provider` e `fallback`. Não comparado em acurácia com o heurístico em amostra ampla |
| JEV do proprietário | **não encontrado** na máquina | preciso do repositório/contrato para comparar, como a V7 exige |
| ComfyUI-ScriptFlow, ComfyUI-Jev, AutoJev, model-comparison | não examinados | pendente |

## Jev ao vivo (rodada 3)
- Teste com gabarito: 30 pedidos PT/EN → Jev 30/30 (p médio 0,97, ~0,27 s) × heurístico local 26/30. Gabarito escrito pelo mantenedor, casos claros: vale como sanidade, não como acurácia geral. Fixado em `tests/test_jev_live.py` (aceita ≤3 erros).
- Pedidos ambíguos: probabilidade cai (ex.: «melhora essa foto» → edit 0,59 / look 0,33), ou seja, a confiança informa.
- `cf_router.plan` + `POST /plan`: planos em série (Choice do próximo app + Noul «já terminou?» numa só chamada). Noul é mal calibrado (0,43 logo após pedido cumprido), então: nunca repete app, para se finished ≥ 0,35 ou se o próximo tem p < 0,5. 4 planos reais corretos (edit→upscale→frame; text2video→clip; upscale; text2video→still).
- UI: botão «Sugerir» na tela inicial (+ «Tenho imagem/vídeo»), mostra a cadeia de apps; clicar abre o app com o pedido preenchido. Verificado no navegador contra o engine real e o Jev real.
- Pendente: o plano ainda não executa a cadeia sozinho (decisão apenas, pela regra de confirmação); mídia só entra como tipo; não testado com GPU.

## Content Factory (rodada 4)
| Fonte | Licença | Estado |
|---|---|---|
| jutsuhq/content-factory `0ea7632` | MIT | clonado, **vendorizado** em `vendor/content_factory` (engine, formats, render; ver `VENDORED.md`), testes upstream **74/74** passam neste snapshot, **render real executado** |
| Remotion (renderizador) | **licença própria** (não MIT; gratuita p/ indivíduos/times pequenos, paga acima) | usado; checar antes de uso comercial |
| MoneyPrinterTurbo `53c4ca3`, openfield `1c36412`, short-video-maker `9bb9a21`, opencut `57dedbc` | MIT (arquivo LICENSE lido) | clonados; **não examinados a fundo** — CF cobre o pipeline brief→roteiro→cenas→render com cache por hash, então não dupliquei |

**Evidência real (CPU, 3 GB RAM, sem GPU):** episódio silencioso modo *drawn* («What if the Sun went out?», 7 beats) → `sun-silent.mp4` h264 1080×1920 30 fps, 41,0 s, 12,3 MB, mais `qa.json` com avisos reais (sem áudio; contador com 17 caracteres, máx. 12). Rodado a partir da cópia vendorizada.

Mudanças locais no vendor (todas em `VENDORED.md`): (1) pular loudnorm quando o vídeo não tem áudio (upstream quebrava com ffmpeg exit 234); (2) `--concurrency=1` no Remotion (o padrão derrubou esta máquina por falta de memória).

Integração ClonField: `cf_factory.py` (configura paths, cria episódio com validação de schema, roda etapas com progresso, instala Remotion uma vez), app **Fábrica de vídeo** (lane CPU), deps no notebook, 3 testes rápidos + 1 teste lento (`CLONFIELD_SLOW=1`).
**Narração real (adicionada):** `kokoro_onnx` (Kokoro-82M int8, modelo com SHA-256) + `faster_whisper` (CPU int8) no vendor. Episódio «Sol narrado» (7 beats, modo drawn): TTS + alinhamento + render + QA em ~230 s numa CPU de 3 GB, saída h264 1080×1920 + AAC 48 kHz, 31,8 s, 11,4 MB, QA `ok: true` (só 1 aviso de tamanho de contador). Colab/T4 não testado (Remotion precisa baixar Chromium lá).
**Não feito/limites:** modos com imagens (`states`/`scenes`) dependem de provedor de imagem — adaptador ComfyUI ainda **não escrito** — e de depth/RIFE (não baixados); cache por etapa só observável nos modos com imagem; UI própria de revisão por beat pendente.
