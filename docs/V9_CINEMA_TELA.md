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

---

# V9-P1-CINEMA-004 — aceite no preview da Vercel e «Vigília» sonorizado pela tela

## Aceite remoto (preview de `beff82f`, Chrome, engine local exposta por `cf_engine.py --share`)
O dono entrou com a senha da sessão; daí em diante tudo pela tela do preview.
| Passo | Visto na tela |
|---|---|
| Cinema (menu) → «A última luz» | revisão 2, s04 v1, sem exportações |
| s04 v1 → v2 | «Editando revisão 3 · s04: tomada v1 → v2» |
| Exportar A e B (cache vazio) | A refez tudo (38,9 s); B refez música/efeitos/mix, 11 do cache; imagem idêntica, −15,9/−15,9 LUFS |
| Recarregar | «Editando revisão 3» e «Assistindo: exportação das 10:43 · revisão 3 · s04 v2»; o filme toca (avançou 2,4 s) |
| Cópia de teste (`p_05f71eb7523b`, criada no servidor) → Exportar A e B | revisão 1, tudo do cache |
| s05 4 → 5 s | aviso «Exportação anterior: a timeline mudou depois deste render (revisão 1 → 2)» |
| tomada de s05 ilegível no servidor → Exportar A e B | «falhou · ffmpeg falhou: … Permission denied»; o player continua na revisão 1 |
| Recarregar | falha e par concluído listados; A e B da revisão 1 tocam |
| tomada restaurada → Exportar A e B | revisão 2 concluída (refez s05, junção, trilhas, mix); aviso some |

Achados no preview, corrigidos depois: um «null» escrito abaixo da linha «Assistindo» (o `append` do DOM escreve `null`), e s05 marcado «do cache» depois de mudar só a duração (a tela comparava só a tomada; agora cada exportação guarda a especificação de cada plano).
O túnel foi fechado e o arquivo com a senha apagado ao fim.

## Som pela tela
Painel «Som · <corte>» acima dos planos:
- **Pistas:** Voz (igual em todos os cortes), Música e Efeitos (só no corte escolhido).
- **Campos de cada som:** «entra em» (s), «encaixar no início de… Plano N», ganho (dB), duração (vazio = o arquivo inteiro), fade de entrada e de saída, um player e o botão «tirar».
- **«Adicionar som»:** lista os ativos de áudio, cada um com player e destino («→ Voz / → Música / → Efeitos»).
- **«Novo corte a partir deste»:** copia música, efeitos e mix e passa a ser o corte escolhido.
- **Gravação:** cada mudança é salva na hora e gera revisão; o histórico diz o que mudou («efeitos: som 2: entrada 9,04 s → 9,25 s»).

API: `POST /cinema/projects/{id}/audio`, `POST …/audio/{track}/{index}` (entrada, ganho, duração, fades, remover), `POST …/cuts`.

## «Vigília» sonorizado (engine local, navegador do app; cada passo é um clique ou digitação na tela)
| Passo | Revisão |
|---|---|
| Mar → Efeitos; ganho −8 dB; fade de entrada 1,5 s. Atravessa os cortes de 6,0 s e 9,04 s | 8–10 |
| Relé do poste → Efeitos; «encaixar no início do Plano 3» (9,04 s) → digitado 9,25 s (a lâmpada sobe de brilho nos primeiros 0,5 s da tomada); ganho −4 dB | 11–14 |
| Voz 5 («Mas toda tarde, eu ainda olho para o mar.») → Voz, 6,5 s, sobre o farol no píer | 15–16 |
| Recarregar: os três sons voltam com entrada, ganho e fade | 16 |
| Exportar (só o som mudou) | refez trilha voz, trilha efeitos e mix; **3 planos + junção da imagem do cache** (2,5 s) |
| «Novo corte a partir deste» → «Com música»; música → Música: fade 2 s, dura 12 s, saída 2,5 s; música +6 dB e mar −14 dB **só neste corte** | 17–23 |
| Exportar A e B | A: nada refeito; B: refez música, efeitos e mix; voz e imagem do cache; imagem idêntica; −16,2 / −16,0 LUFS |

Conferido nos arquivos exportados:
- **Relé:** entra aos 9,254 s.
- **Mar:** sem buraco nos cortes de imagem.
- **Voz:** silêncio até 6,5 s.
- **Música:** as notas do acorde (73, 110 e 175 Hz) ficam 24 a 31 dB acima do entorno em B e 6 a 10 dB em A, que é só ruído; a pista de música de A está vazia.

Evidência: `docs/evidence/V9-P1-CINEMA-004/`.

## O que a sonorização mostrou que falta
| Achado | Estado |
|---|---|
| Os níveis da mix por pista (música −12 dB e efeitos −4 dB por padrão) não aparecem na tela; na primeira tentativa, a música de B ficou enterrada sob o mar | feito em CINEMA-005 (mix do corte na tela) |
| O histórico usava nomes crus («gain_db») | corrigido: «ganho −8 dB → −14 dB» |
| A entrada aparecia arredondada (9,3 s em vez de 9,25 s) | corrigido |
| Sem forma de onda: o encaixe no plano ajuda, mas a sincronia fina ainda é por número | pendente |
| O som adicionado entra em 0 s; seria melhor entrar no plano selecionado | pendente |


# V9-P1-CINEMA-005 — a mix de cada corte na tela

## O que mudou
- **Ganho da pista** no cabeçalho de Voz, Música e Efeitos, por corte (−30 a +12 dB).
- **Ganho do clipe junto do da pista:** cada som mostra «clipe +6 dB + pista −6 dB = 0 dB».
- **Recuo da música sob a voz** (sidechain da voz sobre a música), na pista de música: ligado/desligado, intensidade (razão), limiar (dBFS da voz), ataque e retorno (ms), e «Recuo padrão» para voltar.
- **Projeto antigo:** um corte com `mix: {}` mostra os valores que a engine sempre aplicou (voz 0, música −12, efeitos −4 dB; recuo 6:1, −30,5 dBFS, 80 ms, 900 ms) com a marca «padrão da engine»; o que foi mexido diz «ajustado».
- **Som preservado:** só o que difere do padrão é gravado (`cf_cinema.mix_stored`). Digitar o próprio padrão não cria revisão; a assinatura e a chave da mix de um projeto antigo não mudam. Com o recuo desligado, os ajustes dele ficam guardados (religar devolve) mas saem da chave (`mix_heard`).
- **Exportar com mais de dois cortes:** «Exportar A/B com…» exporta este corte (A) contra outro (B); o botão do conjunto diz «Exportar os N cortes».
- **API:** `POST /cinema/projects/{id}/mix` com `{"mix": {"music": -6, "duck_ratio": 12, …}, "cut": "…"}` (`null` volta ao padrão). O projeto público traz `mix_values`, `mix_changed`, `mix_default` e `mix_range`.

## Prova pela tela (engine local, navegador do app, «Vigília»)
| Passo | Resultado |
|---|---|
| «Novo corte a partir deste» sobre «Com música» → «Música recua» | revisão 24; a mesma música, mar e relé |
| Só o ganho da pista de música: −12 → −8 dB | revisão 25; histórico «pista de música −12 dB → −8 dB» |
| Recarregar | o campo volta −8, marcado «ajustado»; recuo «padrão da engine» |
| Exportar este corte | **refez só a mix**; 3 planos, junção da imagem e as três trilhas do cache (7 passos); player «revisão 25» |
| «Com música» (mix `{}`, de antes desta tela) exportado de novo | nada refeito, 8 do cache; o áudio da mix tem o mesmo MD5 (`d22c34c7…`) do export da rodada anterior |

## Direção: a música entra e recua sob a fala
- **O que o padrão fazia:** media-se com `tests/demo/cinema_mix_measure.py`, que renderiza cada som sozinho com os construtores da engine. A música só cedia no começo da fala (−15 dB em 6,5–7,25 s), voltava no meio da frase, na pausa depois de «Mas toda tarde,», e chegava ao pico em 9,25–10 s, em cima do relé.
- **O ajuste em «Música recua»:** pista −6 dB (a música se ouve entrar antes da fala), recuo 12:1, limiar −40 dBFS (a pausa da frase não solta a música), ataque 40 ms e retorno 1,5 s (a música segue baixa quando o poste acende e volta enquanto a luz fica).
- **«Música contínua»:** cópia dela com o recuo desligado. Mar, relé, voz e música são os mesmos; as trilhas têm o mesmo MD5 nos dois.

| Medida (antes da normalização; o 2º passo do loudnorm é linear) | Música recua | Música contínua | Com música (padrão) |
|---|---|---|---|
| Música antes da fala, 4,5–6,0 s | −32,9 dBFS | −32,9 | −38,9 |
| Música sob a fala | −44,5 (11,6 dB abaixo de antes; 19 dB abaixo de sem recuo) | −25,4 (sobe 7,5 dB, o pad cresce) | −38,8 |
| Música 0,5 s depois da fala | −40,4 | −29,0 | −35,4 |
| Relé, janela 9,25–9,75 s, sobre todo o resto | +8,2 dB | +0,6 dB | +6,2 dB |
| Relé na faixa 1–6 kHz sobre o resto | +28,9 dB | +29,0 dB | +28,7 dB |

- **Envelope da música em «Música recua»:** −33 dBFS antes da fala, −61 a −41 sob a fala, −40 a 9,25 s, −31 a 9,75 s, −28 a 10–10,25 s; depois o fade de saída.
- **Em «Música contínua»:** sobe até −22,5 a 8,25 s, no meio da frase.
- **O relé:** legível nos dois na própria faixa (o pad é grave); em «Música recua» também ganha espaço no volume total.

Export A/B pela tela: as duas exportações refizeram só a mix. A imagem é idêntica (mesmo MD5 do vídeo) e o volume é −16,0 / −15,9 LUFS. São 290 quadros e 12,083 s, com 4 trilhas de áudio (mix, voz, musica, efeitos).
A trilha «musica» do MP4 é a da pista antes da mix (sem o recuo), igual nos dois; a diferença está só na trilha «mix».

Evidência: `docs/evidence/V9-P1-CINEMA-005/`. Contém `so-pista-musica.render.json` (`rendered: ["mix"]`), `ab-*.render.json`, `ab-recua-continua.ab.json`, `projeto-antigo-com-musica.render.json` (`rendered: []`), `mix-medida.json` e o projeto.

Teste: `tests/test_cinema.py::test_the_mix_of_a_cut_is_shown_edited_and_a_mix_only_change_rerenders_only_the_mix`. Ele cobre o padrão sem revisão, a recusa de valores fora da faixa, a cópia intacta igual ao original, a mudança só da pista refazendo só a mix, o recuo mudando o filme entregue e o retorno ao padrão voltando à assinatura original.

## Pendente
- **Decisão do dono** depois de ouvir «Música recua» × «Música contínua».
- **Próxima melhoria:** inserir um som na posição do cursor.
- **Depois:** a forma de onda.
- Faixa do relé: a medida de 1–6 kHz é um corte retangular por FFT, não um modelo de mascaramento.
- O true peak medido no MP4 ficou em −1,3/−1,4 dBTP, contra −1,5 no WAV mestre: a codificação AAC sobe o pico; a margem não foi mexida nesta rodada.
