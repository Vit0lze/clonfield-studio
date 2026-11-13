# ClonField Studio — changelog honesto, depois da entrega dos planos V7/V7.1

> **Nota (2026-11-13):** o Gemma e a API do Google AI Studio foram removidos do Studio. O chat e o agente usam só um modelo local (Qwen3.5-9B abliterado via llama.cpp, ver `cf_llama.py`). Onde este documento fala de Gemma, descreve testes e decisões da época, mantidos como registro.


Janela: commits `36def60` (10/11, 23:02) até `6648b3d` (11/11, 23:55) na `main`, 22 commits, 156 arquivos, +15.510 / −304 linhas.
Ponto de partida: `887e0c3` (33 commits, 19 apps, Studio em Colab, Gradio + API própria + SPA sem build).

**Como ler os estados** (do mais fraco ao mais forte):
`escrito` (código existe) → `testado em CPU` (rodou de verdade nesta máquina sem GPU) → `testado ao vivo` (API real de terceiros) →
`testado na T4` (nunca nesta janela, exceto o item marcado). **Nada abaixo está "aprovado para produção".**

---

## 1. Apps hoje (20 visíveis + 1 interno)
Antes: 19. Novos: **2** (Camadas de anime, Fábrica de vídeo). Removido da galeria: Teste de velocidade (virou o Benchmark em Sistema).

| Grupo | App | Estado real |
|---|---|---|
| Imagem | Criar imagem | interface nova (barra de prompt); **geração só rodou na T4 na versão antiga**; Conjuntos/componentes não testados em GPU |
| Imagem | Editar com referências | idem |
| Imagem | Luz ambiente | idem (sem teste nesta janela) |
| Imagem | Editar região | não mexi; sem teste nesta janela |
| Imagem | Enquadrar imagem | não mexi |
| Identidade | Retrato por referência | interface nova; sem teste em GPU |
| Identidade | Trocar personagem | exige ~90 GB de VRAM: não roda na T4 |
| Vídeo | Foto em movimento, Texto em vídeo | não mexi; sem teste nesta janela |
| Vídeo | **Fábrica de vídeo (novo)** | MP4 1080×1920 gerado de verdade em CPU, mudo e narrado (modo «desenhado» apenas) |
| Vídeo | Cortar vídeo, Extrair quadro, Prancha de cenas, Montar sequência | não mexi |
| Melhorar | Ampliar imagem | Lanczos e upscalers testados em CPU; GPU não testada |
| Melhorar | Restaurar com SeedVR2, Cor e contraste, Comparar imagens | Cor e contraste rodou em CPU via chat; os outros não mexi |
| Editar | **Camadas de anime (novo)** | grafo aceito pelo ComfyUI real; **nunca gerou camadas** (sem GPU) |
| Avançado | Workflow ComfyUI | não mexi |
| Sistema (oculto) | Benchmark da placa | escrito e visto com dados de exemplo; **medição real na T4 pendente** |

Não existem (planejados e **não iniciados**): trocar rosto/cabeça/corpo/roupa (BFS, ReActor, FaceFusion), swap em vídeo (Wan Animate, SCAIL-2),
MOSS BBox, apps H3 de vídeo, Qwen Expand/Restore, imagem→3D, efeitos sonoros e trilha.

---

## 2. O que foi feito, por frente

### See-through V3 (camadas de anime → PSD)
- Reuso direto do pack `jtydhr88/ComfyUI-See-through` (commit `98d754b`, MIT segundo o `pyproject`, sem arquivo LICENSE) sobre `shitagaki-lab/see-through` (Apache-2.0). **Pesos LayerDiff: OpenRAIL++** (restrições de uso).
- App, 3 perfis (NF4, BF16+offload, BF16), instalação fixada, PSD montado no servidor (psd-tools).
- Testado: grafo aceito pelo ComfyUI 0.44 real, PSD sintético relido, job até o carregador (falha esperada «No GPU found» sem CUDA).
- **Não testado:** camadas reais, VRAM, tempo, fidelidade, block swap (não integrado), editor 2.5D/rig.

### Jev, roteador e Scenario
- **Método** (não código) dos skills `scenario-quality-gate` e `scenario-refine-loop` (MIT): gate técnico + loop de refino com teto de rodadas. Só mede propriedades mensuráveis (vazio, nitidez, exposição); **não julga estética nem identidade**; sem nota inventada. Opção «Refino técnico automático» em apps de imagem. Testado em CPU com imagens reais; sem geração real.
- **Contrato** do JevRouter (MIT) em `cf_router.py`: Jev real (`api.typesafe.ai`) decide o app; a disponibilidade é filtrada pelo servidor sem renormalizar; heurística local como fallback declarado. `POST /route`, `POST /plan` (passos em série, para quando o Jev está incerto).
- Testado ao vivo: 30/30 num gabarito escrito por mim (casos claros → vale como sanidade, não como acurácia geral); detecção conversa × tarefa.
- **Não integrado:** ComfyUI-ScriptFlow (GPL-3.0, não copiei), ComfyUI-Jev, AutoJev (outro problema). **O JEV do proprietário não foi encontrado** na máquina; o que existe usa a API da TypeSafe.

### Content Factory (Fábrica de vídeo)
- Vendorizado `jutsuhq/content-factory` `0ea7632` (MIT) em `vendor/content_factory`; 74 testes do projeto passam no snapshot.
- Mudanças locais (todas em `VENDORED.md`): corrige crash em vídeo sem áudio; render do Remotion limitado a 1 aba (o padrão derrubou a máquina de 3 GB); **adicionados** Kokoro-82M int8 (voz, CPU) e faster-whisper (alinhamento).
- **Remotion tem licença própria** (não MIT; paga acima de um porte): conferir antes de uso comercial.
- Evidência: episódio «Sol» mudo e narrado, QA `ok`. **Não feito:** modos com imagem (falta adaptador ComfyUI de frames, depth e RIFE), Remotion no Colab, UI de revisão por cena.

### Núcleo da plataforma (formulário de imagem)
- **Conjunto** Rápido/Moderado/Qualidade/Manual: cada um escolhe **um pipeline inteiro** (modelo + encoder + VAE + passos + tamanho de geração). Na T4 15 GB: Z-Image Turbo / Z-Image / Qwen Image 2.1. **Escolhidos pelas notas de velocidade/qualidade do catálogo e pela VRAM, sem benchmark A/B**; a tela avisa.
- Manual expõe: difusão, encoder, VAE, upscaler, sampler, scheduler (listas lidas do worker), passos, CFG (passo 0,1), shift (Z-Image), expansor de prompt (FLUX.3), seed, liberar VRAM. **Não ligados** (e a tela diz): ControlNet, detectores, VAD, offload real por conjunto.
- **Resolução final** até 4096 px (gera até o limite da placa e amplia em blocos; o job registra «geração → ampliação → saída»). Real-ESRGAN em GPU **não testado**.
- Variações 1–4 sempre liberadas; barra de prompt tipo Higgsfield/Krea (chips + popovers) nos 4 apps de imagem; resultados anteriores em fileira.
- Estrela vermelha ★ = compatibilidade padrão da receita (por modelo). Busca «Pesquisar…» por slot (no worker, CivitAI por base compatível, Hugging Face só descoberta).

### Chat com sessões
- Sessões persistentes em JSON no disco, mídias isoladas por conversa, plano do Jev por mensagem, «Executar» por passo, resultado volta para a conversa. Painel lateral recolhível, redesenhado.
- **Gemma 4 31B** (Google AI Studio) só **escreve** (resposta, pergunta, prompt reescrito); o Jev decide o app; nada roda sem «Executar». Enviado ao Google: texto das mensagens e **tipos** de mídia (nunca arquivos). Latência medida: **30 a 90 s** (26B-A4B: 12 a 19 s).
- Testado: API real + job `Cor e contraste` em CPU + Gemma real. **Não testado no Colab.**
- Credenciais: ambiente ou `.env` (git-ignorado); o notebook lê Secrets `gemini`/`jev`.

### Biblioteca e contratos
- `cf_contracts.py` + `cf_library.py` + cartão único: **Modelos, LoRAs, VAEs, Encoders de texto, Upscalers**, cada um com Recomendados / Instalados / Explorar (CivitAI, Hugging Face, no worker). Status honesto (`descoberto` ≠ executável), ações declaradas, tamanho em bytes ou «não informado».
- Tamanhos reais do Hugging Face (Qwen 17,3 GB, FLUX.2 16,1 GB, Krea 19,0 GB, Z-Image 14,6 GB; FLUX.3 indisponível por repositório restrito). Arquivos compartilhados entre receitas (ex.: encoder de 8 GB de FLUX.2/Z-Image/Z-Image Turbo) são contados uma vez.
- 20+ testes de contrato; busca real em CivitAI e Hugging Face.
- Listas de modelos mostram só os 7 que o Studio executa (SDXL/SD 1.5 saíram da interface).

### Upscalers (de 2 para 17)
- 17 modelos com revisão fixada e SHA-256 quando publicado, licença dos pesos visível (UltraSharp: uso não comercial; Nomos/HFA2k/DeJPG/ParimgCompact: CC-BY-4.0). **Todos carregaram e ampliaram em CPU**; arquivo adulterado é recusado e apagado. Real-ESRGAN anime 6B ainda sem SHA.

### Favoritos (estrela amarela, ≠ ★)
- Apps, modelos, LoRAs, upscalers e resultados de busca; salvos no servidor. **Não há** favorito para imagens geradas nem para opções de slot instaladas.

### Interface e correções
- Início: anexo real (upload com preview). Ctrl/Cmd+K (busca rápida). Erros com «Tentar de novo» e texto em português (detalhe técnico recolhido). Esc fecha popovers. Dicas em CFG/Passos/Variações/Conjunto.
- Benchmark da placa em Sistema (frio, 3 quentes com seeds novas, 1 grande, VRAM em uso, histórico).
- Colab: instala jsonschema, psd-tools, kokoro-onnx, faster-whisper; clona o pack See-through fixado.

---

## 3. Testes (o que de fato roda)
- Suíte offline: **~78 testes passando, 4 pulados** (+ testes ao vivo que dependem de rede/token: Jev, Gemma, CivitAI, Hugging Face, download de pesos pequenos).
- Rodado em **CPU de 4 núcleos, 3 GB de RAM, sem GPU**. Um agente Haiku exerceu a interface como usuário (achados corrigidos nesta mesma janela; os abertos estão na seção 4).

## 4. Limites e pendências (não esconder)
1. **Nada disto rodou na T4.** A única evidência de GPU: FLUX.2 Klein 512², 4 passos, 280 s com download, no Colab de versão antiga.
2. Receitas dos Conjuntos sem benchmark A/B; Real-ESRGAN/upscalers em GPU, instalações pela Biblioteca e geração com slots trocados sem teste.
3. Filtro «Ocultar adulto» desligado por padrão (decisão sua anterior); o testador sugeriu o contrário.
4. Não feitos: estilos com miniatura, comparação antes/depois, tempo estimado no botão Gerar, onboarding, grade de variações, dock para apps de vídeo, favoritos de resultados.
5. Tokens HF/Civitai que apareceram no chat em sessões anteriores devem ser **rotacionados**.
6. Licenças a conferir antes de uso comercial: Remotion, pesos OpenRAIL++ (See-through), UltraSharp NC, FLUX.2 Klein (licença própria).
7. O plano V7.1 pede ainda: apps de swap, MOSS BBox, H3, 3D, áudio, MCP agente, avaliação visual real, DAG com regeneração parcial além do modo «desenhado».

## 5. Commits (para citação)
```
36def60 See-through V3                         6b8b5e1 Resolução final, registry, conjuntos
ac089fd Gate técnico + loop de refino         0de8507 Busca universal de componentes
6c6b2fa Jev ao vivo no roteador               757d462 UI: Conjunto, slots, Pesquisar
7ee772b Planos em série + Sugerir             3e47783 Formulário de imagem refeito
e01390a Content Factory + Fábrica de vídeo    6c7cbcb Chat com sessões
6fe9432 Narração Kokoro + faster-whisper      b70c0b7 Gemma + conversa×tarefa + .env
131f469 Triagem de roteadores                 5fc21ad Painel lateral recolhível
ed9fc4c Benchmark em Sistema                  e10bf76 Secrets do Colab (jev/gemini)
8573f35 Reconciliação plano × código          5a1ab3c Barra de prompt (dock)
1644cc4 9 upscalers + SHA                     63872e9 Favoritos, Explorar, tamanhos
233c79e Contrato + Biblioteca                 6648b3d 17 upscalers, busca HF de upscaler
```
Documentos: `docs/RECONCILIACAO_V7.md` (plano × código), `docs/V7_STATUS.md` (status por fonte), `docs/CONTRATOS.md`, `docs/HANDOFF.md`, `vendor/content_factory/VENDORED.md`.
