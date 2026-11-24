# V9-P1-SOURCE-002: fontes para Asset Graph (P1-P2) e Cinema (P3-P4)

Data: 2026-11-24. Tarefa Haiku FONTE, só leitura. Nada foi instalado, baixado (pesos, pacotes, clones), testado nem executado. Sem pytest, pip, npm, git clone, git commit ou push. A única escrita é este arquivo.

Método: leitura local (arquivo:linha) e leitura remota por `curl` de texto bruto (stdout, sem salvar) e WebFetch quando o domínio foi aceito. WebFetch recusou `raw.githubusercontent.com`, `api.github.com` e `ffmpeg.org`; esses foram lidos por curl. Os SHAs são do HEAD da API no momento da consulta. Os URLs raw usam `main`/`HEAD`, então podem diferir se a branch andar.

Problemas: P1 referências imutáveis; P2 versões e procedência; P3 cache parcial; P4 render por tomada e trilhas separadas.

---

## (a) Já existe no ClonField

### P1 Referências imutáveis

| O que existe | Onde | Lacuna frente ao contrato |
|---|---|---|
| Hash de conteúdo de arquivo (`file_sha256`, com cache por caminho) | `cf_dag.py:43`, `cf_dag.py:59` (`artifact_hash`) | Hash é do conteúdo, mas o id do artefato é o caminho/hash do cache, não um id estável |
| Cache endereçado por hash do nó (`node_hash` = sha256 de cap.id + version + params + hashes das entradas) | `cf_dag.py:311` | Já é o mecanismo do contrato (invariante 6). Não há blob compartilhado entre nós |
| Armazenamento por hash, gravação atômica (`.work-` + `replace`) | `cf_dag.py:354-367` (`store`), `cf_dag.py:321` (`load_cached`) | Saída fica em `dag/cache/<hash>/out`, sem deduplicação global entre execuções |
| Elenco: PNG por personagem, sobrescrevível | `cf_cast.py:57` (`add`), `cf_cast.py:53` (`image_path`) | Sem hash, sem versão (confirmado pelo contrato) |
| Histórico/índice de resultados por leitura de registro | `cf_history.py:32` (`read_record`), `cf_history.py:95` (`choices`) | Indexa arquivos existentes; não tem id estável |
| Uploads copiados por "Usar em" (`POST /import`) | `docs/V9_ASSET_GRAPH_CONTRACT.md` (Problema) | É o problema que o contrato corrige |

### P2 Versões e procedência

| O que existe | Onde | Lacuna |
|---|---|---|
| Registro de execução (run record) gravado em `dag/runs/<id>.json` com escrita atômica | `cf_dag.py:370` (`write_run`), `cf_dag.py:377` (`load_run`), `cf_dag.py:394` (`execute`) | Registra nós e status; não tem árvore de pais de ativos |
| Metadados por saída: capability, version, seconds, outputs | `cf_dag.py:354` (`store`) escreve `meta.json` com capability id/version | Sem autor, sem receita nomeada, sem pais de ativos (só dentro do grafo) |
| Ids de pai no grafo via `{"from": "node.port"}` e `{"media": id}` | `cf_dag.py:1-20` (docstring), `cf_dag.py:69` (`parse_ref`) | Procedência só existe dentro de uma execução |
| Saída de latente com divisão em dois estágios (SaveLatent/LoadLatent) | `cf_wan.py:259-269` | Procedência do latente só no grafo, sem versão |
| Versão de capability (`cap.version`) entra no hash | `cf_dag.py:311` | Já cobre "qual versão produziu" |

### P3 Cache parcial

| O que existe | Onde | Lacuna |
|---|---|---|
| Recalcular só descendentes de nó alterado (`descendants`, `force`) | `cf_dag.py:278` (`descendants`), `cf_dag.py:394` (`force`) | Pronto para o DAG; é o que o contrato reaproveita |
| `each` com cache por item (uma entrada por item de lista) | `cf_dag.py:1-20` (docstring) | Pronto para P4 por tomada (trocar um item recomputa só ele) |
| Cache de estágio do vendor (`digest` + arquivo `.key` ao lado) | `vendor/content_factory/engine/factory/core/cache.py:9-27` (`digest`, `fresh`, `mark`) | Já faz "cache por saída" |
| Quadros reaproveitados por `fresh(raw[i], key)` | `vendor/content_factory/engine/factory/stages/frames.py:73-82` | Cache por cena (quadro) já existe |
| Transições reaproveitadas | `vendor/content_factory/engine/factory/stages/transitions.py:11-25` | Idem, por par |
| Render **sem cache**: `render.py` chama `remotion` para o episódio inteiro | `vendor/content_factory/engine/factory/stages/render.py:76-98` (grep não achou `fresh`/`digest` em `render.py`) | Lacuna para P4: trocar uma tomada re-renderiza o todo |

### P4 Render por tomada / timeline

| O que existe | Onde | Lacuna |
|---|---|---|
| Montagem de sequência com `filter_complex` concat (não é o demuxer) | `cf_finish.py:171-222` (`video_sequence`), linha 209 `concat=n=..` | Remonta tudo a cada chamada; sem cache por clipe |
| Animatic: concat demuxer com duração fixa por imagem | `cf_storyboard.py:65-85` (`animatic`) | Já usa o demuxer do ffmpeg, mas só slideshow silencioso |
| Verificação de emenda de loop | `cf_loop.py:35` (`seam`), `cf_capabilities.py:282` (`run_loop_check`) | Qualidade, não montagem |
| Operação de juntar vídeos no DAG | `cf_capabilities.py:275` (`run_video_join`) | Sem trilhas separadas |
| Timeline do vendor: `timeline.json` (duração e beats) | `vendor/.../stages/qa.py:152`; `vendor/.../render/src/Root.tsx:14-25` (`calculateMetadata` = duração × fps) | Uma composição por episódio, não por tomada |
| Trilha de voz separada (TTS/alinhamento por beat) | `vendor/.../VENDORED.md` (Kokoro + faster-whisper); `vendor/.../stages/__init__.py:15` (`ORDER`) | Áudio separado existe; a mixagem final é no render inteiro |

Conclusão de (a): P3 e a base de P1/P2 já existem em `cf_dag.py`. O que falta de verdade é P4: render sem cache por tomada e montagem sem trilhas.

---

## (b) Candidatos externos

Todas as licenças e SHAs foram lidas na fonte. "Lido" significa o trecho citado. Quando o texto não foi aberto, está marcado NÃO VERIFICADO.

| Candidato | URL | SHA (HEAD) | Arquivo / função lido | Licença (SPDX) | Problema | Modo de reuso | Custo de integração (estimativa) | Teste que prova o ganho no ClonField |
|---|---|---|---|---|---|---|---|---|
| Scenario skills (método) | https://github.com/scenario-labs/skills | 3c4d18cd0be2e5280a5accebfeef9ddc98b9a15b | `skills/scenario-asset-analysis/SKILL.md`, `scenario-workflows/SKILL.md`, `scenario-consistency/SKILL.md`, `scenario-refine-loop/SKILL.md`: frontmatter e primeiros ~1,8 KB lidos (leitura parcial) | MIT (frontmatter de cada SKILL) | Método apenas, sem código | Só conceito | 1 h (escrever critérios) | Medir: tomar 20 saídas, aplicar rubrica escrita por asset, contar retrabalho com e sem a rubrica (NÃO VERIFICADO no corpo completo) |
| OpenCut (floomhq) | https://github.com/floomhq/opencut | 57dedbc606e17cc2013f2ca5fcbf8cc69266e488 | `src/engine/types.ts:137-145` (`TimelineSegment`: id, type, durationSec); `src/examples/quickstart/timeline.ts`; árvore lida (253 entradas). Não é NLE: é um render Remotion de segmentos por tipo | MIT (LICENSE, © 2026 buildingopen) | Modelo de segmento, não de tracks/clips; depende de Remotion | Só conceito (não vendorizar, depende de Remotion) | 2 h para copiar o modelo de segmento | Entrada: 5 segmentos; trocar o 3º; saída: só o 3º re-renderizado (contagem de frames por segmento) |
| Remotion (composições) | https://github.com/remotion-dev/remotion | 0e4c50cc93265b92eaaa40892c86b19c9fc07a0f | `packages/core/src/sequence.tsx` (lido só os primeiros 2,5 KB: imports; `from`, `durationInFrames` e o deslocamento de frames NÃO VERIFICADOS) | Licença própria (ver condições abaixo) | Restrição comercial e RAM (Chromium) | Já usado pelo vendor (`render/`, `@remotion/*` ^4.0.454) | 0 h (já existe) | Mesmo teste de P4 acima, medindo RAM do Chromium com `--concurrency=1` |
| OpenTimelineIO (padrão) | https://github.com/AcademySoftwareFoundation/OpenTimelineIO | f38b2cb6c9d22b91a82c129d5551d41910a3a1db | LICENSE lido (Apache 2.0). Arquivos do schema listados: `clip.py`, `timeline.py`, `transition.py`, `marker.py`, `effect.py`, `external_reference.py`, `image_sequence_reference.py`, `generator_reference.py`. Código das classes NÃO VERIFICADO | Apache-2.0 | Não renderiza; só modela | Dependência (PyPI `opentimelineio` 0.18.1, Apache 2.0, wheels manylinux x86_64 ~0,85 MB, sem dependência de runtime listada; só extras de dev) | 3 h | RAM mínima, CPU puro | Entrada: timeline JSON de 5 tomadas com trilha de voz; saída: JSON round-trip idêntico e a trilha de áudio extraída por nome |
| FFmpeg concat demuxer (motor barato) | https://ffmpeg.org/ffmpeg-formats.html#concat | n/a (doc) | Doc lida via curl: "All files must have the same streams (same codecs, same time base, etc.)" (linha 880); `inpoint` (linha 920) | LGPL/GPL (ffmpeg) | Exige mesmos codecs; `cf_finish.py` usa filter_complex, não demuxer | Já instalado (`ffmpeg`) | 2 h (usar `-c copy` por tomada já codificada) | Entrada: 5 mp4 de mesmo codec; trocar 1; saída: 4 tomadas com `-c copy`, medir tempo e que as outras 4 não mudam (sha dos segmentos) |
| MoviePy | https://pypi.org/project/moviepy/ (2.2.1) | n/a (PyPI) | `requires_dist` (lido): decorator, imageio, imageio_ffmpeg, numpy, pillow, proglog | MIT | Pesado (imageio_ffmpeg traz binário) | Dependência | 2 h; RAM de frames | Descartado para P4: montagem de tomadas prontas não precisa de MoviePy |
| jutsuhq/content-factory | https://github.com/jutsuhq/content-factory | 1e1ebb59cc8ff251828df9a925e0cfda751f2aa8 | Vendorizado em `vendor/content_factory` (commit `0ea76329`, `VENDORED.md:3`). HEAD atual é mais novo (`1e1ebb59`); diff NÃO VERIFICADO | MIT (LICENSE vendorizado) | Snapshot antigo | Já vendorizado | 2 h para atualizar e rodar 74 testes do upstream | Rodar os 74 testes do upstream no snapshot novo (sem executar agora) |
| short-video-maker (gyoridavid) | https://github.com/gyoridavid/short-video-maker | 9bb9a212ced86caa7e09099c382da1a44d638760 | `src/short-creator/libraries/FFmpeg.ts`: só áudio (`saveNormalizedAudio`, `saveToMp3`); sem função de concat. Render em Remotion (`src/components/videos/*.tsx`) | MIT (© 2025 David Gyori) | Não traz montagem por tomada | Só conceito | 0 h | Descartado |
| MoneyPrinterTurbo (harry0703) | https://github.com/harry0703/MoneyPrinterTurbo | dabfd3f8548d30ed0eea8759decbdead9626e0e6 | `app/services/video.py:488-626` (helpers de caminho do concat e `concat_video_clips_with_ffmpeg`, linha 626), `:976` (`combine_videos`), `:1630` (`generate_video`). Corpo das funções NÃO VERIFICADO; importa MoviePy | MIT (© 2024 Harry) | Montagem com moviepy, sem cache por tomada | Só conceito | 0 h | Descartado para P4 |

Condições da licença Remotion (lidas em `LICENSE.md`, versão do HEAD):
- Licença gratuita: indivíduos; organizações com-fins-lucrativos com até 3 funcionários; sem fins lucrativos; quem está avaliando sem uso comercial.
- Permitido: uso comercial ou não comercial para criar vídeos e imagens e modificar.
- Proibido: copiar ou modificar o código para vender, alugar, licenciar ou sublicenciar um derivado.
- Fora da licença gratuita: exige Company License (pago).
- Aviso no topo: "In Remotion 5.0, the license will slightly change". Verificar o texto da 5.0 antes de comercializar.
- Consequência para o ClonField: o vendor já usa Remotion. O ClonField é um projeto de uso próprio, mas o dono deve decidir se se enquadra na faixa gratuita antes de uso comercial (NÃO VERIFICADO quanto ao enquadramento).

Dados de dependências (PyPI, lidos): OpenTimelineIO 0.18.1 (Apache-2.0), MoviePy 2.2.1 (MIT).

---

## (c) Recomendação por problema

- **P1 Referências imutáveis.** Usar o que já existe (`cf_dag.node_hash`/`store`) e implementar o `AssetRef.v1` do contrato (`docs/V9_ASSET_GRAPH_CONTRACT.md`). Nenhuma fonte externa de código serve; o Scenario (MIT) dá só o vocabulário de identidade (consistência). Descartar: sistemas de blob ou DAG externos (dependência nova sem ganho).
- **P2 Versões e procedência.** Usar o run record de `cf_dag.py:370` e acrescentar `parents`/`producer` do contrato. OpenTimelineIO serve só como formato de troca se o dono quiser exportar; não é necessário para P2. Descartar: qualquer gerenciador de versão de mídia (a lógica é pequena e já é do projeto).
- **P3 Cache parcial.** Já resolvido pelo DAG (`cf_dag.py:278,394`) e pelo cache do vendor (`core/cache.py`). Não trazer código novo. Teste de aceite: trocar uma entrada e contar nós recalculados.
- **P4 Render por tomada.** Maior lacuna. Recomendação: (1) cache por tomada no vendor, reaproveitando `digest`/`fresh`/`mark` (`core/cache.py`) em `stages/render.py` (hoje sem cache), com um `timeline.json` por tomada; (2) para a montagem final, ffmpeg concat demuxer com `-c copy` quando os codecs batem (é o motor barato); (3) OpenTimelineIO só se for preciso exportar/importar timeline; (4) descartar OpenCut e MoneyPrinterTurbo como fonte de código (conceito apenas).
- **Teste de aceite P4** (concreto): entrada, 5 tomadas (mp4, mesmo codec, 1080x1920, 30 fps) mais uma trilha de voz; trocar a tomada 3; saída: só a tomada 3 re-renderizada (contagem de chamadas ao render), montagem final com `-c copy`, e sha256 das tomadas 1, 2, 4 e 5 iguais. Medida: tempo de remontagem e RAM pico do Chromium com `CF_RENDER_CONCURRENCY=1`.

RAM: o ambiente tem 3,7 GB; no momento da consulta `free -m` mostrava 3,2 GB em uso. Nenhuma fonte acima deve ser testada localmente com render; isso vai para o Colab T4.

---

## (d) Fora da busca

- **Acervo de milhares de repositórios:** NÃO ENCONTRADO. Não está no disco (busca de nomes `*acervo*`, `*repos*`, `*awesome*`, `*corpus*` em `/home/lze`; só `~/.local/share/kilo/repos` e `~/.local/share/opencode/repos`, ambos vazios, 0 entradas). Não está na conta GitHub: `gh repo list` retornou 38 repositórios, todos pessoais (ex.: `Vit0lze/clonfield-studio`, `Vit0lze/research-lab`), nenhum acervo com milhares de entradas.
- **Fontes não reabertas nesta tarefa (das 93 citadas no contexto do projeto):** só as 15 de `docs/sources/INDEX.md` foram reconferidas pelo índice local (V9-SRC-001 a 015); nenhuma foi reaberta na fonte. Os 15 não servem a P3/P4 (áudio, agente, QA de vídeo). A única ligação com P1 é V9-SRC-005 (token-pooling, busca/índice, licença NÃO VERIFICADO, bloqueio P&D). V9-SRC-008 (dvlt, Asset Graph) está BLOQUEADO_LICENÇA e BLOQUEADO_HARDWARE. Não há candidato aprovado para P4.
- **Não verificado nesta tarefa:** corpo completo das quatro SKILL.md (só início lido); `sequence.tsx` além dos imports; classes do schema OTIO; corpo das funções do MoneyPrinterTurbo e do short-video-maker; diff entre o snapshot vendorizado e o HEAD do jutsuhq; `stages/render.py` além da linha 98.

## Falhas de leitura

- WebFetch recusou `raw.githubusercontent.com`, `api.github.com` e `ffmpeg.org` ("Unable to verify if domain ... is safe to fetch"). Os conteúdos foram lidos via curl (stdout).
- `https://api.github.com/repos/floomhq/opencut/git/trees/HEAD?recursive=1` falhou no primeiro teste por causa do glob do zsh (URL sem aspas); o segundo teste com aspas funcionou.
- Nenhuma página de conteúdo falhou de fato depois disso.
