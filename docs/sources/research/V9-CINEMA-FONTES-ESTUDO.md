# V9 Cinema alfa: estudo de fontes externas

Data da leitura: 2026-11-24. Método: apenas leitura, via `gh api` (GitHub REST e raw), HF API e páginas web. Nenhum repositório foi clonado e nada foi executado ou testado. Os SHAs são o HEAD da branch padrão no momento da leitura. Onde algo não pôde ser lido, está dito explicitamente na seção final.

## Tabela resumo

| Fonte | Revisão (SHA) | Licença | Veredito |
|---|---|---|---|
| 1. ComfyArt (`jtydhr88/ComfyArt`) | `5ce760912de2bf7263dc27bddfabbf70daf4aaae` | MIT | ESTUDO (versionamento de projeto e storyboard; sem timeline) |
| 2. Creativefield (`rhymeas/Creativefield`) | `e8caee98ed8c238be4db0d6ddc758e42e22d0b56` | GPL-3.0 | ESTUDO / FILME FUTURO (ângulos novos do mesmo set; grey-block) |
| 3. ComfyUI-Panorama-Stickers (`nomadoor/ComfyUI-Panorama-Stickers`) | `732146a0f1dcbafe9ce331401e4465d95e42abe1` | MIT | ESTUDO (cache por bytes e mapeamento de timeline por camada) |
| 4. Imagination Studio (`Keys-Wasserman/Imagination-Studio-by-keys-Wasserman`) | `16f00b462a5a389e2c5e19c2cbf7d9527ad526ea` | Apache-2.0 (código); pesos com licença própria | ESTUDO / FILME FUTURO (storyboard e checagem de plano) |
| 5. Paint a Plate (`AInVFX/ainvfx-paintaplate`) | `d95292c1a96073a34bfec82d7462dbd2887d0000` | Apache-2.0 | ESTUDO / FILME FUTURO (correção no primeiro quadro, propagada) |
| 6. Depth Pro 2 (pesos HF e Apple) | HF Space `3dedf9cef...`; LiteRT `71cac3790...`; `apple/DepthPro2` `b1c7c989d...` | apple-amlr (pesquisa não comercial) | DESCARTAR para o ClonField (uso comercial proibido) |
| 7. Catálogo comfy.org e vídeo | página lida; vídeo sem transcrição | n/a | Contexto apenas |
| 8. OpenTimelineIO (`AcademySoftwareFoundation/OpenTimelineIO`) | tag `v0.18.1` = `44236713c1db295a6ffc66189ae98dbdfd0cb9c4`; `main` = `f38b2cb6c9d22b91a82c129d5551d41910a3a1db` | Apache-2.0 | ESTUDO - exportar depois (formato de intercâmbio) |

Resultado geral: nenhuma fonte entra agora (INCORPORAR AGORA). Nenhuma delas entrega um timeline de montagem em CPU com cache de planos. As úteis são ideias de desenho e padrões de código. Qualquer uso de código precisa respeitar a licença de cada uma (GPL-3.0 no caso do Creativefield).

---

## 1. ComfyArt

- **URL:** https://github.com/jtydhr88/ComfyArt
- **Revisão:** `5ce760912de2bf7263dc27bddfabbf70daf4aaae` (branch `main`, lido em 2026-11-24)
- **Licença:** MIT (arquivo `LICENSE`, "MIT License, Copyright (c) 2026 Terry Jia").
- **Stack:** TypeScript/React (canvas com tldraw) mais Python. Roda como custom node do ComfyUI, com a interface em `dist/` já compilada. Os projetos ficam em SQLite (`user/__comfyart/data.db`), conforme o README.
- **Arquivos relevantes (somente leitura):**
  - `api/projects.py`, `api/project_store.py`, `api/db.py`: persistência de projetos, histórico de snapshots e chats.
  - `api/mcp_tools/media.py`, `api/mcp_tools/canvas.py`: ferramentas do agente para gerar mídia e editar o canvas.
  - `bot/turns.py`, `api/bot_turns.py`: turnos do agente.
  - README: "storyboard" aparece como modo de geração de vídeo (5 a 15 s, 768p ou 1080p) e como "storyboard split" feito por uma única chamada ao agente (`POST /comfyart/bot/complete`).
- **Ideias úteis:**
  - (a) Versionamento por projeto com histórico de snapshots em banco local. Serve de referência para versionar planos e referências, mas não para o cache de render do ClonField.
  - (b) Storyboard que é dividido em planos e cada plano vira um vídeo. Útil como modelo mental da revisão de plano, não como implementação.
  - (d) Roteiro -> storyboard -> vídeos: o fluxo existe, mas depende de modelo de geração.
- **Rodaria em CPU?** Não. Exige GPU local do ComfyUI ou a API Comfy Cloud (paga). O README não descreve nenhum modo CPU.
- **Veredito:** ESTUDO. Não há timeline, montagem nem trilhas de áudio. O modelo de snapshot pode inspirar o histórico de versões de plano no ClonField.

## 2. Creativefield

- **URL:** https://github.com/rhymeas/Creativefield
- **Revisão:** `e8caee98ed8c238be4db0d6ddc758e42e22d0b56` (branch `main`, lido em 2026-11-24)
- **Licença:** GPL-3.0 (arquivo `LICENSE`, "GNU GENERAL PUBLIC LICENSE Version 3"). Copiar código para o ClonField obriga o ClonField a ser GPL. Usar as ideias não tem essa obrigação.
- **Stack:** `index.html` e front-end em TypeScript (o GitHub lista TypeScript), mais workflows JSON da API do ComfyUI em `native-workflows/*/template.api.json`, cada um com `manifest.json` e README. Roda sobre o ComfyUI. Docs de instalação em `docs/`.
- **Arquivos relevantes:**
  - `native-workflows/flux2-klein-angles/README.md` e `manifest.json`: "FLUX 3 Klein camera angles (local only)". Gera o mesmo set de outros ângulos de câmera a partir de uma imagem.
  - `native-workflows/previs-to-video/manifest.json` (v0.5.0): "Grey-block to video". Transforma um clipe de bloqueio em cinza em um plano final, mantendo o caminho da câmera e a posição dos objetos.
  - `native-workflows/film-frame-interpolation/`, `native-workflows/kenburns-still/`: interpolação entre quadros e movimento de câmera sobre uma imagem fixa.
  - `native-workflows/overlay-inpaint/`, `native-workflows/image-edit-sd21-inpaint/`: edição com máscara.
  - `docs/LICENSE-INVENTORY.md`: as licenças dos modelos chamados pelos workflows (MiniMax H3, SAM 3.1, HyperFlow, etc.) estão listadas aqui, não só a do código.
- **Ideias úteis:**
  - (c) Novos ângulos do mesmo set: o pack `flux2-klein-angles` (que agora roda FLUX 3 Klein) é a ideia direta para o "plano de estabelecimento com câmera girando no mesmo cenário".
  - (b) Storyboard -> bloqueio de câmera -> revisão: o `previs-to-video` faz exatamente essa ponte, do grey-block ao plano final.
  - (a) Referências e máscaras por plano: os workflows de inpaint e de edição com máscara mostram como guardar a máscara junto do plano.
- **Rodaria em CPU?** Não. O README pede Windows com GPU NVIDIA. Os workflows chamam modelos de difusão e de vídeo grandes.
- **Veredito:** ESTUDO / FILME FUTURO. Serve a um filme com planos gerados (ex.: "plano de estabelecimento com câmera girando no mesmo cenário", ou um plano de transição de cena). Não serve à montagem em CPU de hoje.

## 3. ComfyUI-Panorama-Stickers

- **URL:** https://github.com/nomadoor/ComfyUI-Panorama-Stickers
- **Revisão:** `732146a0f1dcbafe9ce331401e4465d95e42abe1` (branch `main`, lido em 2026-11-24)
- **Licença:** MIT (arquivo `LICENSE`, "MIT License, Copyright (c) 2026 nomadoor").
- **Stack:** Python (pacote `comfyui_pano_suite/`, nós do ComfyUI) mais JavaScript para o editor. Roda como custom node do ComfyUI, com `torch` e `numpy`.
- **Arquivos relevantes:**
  - `comfyui_pano_suite/core/cache.py`: cache de um só pacote, limitado em bytes. O teto é o menor entre 4 GiB e 25% da RAM livre, com no máximo 256 entradas e remoção por menos usado recentemente (LRU). Arrays são devolvidos somente leitura, sem cópia. Está documentado em `docs/runtime-resources.md` (texto em japonês).
  - `comfyui_pano_suite/scene_timeline.py`: para cada quadro de saída, diz qual quadro de fundo e qual quadro de cada camada usar, com as poses de clipes glTF. É o mapeamento tempo de saída -> quadro de fonte por camada, o que se parece com o que um timeline de montagem precisa.
  - `comfyui_pano_suite/core/scene_state.py` e `docs/adr/0026-keyframe-lanes.md`: pistas de keyframe por camada.
  - `comfyui_pano_suite/sticker_media.py`, `comfyui_pano_suite/core/video_source.py`: fonte de vídeo por camada e tolerância de PTS.
  - `docs/adr/0039-da3-depth-grid.md`, `docs/adr/0040-moge-depth-grid.md`, `docs/adr/0054-depth-grid-playback-sync-and-cache.md`: grade de profundidade estimada com DA3 ou MoGe, com cache.
  - README: round trip "Fix a Shot and Put It Back": um plano corrigido por um modelo de imagem volta ao mesmo lugar pelo `sticker_state`.
- **Ideias úteis:**
  - (a) Cache de render limitado em bytes com LRU e leitura só-leitura: é o padrão mais próximo do "cache de render por plano" que o ClonField precisa. Pode ser reescrito em Python puro.
  - (d) Mapeamento de tempo por camada (fundo, voz, efeitos) que aparece em `scene_timeline.py`. Serve de referência para as trilhas separadas.
  - (f) Profundidade estimada a partir de uma imagem (DA3 ou MoGe) para dar parallax de 2,5D em uma prévia.
  - (e) Pode ser lido como correção de um quadro que volta ao plano, mas o mecanismo é de stickers, não de propagação ao plano inteiro.
- **Rodaria em CPU?** Não verificado. O código é `torch` e `numpy`, e o ComfyUI roda em CPU, mas os modelos de profundidade (DA3, MoGe) e o editor não foram lidos com essa finalidade. Nenhum teste de CPU foi lido.
- **Veredito:** ESTUDO. A ideia de cache limitado por bytes entra no desenho do cache de render. Não se copia o código: é um nó do ComfyUI, e o ClonField é em FFmpeg.

## 4. Imagination Studio by keys + Wasserman

- **URL:** https://github.com/Keys-Wasserman/Imagination-Studio-by-keys-Wasserman
  - Observação: o catálogo do comfy.org lista `https://github.com/drowzeys/Imagination-Studio-by-keys-Wasserman`. Essa URL redireciona para o mesmo repositório (a API devolve `Keys-Wasserman/...`).
- **Revisão:** `16f00b462a5a389e2c5e19c2cbf7d9527ad526ea` (branch `main`, lido em 2026-11-24)
- **Licença:** Apache-2.0 para o código (`LICENSE`, `NOTICE`). Os pesos e ferramentas têm licença própria, segundo o README e `docs/licensing.md`: Qwen-Image-2.1 e MMAudio são não comerciais; MiniMax H3 tem limites territoriais; Fish Audio hosted exige licença separada.
- **Stack:** Python (FastAPI em `app/server.py`) mais front-end em HTML/JS (`app/static/*.js`). Roda como app local em `http://127.0.0.1:7870`, em Windows nativo, Mac com Apple Silicon ou NVIDIA Linux. Não é um custom node.
- **Arquivos relevantes:**
  - `app/slate.py`: porte do fluxo Slate (planejar o filme como uma equipe, planos de cobertura, perfis de modelo). O docstring diz que é o "prompt studio" de Sam Wasserman, Apache-2.0.
  - `app/shot.py`: checagem de um clipe: se os keyframes foram mantidos e se há corte dentro do clipe. O docstring descreve os casos reais (primeiro keyframe não mantido, corte seco para close-up).
  - `app/roughcut.py`, `app/finish.py`, `app/revise.py`, `app/director.py`: montagem de corte bruto, acabamento, revisão de plano e direção.
  - `app/captions.py`, `app/sound.py`, `app/music.py`: legendas, som e música. São as trilhas que tocam o ClonField.
- **Ideias úteis:**
  - (b) Storyboard -> bloqueio de câmera -> revisão: `slate.py` e `director.py` mostram a ordem de planejamento por plano.
  - (b) Revisão automática de plano: `shot.py` é uma checagem objetiva (keyframe mantido, corte no meio) que pode virar um teste de qualidade de plano no ClonField, feito com análise de quadros.
  - (d) Roteiro -> planos -> versões -> montagem: `roughcut.py` e `finish.py` são a sequência que o ClonField quer.
  - (a) Referências por plano em formato de projeto próprio (`slate.py`).
- **Rodaria em CPU?** Não. Os pesos exigem GPU NVIDIA ou Mac com Apple Silicon, e o README traz tabelas de RAM e VRAM. A aplicação não foi lida para uso em CPU.
- **Veredito:** ESTUDO / FILME FUTURO. A checagem de keyframe e de corte em `shot.py` pode ser reimplementada em CPU para a revisão de plano, o que é direto para o ClonField. O resto depende de modelos que não rodam em CPU.

## 5. Paint a Plate (AInVFX)

- **URL:** https://github.com/AInVFX/ainvfx-paintaplate
- **Revisão:** `d95292c1a96073a34bfec82d7462dbd2887d0000` (branch `main`, lido em 2026-11-24)
- **Licença:** Apache-2.0 (`LICENSE`).
- **Stack:** Python (nó do ComfyUI: `nodes.py`, `plateio.py`, `mathops.py`, `ocio.py`) mais JavaScript (`web/*.mjs`, com testes em `tests/js`). Roda como node pack do ComfyUI.
- **Arquivos relevantes:**
  - `ARCHITECTURE.md`: descreve o fluxo. Pinta-se o primeiro quadro (apagar, adicionar ou relightar); FLUX 3 Image Klein faz a edição no primeiro quadro; LTX 2.5 leva a edição a todos os quadros; SAM 3.1 rastreia as áreas alteradas; Follow Matte mantém o elemento dentro da matte; o resultado é composto sobre a placa. Há uma prévia rápida e depois o passe em tamanho real.
  - `ARCHITECTURE.md`: "Generate nunca faz um resultado duas vezes": a mesma edição (traços, texto, semente) mantém o resultado já feito. É um cache por identidade de entrada.
  - `plateio.py`: exporta no formato da placa de origem (tipo de arquivo, bit depth, quadros, tags de cor, timecode, áudio copiado). Só o que foi editado muda; o resto é o pixel de origem.
- **Ideias úteis:**
  - (e) Correção feita no primeiro quadro e propagada pelo plano inteiro, com a composição sobre a placa. É a ideia exata do item (e).
  - (a) Cache por identidade de entrada (traços, texto, semente): o ClonField pode usar o mesmo critério para o cache de render por plano (hash de planos, versões e referências).
  - Exportação preservando formato e áudio da fonte (`plateio.py`) é uma referência para o passo de montagem final com FFmpeg.
- **Rodaria em CPU?** Não. O README exige GPU NVIDIA com 32 GB de VRAM ou mais. Em Mac ou em placas menores, o autor indica rodar em Runpod. O README cita um teste de CPU no CI, mas isso é para o teste da interface, não para a edição.
- **Veredito:** ESTUDO / FILME FUTURO. A propagação de correção no primeiro quadro é útil para um filme com efeitos. O cache por identidade de entrada entra no desenho do cache do ClonField como princípio, sem o código.

## 6. Depth Pro 2 (Apple): pesos e licença

- **Fontes lidas:**
  - Space: https://huggingface.co/spaces/byoussef/DepthPro2-WebGPU, revisão HF `3dedf9cefee231dfa9ba9edf997c664076e35486`, cardData `license: other`, `license_name: apple-amlr`.
  - LiteRT: https://huggingface.co/byoussef/DepthPro2-litert, revisão `71cac37902f09fc1668be1820938d627dad920e3`. Conversão não oficial, feita por terceiro. Arquivos: `depthpro2-s_480x854.tflite` (98 MB), `depthpro2-b_480x854.tflite` (387 MB), `depthpro2-fov_480x832.tflite` (95 MB).
  - Oficial: https://huggingface.co/apple/DepthPro2, revisão `b1c7c989d82feb6be85a1d09521e47de424afbfc`, `license: other`, `license_name: apple-amlr`.
  - Código: https://github.com/apple-aiml-research/ml-depth-pro-2, commit `aa389cbb0b74341664ed663a0966c859905cd6c0`. Licença do código `NOASSERTION` na API (o arquivo `LICENSE` é um termo de amostra da Apple, não o de pesos). O arquivo `LICENSE_MODEL` é o que vale para os pesos.
- **Licença dos pesos (texto lido em `LICENSE_MODEL`, idêntico no HF):**
  - Concessão: licença "personal, non-exclusive, worldwide, non-transferable, royalty-free, revocable, and limited", "exclusively for Research Purposes".
  - Definição: "Research Purposes" "means non-commercial scientific research and academic development activities" e "does not include any commercial exploitation, product development or use in any commercial product or service".
  - Derivados (Model Derivatives) também ficam limitados a Research Purposes.
  - Redistribuição: é preciso entregar o acordo a terceiros e incluir a frase "Apple Machine Learning Research Model is licensed under the Apple Machine Learning Research Model License Agreement."
  - Marcas da Apple não podem ser usadas para endosso.
  - Terminação: a Apple pode encerrar o acordo se houver violação.
  - O model card confirma: "for research use only: non-commercial scientific research and academic development".
- **O que isso permite, em termos práticos:** pesquisa e experimento privado e não comercial. Não permite usar os pesos em um produto, em um serviço ou em um filme comercial do ClonField, nem redistribuir derivados fora da pesquisa. A conversão LiteRT de terceiro herda a mesma licença.
- **Tamanho:** a família oficial tem S (24M parâmetros, 97 MB), B (97M, 386 MB), L (334M, 1,3 GB) e H+ (872M, 3,5 GB). O modelo de campo de visão (focal) tem 23,5M parâmetros, 94 MB. A conversão LiteRT só traz S, B e o FOV; L e H+ não foram convertidos.
- **Roda em CPU?** Não há indicação. O quick start oficial usa `model.to("cuda")` e `bfloat16`, que é o caminho de GPU. A conversão LiteRT é para GPU delegate e WebGPU. Não encontrei nenhuma medição em CPU, então não afirmo que roda ou não roda em CPU.
- **Veredito:** DESCARTAR para o ClonField. Como ideia, a profundidade em 2,5D (f) pode ser pensada com outra fonte de profundidade de licença comercial. Não usar estes pesos num produto. Estudar apenas para pesquisa privada e não comercial.

## 7. Catálogo comfy.org e vídeo

- **Página:** https://comfy.org/open-source-higgsfield . O `WebFetch` não encontrou a seção `#challenge-content`. A página tem a seção "Winners are in" com os projetos premiados e as menções honrosas. A lista abaixo vem desse resumo feito pelo `WebFetch`; não conferi cada linha no HTML original.

Projetos nomeados, com URL de repositório e uma linha. Os marcados com **[timeline/edição/montagem/áudio]** tocam o que o ClonField precisa. As descrições só são as que eu li nos repositórios (1 a 5); os outros estão só pelo nome e pela categoria do catálogo, sem leitura.

| Projeto | URL | Premiação | Nota |
|---|---|---|---|
| ComfyUI Panorama Stickers | https://github.com/nomadoor/ComfyUI-Panorama-Stickers | Best Overall ($10.000) | Lido. Panorama, stickers e timeline de keyframes. **[timeline/edição]** |
| Blocksfield | https://github.com/Hcoder10/blocksfield | Most Innovative | Não lido. |
| Imagination Studio | https://github.com/drowzeys/Imagination-Studio-by-keys-Wasserman (redireciona para Keys-Wasserman) | Most Viral | Lido. Estúdio de filme com planejamento, montagem, legenda, som e música. **[timeline/edição/montagem/áudio]** |
| Paint a Plate | https://github.com/AInVFX/ainvfx-paintaplate | Open Weights Only; VFX com LTX ($2.000) | Lido. Edição de VFX no primeiro quadro e exportação. **[edição/montagem]** |
| ComfyArt | https://github.com/jtydhr88/ComfyArt | Built with FLUX ($1.000) | Lido. Canvas de design com geração de vídeo a partir de storyboard. |
| Creativefield | https://github.com/rhymeas/Creativefield | Built with FLUX ($500) | Lido. Estúdio com workflows de ângulos, grey-block e edição de área. |
| Genobi | https://github.com/koshimazaki/genobi | Built with FLUX ($250) | Não lido. |
| H3 Motion | https://github.com/PxTicks/h3-motion | Built with MiniMax H3 ($1.000) | Não lido. |
| Reshoot 4D | https://github.com/itsmetamike/reshoot-4d | Menção honrosa | Não lido. |
| OneShot MV | https://github.com/VisualFrisson/ComfyUI-OneShotMV | Menção honrosa | Não lido pelo nome; "MV" sugere clipe musical. **[áudio/montagem]** a confirmar. |
| Freefield | https://github.com/neuregex/freefield | Menção honrosa | Não lido. |
| Splat Edit Engine | https://github.com/Burgstall-labs/ComfyUI-SpEdE | Menção honrosa | Não lido. Nome sugere edição de splat. |
| Sonder App | https://github.com/SonderSaid/ComfyUI-Sonder-Editor | Menção honrosa | Não lido. Nome sugere editor. **[edição]** a confirmar. |
| Max Editor | https://github.com/xentome/EDITS-WITH-AI | Menção honrosa | Não lido. Nome sugere editor. **[edição]** a confirmar. |
| Henge | https://github.com/alisson-anjos/Henge | Menção honrosa | Não lido. |
| H3-AudioRetake-Studio | https://github.com/Nebuluss/H3-AudioRetake-studio | Menção honrosa | Não lido. Nome sugere refazer áudio. **[áudio]** a confirmar. |

- **Vídeo:** https://www.youtube.com/watch?v=ddirEBVYVno. Título lido: "A 'NOVA' ComfyUI humilhou o Higgsfield (e é de graça)". A descrição (lida pela página, que não traz transcrição): é um vídeo de um criador que fala do desafio, de uma carta de advogado, de quem venceu e de ferramentas da comunidade, e que promove cursos próprios. **Não consegui assistir ao vídeo nem ler a transcrição.** Não tenho nada do conteúdo do áudio ou das cenas.

## 8. OpenTimelineIO (exportar depois)

- **URL:** https://github.com/AcademySoftwareFoundation/OpenTimelineIO
- **Versão atual:** a última tag é `v0.18.1` (commit `44236713c1db295a6ffc66189ae98dbdfd0cb9c4`, data do commit 2025-11-08). O repositório não publica GitHub Releases (`releases/latest` dá 404), então a "release atual" é a tag mais recente. O `main` (`f38b2cb6c9d22b91a82c129d5551d41910a3a1db`) teve push em 2026-11-23.
- **Licença:** Apache-2.0 (`LICENSE`, texto completo lido).
- **Stack:** C++ com bindings Python. Formato `.otio` (JSON).
- **Uso no ClonField:** é um formato de intercâmbio de timeline de edição (faixas, clipes, transições, tempo). Serve para exportar a montagem para um editor de NLE depois, não para montar o vídeo em CPU. Não entra agora.
- **Veredito:** ESTUDO, exportar depois.

---

## Não consegui ler

- **Seção `#challenge-content` do comfy.org:** não existe na página lida. A lista de projetos veio da seção "Winners are in", por resumo do `WebFetch`, não do HTML bruto.
- **Vídeo `ddirEBVYVno`:** não assisti. Só li título e descrição da página. Não tenho transcrição.
- **Repositórios não lidos do catálogo:** Blocksfield, Genobi, H3 Motion, Reshoot 4D, Freefield, Splat Edit Engine, Sonder App, Max Editor, Henge, H3-AudioRetake-Studio, OneShot MV. Estão listados só pelo nome e pela categoria da página.
- **Depth Pro 2 em CPU:** não há medição nem indicação na documentação lida. Não sei se roda em CPU e na velocidade de quê.
- **Panorama Stickers em CPU:** o código não foi lido para o caminho de CPU; o `cache.py` e o `scene_timeline.py` foram lidos só como código.
- **Imagination Studio e Paint a Plate em CPU:** os READMEs exigem GPU; não li um caminho de CPU.
- **Licenças dos modelos de terceiros citados por Creativefield (MiniMax H3, SAM 3.1, HyperFlow, FLUX 3):** só li o que o próprio repositório lista em `docs/LICENSE-INVENTORY.md`. Não abri as licenças dos próprios modelos.
- **Nenhum teste rodado:** tudo aqui é leitura de código, README e metadados.
