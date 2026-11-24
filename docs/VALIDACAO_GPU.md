# Validação na GPU real (Colab, Tesla T4) — 20 a 23/11/2026

Rodado com `tests/gpu/validate_remote.py` e scripts auxiliares contra o Studio de verdade (link gradio.live + senha da sessão, API `/clonfield/api`).
Cada resultado foi baixado e conferido (imagem não chapada, vídeo com `ffprobe` + movimento, áudio com duração) e os quadros dos vídeos foram olhados.
Máquina remota: Tesla T4, 15 GB de VRAM, **12,7 GB de RAM**. Tempos são de parede (incluem fila, download de modelo e reinícios quando houve).

## Estado por item

| Item | Estado | Evidência |
|---|---|---|
| Qwen 2.1 Turbo / padrão | TESTADO GPU | Turbo **93,4–372,2 s (n=11, corrigido pela auditoria)** (o primeiro, a frio, é o mais lento), padrão 284 s; 768×768 válidas |
| Upscale RealESRGAN x4 | TESTADO GPU | 21,6 s. O «4x UltraSharp» que o agente escolheu levou 457 s |
| Receitas «Melhor de N sementes», «Cenários em matriz», «Animatic» | TESTADO GPU | 409 s, 39 s, 9 s; «sementes por item geram imagens distintas»: **PROVA NÃO RETIDA** (só a melhor imagem foi salva) |
| Remover fundo (U²-Net) | TESTADO GPU (CPU do Colab) | 7 s, foto real |
| Wan 5B Q6 | TESTADO GPU | 350–478 s por 3 s de vídeo. Em retrato vertical (480×832) a identidade se mantém, mas quase não se mexe (movimento ~5) |
| «Planos em filme» / «Storyboard em filme» | TESTADO GPU | 1280×720, 385 s / 922 s (este inclui 7,2 GB de download); alguns artefatos pequenos no céu |
| «Personagem pronto» | TESTADO GPU | 37 min; folha 2700×1084 com 4 vistas; identidade mantida em UM personagem e UM conjunto (olhado a olho); faixas cinza nas vistas |
| Fábrica de vídeo | TESTADO GPU | 1381 s; MP4 1080×1920, 31,8 s, narração e legenda palavra por palavra. QC acusou «MILLIONS OF YEARS» com 17 caracteres (máx. 12) |
| Wan A14B Q6_K | **NÃO CABE** na máquina de 12,7 GB | morreu 4× ao carregar o segundo especialista (12 GB cada); o Studio o recusa com menos de 24 GB de RAM. Q6_K em dois estágios NÃO foi testado |
| Wan A14B Q4_K_S, em dois prompts | TESTADO GPU | «Imagem em loop»: 361 s. Depois de um job 5B: 537 s. Segue o prompt melhor que o 5B (sorri, mexe o corpo) com a identidade preservada. Q3_K_S e 20 passos NÃO testados |
| LLM local na GPU, dormindo durante jobs de GPU | TESTADO GPU | `--list-devices` → `CUDA0: Tesla T4`; o job de GPU espera o servidor dormir (< 6 s); o LLM acorda depois do job em 37–48 s |
| Agente local (Qwen3.5-9B) monta imagem → ampliar → vídeo | TESTADO GPU, com ressalva | cadeia completa em 907 s, vídeo 832×480 de 3 s. **O resultado não bateu com o pedido**: pedi um farol com ondas e saiu um poste de rua ao entardecer, sem ondas |
| `POST /jobs` com campos omitidos; validação de parâmetro obrigatório | TESTADO API REAL | sem `KeyError`; um vídeo sem `prompt` é recusado antes de gastar GPU |
| Reinício do worker pelo Studio | TESTADO GPU | depois de um job 5B o ComfyUI chega a 8,1–9,1 GB; o reinício o leva a ~1,3 GB. A sequência 5B → A14B, que falhava 2×, passou |

## O que a máquina de 12,7 GB ensinou
- **[Corrigido em 23/11, V9, pela auditoria]** O `/free` devolve **parte** da RAM (8,12 → 3,83 GB no `agent-full.log`), mas sozinho não bastou para o A14B depois de um 5B; um processo novo começa em ~1,2–1,3 GB. A frase anterior («`/free` não devolve a RAM») era exagero. Por isso o Studio reinicia o worker (antes do A14B, entre os dois estágios, e antes de qualquer job se passar de 7 GB).
- O A14B roda um especialista por prompt (`SaveLatent` → reinício → `LoadLatent`). O ciclo do latente foi provado num ComfyUI real em CPU (tensor idêntico na volta).
- O LLM de 9B não pode ficar carregado durante um job de GPU, e o ComfyUI não pode estar com os modelos do Wan na VRAM quando o LLM acorda: o Studio faz as duas trocas.

## Bugs achados pela GPU e corrigidos
- `llama-server` rodava na CPU (faltava `libcudart` no `LD_LIBRARY_PATH`); depois a trava de CUDA dava falso alarme (este build não escreve nada sobre o backend no log): agora usa `--list-devices` e a variação de VRAM.
- Receitas de vídeo juntavam o modo rápido (só A14B) com o 5B; `POST /jobs` não preenchia campos omitidos; a Fábrica falhava com `metadata_errors` (PyAV velho no Colab: o provider entrega as amostras ao faster-whisper).
- O agente gastava todos os passos descobrindo capacidades (ids de atalho no prompt, 14 passos) e montava vídeo sem o prompt (validação de parâmetro obrigatório).
- O worker morria por RAM (reinício pelo Studio) e o LLM morria ao acordar ao lado dos modelos do Wan (`/free` antes do despertar).

## Não medido / pendente
- A14B com 20 passos (sem o modo rápido), Q3_K_S, e o Q6_K em dois estágios.
- Wan 5B com um prompt de movimento mais forte; foto em movimento com foto real.
- `run_eval.py --chains` com o Qwen real; se `force` com semente fixa regenera a mesma saída; apps com offload; outros conjuntos de vistas e outros personagens.
- Qualidade do plano do agente: ele ignorou «ondas» e interpretou «farol» como poste. Não há medição de aderência ao pedido.
- Testes locais **[corrigido]**: a última invocação única da suíte foi **408 passed / 19 skipped** (20/11, árvore de `4b55197`); «419» é a soma de 43 arquivos rodados um a um. Texto original: a suíte inteira (419 passed, 0 falhas) rodou ANTES das últimas mudanças de reinício do worker, de validação e de família do Wan. Depois delas rodaram só arquivos isolados (`test_dag` 10, `test_llm_release` 14, `test_agent` 16, `test_worker_restart` 5). A suíte completa derrubou a máquina de 3,7 GB e não é mais executada aqui.
- Itens do backlog nunca iniciados (cerca de 20) e legenda automática.
