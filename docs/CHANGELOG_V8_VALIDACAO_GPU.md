# ClonField Studio — changelog detalhado da validação na GPU real (15 a 23/11/2026)

Continuação de `docs/CHANGELOG_V8.md` (que termina em `6964d0a`, antes de existir qualquer teste na GPU).
Tudo abaixo está na `main` do GitHub até `201a9e1`, **exceto** o item «Pendente no stash» no fim.

**Janela:** `6964d0a..201a9e1` — 27 commits, 31 arquivos, +1395 / −39 linhas. 5 arquivos novos: `cf_worker.py`, `docs/VALIDACAO_GPU.md`, `tests/test_llm_release.py`, `tests/test_tiers_extra.py`, `tests/test_worker_restart.py`.
**Máquina de teste remota:** Colab, Tesla T4 (15 GB de VRAM), **12,7 GB de RAM**. **Máquina local:** CPU, 3,7 GB de RAM (a suíte completa a derrubou 3 vezes; ver «Limites»).
**Estados:** `TESTADO GPU` = rodou na T4 e o arquivo foi baixado e conferido. `TESTADO CPU` = teste local. `CÓDIGO ESCRITO` = só compilado/sem prova de execução.

## 1. Resumo em dez linhas
1. O Studio foi validado de ponta a ponta na T4: imagem, ampliação, vídeo (Wan 5B e A14B), receitas de vídeo e personagem, Fábrica de vídeo e o agente local.
2. O que mais exigiu trabalho foi a **memória**: 12,7 GB de RAM não comportam dois modelos grandes em sequência no mesmo processo do ComfyUI.
3. O LLM de 9B passou a **descarregar durante jobs de GPU** e a voltar depois; o worker do ComfyUI passou a ser **reiniciado pelo próprio Studio**.
4. O Wan A14B só roda na T4 em **Q4_K_S, um especialista por prompt**; o Q6_K (12 GB por especialista) não cabe e é recusado abaixo de 24 GB de RAM.
5. O agente passou a montar a cadeia imagem → ampliar → vídeo, mas **o conteúdo nem sempre bate com o pedido** (pedi um farol com ondas, saiu um poste de rua).
6. Seis defeitos do código só apareceram com GPU real e estão corrigidos (seção 3).
7. Quatro hipóteses minhas estavam erradas ou não resolveram (seção 4); estão registradas para ninguém repetir.
8. Há itens **não medidos** e limites de qualidade (seção 6).
9. A suíte local completa deu 419 passed, 0 falhas **antes** das últimas mudanças de memória; depois só rodaram arquivos isolados.
10. O novo prompt do agente (seção 7) está **fora do GitHub**, guardado num stash local, esperando a linha de base.

## 2. Linha do tempo por commit

### A. LLM local (llama-server) na GPU
| Commit | Data | O que mudou | Estado |
|---|---|---|---|
| `0c741e9` | 15/11 | `llama-server` escolhe uma porta livre (a 8080 é do próprio Colab) e publica a URL escolhida; log de saída maior | TESTADO GPU |
| `d6a72b7` | 15/11 | `LD_LIBRARY_PATH` inclui todas as pastas com `.so` (a `libcudart`/`libcublas` desempacotam numa pasta irmã, sem isso caía na CPU); log vai para arquivo; validador reescrito (token por `/clonfield/connect`, polling do agente, apps de CPU) | TESTADO GPU |
| `5a6169a` | 20/11 | trava de CUDA lê o log inteiro e, ao recusar, mostra as linhas de backend e as libs não resolvidas | substituído pelo `3874245` |
| `3874245` | 20/11 | **a trava passou a perguntar ao próprio build** (`llama-server --list-devices`) e a medir o crescimento de VRAM, em vez de procurar uma linha de log que este build não escreve | TESTADO GPU (`CUDA0: Tesla T4`) |
| `2b43e7f` | 20/11 | o diagnóstico de CUDA resolve as bibliotecas com o `LD_LIBRARY_PATH` do próprio servidor | TESTADO CPU |
| `4b55197` | 20/11 | **o LLM descarrega durante jobs de GPU**: `llama-server --sleep-idle-seconds` (30 s, `CLONFIELD_LLM_SLEEP=0` desliga); o job de GPU espera o servidor dormir (< 6 s medidos) e falha com mensagem clara se não dormir; o modelo de texto é recusado enquanto o job roda; o turno do agente termina com resposta fixa ao iniciar um job de GPU | TESTADO GPU |
| `0d75d05` | 22/11 | o ComfyUI descarrega seus modelos **logo antes** de o LLM acordar (o 9B morreu ao acordar ao lado dos modelos do Wan na VRAM) | TESTADO GPU (acorda em 37–48 s) |

### B. API e jobs
| Commit | Data | O que mudou | Estado |
|---|---|---|---|
| `bbeb8ae` | 15/11 | `POST /jobs` preenche campos omitidos (inclusive os `hidden`) com o default do formulário; antes um cliente de API recebia `KeyError: 'mode'` | TESTADO API REAL |
| `a38526f` | 22/11 | a validação de grafo recusa um parâmetro **obrigatório vazio** (o vídeo do agente não tinha `prompt` e falhou depois de 4,5 min de GPU) | TESTADO GPU |
| `60cba8b` | 22/11 | `/system` passa a trazer `worker_rss_gb` (memória residente do ComfyUI) para ver a memória crescer job a job | TESTADO GPU |
| `201a9e1` | 23/11 | o job do agente expõe `plan` (capacidade + parâmetros de cada passo) em `/jobs/{id}`, disponível assim que o job nasce | CÓDIGO ESCRITO (compilado; não medido na T4) |

### C. Vídeo Wan
| Commit | Data | O que mudou | Estado |
|---|---|---|---|
| `d6a72b7` | 15/11 | as receitas de vídeo não juntam mais o modo rápido (só existe no A14B) com o 5B | TESTADO GPU |
| `e45bbd3` | 20/11 | o caso `animate` do validador roda o 5B sem o modo rápido | TESTADO GPU |
| `6789ac2` | 20/11 | catálogo ganha **A14B Q4_K_S** (8,75 GB por especialista) e **Q3_K_S** (6,52 GB), com nomes, tamanhos e hashes tirados da API do Hugging Face | Q4_K_S TESTADO GPU; Q3_K_S não testado |
| `2e78008` | 22/11 | o padrão de «Entre dois quadros» passa a ser o Q4_K_S; o Q6_K é **recusado com menos de 24 GB de RAM** | TESTADO GPU |
| `13e13a5` | 22/11 | **o A14B roda um especialista por prompt**: o de alto ruído salva o latente (`SaveLatent`), o worker é reiniciado, o de baixo ruído carrega o latente (`LoadLatent`) e termina; o `.latent` trafega pelo executor | TESTADO GPU; ciclo do latente provado em ComfyUI real |
| `603b5a9` | 22/11 | a «família» do Wan passa a ser o modelo (`wan:5b-q6`, `wan:a14b-q4`), de modo que trocar de modelo libera o ComfyUI antes | TESTADO GPU |
| `a2b1a9a` | 20/11 | variável `CLONFIELD_COMFY_EXTRA` para passar flags ao ComfyUI sem mudar o padrão dos tiers | TESTADO GPU (as flags testadas não resolveram) |

### D. Memória do worker do ComfyUI
| Commit | Data | O que mudou | Estado |
|---|---|---|---|
| `99ae52e` | 22/11 | **novo módulo `cf_worker.py`**: o Studio guarda (só em memória) o comando, a pasta e o ambiente do worker enquanto ele vive e consegue reiniciá-lo igual; revive um worker morto, reinicia um inchado antes do A14B e entre os dois estágios; só toca o processo que escuta na porta do ComfyUI | TESTADO GPU; 5 testes locais |
| `65eaaae` | 23/11 | antes de **qualquer** job de GPU o worker é reiniciado se passar de 7 GB (`CLONFIELD_WORKER_RESTART_GB`) | CÓDIGO ESCRITO (compilado; validado só pela sequência 5B → A14B, que usa o outro gatilho) |

### E. Agente
| Commit | Data | O que mudou | Estado |
|---|---|---|---|
| `2348f3f` | 22/11 | o turno do agente termina quando a faixa de GPU está ocupada, qualquer que seja o formato devolvido pela ferramenta; uma recusa logo depois de uma ferramenta é lida como «job iniciado» | TESTADO GPU |
| `272dc32` | 22/11 | o prompt do agente ganha um atalho de ids reais (`app.create`, `upscale`, `app.animate`, `app.flf2v`, `removebg`) e o limite sobe de 10 para 14 passos; o validador exige que haja um job | TESTADO GPU |

### F. Fábrica de vídeo
| Commit | Data | O que mudou | Estado |
|---|---|---|---|
| `5c69089` | 20/11 | o provider de transcrição entrega ao `faster-whisper` o áudio já lido (mono, 16 kHz), sem passar pelo PyAV, que no Colab rejeitava `metadata_errors=` | TESTADO GPU |

### G. Validador e documentação
`aa0d882`, `2ae585f`, `1dbe158`, `e466560`: `docs/VALIDACAO_GPU.md` e ajustes do validador (a receita de personagem passa a receber um retrato de personagem, não um farol). `8306318` é o seu commit «Personal changes» (inclui o notebook, `cf_faceswap.py` e a renomeação `prepare_facefusion.py → prepare_ff.py`); **não revisei o conteúdo**.

## 3. Defeitos que só a GPU real revelou (causa → correção)
| # | Sintoma | Causa | Correção |
|---|---|---|---|
| 1 | chat/agente esperava 300 s por resposta | `llama-server` sem `libcudart`/`libcublas` no caminho: caía na CPU | `d6a72b7` |
| 2 | trava de CUDA recusava um servidor que estava na GPU | este build não escreve nada de backend no log (783 bytes) | `3874245` |
| 3 | `KeyError: 'mode'` em `/jobs` | a API não preenchia campos omitidos | `bbeb8ae` |
| 4 | receitas de vídeo falhavam | modo rápido (só A14B) combinado com o 5B | `d6a72b7` |
| 5 | Fábrica falhava em 98 s com `open() got an unexpected keyword argument 'metadata_errors'` | `faster-whisper` chama o PyAV com um argumento que o PyAV do Colab não aceita | `5c69089` |
| 6 | o agente gastava os 10 passos descobrindo capacidades; depois montava vídeo sem prompt; o LLM morria ao acordar | prompt sem atalho; validação sem parâmetro obrigatório; VRAM ocupada pelo Wan | `272dc32`, `a38526f`, `0d75d05` |
| 7 | o worker do ComfyUI morria no A14B e depois do 5B | o processo guarda 6,5–9 GB depois de um job e **não os devolve** com `/free` | `13e13a5`, `603b5a9`, `99ae52e`, `65eaaae` |

## 4. Hipóteses que não resolveram (para não repetir)
- **Procurar o banner de CUDA em todo o log** (`5a6169a`): o log não tem nenhuma linha de backend; o falso alarme continuou.
- **`--fast-disk`** no ComfyUI: o log confirmou `fast_disk=True`, o A14B morreu no mesmo ponto (os GGUF não usam o carregamento por disco, `paths=[]`).
- **`--disable-pinned-memory`**: derrubou o Studio inteiro em vez de só o worker.
- **Rodar o A14B Q6_K em um prompt só**: morreu 4 vezes ao carregar o segundo especialista; o Q4_K_S em um prompt só passou uma vez, num worker recém-criado, e falhou depois de outros jobs.

## 5. Resultados medidos na T4
| Item | Resultado |
|---|---|
| Qwen 2.1 Turbo | 95–344 s (a primeira vez, a frio, é a mais lenta); 768×768 |
| Qwen 2.1 padrão | 284 s |
| Upscale RealESRGAN x4 | 21,6 s (o «4x UltraSharp» que o agente escolheu: 457 s) |
| Melhor de N sementes / Cenários em matriz / Animatic | 409 s / 39 s / 9 s |
| Remover fundo (U²-Net) | 7 s |
| Wan 5B Q6 | 350–478 s por 3 s de vídeo; deixa o worker em 6,5–9 GB |
| Planos em filme / Storyboard em filme | 385 s / 922 s (este inclui 7,2 GB de download) |
| Personagem pronto | 37 min, folha 2700×1084 com 4 vistas |
| Fábrica de vídeo | 1381 s, MP4 1080×1920, 31,8 s, com narração e legenda palavra por palavra |
| Wan A14B Q4_K_S «Imagem em loop» | 361 s; depois de um job 5B: 537 s (worker 8,4 → 4,4 GB) |
| Agente local, cadeia completa | 101 s de planejamento + 907 s de job, vídeo 832×480 |
| LLM acordando depois de um job de GPU | 37 s, 42 s, 48 s |
| Download do A14B Q4_K_S | ~17,5 GB em ~3 min (120–140 MB/s) |

## 6. Qualidade observada (olhando os quadros, sem métrica)
- **Wan 5B** em retrato vertical: identidade preservada, **quase não se mexe** (movimento ~5).
- **A14B Q4_K_S** rápido, mesma imagem e prompt: sorri e muda o peso do corpo, identidade preservada.
- **Agente:** pedi «um farol ao entardecer com as ondas se movendo»; saiu **um poste de rua ao entardecer, sem ondas**.
- **Folha de personagem:** identidade mantida em UMA personagem e UM conjunto; faixas cinza em cada vista.
- **Fábrica:** o QC acusou «MILLIONS OF YEARS» com 17 caracteres (máximo 12).
- **Planos em filme (farol):** pequenos objetos flutuando no céu.

## 7. Pendente
- **Pendente no stash (não está no GitHub):** um prompt novo do agente que manda escrever os prompts de geração em inglês descritivo, separar a cena (imagem) do movimento (vídeo), resolver palavras ambíguas e não perder o movimento citado. Só aplico depois de medir a linha de base do prompt atual, e **essa linha de base ainda não existe**: a tentativa saiu com o LLM fora do ar e as seis leituras vazias não valem como resultado.
- **Não medido:** A14B com 20 passos (o resultado se perdeu quando a GPU foi desligada), Q3_K_S, Q6_K em dois estágios, `run_eval.py --chains` com o Qwen real, `force` com semente fixa, apps com offload, foto real em movimento, outros conjuntos de vistas.
- **Itens nunca iniciados:** cerca de 20 do backlog, e a legenda automática.

## 8. Limites e riscos
- **Suíte local:** 419 passed, 0 falhas rodaram **antes** de `99ae52e`, `65eaaae` e `201a9e1`. Depois só rodaram arquivos isolados (`test_dag`, `test_llm_release`, `test_agent`, `test_worker_restart`). A suíte completa derrubou o PC de 3,7 GB três vezes e não é mais executada ali; fica registrado em memória.
- **`65eaaae` e `201a9e1` foram só compilados**, sem teste dedicado.
- **O reinício do worker** interrompe e recarrega modelos (cerca de 30 s mais o carregamento); o limite de 7 GB é uma escolha minha, calibrada em duas medições.
- **O Colab perdeu sessões** durante os testes (reciclagem do runtime e queda de RAM); o `.env` com link e senha muda a cada subida.

## 9. Variáveis de ambiente novas
`CLONFIELD_LLM_SLEEP` (segundos de ociosidade até o LLM dormir; 0 desliga; padrão 30) · `CLONFIELD_COMFY_EXTRA` (flags extras do ComfyUI) · `CLONFIELD_WORKER_RESTART_GB` (limite para reiniciar o worker; padrão 7).

## 10. Como retomar
1. No Colab: célula 1 (`git pull`), depois 6, 7 e 8; atualize `api=` e `bearer=` no `.env` (`/home/lze/Documents/ClonField/.env`, nunca versionado).
2. Linha de base do agente: `plan_eval.py` (3 pedidos × 2 tentativas, lê o `plan` do job e o cancela) com o LLM no ar.
3. Aplicar o stash (`git stash pop`), empurrar, repetir a medição e comparar.
