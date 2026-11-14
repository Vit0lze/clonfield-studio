# Backlog de capacidades e apps — matriz das 93 fontes

Gerado de `CLONFIELD_STUDIO_REGISTRO_COMPLETO_LINKS_2026-11-10_v7.md` (93 links únicos, 9 categorias). Cada linha: fonte → motor → forma da capacidade → consumidores → contrato de entrada/saída → estado → evidência ou próxima ação.
Estados: NÃO INICIADO · CÓDIGO ESCRITO · TESTADO CPU · TESTADO API REAL · TESTADO GPU · INTEGRADO E VALIDADO · BLOQUEADO_GPU. **Uma fonte «NÃO INICIADO» não foi aberta nem testada**: o registro é lista de insumos, não prova. Nenhuma linha afirma GPU sem medida (a única medida é o FLUX.2 Klein 512², 280 s).
Cada item é decidido como: motor compartilhado, passo reutilizável de DAG, ação universal (chat/agente/UI), modo de um app ou app dedicado. Apps podem ser criados livremente; o catálogo central é `cf_capabilities.py` (`/capabilities`).

## Projeto, documentação e fontes gerais

| Fonte | Motor | Capacidade-alvo | Consumidores | Contrato I/O | Estado | Evidência / próxima ação |
|---|---|---|---|---|---|---|
| civitai.com/ | Civitai (via civitai.red) | Biblioteca / Explorar / instalar | Biblioteca | — | TESTADO API REAL | Lote 1: variantes por arquivo, entrega conferida, capas em cache |
| clonfield-studio-portal.vercel.app/ | portal público | — | — | — | NÃO INICIADO | não aberto |
| github.com/Comfy-Org/workflow_templates | repositório de templates | fonte de grafos oficiais por capacidade | Lote 3 (Wan) e H3 | json de grafo | CÓDIGO ESCRITO | lido como referência para Wan 2.2; templates de vídeo ainda não carregados |
| github.com/Vit0lze/clonfield-studio | baseline do próprio Studio | — | todos | — | baseline (não é capacidade) | código lido e alterado; 8 commits do Lote 1 + Lote 2 em main/local |
| github.com/Vit0lze/clonfield-studio/blob/main/cf_apps.py | baseline do próprio Studio | — | todos | — | baseline (não é capacidade) | código lido e alterado; 8 commits do Lote 1 + Lote 2 em main/local |
| github.com/Vit0lze/clonfield-studio/blob/main/cf_model_lab.py | baseline do próprio Studio | — | todos | — | baseline (não é capacidade) | código lido e alterado; 8 commits do Lote 1 + Lote 2 em main/local |
| github.com/Vit0lze/clonfield-studio/blob/main/cf_workflows.py | baseline do próprio Studio | — | todos | — | baseline (não é capacidade) | código lido e alterado; 8 commits do Lote 1 + Lote 2 em main/local |
| huggingface.co/models | busca de modelos | slot Pesquisar | Biblioteca | — | TESTADO API REAL | busca HF real; HF só descobre, não instala |
| youtu.be/VefUJLzxQWg | vídeo de apoio | — | — | — | NÃO INICIADO | não assistido |
| youtu.be/aetuL154-pE | vídeo de apoio | — | — | — | NÃO INICIADO | não assistido |

## JEV, orquestração, MCP e decisões

| Fonte | Motor | Capacidade-alvo | Consumidores | Contrato I/O | Estado | Evidência / próxima ação |
|---|---|---|---|---|---|---|
| docs.comfy.org/agent-tools/mcp | documentação do MCP | — | agente | — | NÃO INICIADO | não aberto |
| github.com/BillionsBobby/JevRouter | contrato de roteador tipado (cf_router) | decisão atrás de feature flag CLONFIELD_JEV (desligada por padrão) | chat legado | text→escolha | TESTADO API REAL | 30/30 no gabarito próprio (V7); substituído como padrão pelo agente |
| github.com/Comfy-Org/comfy-mcp | MCP oficial do ComfyUI | alternativa ao conjunto de ferramentas do agente | agente | tool calls | NÃO INICIADO | avaliar se vale expor as ferramentas do Studio por MCP |
| github.com/hndrr/ComfyUI-Jev | nó ComfyUI de Jev | comparação | — | — | NÃO INICIADO | não aberto; o Studio usa a API direta |
| github.com/kantan-kanto/ComfyUI-ScriptFlow | projeto relacionado | comparação com cf_dag | — | — | NÃO INICIADO | não aberto |
| github.com/thinkany-ai/autojev | projeto relacionado | comparação | — | — | NÃO INICIADO | não aberto |

## Scenario Skills (métodos e evidência)

| Fonte | Motor | Capacidade-alvo | Consumidores | Contrato I/O | Estado | Evidência / próxima ação |
|---|---|---|---|---|---|---|
| github.com/scenario-labs/skills | método (MIT) | ver as 7 linhas acima | — | — | TESTADO CPU | ver linhas por skill |
| github.com/scenario-labs/skills/blob/main/skills/scenario-asset-analysis/SKILL.md | método | análise de ativos de entrada | agente (inspect_artifact) | image→json | CÓDIGO ESCRITO | inspect_artifact mede dimensões e gate técnico; sem análise semântica |
| github.com/scenario-labs/skills/blob/main/skills/scenario-consistency/SKILL.md | método | consistência de personagem entre cenas | chat, Fábrica | image[]→report | ESTUDADO — SEM CÓDIGO | lido: consistência vem de prompt-base + delta, imagens de referência e (depois) modelo treinado; seed não resolve. O Studio já passa referências e o prompt vai por conta do agente; nada novo implementado |
| github.com/scenario-labs/skills/blob/main/skills/scenario-formats/SKILL.md | método | formatos de saída por rede social | frame | image→image | TESTADO CPU | capacidade frame com 4 proporções |
| github.com/scenario-labs/skills/blob/main/skills/scenario-model-comparison/SKILL.md | método | comparar modelos A/B com a mesma seed | benchmark do Studio | image[]→report | TESTADO CPU | app «Comparar modelos» (cf_compare.py): mesma entrada em 2-3 modelos, tempo frio/quente, segundos por passo, VRAM e folha lado a lado; sem preço (modelos locais); sementes não transferem entre modelos, como o método diz; geração em si BLOQUEADA_GPU |
| github.com/scenario-labs/skills/blob/main/skills/scenario-quality-gate/SKILL.md | método adaptado (cf_refine) | capacidade quality_gate | create, edit, agente | image→report json | TESTADO CPU | tests/test_capabilities.py, test_refine_router.py |
| github.com/scenario-labs/skills/blob/main/skills/scenario-refine-loop/SKILL.md | método adaptado (cf_refine.refine) | laço de reparo com teto de rodadas | create (opção refinar) | image→image | TESTADO CPU | test_refine_router.py |
| github.com/scenario-labs/skills/blob/main/skills/scenario-workflows/SKILL.md | método: workflow como grafo tipado | cf_dag | agente, API /dag | graph json | TESTADO CPU | tests/test_dag.py (cache por hash, retomada) |

## See-through, PSD e animação em camadas

| Fonte | Motor | Capacidade-alvo | Consumidores | Contrato I/O | Estado | Evidência / próxima ação |
|---|---|---|---|---|---|---|
| arxiv.org/abs/2602.03749 | artigo | — | seethrough | — | CÓDIGO ESCRITO | método lido para a escolha de perfis |
| github.com/852wa/Anime2.5DRig | editor 2.5D / rig | etapa pós-camadas | seethrough (futuro) | psd→rig | NÃO INICIADO | depende das camadas reais |
| github.com/MangoLion/stretchystudio | editor 2D/2.5D | etapa pós-camadas | seethrough (futuro) | psd→animação | NÃO INICIADO | depende das camadas reais |
| github.com/jtydhr88/ComfyUI-See-through | pacote ComfyUI fixado em 98d754b | camadas anime → PSD | app seethrough; capacidade app.seethrough | image→file(psd) | BLOQUEADO_GPU | grafo aceito pelo ComfyUI 0.44; nunca gerou camadas na T4 |
| github.com/kazuya-bros/PachiPakuGen | animação labial 2.5D | etapa pós-camadas | seethrough (futuro) | psd+audio→video | NÃO INICIADO | depende das camadas reais |
| github.com/shitagaki-lab/see-through | modelo base do pacote acima | — | seethrough | image→layers | BLOQUEADO_GPU | pesos NF4/BF16 só na T4 |
| huggingface.co/spaces/24yearsold/see-through-demo | demo | comparação de saída | seethrough | — | NÃO INICIADO | não aberto |

## Content Factory e produção de conteúdo

| Fonte | Motor | Capacidade-alvo | Consumidores | Contrato I/O | Estado | Evidência / próxima ação |
|---|---|---|---|---|---|---|
| github.com/floomhq/opencut | editor de vídeo web | comparação | Fábrica | — | NÃO INICIADO | não aberto |
| github.com/gyoridavid/short-video-maker | gerador de vídeos curtos | comparação | Fábrica | — | NÃO INICIADO | não aberto |
| github.com/harry0703/MoneyPrinterTurbo | gerador de vídeos | comparação | Fábrica | — | NÃO INICIADO | não aberto |
| github.com/jutsuhq/content-factory | vendorizado em vendor/content_factory (MIT) | Fábrica de vídeo: modo desenhado + modo «states» com cenas do ComfyUI local | app factory | texto→vídeo | TESTADO CPU | render narrado real em CPU (V6); modo «states» ligado ao gerador local pelo hook `private` (sem API paga), frames/cache/9:16 testados com o motor real e um pintor de imagens no lugar do ComfyUI (tests/test_factory_scenes.py); cenas reais BLOQUEADO_GPU |
| github.com/wexloops/openfield | projeto de produção de conteúdo | comparação | Fábrica | — | NÃO INICIADO | não aberto |
| higgsfield.ai/blog/higgsfield-introduces-content-factory | referência de produto | UX da Fábrica | Fábrica | — | CÓDIGO ESCRITO | inspirou o fluxo; sem cópia de código |

## Workflows e modelos do catálogo comunitário

| Fonte | Motor | Capacidade-alvo | Consumidores | Contrato I/O | Estado | Evidência / próxima ação |
|---|---|---|---|---|---|---|
| civitai.red/models/1817819/wan-22-image-to-video | workflow comunitário | grafo I2V de referência | animate | image→video | NÃO INICIADO | abrir o JSON e comparar com o grafo oficial |
| civitai.red/models/1852904/wan-22-video-sound-workflow-optimized-for-rtx-3060-12-gb-vram-gpu | workflow comunitário | vídeo com som em 12 GB | text2video | text→video+audio | NÃO INICIADO | — |
| civitai.red/models/2881362/minimax-h3-seed-hunter-latent-upscaler-seamless-video-continuation-dialogue-gen-tool-speedups-ref-mods | workflow H3 | continuação de vídeo / upscaler latente | app H3 (futuro) | video→video | ESTUDADO — INVIÁVEL NA T4 | medido na API do HF (Comfy-Org/MiniMax-H3): o menor modelo de difusão é 16 GB (w6a8 podado) e o codificador Qwen3-VL 32B menor é 15,7 GB (nvfp4): ~32 GB de pesos só para começar, sem os VAEs (2,8–5,2 GB). Há ~50 templates oficiais (convertíveis com `cf_ui2api`); fica para uma GPU de ≥48 GB. Licença «other»
| civitai.red/models/2967375/qwen-image-21-outpaint-lora-extend-any-side?modelVersionId=3362269 | LoRA Qwen 2.1 Outpaint v2 (ausboss, HF) | app Expandir imagem + capacidades outpaint_pad/outpaint_stitch | outpaint, agente, DAG | image→image (+mask, plan) | CÓDIGO ESCRITO | receita da página e do cartão HF seguida (canvas #808080 ×32 ≤2 MP, instrução-gatilho, 25 passos CFG 1 euler/simple, colar o original); canvas, stitch e grafo testados em CPU (tests/test_edits.py); geração BLOQUEADO_GPU; licença «other» |
| civitai.red/models/2975820/qwen-image-21-edit-super-duper-stable-nsfw-workflow | workflow Qwen 2.1 edit | referência de grafo | edit | image→image | NÃO INICIADO | — |
| civitai.red/models/2983159/qwen-image-21-outfit-swap-consistency-lora?modelVersionId=3381922 | LoRA Qwen 2.1 Outfit Swap Consistency (ausboss, HF) | app Trocar roupa | outfit | image+image→image | CÓDIGO ESCRITO | prompt oficial, pessoa=imagem 1, roupa=imagem 2; testado em CPU; geração BLOQUEADO_GPU |
| civitai.red/models/2986253/qwen-image-21-character-sheet-designer-image-generation | workflow folha de personagem | capacidade character_sheet (futura) | chat, Fábrica | text+image→image[] | CÓDIGO ESCRITO | app «Folha de personagem» (cf_character.py): receita própria com o modo edição do Qwen 2.1, uma edição por vista com a mesma seed e baseline+delta; o zip do workflow não foi baixado nem usado (exige rgthree e outros pacotes); fidelidade entre vistas BLOQUEADA_GPU |
| civitai.red/models/2988187/minimax-h3-character-swap-workflow | workflow H3 character swap | troca de personagem em vídeo | alternativa a openjutsu | video+image→video | ESTUDADO — INVIÁVEL NA T4 | medido na API do HF (Comfy-Org/MiniMax-H3): o menor modelo de difusão é 16 GB (w6a8 podado) e o codificador Qwen3-VL 32B menor é 15,7 GB (nvfp4): ~32 GB de pesos só para começar, sem os VAEs (2,8–5,2 GB). Há ~50 templates oficiais (convertíveis com `cf_ui2api`); fica para uma GPU de ≥48 GB. Licença «other»
| civitai.red/models/2989697/qwen-image-21-restore-lora?modelVersionId=3390033 | LoRA Qwen 2.1 Restore (ausboss, HF) | app Restaurar foto | restore | image→image | CÓDIGO ESCRITO | prompts oficiais, ~2 MP, força 1,0 ou 0,5 (foto desfocada); testado em CPU; geração BLOQUEADO_GPU |
| civitai.red/models/3004026/flux-3-image-klein-multi-image-edit-or-up-to-6-pictures | FLUX.3 Klein multi-imagem | edição com até 6 imagens | edit (modelo) | image[]→image | ESTUDADO — SEM CÓDIGO | página lida: usa nós AusBoss e o modelo gated da BFL (não consegui ler o cartão); o preset FLUX.3 mantém as 3 referências do template oficial, 6 só se medido em GPU |
| civitai.red/models/3010615/moss-image-inpainting-workflow | workflow MOSS inpainting | capacidade inpaint por máscara | region | image+mask→image | NÃO INICIADO | a máscara a partir de caixas já existe (bbox_mask) |
| civitai.red/models/3020564/artfat-moss-bbox-studio-or-generate-edit-llm-prompter-50-presets-dlss5-enhancer | MOSS BBox Studio (Artfat) | app Caixas (MOSS): gerar por caixas, editar só as caixas (DifferentialDiffusion + colagem do original), editar por instrução (template oficial) — tudo com nós do núcleo do ComfyUI | app moss, agente (futuro) | image?+boxes+texto→image | CÓDIGO ESCRITO | CORREÇÃO: eu tinha escrito que o MOSS não tinha versão quantizada: tem (Comfy-Org/MOSS-Image: INT8 5,4 GB + Qwen3.5-9B W4A8 7,3 GB + VAE 0,25 GB). Os 3 grafos são ACEITOS pelo ComfyUI 0.44 real em CPU, e a cadeia caixas→CreateBoundingBoxes→MOSSImageLayoutPrompt foi EXECUTADA de verdade e produziu o prompt de layout. Nenhuma imagem gerada (T4) |
| civitai.red/models/3028227/qwen-character-asset-generator-emotionactionangle-workflows | workflow de ativos de personagem | emoção/ação/ângulo | Fábrica | image→image[] | CÓDIGO ESCRITO | parcial: ângulos e expressões saem do app «Folha de personagem»; ações não foram feitas; o workflow (5 pacotes de nós extras) não foi usado |
| civitai.red/models/3038333/workflow-action-transfer-dance | workflow ação/dança | transferência de movimento | animate (modo) | video+image→video | NÃO INICIADO | — |
| civitai.red/models/453194/swapping-deepfake-training-face-model-and-upscaling | treino de rosto + upscale | referência | — | — | NÃO INICIADO | — |
| civitai.red/models/736681/flux-realistic-amateurs | LoRA FLUX realismo amador | LoRA de estilo | create | — | NÃO INICIADO | — |
| comfy.icu/files/qwenImage21Person_v10.json | workflow Qwen 2.1 pessoa | referência | edit | image→image | NÃO INICIADO | — |
| comfy.org/hub/workflows/?category=swap-faces-and-characters | hub de workflows | swap de rostos e personagens | swap | — | NÃO INICIADO | — |
| comfy.org/hub/workflows/wan2-2-animate-character-animation-and-replacement-c2c4b45b7df5/ | hub de workflows | swap de rostos e personagens | swap | — | NÃO INICIADO | — |

## BFS, identidade, edição e swap

| Fonte | Motor | Capacidade-alvo | Consumidores | Contrato I/O | Estado | Evidência / próxima ação |
|---|---|---|---|---|---|---|
| blog.comfy.org/p/wan22-animate-and-qwen-image-edit-2509 | Wan Animate 2 (template oficial `video_wan_animate2_distilled`, INT8 16,6 GB) + Wan 2.1 SCAIL-2 (`video_wan21_scail2_character_replacement_int8`) | apps Animar personagem e Substituir personagem (cf_templates.py), alternativas ao OpenJutsu | scail2, animate2 | video+image→video | TESTADO CPU | templates com subgrafos convertidos por `cf_ui2api.flatten`; o ComfyUI 0.44 real em CPU ACEITA os grafos (30–39 nós podados); pesos com revisão/SHA da API do HF. Modelos de 16,6 GB + codificador de 6,7 GB: apps travados em 24 GB de VRAM com o motivo à mostra; NADA gerado (BLOQUEADO_GPU) e a T4 de 15 GB provavelmente não roda |
| docs.facefusion.io/usage/cli-arguments/face-selector | documentação | seleção de rosto (`--face-selector-*`) | swap | — | TESTADO CPU | opções usadas conferidas contra o `--help` real |
| github.com/Gourieff/comfyui-reactor | ReActor (ComfyUI) | troca de rosto | swap | image+image→image | ESTUDADO — DISPENSADO | troca de rosto já coberta pelo FaceFusion (app «Trocar rosto», troca real em CPU); README do ReActor não foi aberto, não foi duplicado |
| github.com/PrunaAI | organização de modelos quantizados | — | — | — | NÃO INICIADO | — |
| github.com/facefusion/facefusion | FaceFusion 3.9.2 (CLI headless-run, venv próprio, licença «other») | app Trocar rosto (cf_faceswap.py, prepare_facefusion.py) | swap, agente (com confirmação: risco médio) | image+image→image · image+video→video | TESTADO CPU | troca real em CPU com o programa real: mudou só a região do rosto (tests/test_faceswap.py); sem rosto no destino ou na origem o Studio diz o motivo; consentimento obrigatório. Vídeo, GPU e os outros modelos de troca NÃO testados |
| huggingface.co/Alissonerdx/BFS-Best-Face-Swap | LoRAs BFS (MIT) para Qwen 2.1: cabeça v1.1 / v1.1 alternativa / corpo v1.0 | app Trocar cabeça ou corpo (BFS), com os prompts e a ordem de imagens do autor | bfs, agente (com confirmação) | image+image→image | CÓDIGO ESCRITO | prompts palavra por palavra dos docs; LoRAs no catálogo fixado e conferidos na API do HF; grafo com a cena primeiro e duas referências aceito pelo ComfyUI real (mesmo grafo do Qwen); consentimento obrigatório; geração BLOQUEADO_GPU
| huggingface.co/Alissonerdx/BFS-Best-Face-Swap/blob/main/README.md | LoRAs BFS (Qwen 2.1 / LTX2) | troca de cabeça/corpo | swap | image+image→image | CÓDIGO ESCRITO | LoRAs catalogadas e classificáveis; sem app de swap |
| huggingface.co/Alissonerdx/BFS-Best-Face-Swap/blob/main/docs/qwen-image-2.1-body.md | LoRAs BFS (Qwen 2.1 / LTX2) | troca de cabeça/corpo | swap | image+image→image | CÓDIGO ESCRITO | LoRAs catalogadas e classificáveis; sem app de swap |
| huggingface.co/PrunaAI/P-Q-Image-2.1-Comfy | Qwen Image 2.1 quantizado | variante leve | create | — | CÓDIGO ESCRITO | a variante rápida do Qwen 2.1 entregue é o modelo Turbo INT8 oficial do ComfyUI (8 passos); os LoRAs de passos reduzidos da Pruna (5/6/8 passos) seguem sem uso |

## Modelos e pipelines de vídeo, áudio e 3D

| Fonte | Motor | Capacidade-alvo | Consumidores | Contrato I/O | Estado | Evidência / próxima ação |
|---|---|---|---|---|---|---|
| blog.comfy.org/p/stable-audio-3-day-0-support | Stable Audio 3 (ComfyUI nativo; Comfy-Org/stable-audio-3, licença «other») | app Áudio (cf_audio.py): SFX, música curta, faixas longas; prompt expandido pelo LLM local | áudio, agente, Fábrica (futuro) | text→audio | TESTADO CPU | os 9 grafos (3 modelos × 3 formatos) são ACEITOS pelo ComfyUI 0.44 real; grafo conferido contra o código do ComfyUI v0.44.0 (nós, entradas, tipo stable_audio), arquivos fixados conferidos na API do HF; player de áudio testado no navegador com um mp3 real; NENHUM áudio gerado (RAM/GPU): velocidade e qualidade não medidas |
| blog.comfy.org/p/trellis2-and-pixal3d-are-now-native | TRELLIS.2 / Pixal3D (ComfyUI nativo; Comfy-Org/{Pixal3D,MoGe,BiRefNet,TRELLIS.2}, todos MIT) | app Imagem para 3D (cf_3d.py + cf_ui2api.py) | image3d | image→GLB | CÓDIGO ESCRITO | o template oficial (66 nós) é convertido mecanicamente com o /object_info do worker, o interruptor de motor é dobrado (só os pesos do motor escolhido) e o ComfyUI 0.44 real em CPU ACEITA os dois grafos. Nenhum GLB gerado (T4) |
| design.minimax.io/h3 | página do produto | — | app H3 | — | ESTUDADO — INVIÁVEL NA T4 | medido na API do HF (Comfy-Org/MiniMax-H3): o menor modelo de difusão é 16 GB (w6a8 podado) e o codificador Qwen3-VL 32B menor é 15,7 GB (nvfp4): ~32 GB de pesos só para começar, sem os VAEs (2,8–5,2 GB). Há ~50 templates oficiais (convertíveis com `cf_ui2api`); fica para uma GPU de ≥48 GB. Licença «other»
| docs.comfy.org/tutorials/video/wan/wan2_2 | ComfyUI nativo + ComfyUI-GGUF | vídeo T2V/I2V Wan 2.2 A14B Q6_K (alta qualidade) e 5B baseline | text2video, animate | text/image→video | TESTADO CPU | app de vídeo com A14B Q6_K (T2V/I2V) e 5B Q6/Q8/FP16, segundos/FPS/tamanho; os 8 grafos (4 modelos × 2 modos) são ACEITOS pelo ComfyUI 0.44 real com o ComfyUI-GGUF fixado; nenhum vídeo gerado (T4) |
| github.com/Comfy-Org/docs/blob/main/tutorials/video/minimax/minimax-h3-native.mdx | documentação H3 | — | app H3 | — | ESTUDADO — INVIÁVEL NA T4 | medido na API do HF (Comfy-Org/MiniMax-H3): o menor modelo de difusão é 16 GB (w6a8 podado) e o codificador Qwen3-VL 32B menor é 15,7 GB (nvfp4): ~32 GB de pesos só para começar, sem os VAEs (2,8–5,2 GB). Há ~50 templates oficiais (convertíveis com `cf_ui2api`); fica para uma GPU de ≥48 GB. Licença «other»
| github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_fun_controlnet_union.json | ComfyUI nativo | ControlNet Union do H3 (vídeo) | app H3 (futuro) | video+image→video | ESTUDADO — INVIÁVEL NA T4 | medido na API do HF (Comfy-Org/MiniMax-H3): o menor modelo de difusão é 16 GB (w6a8 podado) e o codificador Qwen3-VL 32B menor é 15,7 GB (nvfp4): ~32 GB de pesos só para começar, sem os VAEs (2,8–5,2 GB). Há ~50 templates oficiais (convertíveis com `cf_ui2api`); fica para uma GPU de ≥48 GB. Licença «other»
| github.com/MiniMax-AI/awesome-minimax-h3-integration | MiniMax H3 | família de vídeo (FL2VA, Ref2VA, FastH3) | app H3 (futuro) | text/image/audio→video | ESTUDADO — INVIÁVEL NA T4 | medido na API do HF (Comfy-Org/MiniMax-H3): o menor modelo de difusão é 16 GB (w6a8 podado) e o codificador Qwen3-VL 32B menor é 15,7 GB (nvfp4): ~32 GB de pesos só para começar, sem os VAEs (2,8–5,2 GB). Há ~50 templates oficiais (convertíveis com `cf_ui2api`); fica para uma GPU de ≥48 GB. Licença «other»
| github.com/ModelTC/LightX2V | LightX2V (aceleração) | inferência rápida de vídeo | text2video | — | CÓDIGO ESCRITO | Wan A14B «Rápido»: LoRAs LightX2V de 4 passos no empacotamento do ComfyUI (Comfy-Org/Wan-2.2), receita do template oficial (4 passos, CFG 1, shift 5); grafos ACEITOS pelo ComfyUI 0.44 real; nada gerado em GPU |
| github.com/Stability-AI/stable-audio-3 | Stable Audio 3 (ComfyUI nativo; Comfy-Org/stable-audio-3, licença «other») | app Áudio (cf_audio.py): SFX, música curta, faixas longas; prompt expandido pelo LLM local | áudio, agente, Fábrica (futuro) | text→audio | TESTADO CPU | os 9 grafos (3 modelos × 3 formatos) são ACEITOS pelo ComfyUI 0.44 real; grafo conferido contra o código do ComfyUI v0.44.0 (nós, entradas, tipo stable_audio), arquivos fixados conferidos na API do HF; player de áudio testado no navegador com um mp3 real; NENHUM áudio gerado (RAM/GPU): velocidade e qualidade não medidas |
| github.com/barelymining/ComfyUI-MiniMax-H3-FastVideo | MiniMax H3 | família de vídeo (FL2VA, Ref2VA, FastH3) | app H3 (futuro) | text/image/audio→video | ESTUDADO — INVIÁVEL NA T4 | medido na API do HF (Comfy-Org/MiniMax-H3): o menor modelo de difusão é 16 GB (w6a8 podado) e o codificador Qwen3-VL 32B menor é 15,7 GB (nvfp4): ~32 GB de pesos só para começar, sem os VAEs (2,8–5,2 GB). Há ~50 templates oficiais (convertíveis com `cf_ui2api`); fica para uma GPU de ≥48 GB. Licença «other»
| huggingface.co/Comfy-Org/MiniMax-H3 | MiniMax H3 | família de vídeo (FL2VA, Ref2VA, FastH3) | app H3 (futuro) | text/image/audio→video | ESTUDADO — INVIÁVEL NA T4 | medido na API do HF (Comfy-Org/MiniMax-H3): o menor modelo de difusão é 16 GB (w6a8 podado) e o codificador Qwen3-VL 32B menor é 15,7 GB (nvfp4): ~32 GB de pesos só para começar, sem os VAEs (2,8–5,2 GB). Há ~50 templates oficiais (convertíveis com `cf_ui2api`); fica para uma GPU de ≥48 GB. Licença «other»
| huggingface.co/Lightricks/LTX-Video | LTX-Video 2B v0.9.5 (templates oficiais ltxv_text_to_video / ltxv_image_to_video, convertidos por cf_ui2api) | opção «LTX-Video 2B» nos apps de vídeo (cf_ltxv.py), o único modelo de vídeo pequeno o bastante para a T4 | text2video, animate | text/image→video | TESTADO CPU | 2 grafos aceitos pelo ComfyUI 0.44 real; pesos (6,3 GB + codificador T5 fp8 de 5,2 GB, NÃO o fp16 do template) com revisão/SHA da API do HF; licença do modelo «other»; nada gerado (BLOQUEADO_GPU) |
| huggingface.co/MiniMaxAI/MiniMax-H3 | MiniMax H3 | família de vídeo (FL2VA, Ref2VA, FastH3) | app H3 (futuro) | text/image/audio→video | ESTUDADO — INVIÁVEL NA T4 | medido na API do HF (Comfy-Org/MiniMax-H3): o menor modelo de difusão é 16 GB (w6a8 podado) e o codificador Qwen3-VL 32B menor é 15,7 GB (nvfp4): ~32 GB de pesos só para começar, sem os VAEs (2,8–5,2 GB). Há ~50 templates oficiais (convertíveis com `cf_ui2api`); fica para uma GPU de ≥48 GB. Licença «other»
| huggingface.co/VideoRebirthAI/hyperflow-h3-flash | H3 flash | — | app H3 | — | ESTUDADO — INVIÁVEL NA T4 | medido na API do HF (Comfy-Org/MiniMax-H3): o menor modelo de difusão é 16 GB (w6a8 podado) e o codificador Qwen3-VL 32B menor é 15,7 GB (nvfp4): ~32 GB de pesos só para começar, sem os VAEs (2,8–5,2 GB). Há ~50 templates oficiais (convertíveis com `cf_ui2api`); fica para uma GPU de ≥48 GB. Licença «other»
| huggingface.co/alibaba-pai/MiniMax-H3-Fun-Controlnet-Union-2.0 | MiniMax H3 | família de vídeo (FL2VA, Ref2VA, FastH3) | app H3 (futuro) | text/image/audio→video | ESTUDADO — INVIÁVEL NA T4 | medido na API do HF (Comfy-Org/MiniMax-H3): o menor modelo de difusão é 16 GB (w6a8 podado) e o codificador Qwen3-VL 32B menor é 15,7 GB (nvfp4): ~32 GB de pesos só para começar, sem os VAEs (2,8–5,2 GB). Há ~50 templates oficiais (convertíveis com `cf_ui2api`); fica para uma GPU de ≥48 GB. Licença «other»
| huggingface.co/collections/FastVideo/fasth3-omni | FastH3 | — | app H3 | — | ESTUDADO — INVIÁVEL NA T4 | medido na API do HF (Comfy-Org/MiniMax-H3): o menor modelo de difusão é 16 GB (w6a8 podado) e o codificador Qwen3-VL 32B menor é 15,7 GB (nvfp4): ~32 GB de pesos só para começar, sem os VAEs (2,8–5,2 GB). Há ~50 templates oficiais (convertíveis com `cf_ui2api`); fica para uma GPU de ≥48 GB. Licença «other»
| huggingface.co/lightx2v | pesos LightX2V | — | text2video | — | CÓDIGO ESCRITO | Wan2.2-Distill/Lightning: usados via os mesmos LoRAs repacotados do ComfyUI; o LoRA «Qwen-Image-2.1-Lightning» (formato diffusers) NÃO foi usado: a receita oficial do ComfyUI é o modelo Turbo (ver Qwen 2.1 Turbo) |
| ia.seenupdigital.com/noticias/criador-mostra-como-rodar-o-minimax-h3-mais-rapido-com-versoes-lora-e-prompts-ce302c | artigo | — | app H3 | — | ESTUDADO — INVIÁVEL NA T4 | medido na API do HF (Comfy-Org/MiniMax-H3): o menor modelo de difusão é 16 GB (w6a8 podado) e o codificador Qwen3-VL 32B menor é 15,7 GB (nvfp4): ~32 GB de pesos só para começar, sem os VAEs (2,8–5,2 GB). Há ~50 templates oficiais (convertíveis com `cf_ui2api`); fica para uma GPU de ≥48 GB. Licença «other»

## Modelos, otimizações e componentes de imagem

| Fonte | Motor | Capacidade-alvo | Consumidores | Contrato I/O | Estado | Evidência / próxima ação |
|---|---|---|---|---|---|---|
| bfl.ai/models/flux-2-klein | FLUX.2 Klein 4B | modelo de imagem leve | create, edit | text/image→image | TESTADO GPU | única evidência de GPU: 512², 4 passos, 280 s com download (Colab antigo) |
| github.com/Blueforcer/ComfyUI-DLSS5-Enhancer | pacote ComfyUI | realce/upscale | upscale (modo) | image→image | ESTUDADO — INVIÁVEL NA T4 | README lido: roda num worker nativo D3D12 (ReShade + RenoDX + NGX) só no Windows com GPU RTX; não existe no Colab/Linux |
| github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_2_1_image_edit.json | ComfyUI nativo (template oficial) | grafo de edição Qwen 2.1 (modo do app Editar) | edit | image+text→image | TESTADO CPU | grafo do preset qwen21 validado contra /object_info (V7); GPU não medida |
| github.com/Niko1221/Strata | projeto de imagem | comparação | — | — | NÃO INICIADO | — |
| github.com/artfat-creator/ComfyUI-Artfat-MOSS-BBox | pacote ComfyUI (MIT) | não é necessário: o app usa só nós do núcleo; o pacote serviu de referência da receita de edição | moss | image+bbox→image | TESTADO CPU | código lido; receita reimplementada com nós do núcleo e validada no ComfyUI real |
| github.com/black-forest-labs/flux2 | FLUX.2 | modelo de imagem | create | — | TESTADO GPU | mesma evidência acima |
| github.com/black-forest-labs/flux2/blob/main/model_licenses/LICENSE-FLUX-NON-COMMERICAL | FLUX.2 | modelo de imagem | create | — | TESTADO GPU | mesma evidência acima |
| huggingface.co/OpenMOSS-Team/MOSS-Image-Base | pesos MOSS (Apache-2.0); o Studio usa o reempacotado Comfy-Org/MOSS-Image (INT8 ConvRot) | motor | moss | — | CÓDIGO ESCRITO | tamanhos e SHA conferidos na API do HF |
| huggingface.co/OpenMOSS-Team/MOSS-Image-SFT | pesos MOSS (Apache-2.0); o Studio usa o reempacotado Comfy-Org/MOSS-Image (INT8 ConvRot) | motor | moss | — | CÓDIGO ESCRITO | tamanhos e SHA conferidos na API do HF |
| huggingface.co/vistralis/FLUX.2-klein-4b-INT8-transformer | variante INT8 do Klein | variante leve | create | — | NÃO INICIADO | — |

## Resumo por estado

| Estado | Fontes |
|---|---|
| NÃO INICIADO | 29 |
| TESTADO CPU | 16 |
| CÓDIGO ESCRITO | 19 |
| ESTUDADO — INVIÁVEL NA T4 | 14 |
| ESTUDADO — DISPENSADO | 1 |
| ESTUDADO — SEM CÓDIGO | 2 |
| baseline (não é capacidade) | 4 |
| TESTADO API REAL | 3 |
| TESTADO GPU | 3 |
| BLOQUEADO_GPU | 2 |

Total: 93. Decisões: MOSS fica como app «Caixas (MOSS)» E como motor em «Editar região»; OpenJutsu, SCAIL-2 e Animate 2 rodam com offload (aviso de lentidão, sem bloqueio). Próximas ondas (o que tem motor e dá para testar em CPU/API): workflows do Civitai convertidos (folha de personagem, ativos de personagem, ação/dança; dependem de pacotes de nós extras), Fábrica com cenas do ComfyUI, e o restante dos não iniciados (referências, comparações, vídeos de apoio).
