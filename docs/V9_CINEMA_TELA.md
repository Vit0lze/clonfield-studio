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

---

# V9-P1-CINEMA-003 — versões visíveis, falha que não apaga o par bom, e um filme do zero

## O que mudou na tela
- **Qual versão estou editando:** «Editando revisão N · salvo às HH:MM · última mudança». Toda edição é salva na hora e ganha revisão; o histórico diz o que mudou.
- **Qual versão estou assistindo:** o player diz «Assistindo: exportação das HH:MM · revisão N · s04 v2». Se a timeline mudou depois daquele render (assinatura do corte diferente), aparece **«Exportação anterior: a timeline mudou depois deste render (revisão N → M; s04 mudou)»** até sair um corte novo.
- **O que cada exportação reaproveitou:** lista «Exportações» (até 6), cada uma com revisão, estado e, por corte, «refez …» e «N do cache». A que está no player é marcada.
- **Falha:** uma exportação que falha entra no histórico com o motivo; o player continua no **último par concluído** (`last_good`), que não é sobrescrito porque cada exportação tem pasta própria.
- **Do zero:** «Novo projeto» na lista; projeto vazio com um corte mudo; «Adicionar planos» abre os Ativos (imagem e vídeo) e põe no fim com a versão atual fixada; em cada plano, duração (0,5–60 s; tomada mais curta que o plano repete), ↑ ↓ e tirar.
- A engine local responde `POST /clonfield/connect` como o Colab, e `python cf_engine.py --share` abre um túnel gradio.live, único destino que o CSP do Studio hospedado aceita.

## Segundo filme, «Vigília», montado pela tela (engine local, navegador do app)
Projeto vazio → três ativos (farol no píer, poste, farol no azul) → s03 subiu duas vezes → s03 de 2,06 s para 6 s (repete) → página recarregada (ordem e duração mantidas, revisão 7) → «Exportar». Resultado: 290 quadros, 12,08 s, ordem s03 · s01 · s02; render em 4,7 s. Evidência: `docs/evidence/V9-P1-CINEMA-003/`.

## O que essa montagem mostrou que a interface precisa
| Achado | Estado |
|---|---|
| O filme sai **mudo**: não há como pôr voz, música ou efeito pela tela | próximo passo (pistas de áudio editáveis a partir dos Ativos de áudio) |
| Um projeto novo sem som quebrava o `loudnorm` (−inf) e gravava −inf no JSON | corrigido e testado |
| Depois de reordenar, «s03» aparecia primeiro sem dizer a posição | corrigido: «Plano 1 · s03» |
| O histórico escrevia «2.06 s» | corrigido: vírgula |
| A duração padrão é a da tomada (3,04 s), número estranho de digitar | a decidir: arredondar para 0,1 s ao adicionar |
| Não há transição, fade nem enquadramento (crop) pela tela | pendente |
| Não há desfazer; o histórico existe mas não volta | pendente |
| O seletor de ativos desce quando a régua aparece (primeiro plano) | pendente, pequeno |
| O Studio chama de «Biblioteca» os modelos; os planos vêm de «Ativos» | nomes a alinhar |

## Preview da Vercel
`e4bc594` gerou o preview (`clonfield-studio-portal-git-v9-integration-vitorgroup.vercel.app`, status Vercel «success»), e a engine com túnel ficou de pé. **O percurso no preview não foi feito:** o preview exige SSO da Vercel e a conta logada no Chrome recebe «You Need Access» do time `vitorgroup`. Não pedi acesso em nome do dono. Pendente: acesso ao preview (ou um link de bypass de proteção) para repetir o percurso de «A última luz» e a falha provocada lá.
