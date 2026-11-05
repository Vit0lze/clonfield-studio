# ClonField Studio

Estúdio para criar imagens, editar fotos, animar referências e montar clipes no Colab. O app novo abre em **`/studio/`** no link público: uma página por app, biblioteca de modelos com página própria, LoRAs com controle de força, histórico, fila e diagnóstico da placa. O Gradio antigo continua no link raiz como modo clássico.

[![Abrir no Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Vit0lze/clonfield-studio/blob/main/ClonField_Colab.ipynb)

## Studio (app novo)

| Página | O que faz |
| --- | --- |
| Início | Campo de prompt rápido, resultados recentes e apps em destaque |
| Apps | 18 apps com controles próprios; os padrões e limites se ajustam à sua GPU (perfil Leve, Médio ou Pro) |
| App | Painel de controles à esquerda, palco à direita com tempo, fila, progresso real e **Cancelar**. Resultados seguem para outros apps com "Usar em…" |
| Modelos | Capas, requisitos, arquivos e instalação com bytes, velocidade e retomada |
| LoRAs | Biblioteca por família; no app, cada LoRA tem slider de força (−2 a 2) e de encoder |
| Histórico / Fila | Acervo em grade e jobs que continuam no Colab mesmo se você fechar a aba |
| Sistema | GPU, perfil, RAM, disco, worker, credenciais (só presença), teste de velocidade e log do ComfyUI |

O frontend não usa build: HTML, CSS e módulos ES em [portal/](portal/). Também roda no Vercel (Root Directory `portal`); o mesmo código fala com `/clonfield/api` do Colab.

## O que mudou para acabar com travamentos

- **Qwen agora roda no ComfyUI** (pesos INT8 prontos), não mais dentro do Gradio com quantização na hora. Isso removeu o download de ~40 GB e o pico de RAM que derrubava o processo.
- **Coleta de jobs com fila e watchdog** ([cf_workflows.py](cf_workflows.py)): mostra a posição na fila, falha com o log do worker se ele morrer, detecta job perdido e interrompe um nó que fica mudo além do limite.
- **Cancelar de verdade**, inclusive durante download.
- **Downloads com progresso e retomada** ([cf_download.py](cf_download.py)): bytes, velocidade e ETA; leitura parada por 45 s reconecta com `Range`.
- **Portal resiliente**: a conexão de eventos tem watchdog de 30 s e reabre sozinha; o job fica salvo no servidor.
- **Flags do ComfyUI por GPU** ([cf_tiers.py](cf_tiers.py)): o notebook não força mais `--lowvram` em qualquer placa.

## Testes

Os testes em [tests/](tests/) não usam stubs: rodam contra um ComfyUI real, o engine real e downloads reais do Hugging Face (exigem `HF_TOKEN`).

```bash
python cf_engine.py --port 7861 &   # com ComfyUI em :8188
pytest tests/ -v
```

## Ferramentas

| Área | O que tem na interface | Implementação |
| --- | --- | --- |
| Bancada de modelos | Presets de Qwen 2.1, FLUX.2/3 Klein, Krea 2 Raw/Turbo, Z-Image Base/Turbo, SDXL e SD 1.5. Permite trocar componentes e ver o grafo | [Presets e executor](cf_model_lab.py) |
| Catálogo Civitai | Busca compatível com o preset e o slot, escolha de versão/arquivo, instalação sob demanda e galeria de exemplos | [Catálogo](cf_civitai.py) |
| Direção de cena | Organiza ação, enquadramento, movimento, luz e função das referências em um prompt editável | [Direção](cf_lab_ui.py) |
| Criar | Texto para imagem, edição com referências, retrato por referência, LoRAs, prompt negativo, composição por máscara e upscale após gerar | [Apps](cf_apps.py) · modelos Comfy da [Bancada](cf_model_lab.py) |
| Editar região | Retocar uma área marcada por máscara com margem de contexto, suavização e exportação no tamanho da foto | [Qwen-Image-2.1 no ComfyUI + Pillow](cf_region.py) |
| Vídeo | Animar foto ou gerar clipe por texto | [Wan 2.2 5B](cf_wan.py) |
| Upscale | Real-ESRGAN para imagem e SeedVR2 INT8 para imagem ou vídeo | [SeedVR2](cf_seedvr2.py) · [Real-ESRGAN](studio_app.py) |
| Comparar | Controle deslizante de antes e depois e exportação lado a lado em PNG | [Comparação com Pillow](cf_finish.py) |
| Acabamento | Cor e contraste, enquadramento e exportação em PNG, JPEG ou WebP | [Pillow](cf_finish.py) |
| Montagem | Corte, extração de quadro, prancha de cenas e sequência de até oito clipes com ordem e proporção ajustáveis | [FFmpeg](cf_finish.py) |
| Identidade em vídeo | Trocar personagem com referência em um worker H3 preparado. Perfil upstream de classe 96 GB | [OpenJutsu](docs/OPENJUTSU.md) |
| Workflows | Seis grafos de referência e execução de grafos no formato ComfyUI API JSON | [Grafos](workflows/) · [Executor](cf_workflows.py) |
| Histórico | Busca por mídia, prompt e ferramenta. Abre saídas em Acabamento, Montagem, Wan ou SeedVR2 | [Acervo](cf_history.py) |
| Biblioteca | Catálogo de LoRAs do Hugging Face e 18 versões fixadas do Civitai | [Catálogo Civitai](assets.json) · [Instalador](cf_assets.py) |

## Rodar no Colab

1. Abra o notebook e selecione um runtime GPU.
2. Cadastre `CIVITAI_TOKEN` e `HF_TOKEN` em Secrets no Colab e dê acesso ao notebook. Use credenciais de leitura.
3. Execute as células na ordem. O notebook atualiza este repo por fast-forward, prepara o ComfyUI e inicia o Gradio. A célula opcional do Civitai só baixa versões se você preencher `VERSOES_CIVITAI`; a lista começa vazia. O Colab imprime o link público do Gradio e a senha da sessão. Se o túnel falhar, o notebook mostra a interface na própria célula.
4. Abra **Explorar** e escolha uma ferramenta. Os pesos do Qwen são carregados ao gerar.

## Portal no Vercel

Importe este repositório no Vercel e configure **Root Directory** como `portal`, com preset **Other**. Depois que o Colab imprimir **LINK PÚBLICO** e **SENHA DA SESSÃO**, use os dois para conectar. O Studio roda no site estático e chama a API do Gradio diretamente pelo navegador. Os resultados e o progresso aparecem no site. O token fica em memória até desconectar ou recarregar a página.

A Bancada mostra os componentes e controles compatíveis com o preset escolhido. **Procurar mais** abre o catálogo com o preset e o tipo preenchidos. No frontend, o catálogo mostra um bloco por recurso com capa, link da versão e download. Após o download, a Bancada atualiza a lista de arquivos compatíveis. Cada LoRA adicionada tem pesos próprios para o modelo e o encoder.

## Civitai e Bancada

1. No **Catálogo Civitai**, escolha o preset e o componente. Busque pelo nome ou cole um link de modelo, inclusive com `modelVersionId`.
2. O Studio filtra por família exata, tipo de componente e formato. Quando o Civitai chama um arquivo de checkpoint e o slot pede difusão separada, o Studio tenta confirmar pelo cabeçalho SafeTensors antes de listar. Candidatos inconclusivos ficam fora da lista. Se a busca não encontrar uma versão específica, tente o link direto.
3. Use **Usar na Bancada · baixar ao gerar** para selecionar o arquivo sem iniciar o download. **Instalar agora** guarda o arquivo no acervo de componentes. Na versão selecionada, **Ver imagens da versão** abre a galeria. Selecione uma imagem para abrir como referência no preset Qwen da Bancada.
4. Use **Checar conjunto** para inspecionar o grafo, os nós e as opções do ComfyUI. Ao gerar, o Studio prepara os componentes, verifica a estrutura SafeTensors e o SHA-256 do Civitai quando publicado, e submete o grafo. A execução é que confirma carga, encaixe de memória e qualidade visual.

O formulário da Bancada oferece os slots aplicáveis ao preset. SDXL e SD 1.5 precisam de um checkpoint completo instalado ou selecionado no catálogo. ControlNet, embeddings, CLIP Vision, módulos de movimento e workflows usam seus próprios grafos. Arquivos ZIP/PNG de workflow ficam para revisão manual, e grafos API JSON podem ser abertos na aba Workflows. A Bancada usa o worker ComfyUI da célula do Colab. Alguns pesos, como o FLUX.3, exigem aceitar as condições no Hugging Face e fornecer um token de leitura.

As receitas seguem os [templates do ComfyUI](https://github.com/Comfy-Org/workflow_templates/tree/9a51089f3bcacf84ccceca3907a493027ae32bfa), com o grafo Qwen INT8 reaproveitado do alpha e revisões dos pesos registradas no código. O preset é ponto de partida. Resolução, referências e pós-upscale afetam o pico de memória. O painel de direção adapta a estrutura de prompt da [Higgsfield AI Prompt Skill](https://github.com/OSideMedia/higgsfield-ai-prompt-skill). Os filtros usam a [API de modelos e imagens do Civitai](https://developer.civitai.com/site/reference/).

## Reaproveitar resultados

Abra **Histórico** para localizar imagens, vídeos e áudios já salvos. O acervo lê a pasta de saídas atual, inclusive mídias de execuções anteriores que continuam nessa pasta. No Colab, monte o Drive para manter esse acervo entre sessões. Imagens podem seguir para **Acabamento**, **Animar foto** ou **SeedVR2**. Vídeos podem seguir para **Montagem** ou **SeedVR2**.

Quando uma geração do Qwen tiver o original e a versão pós-processada, **Comparar original e final** abre os dois arquivos. Também é possível abrir a comparação a partir de **Editar região** ou enviar duas imagens pela aba **Comparar**. Cada lado da prancha usa a proporção da segunda imagem e mantém a imagem inteira. O lado maior de cada painel tem até 1600 px.

## Resolução do Qwen

**Criar** começa em **768 × 768**, NF4, uma imagem por execução. O seletor inclui 1024 × 1024, 1536 × 1536, 2048 × 2048 e 2752 × 1536 com opção vertical. Também dá para ajustar largura e altura manualmente. O [model card oficial](https://huggingface.co/Qwen/Qwen-Image-2.1) mostra exemplos em 2048 × 2048 e 2752 × 1536. O máximo prático no Colab depende da GPU, das imagens de referência e da memória da sessão.

A [sondagem do Colab](docs/DIAGNOSTICO.md) usa 512 × 512 e dois passos para localizar falhas de inicialização ou inferência. Ela gera logs em `/content/clonfield_runtime/logs/`.

## Arquivos e integrações

Os grafos visuais em [workflows/](workflows/) podem ser abertos no ComfyUI e exportados como API JSON para execução no Studio. O instalador Civitai verifica SHA-256 quando informado no metadado. Para repetir uma versão, rode `python cf_assets.py --version NUMERO`. Logs e pesos ficam no runtime. Os termos de cada modelo e grafo se aplicam aos respectivos arquivos.
