# Reconciliação plano V7.1 × código real

Atualizada na rodada 5 (núcleo). Escrita após leitura de `PLANO_MESTRE_V7_1` até a seção 6 e do índice do restante (o arquivo histórico de 06/11,
linhas ~1039-1331, **ainda não foi lido por inteiro**). Estados: `pronto-testado-T4`, `pronto-testado-CPU`,
`pronto-sem-teste-real`, `parcial`, `não iniciado`. Nada abaixo é «aprovado para produção».

## Núcleo da plataforma (o que o plano chama de plataforma extensível)

| # | Item do plano | Fonte | Estado no código | Evidência | Lacuna |
|---|---|---|---|---|---|
| 1 | ★ vermelha de compatibilidade padrão por app+tarefa, ordem ★ → instalados → catálogo → «Pesquisar» | V5.1 | **parcial (rodada 5)**: `cf_registry` deriva a ★ da receita; ordem ★ → instalados; estrela vermelha com `aria-label` | testes + navegador local | ★ ainda só em Criar/Editar/Luz/Retrato (apps de imagem); não derivado de `validated_on_gpu`; sem ★ nos apps de vídeo/outros |
| 2 | Dropdown contextual em TODO slot com «Pesquisar» filtrado e «Usar aqui» | 2.1 | **parcial (rodada 5)**: slots Difusão/Checkpoint, Encoder, VAE, Upscaler, sampler e scheduler (lista do worker real); modal Pesquisar com 3 fontes e instalação Civitai por papel | navegador local + APIs HF/Civitai reais; 11 testes novos | **instalação de um VAE/encoder e uma geração com o slot trocado não foram testadas na T4**; ControlNet/embedding/CLIP Vision sem slot; LoRA segue no painel próprio; HF só descobre (não baixa) |
| 3 | Presets **Rápido/Moderado/Qualidade/Manual** = conjunto inteiro | V4/V5.2 | **parcial (rodada 5)**: campo «Conjunto» aplica passos, CFG, tamanho de geração, sampler/scheduler e lista os componentes ★; mexer à mão vira Manual | testes + navegador | **cada conjunto escolhe um modelo diferente** (Rápido: mais rápido que cabe; Moderado: equilíbrio; Qualidade: maior fidelidade) a partir das notas do catálogo, **sem benchmark A/B**; Manual mostra difusão, encoder, VAE, upscaler, sampler, scheduler, passos, CFG, shift (Z-Image), expansor (FLUX.3), seed, liberar VRAM; offload real por conjunto, ControlNet, VAD e workflow **não** estão ligados; só apps de imagem |
| 4 | Biblioteca universal HF + CivitAI + local, estados encontrado→validado, matriz de compatibilidade | 4 | **parcial (rodada 5)**: busca unificada `/search` (local, Civitai por papel+base, HF) com `status` honesto (instalado / compatível / descoberto); LoRAs Civitai com capas | testado real contra civitai.red e huggingface.co | sem aba Biblioteca geral (só dentro dos slots); sem matriz validada por GPU; sem vídeo/3D/áudio; HF não instala |
| 5 | Escala de qualidade **Muito Alta 2048 / Ultra 4096** com upscale em estágios e tiles, mostrando «Geração → Ampliação → Saída» | 3 | **parcial (rodada 5)**: campo «Resolução final», `resolution_plan`, ampliação em blocos (Real-ESRGAN via spandrel, Lanczos de reserva), job registra «Geração → ampliação → saída» | 3 testes com arquivos reais (caminho Lanczos) | **Real-ESRGAN em GPU e artefatos de bloco não testados**; 1:1 e 9:16 não comparados; sem painel «Como obter esta resolução?» completo; SeedVR2/Qwen generativo como método não ligados |
| 6 | «Ampliar depois» abre painel completo de pós-processamento | 9 | **não iniciado** (só um select) | — | |
| 7 | Variações 1-4 de fato editáveis | 2.2/11.2 | **feito (rodada 6)**: seletor 1-2-3-4 sem depender do perfil; servidor limita a 4 | teste de formulário | tempo estimado por variação não mostrado |
| 8 | Capa do modelo não sobrescrita pela última geração | 11.1 | **feito** (capa de modelo vs. amostras) | testado local | — |
| 9 | Chat de criação com **sessões/projetos persistentes**, anexos, memória de originais/revisões | V7.4 | **parcial (rodada 6)**: página Chat; sessões em JSON no disco, anexos, plano do Jev por mensagem, «Executar» por passo, job com progresso, resultado volta para a sessão ao lado do original; sessões isoladas | 6 testes via API real (job `look` em CPU) + navegador | só passos de um clique (apps com entradas preenchíveis pela sessão); sem parâmetros inferidos pelo JEV; sem execução automática encadeada; sem vários personagens por projeto; histórico de revisões sem comparação lado a lado; sessões em disco do Colab (somem sem Drive) |
| 10 | JEV como decisor estruturado + roteador por capacidade | V7.4 | **parcial**: Jev real (`api.typesafe.ai`), escolha de app, plano em série | **testado ao vivo**: 30/30 em gabarito próprio | só decide o app, não parâmetros/slots/modelos/LoRAs; não executa a cadeia; sem DAG tipado |
| 11 | Autoavaliação e reparo com teto de rodadas | V7.4/6 | **parcial**: gate técnico + loop (nitidez/exposição/vazio) | testado CPU com imagens reais | sem avaliador visual real (identidade, anatomia); sem reexecução parcial de DAG |
| 12 | Projeto como DAG versionado com cache por hash, regeneração parcial | V6 §4 | **parcial** via Content Factory vendorizado | render real em CPU (mudo e narrado) | só modo *drawn*; sem UI de revisão por cena; modos com imagem sem provedor ComfyUI |
| 13 | Instalar conjunto, dedupe por hash, estimativa de disco/VRAM/RAM antes de baixar | 5 | **não iniciado** | — | observado na T4: teste «mínimo» baixou 14,7 GB sem aviso |
| 14 | Offload `Desligado/Auto/CPU/Disco` por componente | 5/V5.2 | **não iniciado** (flags por perfil de GPU apenas) | — | |
| 15 | Capa criada para CADA modelo e CADA app | V5.6 | **parcial**: 7 modelos + 4 capas de grupo de app | verificado visualmente | apps novos (Camadas de anime, Fábrica de vídeo) sem capa própria; Wan/LTX/Mochi etc. sem |

## Apps e capacidades pedidos

| Capacidade | Fonte | Estado | Evidência | Lacuna |
|---|---|---|---|---|
| See-through V3 → camadas → PSD | V7.2 | **pronto-sem-teste-real**: app, perfis NF4/BF16/offload, PSD no servidor, instalação fixada | grafo aceito pelo ComfyUI 0.44; PSD sintético relido; job até o loader | **nunca gerou camadas** (a T4 ainda roda código antigo); block swap não integrado; editor `LAYERS`/2.5D/rig não feito |
| Face/cabeça/corpo/roupa swap (BFS, ReActor, FaceFusion), multi-sujeito 1:N, máscaras | V5.3 | **não iniciado** | — | BFS só catalogado como LoRA; sem apps de swap |
| Swap/animação em vídeo (Wan Animate, SCAIL-2, FaceFusion) | V5.3 | **não iniciado** (OpenJutsu exige ~96 GB) | — | |
| MOSS BBox Studio (layout por caixas + edição localizada + prompter opcional) | V5.2 | **não iniciado** | — | decidir app próprio × modo (plano diz consultar só se não houver decisão antiga) |
| MiniMax H3 (FL2VA, Ref2VA, FastH3, Singularity, ControlNet Union) e apps de vídeo por quadros-chave/referências | V3 | **não iniciado** (existe Wan e LTX parcial) | — | |
| Qwen Expand/Restore/Upscale/Outfit Swap | 8 | **parcial**: LoRAs catalogadas | — | sem apps/modos dedicados |
| Imagem→3D (TRELLIS.2/Pixal3D), SFX/trilha (Stable Audio 3) | V4 | **não iniciado** | — | |
| Agente multimodal opcional (Comfy MCP) | V4 | **não iniciado** | — | |
| Content Factory (cache por etapa, narração, render) | V6 §4 | ver item 12 | ver item 12 | |
| Luz ambiente, Enquadrar, reenquadramento, painel público | pedidos anteriores | **pronto-testado** (local; público testado entre origens) | testes + navegador | luz ambiente fiel ao traço/identidade: relato de problema em 11.4 não tratado |
| Qwen INT8 ConvRot preservado | baseline | **preservado** (nenhuma mudança no preset) | — | não medido de novo na T4 |

## O que a T4 real já provou (única evidência de GPU até aqui)
Studio no Colab com T4 15 GB, perfil Leve; FLUX.2 Klein 4B gerou 512² em 4 passos (280 s incluindo ~14,7 GB de download e
carga). Rodada seguinte de 1,1 s é provável cache (mesma seed). Nada mais foi medido em GPU.

## Decisões do plano que exigem resposta do proprietário (só estas)
1. MOSS BBox: app próprio ou modo em Criar/Editar região? (plano: perguntar só se não houver decisão anterior)
2. «T4 de 12 GB»: teto de VRAM ou RAM do host? (medido agora: T4 15 GB VRAM, 12,7 GB RAM host)
Todo o resto é decisão técnica minha.


## Rodada 7 (favoritos, upscalers, catálogo explorável)
- **Favoritos (estrela amarela, ≠ ★ vermelha de compatibilidade):** apps, modelos, LoRAs, upscalers e resultados de busca de componentes; salvos no servidor (`favorites.json`); aparecem primeiro nas listas e em filtros «Favoritos». Não há favorito para resultados gerados (imagens) nem para opções de slot instaladas.
- **Upscalers:** de 2 para **17** (Real-ESRGAN x4plus/anime/geral v3, NMKD-Siax, Remacri, UltraSharp, UltraSharp V2, OmniSR x2/x4 e 8 modelos Nomos/HFA2k/ParimgCompact/DeJPG da Phips, CC-BY-4.0), revisão HF fixada e SHA-256 conferido quando publicado; licença dos pesos exibida (NC marcado). 9/9 carregam e ampliam em CPU de verdade.
- **Modelos › Explorar:** checkpoints, difusão, VAEs, encoders (CivitAI por base compatível, Hugging Face só descoberta, no worker) e upscalers; tamanhos reais de download no Catálogo (Qwen 17,3 GB, FLUX.2 16,1 GB, Krea 19,0 GB, Z-Image 14,6 GB; FLUX.3 indisponível por repositório restrito).
- **LoRAs:** a família agora cobre todos os modelos (inclui SDXL e SD 1.5), com marca de modelo instalado e contagem de LoRAs prontas; aba Favoritas.
