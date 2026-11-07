# ClonField Studio: handoff

Estado em 2026-11-07, `main` em `github.com/Vit0lze/clonfield-studio`. Este arquivo não contém chaves. HF e Civitai ficam só em variáveis de ambiente.

## O que é

Colab com GPU roda o ComfyUI (worker) e um Gradio. O Gradio expõe a API própria do Studio e serve um painel web estático (`portal/`). O painel pode rodar no mesmo link (`/studio/`) ou hospedado em qualquer lugar (Vercel, Pages): quem abre informa o link `gradio.live` da sessão e a senha (Bearer).

```
Colab: ComfyUI (GPU)  <-  cf_api.py (Starlette, /clonfield/api/*)  <-  portal/ (SPA sem build)
                          montado no Gradio por cf_portal.PortalAPI      /studio/ ou host público
```

## Pedido original e decisões do usuário

- Parar de travar por horas e refazer a interface com base vermelha ("Sala de projeção"), modular, estilo "ComfyUI com rodinhas e apps tipo Higgsfield".
- Regra do usuário: nunca usar stub, sempre credencial real e teste real.
- Push na `main` autorizado. Qwen roda pelo ComfyUI.
- Conteúdo adulto no Civitai é para incluir (capas e nomes), via `civitai.red`.
- Sem disco do Drive e sem GPU para teste real neste momento.

## Mapa do código

Backend (raiz do repo):
- `studio_app.py`: entrypoint do Colab. Sobe Gradio (modo clássico na raiz), imprime `STUDIO:` e `SENHA DA SESSÃO`, define `CLONFIELD_FRONT` opcional para imprimir o link do painel público.
- `cf_api.py`: rotas `/clonfield/api/*` (system, apps, models, loras, civitai/loras, civitai/install, cover assinada, jobs, events SSE, upload, uploads/{id}, import, files assinados, logs). CORS próprio via `cf_portal`.
- `cf_portal.py`: `PortalAPI` (login em `/clonfield/connect`, bloqueio de 8 erros/min por IP, CORS aberto só em `/clonfield/*` e `/studio/*`, `let_studio_answer_cors`).
- `cf_apps.py`: registro de 19 apps, runners, `dimensions`/`ASPECT_INFO`, `relight_fields`/`run_relight`, `install_civitai_lora`.
- `cf_jobs.py`: fila (1 faixa GPU + pool CPU), cancelar, persistência JSON.
- `cf_workflows.py`: coleta inteligente do ComfyUI (fila, stall, worker morto, cancelar).
- `cf_download.py`: downloads com retomada, bytes/velocidade/ETA.
- `cf_tiers.py`: perfis Leve/Médio/Pro por VRAM (`CLONFIELD_FAKE_VRAM` para simular).
- `cf_model_lab.py`: presets de modelos (Qwen 2.1 aceita 10 referências).
- `cf_civitai.py` / `cf_assets.py`: Civitai (host `civitai.red` por padrão, `CLONFIELD_CIVITAI_HOST` muda), `browse_loras`, `entry_for`, covers.
- `cf_loras.py`: catálogo HF + LoRAs locais com sidecar `.json`; `link_civitai`.
- `cf_finish.py`: Enquadrar/Cor/Cortar etc. (`image_edit` aceita `focus`).
- `ClonField_Colab.ipynb`: instala só o que falta, flags por tier, log do ComfyUI.

Frontend (`portal/`): `index.html` (assets com `?v=N`, hoje 15), `css/base.css`, `css/views.css`, `js/{main,api,ui,lights}.js`, `js/views/*`. Fontes e arte locais em `assets/` (capas geradas pelo Codex em `assets/art/*.webp`). `vercel.json` tem CSP que só libera `*.gradio.live`.

## Funcionalidades entregues (todas na main)

- Destravamento: Qwen via ComfyUI, watchdogs, cancelar, downloads retomáveis, reconexão de SSE.
- 19 apps, cada um com glifo próprio no mesmo bloco visual. Apps de escolha usam dropdown com ícone de proporção, grupos e explicação (Auto, redes sociais, vídeo e tela, foto).
- Luz ambiente: luzes arrastáveis sobre a foto (cor, intensidade, maciez, profundidade, 4 tipos), vira prompt para a IA.
- Resultado: menu "Usar em", barra de ações, visualizador com reenquadramento sobre a imagem original (contorno arrastável, persiste por job em localStorage, rota `/uploads/{id}` renova link).
- Painel público: tela de conexão com link da API + senha, `?api=` pré-preenche, CORS, bloqueio de tentativas.
- Modelos com capa própria (7 imagens do Codex), nomes distintos (Krea 2 Turbo, Z-Image Turbo), capa pelo último resultado.
- LoRAs: aba Civitai com cards no estilo do site, filtros por modelo, ordenação, busca, "Ocultar adulto" (padrão desligado), instalação com SHA-256; aba Instaladas; reordenar LoRAs arrastando.

## Como rodar local (sem GPU)

```bash
python -m venv venv && venv/bin/pip install gradio==5.49.1 websockets pillow requests spandrel numpy uvicorn python-multipart safetensors huggingface_hub pytest
export CLONFIELD_PASSWORD=<senha-qualquer> CLONFIELD_DIR=/tmp/lab HF_TOKEN=<...> CIVITAI_TOKEN=<...>
venv/bin/python studio_app.py --local        # http://localhost:7860/studio/
```
ComfyUI real em CPU (`main.py --cpu --listen`, porta 8188) serve para testar fluxo, fila e cancelar. Para ver o painel em outra origem: `python -m http.server 8099` dentro de `portal/` e conectar em `http://localhost:7860`.

Testes (`tests/`): `test_live.py`, `test_download_live.py`, `test_resilience_live.py` (ComfyUI e Hugging Face reais), `test_civitai_live.py` (precisa `CIVITAI_TOKEN`), `test_portal_cors.py`, `test_relight.py`. Sem stubs.

## Não verificado

- Nenhuma geração em GPU. Velocidade e estabilidade no T4 não foram medidas (use o app Teste de velocidade na página Sistema).
- Colab real não foi rodado com esta versão.
- Painel público testado só entre `localhost:8099` e `localhost:7860`, não com `gradio.live` nem Vercel de verdade.

## Pendências

- Variantes GGUF para T4 (exige nó ComfyUI-GGUF e nomes de repositórios confirmados).
- Encoder de texto na CPU para a placa Leve; copiar pesos do Drive para disco local (usuário sem Drive agora).
- Contorno arrastável dentro do app Enquadrar imagem avulso (existe só no visualizador).
- A "imagem das logos" da aba Modelos citada pelo usuário nunca foi identificada.
- Hospedar o painel (decisão do usuário), ajustando a CSP se não for `gradio.live`.

## Armadilhas conhecidas

- `pkill -f`/`pgrep -f` com texto que aparece na própria linha de comando mata o shell (exit 144).
- Reiniciar o Gradio invalida o token da sessão: é preciso entrar de novo no painel.
- Módulos JS ficam em cache do navegador. O servidor já manda `no-cache`, mas em testes use `fetch(url, {cache: "reload"})` ou suba o `?v=` no `index.html`.
- `--normalvram` não existe no ComfyUI 0.44.
- O GitHub às vezes recusa o push (`commit_refs`); repetir depois de alguns segundos funciona.
- Screenshots do painel pegam a animação de entrada pela metade; espere 2 s ou 3 s.

## Segurança

- As chaves do Hugging Face e do Civitai foram coladas no chat da sessão. Rotacione as duas.
- Quem tem o link `gradio.live` e a senha controla a GPU da sessão. O bloqueio é por IP (8 erros/min).
- Adulto: `civitai.red` lista tudo; o botão "Ocultar adulto" filtra só no cliente.
