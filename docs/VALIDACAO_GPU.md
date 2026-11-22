# Validação na GPU real (Colab, Tesla T4) — 2026-11-20

Rodado com `tests/gpu/validate_remote.py` contra o Studio de verdade (link gradio.live + senha da sessão, via API `/clonfield/api`).
Cada resultado foi baixado e conferido (imagem não chapada, vídeo com `ffprobe` + movimento, áudio com duração); os quadros dos vídeos foram olhados.
Máquina remota: Tesla T4, 15 GB de VRAM, 12,7 GB de RAM. Tempos são de parede, incluem fila e download de modelo quando houve.

## Estado por item

| Item | Estado | Evidência |
|---|---|---|
| Qwen 2.1 Turbo (criar imagem) | TESTADO GPU | 768×768 válida, 257–344 s (344 s com modelo frio, 257 s depois) |
| Qwen 2.1 padrão | TESTADO GPU | 284 s |
| Upscale RealESRGAN x4 | TESTADO GPU | 21,6 s |
| Receita «Melhor de N sementes» | TESTADO GPU | 409 s; sementes por item geram imagens distintas |
| Receita «Cenários em matriz» | TESTADO GPU | 39 s |
| Receita «Animatic do storyboard» | TESTADO GPU | 9 s |
| Remover fundo (U²-Net) | TESTADO GPU (CPU do Colab) | 7 s isolado, foto real |
| Wan 2.2 5B Q6 (Foto em movimento) | TESTADO GPU | 832×480, 3,04 s, movimento 26,4; 470,6 s |
| Receita «Planos prontos em filme» | TESTADO GPU | 1280×720, 4,08 s, 385 s |
| Receita «Storyboard em filme» | TESTADO GPU | 1280×720, 4,08 s, 922 s (inclui 7,2 GB de download do FLUX.2 klein) |
| Agente local → cadeia imagem→vídeo | TESTADO GPU | Qwen3.5-9B na T4 chamou `compose_chain`; o job gerou 832×480, 3 s; 122 s |
| LLM local na GPU | TESTADO GPU | `llama-server --list-devices` → `CUDA0: Tesla T4` |
| `POST /jobs` sem campos hidden | TESTADO API REAL | `animate` só com `image` + `prompt` concluiu (antes: `KeyError: 'mode'`) |
| Receita «Personagem pronto» | TESTADO GPU | com um retrato de personagem (mulher ruiva de cabelo curto, jaqueta de couro verde, jeans, tênis brancos) como entrada: folha 2700×1084 com Frente, 3/4, Perfil e Costas, 2232 s (37 min, quase tudo na folha com offload de 24 GB). Olhando as 4 vistas, a identidade e a roupa se mantêm (cabelo, jaqueta, jeans, tênis; costas com bolsos e costura). Falha visual: faixas cinza claras em cima e embaixo de cada vista (a imagem 3:4 não preenche o painel). Fidelidade medida só por olho, em UMA personagem e UM conjunto (turnaround) |
| Wan A14B «Entre dois quadros» (loop) | TESTADO GPU com o Q4_K_S; Q6_K NÃO cabe | **Q4_K_S: 469 s**, 832×480, 33 quadros a 16 fps, sem o worker cair (download de ~17,5 GB em ~3 min a 120–140 MB/s; o job começou com «Liberando a GPU do modelo de texto» e baixou em < 6 s). Qualidade: farol quase parado (movimento 1,52), um risco de luz que aparece no meio e some, medidor de emenda «visível» (8,4× um passo normal, mas o passo normal é minúsculo). **Q6_K (12 GB por especialista) morreu 4×** ao carregar o segundo especialista, com `--fast-disk` (log confirmou `fast_disk=True`), com `--disable-pinned-memory` (derrubou o Studio inteiro) e sem flags. O Studio agora recusa o Q6_K com menos de 24 GB de RAM e o padrão do app é o Q4_K_S. A receita «Imagem em loop» herda esse padrão: ainda não rodei a receita inteira com ele |
| Fábrica de vídeo | CÓDIGO ESCRITO (correção), NÃO validado na GPU | erro real: `open() got an unexpected keyword argument 'metadata_errors'` (98 s). Hipótese: faster-whisper decodifica o WAV com PyAV e passa `metadata_errors=`, que o PyAV do Colab rejeita. Correção: o provider entrega as amostras (mono 16 kHz), sem PyAV; teste local com faster-whisper falso. Falta rodar no Colab depois do pull + reinício do Studio |

## Qualidade (olhada nos quadros, sem métrica)
- Planos em filme (farol): movimento presente, mas aparecem pequenos objetos flutuantes/artefatos no céu.
- Storyboard em filme: duas cenas coerentes (mulher abrindo uma porta; mulher escrevendo), movimento sutil.
- Foto em movimento com imagem sintética (círculo): o modelo inventou uma câmera e uma mão. A imagem de teste era ruim; falta repetir com foto real.
- Cadeia do agente: farol coerente, mas movimento baixo (6,6).

## Bugs achados pela GPU e corrigidos
- `llama-server` não achava `libcudart`/`libcublas` (pasta irmã) → rodava na CPU; agora o `LD_LIBRARY_PATH` inclui todas as pastas com `.so`.
- Trava de CUDA procurava uma linha no log que o build b12360 não escreve (log de 783 bytes) → falso alarme; agora pergunta ao build (`--list-devices`) e mede o crescimento de VRAM.
- Receitas de vídeo juntavam modo rápido (LightX2V, só A14B) com o 5B → erro; agora `fast=False` com o 5B.
- `POST /jobs` não preenchia campos omitidos → `KeyError`; agora usa o default do formulário.
- Cliente de validação trocava a senha da sessão por token (`/clonfield/connect`) e aguardava a resposta assíncrona do agente.

## Pendente
- «Personagem pronto»: faixas cinza em cada vista; testar outros conjuntos de vistas e outros personagens (só 1 foi olhado).
- Receita «Imagem em loop» inteira com o A14B Q4_K_S (o teste foi do app «Entre dois quadros» direto); Q3_K_S não foi testado.
- Medir se o LLM descarregado de fato libera VRAM/RAM (hoje só vi que o job de GPU espera o sono do servidor e começa).
- Fábrica de vídeo: rodar no Colab com a correção (célula 1 + reiniciar a 8).
- Medir Qwen 2.1 padrão × Turbo com cuidado (um run só por modo; o frio inclui download), Wan «Rápido» (só A14B), apps com offload.
- Repetir a foto em movimento com foto real.
