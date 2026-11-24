# Cinema na tela — «A última luz» no Studio (V9-P1-CINEMA-002)

Base: `3ba5df6` (Cinema alfa pela API). Tela: `portal/js/views/cinema.js`, rota `#/cinema`, item «Cinema» no menu.

## O que a tela faz
| Ação pedida | Onde | Gesto |
|---|---|---|
| Abrir o projeto salvo | `#/cinema` → cartão do projeto | lista de projetos salvos (`GET /cinema/projects`) |
| Ver os planos na ordem | régua de tempo + lista de planos | cada plano com miniatura **no enquadramento do plano** (o `crop`), tempo, versão e a fala que cai sobre ele |
| Trocar a versão do plano 4 | cartão do s04 → «Tomadas» | as versões do mesmo ativo lado a lado (v1, v2) com a origem; clicar troca. Só versões **do mesmo ativo** são aceitas |
| Alternar música × mar | seletor «O mar toma conta / Música até o fim» | as pistas de áudio mudam na régua; a opacidade do clipe segue o ganho (o mar a −13 dB fica apagado, a −4 dB fica aceso) |
| Exportar | «Exportar este corte» ou «Exportar A e B» | job de CPU; barra de progresso com o passo atual |
| Ver o que foi refeito e o que veio do cache | painel «Última exportação» + marcas nos planos | por corte: «Refeito» (laranja) e «Do cache» (verde); o bloco do plano na régua ganha a mesma cor |
| Sessão A/B | painel «Sessão A/B» | um player só; A e B trocam **no mesmo instante** do filme; atalhos «Transição · «Ninguém mais sobe a escada.»» e «Preto final · 8,0 s»; «Ficar com este corte» grava a escolha (o outro continua salvo) |

A última exportação reaparece ao reabrir o projeto (`last_export`). Cada exportação tem pasta própria (`outputs/cinema_<job>`), então pares A/B antigos não são sobrescritos.

## Contrato (acréscimos ao `docs/V9_CINEMA_ALFA.md`)
`CinemaProject.v1` em `<base>/cinema/projects/p_<12hex>.json`: `timeline` (imagem + voz), `cuts` {id: {label, note, music, sfx, mix}}, `cut` (escolhido), `history` (trocas de tomada), `last_export`.
Os cortes **só** mudam música, efeitos e mix: imagem e voz são as mesmas por construção, por isso a imagem de A e B é idêntica.
`note` em plano ou clipe de áudio (a fala) não entra na chave de cache.

| Rota | Faz |
|---|---|
| `GET/POST /cinema/projects` | lista / cria (valida todos os cortes) |
| `GET /cinema/projects/{id}` | projeto + planos com tempos e versões do ativo (URLs assinadas) + pistas por corte |
| `POST /cinema/projects/{id}/shots/{shot}` `{"version": "v_…"}` | troca a tomada (só versão do mesmo ativo); registra no histórico |
| `POST /cinema/projects/{id}/cut` `{"cut": "mar"}` | escolhe o corte |
| `POST /cinema/projects/{id}/export` `{"cuts": ["mar","musica"]}` | job de CPU; com 2+ cortes grava `<slug>.ab.json` (`picture_identical`: mesma junção e mesmo MD5 do vídeo; `loudness` de cada um e `loudness_spread_lu`) |

## Prova pela tela (navegador real, engine local, cache de render vazio no início)
| Passo | Corte A «O mar toma conta» | Corte B «Música até o fim» |
|---|---|---|
| 1. Exportar A e B (s04 = v1) | refez tudo: 9 planos, junção, 3 trilhas, mix (35,5 s) | refez só música, efeitos e mix; 9 planos, junção e voz do cache (13,1 s) |
| 2. Trocar s04 para v2 na tela e exportar A e B | **refez s04 e a junção**; 8 planos, trilhas e mix do cache (13,0 s) | **nada refeito** (6,5 s) |
| A/B | imagem idêntica (mesma junção, MD5 do vídeo igual), −15,9 e −15,9 LUFS (diferença 0 LU) | |

Os segmentos feitos pela tela são **idênticos byte a byte** aos da prova pela API (`V9-P1-CINEMA-001`). Evidência: `docs/evidence/V9-P1-CINEMA-002/`.
Também conferido: troca A↔B mantém o instante (26,1 s → 27,5 s tocando); «Ficar com este corte» grava e volta; 375 px sem rolagem lateral.

## Repertório dos cinco projetos estudados (ideia, não código)
| Projeto | Gesto | Onde ajudou aqui |
|---|---|---|
| ComfyArt (MIT) | projeto com versões salvas (snapshots) | cada corte é uma variante salva do mesmo projeto; trocar de corte não perde o outro; histórico das trocas de tomada |
| Creativefield (GPL-3.0, só ideia) | revisão de uma tomada comparando alternativas | v1 e v2 lado a lado no próprio cartão do plano, com a origem (5B Q6 × A14B Q4) |
| Imagination Studio (Apache-2.0) | roteiro → planos → versões → montagem | a fala aparece no plano em que cai; o roteiro se lê descendo a lista |
| ComfyUI-Panorama-Stickers (MIT) | pistas de keyframe por camada | voz, música e efeitos como pistas sob a mesma régua; clipes que se sobrepõem descem de linha |
| Paint a Plate (Apache-2.0) | «só o que foi editado muda; o resto é a placa original» | depois de exportar, só o que mudou fica laranja; o resto é verde (cache) |

## Pendente
- Assistir aos dois cortes com som e decidir (o projeto está em «O mar toma conta», o corte que eu assino; B está salvo e exportado).
- Sem edição de tempo/duração nem reordenação de planos na tela (a timeline continua editável pela API).
- Sem cancelar a exportação pela tela (a fila geral cancela).
- A14B e SeedVR2 na T4 seguem pendentes.
