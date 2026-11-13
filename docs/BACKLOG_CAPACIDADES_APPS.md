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
| github.com/scenario-labs/skills/blob/main/skills/scenario-consistency/SKILL.md | método | consistência de personagem entre cenas | chat, Fábrica | image[]→report | NÃO INICIADO | sem avaliador de identidade |
| github.com/scenario-labs/skills/blob/main/skills/scenario-formats/SKILL.md | método | formatos de saída por rede social | frame | image→image | TESTADO CPU | capacidade frame com 4 proporções |
| github.com/scenario-labs/skills/blob/main/skills/scenario-model-comparison/SKILL.md | método | comparar modelos A/B com a mesma seed | benchmark do Studio | image[]→report | NÃO INICIADO | exige GPU para comparar de verdade |
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
| civitai.red/models/2881362/minimax-h3-seed-hunter-latent-upscaler-seamless-video-continuation-dialogue-gen-tool-speedups-ref-mods | workflow H3 | continuação de vídeo / upscaler latente | app H3 (futuro) | video→video | NÃO INICIADO | — |
| civitai.red/models/2967375/qwen-image-21-outpaint-lora-extend-any-side?modelVersionId=3362269 | LoRA Qwen 2.1 Outpaint v2 (ausboss, HF) | app Expandir imagem + capacidades outpaint_pad/outpaint_stitch | outpaint, agente, DAG | image→image (+mask, plan) | CÓDIGO ESCRITO | receita da página e do cartão HF seguida (canvas #808080 ×32 ≤2 MP, instrução-gatilho, 25 passos CFG 1 euler/simple, colar o original); canvas, stitch e grafo testados em CPU (tests/test_edits.py); geração BLOQUEADO_GPU; licença «other» |
| civitai.red/models/2975820/qwen-image-21-edit-super-duper-stable-nsfw-workflow | workflow Qwen 2.1 edit | referência de grafo | edit | image→image | NÃO INICIADO | — |
| civitai.red/models/2983159/qwen-image-21-outfit-swap-consistency-lora?modelVersionId=3381922 | LoRA Qwen 2.1 Outfit Swap Consistency (ausboss, HF) | app Trocar roupa | outfit | image+image→image | CÓDIGO ESCRITO | prompt oficial, pessoa=imagem 1, roupa=imagem 2; testado em CPU; geração BLOQUEADO_GPU |
| civitai.red/models/2986253/qwen-image-21-character-sheet-designer-image-generation | workflow folha de personagem | capacidade character_sheet (futura) | chat, Fábrica | text+image→image[] | NÃO INICIADO | — |
| civitai.red/models/2988187/minimax-h3-character-swap-workflow | workflow H3 character swap | troca de personagem em vídeo | alternativa a openjutsu | video+image→video | NÃO INICIADO | sem gate de 96 GB: a decisão do mandato é achar alternativas |
| civitai.red/models/2989697/qwen-image-21-restore-lora?modelVersionId=3390033 | LoRA Qwen 2.1 Restore (ausboss, HF) | app Restaurar foto | restore | image→image | CÓDIGO ESCRITO | prompts oficiais, ~2 MP, força 1,0 ou 0,5 (foto desfocada); testado em CPU; geração BLOQUEADO_GPU |
| civitai.red/models/3004026/flux-3-image-klein-multi-image-edit-or-up-to-6-pictures | FLUX.3 Klein multi-imagem | edição com até 6 imagens | edit (modelo) | image[]→image | NÃO INICIADO | FLUX.3 está indisponível no catálogo (repo restrito) |
| civitai.red/models/3010615/moss-image-inpainting-workflow | workflow MOSS inpainting | capacidade inpaint por máscara | region | image+mask→image | NÃO INICIADO | a máscara a partir de caixas já existe (bbox_mask) |
| civitai.red/models/3020564/artfat-moss-bbox-studio-or-generate-edit-llm-prompter-50-presets-dlss5-enhancer | MOSS BBox Studio (Artfat) | edição por caixas: editor de caixas e máscara já existem no Studio; o motor MOSS não | modo do app Editar região (recomendação) em vez de app novo | image+bbox[]→image | CÓDIGO ESCRITO | estudado: exige ComfyUI ≥0.42, RES4LYF, pesos MOSS-Image de ~27 GB sem versão quantizada confirmada; canvas deles é widget Nodes 2.0. Feito e testado: caixas→máscara (bbox_mask) e editor de caixas. Motor MOSS BLOQUEADO_GPU. Decisão app×modo é do usuário (recomendo modo) |
| civitai.red/models/3028227/qwen-character-asset-generator-emotionactionangle-workflows | workflow de ativos de personagem | emoção/ação/ângulo | Fábrica | image→image[] | NÃO INICIADO | — |
| civitai.red/models/3038333/workflow-action-transfer-dance | workflow ação/dança | transferência de movimento | animate (modo) | video+image→video | NÃO INICIADO | — |
| civitai.red/models/453194/swapping-deepfake-training-face-model-and-upscaling | treino de rosto + upscale | referência | — | — | NÃO INICIADO | — |
| civitai.red/models/736681/flux-realistic-amateurs | LoRA FLUX realismo amador | LoRA de estilo | create | — | NÃO INICIADO | — |
| comfy.icu/files/qwenImage21Person_v10.json | workflow Qwen 2.1 pessoa | referência | edit | image→image | NÃO INICIADO | — |
| comfy.org/hub/workflows/?category=swap-faces-and-characters | hub de workflows | swap de rostos e personagens | swap | — | NÃO INICIADO | — |
| comfy.org/hub/workflows/wan2-2-animate-character-animation-and-replacement-c2c4b45b7df5/ | hub de workflows | swap de rostos e personagens | swap | — | NÃO INICIADO | — |

## BFS, identidade, edição e swap

| Fonte | Motor | Capacidade-alvo | Consumidores | Contrato I/O | Estado | Evidência / próxima ação |
|---|---|---|---|---|---|---|
| blog.comfy.org/p/wan22-animate-and-qwen-image-edit-2509 | Wan Animate + Qwen Edit 2509 | alternativa ao OpenJutsu (animar/substituir personagem) | swap em vídeo | video+image→video | NÃO INICIADO | — |
| docs.facefusion.io/usage/cli-arguments/face-selector | documentação | seleção de rosto (`--face-selector-*`) | swap | — | TESTADO CPU | opções usadas conferidas contra o `--help` real |
| github.com/Gourieff/comfyui-reactor | ReActor (ComfyUI) | troca de rosto | swap | image+image→image | NÃO INICIADO | — |
| github.com/PrunaAI | organização de modelos quantizados | — | — | — | NÃO INICIADO | — |
| github.com/facefusion/facefusion | FaceFusion 3.9.2 (CLI headless-run, venv próprio, licença «other») | app Trocar rosto (cf_faceswap.py, prepare_facefusion.py) | swap, agente (com confirmação: risco médio) | image+image→image · image+video→video | TESTADO CPU | troca real em CPU com o programa real: mudou só a região do rosto (tests/test_faceswap.py); sem rosto no destino ou na origem o Studio diz o motivo; consentimento obrigatório. Vídeo, GPU e os outros modelos de troca NÃO testados |
| huggingface.co/Alissonerdx/BFS-Best-Face-Swap | LoRAs BFS (Qwen 2.1 / LTX2) | troca de cabeça/corpo | swap | image+image→image | CÓDIGO ESCRITO | LoRAs catalogadas e classificáveis; sem app de swap |
| huggingface.co/Alissonerdx/BFS-Best-Face-Swap/blob/main/README.md | LoRAs BFS (Qwen 2.1 / LTX2) | troca de cabeça/corpo | swap | image+image→image | CÓDIGO ESCRITO | LoRAs catalogadas e classificáveis; sem app de swap |
| huggingface.co/Alissonerdx/BFS-Best-Face-Swap/blob/main/docs/qwen-image-2.1-body.md | LoRAs BFS (Qwen 2.1 / LTX2) | troca de cabeça/corpo | swap | image+image→image | CÓDIGO ESCRITO | LoRAs catalogadas e classificáveis; sem app de swap |
| huggingface.co/PrunaAI/P-Q-Image-2.1-Comfy | Qwen Image 2.1 quantizado | variante leve | create | — | NÃO INICIADO | — |

## Modelos e pipelines de vídeo, áudio e 3D

| Fonte | Motor | Capacidade-alvo | Consumidores | Contrato I/O | Estado | Evidência / próxima ação |
|---|---|---|---|---|---|---|
| blog.comfy.org/p/stable-audio-3-day-0-support | Stable Audio 3 (ComfyUI nativo; Comfy-Org/stable-audio-3, licença «other») | app Áudio (cf_audio.py): SFX, música curta, faixas longas; prompt expandido pelo LLM local | áudio, agente, Fábrica (futuro) | text→audio | CÓDIGO ESCRITO | grafo conferido contra o código do ComfyUI v0.44.0 (nós, entradas, tipo stable_audio), arquivos fixados conferidos na API do HF; player de áudio testado no navegador com um mp3 real; NENHUM áudio gerado (RAM/GPU): velocidade e qualidade não medidas |
| blog.comfy.org/p/trellis2-and-pixal3d-are-now-native | TRELLIS.2 / Pixal3D (ComfyUI nativo desde o v0.44: nodes_trellis2.py; pesos Comfy-Org/Pixal3D, MoGe, BiRefNet, TRELLIS.2) | app 3D (adiado) | 3D (futuro) | image→mesh (GLB) | NÃO INICIADO | estudado: o template oficial `3d_pixal3d_trellis2_image_to_model` tem ~60 nós em vários estágios (forma, textura, MoGe, remoção de fundo, bake de normal/AO, remesh) e chaves de seleção; traduzir isso para um grafo API sem rodar o ComfyUI é arriscado. Recomendação: importar o workflow oficial exportado em formato API pelo app «Workflow» (já existe) até haver GPU para validar |
| design.minimax.io/h3 | página do produto | — | app H3 | — | NÃO INICIADO | — |
| docs.comfy.org/tutorials/video/wan/wan2_2 | ComfyUI nativo + ComfyUI-GGUF | vídeo T2V/I2V Wan 2.2 A14B Q6_K (alta qualidade) e 5B baseline | text2video, animate | text/image→video | CÓDIGO ESCRITO | Lote 3: cf_wan.py ainda no 5B FP16; GGUF não integrado |
| github.com/Comfy-Org/docs/blob/main/tutorials/video/minimax/minimax-h3-native.mdx | documentação H3 | — | app H3 | — | NÃO INICIADO | — |
| github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_fun_controlnet_union.json | ComfyUI nativo | ControlNet Union do H3 (vídeo) | app H3 (futuro) | video+image→video | NÃO INICIADO | abrir o template e validar nós no worker |
| github.com/MiniMax-AI/awesome-minimax-h3-integration | MiniMax H3 | família de vídeo (FL2VA, Ref2VA, FastH3) | app H3 (futuro) | text/image/audio→video | NÃO INICIADO | — |
| github.com/ModelTC/LightX2V | LightX2V (aceleração) | inferência rápida de vídeo | text2video | — | NÃO INICIADO | — |
| github.com/Stability-AI/stable-audio-3 | Stable Audio 3 (ComfyUI nativo; Comfy-Org/stable-audio-3, licença «other») | app Áudio (cf_audio.py): SFX, música curta, faixas longas; prompt expandido pelo LLM local | áudio, agente, Fábrica (futuro) | text→audio | CÓDIGO ESCRITO | grafo conferido contra o código do ComfyUI v0.44.0 (nós, entradas, tipo stable_audio), arquivos fixados conferidos na API do HF; player de áudio testado no navegador com um mp3 real; NENHUM áudio gerado (RAM/GPU): velocidade e qualidade não medidas |
| github.com/barelymining/ComfyUI-MiniMax-H3-FastVideo | MiniMax H3 | família de vídeo (FL2VA, Ref2VA, FastH3) | app H3 (futuro) | text/image/audio→video | NÃO INICIADO | — |
| huggingface.co/Comfy-Org/MiniMax-H3 | MiniMax H3 | família de vídeo (FL2VA, Ref2VA, FastH3) | app H3 (futuro) | text/image/audio→video | NÃO INICIADO | — |
| huggingface.co/Lightricks/LTX-Video | LTX-Video | vídeo alternativo | text2video | text/image→video | NÃO INICIADO | LTX parcial no V7 |
| huggingface.co/MiniMaxAI/MiniMax-H3 | MiniMax H3 | família de vídeo (FL2VA, Ref2VA, FastH3) | app H3 (futuro) | text/image/audio→video | NÃO INICIADO | — |
| huggingface.co/VideoRebirthAI/hyperflow-h3-flash | H3 flash | — | app H3 | — | NÃO INICIADO | — |
| huggingface.co/alibaba-pai/MiniMax-H3-Fun-Controlnet-Union-2.0 | MiniMax H3 | família de vídeo (FL2VA, Ref2VA, FastH3) | app H3 (futuro) | text/image/audio→video | NÃO INICIADO | — |
| huggingface.co/collections/FastVideo/fasth3-omni | FastH3 | — | app H3 | — | NÃO INICIADO | — |
| huggingface.co/lightx2v | pesos LightX2V | — | text2video | — | NÃO INICIADO | — |
| ia.seenupdigital.com/noticias/criador-mostra-como-rodar-o-minimax-h3-mais-rapido-com-versoes-lora-e-prompts-ce302c | artigo | — | app H3 | — | NÃO INICIADO | não lido |

## Modelos, otimizações e componentes de imagem

| Fonte | Motor | Capacidade-alvo | Consumidores | Contrato I/O | Estado | Evidência / próxima ação |
|---|---|---|---|---|---|---|
| bfl.ai/models/flux-2-klein | FLUX.2 Klein 4B | modelo de imagem leve | create, edit | text/image→image | TESTADO GPU | única evidência de GPU: 512², 4 passos, 280 s com download (Colab antigo) |
| github.com/Blueforcer/ComfyUI-DLSS5-Enhancer | pacote ComfyUI | realce/upscale | upscale (modo) | image→image | NÃO INICIADO | — |
| github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_2_1_image_edit.json | ComfyUI nativo (template oficial) | grafo de edição Qwen 2.1 (modo do app Editar) | edit | image+text→image | TESTADO CPU | grafo do preset qwen21 validado contra /object_info (V7); GPU não medida |
| github.com/Niko1221/Strata | projeto de imagem | comparação | — | — | NÃO INICIADO | — |
| github.com/artfat-creator/ComfyUI-Artfat-MOSS-BBox | pacote ComfyUI (MIT) | motor do MOSS BBox | region | image+bbox→image | NÃO INICIADO | README lido; exige ComfyUI ≥0.42, Nodes 2.0, RES4LYF para res_6s; não instalado |
| github.com/black-forest-labs/flux2 | FLUX.2 | modelo de imagem | create | — | TESTADO GPU | mesma evidência acima |
| github.com/black-forest-labs/flux2/blob/main/model_licenses/LICENSE-FLUX-NON-COMMERICAL | FLUX.2 | modelo de imagem | create | — | TESTADO GPU | mesma evidência acima |
| huggingface.co/OpenMOSS-Team/MOSS-Image-Base | pesos MOSS (Apache-2.0, 27,2 GB cada: Base e SFT) | motor | region | — | NÃO INICIADO | tamanho conferido na API; sem variante quantizada confirmada para T4 |
| huggingface.co/OpenMOSS-Team/MOSS-Image-SFT | pesos MOSS | motor | region | — | NÃO INICIADO | — |
| huggingface.co/vistralis/FLUX.2-klein-4b-INT8-transformer | variante INT8 do Klein | variante leve | create | — | NÃO INICIADO | — |

## Resumo por estado

| Estado | Fontes |
|---|---|
| NÃO INICIADO | 58 |
| CÓDIGO ESCRITO | 14 |
| TESTADO CPU | 9 |
| baseline (não é capacidade) | 4 |
| TESTADO API REAL | 3 |
| TESTADO GPU | 3 |
| BLOQUEADO_GPU | 2 |

Total: 93. Próximas ondas de apps (ordem sugerida pelo que já tem motor e pode ser testado em CPU/API): swap de rosto (FaceFusion/ReActor), Qwen Expandir/Restaurar/Trocar roupa como modos do Editar, MOSS BBox (decisão app×modo pendente), Fábrica com cenas do ComfyUI, vídeo Wan GGUF (Lote 3), áudio e 3D.
