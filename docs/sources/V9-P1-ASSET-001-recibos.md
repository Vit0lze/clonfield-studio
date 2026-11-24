# V9-P1-ASSET-001 — recibos das fontes efetivamente usadas

Data: 2026-11-24. Pesquisa completa (só leitura) em `docs/sources/research/V9-P1-ASSET-CINEMA-FONTES.md`.

## Usadas no código desta entrega
Todas internas ao ClonField. **Nenhum código externo foi copiado, vendorizado ou adicionado como dependência.**

| Fonte | Arquivo / função | Como foi usada | Licença |
|---|---|---|---|
| ClonField `cf_dag.py` | `artifact_hash` / `file_sha256` (l. 43–62), `node_hash` (l. 311), `execute` → `recomputed`/`cached` (l. 544–545) | O cache parcial **não foi reescrito**: o Asset Graph só entrega o caminho do blob ao `resolve_media`; o hash de conteúdo já faz trocar v1→v2 recomputar só os descendentes | do projeto |
| ClonField `cf_cast.py` | `load`, `image_path` | A foto do personagem é publicada como `kind: character` | do projeto |
| ClonField `cf_jobs.py` | `KINDS` | Mesma tabela de extensão → tipo de mídia | do projeto |
| ClonField `cf_api.py` | `sign`, rota `/files`, `public_job` | URL assinada dos blobs; `asset_versions` exposto como `plan` | do projeto |
| ClonField `portal/js/views/app.js` | `actionMenu`, `SEND_TO` | «Usar em» reaproveitado e exportado para a tela Ativos (sem duplicar a lista) | do projeto |

## Avaliadas e não usadas nesta entrega (motivo)
| Fonte | Revisão lida | Decisão |
|---|---|---|
| Scenario skills (MIT) — asset-analysis, workflows, consistency, refine-loop | `main` (SHA na pesquisa) | Método, sem código executável. `inspect_artifact`/`quality_gate` já existem; nada novo para referências e versões. Corpo das SKILL.md lido parcialmente |
| `vendor/content_factory/engine/factory/core/cache.py` (MIT, já vendorizado) | snapshot `0ea76329` | `digest`/`fresh`/`mark` servem para **render por tomada** no Cinema (P4), não para esta entrega |
| OpenTimelineIO (Apache-2.0, PyPI 0.18.1) | ver pesquisa | Candidato para **exportar** a timeline do Cinema; não entra até haver timeline |
| Remotion | ver pesquisa | Licença própria: gratuita para pessoa física e empresas de até 3 funcionários; acima disso, licença paga. **Decisão de enquadramento é do dono** antes de qualquer uso |
| OpenCut, MoneyPrinterTurbo, short-video-maker | ver pesquisa | Só conceito (outra pilha ou montagem simples); nada a trazer |
| ffmpeg concat demuxer | documentação oficial | Motor de montagem barato para o Cinema (já é dependência do Studio) |

## Fora da busca
- O «acervo de milhares de repositórios» citado pelo dono **não foi encontrado**: nada no disco (`~`, `~/Downloads`, `~/Documents`, `~/Projects`) e a conta GitHub tem 40 repositórios próprios e 12 estrelas. A busca usou as 93 fontes, os 15 aprovados e o `vendor/`.
- Das 93 fontes, só as listadas acima e na pesquisa foram reabertas; as demais continuam no estado da matriz.
