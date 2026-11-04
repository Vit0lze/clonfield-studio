# ClonField Studio

Estúdio Gradio para criar imagens, editar fotos, animar referências e montar clipes no Colab. Na aba **Explorar**, filtre por Imagem, Identidade, Vídeo ou Melhorar e abra a ferramenta pelo cartão.

[![Abrir no Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Vit0lze/clonfield-studio/blob/main/ClonField_Colab.ipynb)

## Ferramentas

| Área | O que tem na interface | Implementação |
| --- | --- | --- |
| Criar | Texto para imagem, edição com referências, retrato por referência, LoRAs, prompt negativo, composição por máscara e upscale após gerar | [Qwen-Image-2.1 / Turbo](studio_app.py) |
| Editar região | Retocar uma área marcada por máscara com margem de contexto, suavização e exportação no tamanho da foto | [Qwen-Image-2.1 + Pillow](cf_region.py) |
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
3. Execute as células na ordem. O notebook atualiza este repo por fast-forward, baixa os recursos Civitai selecionados na célula, prepara o ComfyUI e inicia o Gradio. O Colab mostra a URL e a senha da sessão.
4. Abra **Explorar** e escolha uma ferramenta. Os pesos do Qwen são carregados ao gerar.

## Reaproveitar resultados

Abra **Histórico** para localizar imagens, vídeos e áudios já salvos. O acervo lê a pasta de saídas atual, inclusive mídias de execuções anteriores que continuam nessa pasta. No Colab, monte o Drive para manter esse acervo entre sessões. Imagens podem seguir para **Acabamento**, **Animar foto** ou **SeedVR2**. Vídeos podem seguir para **Montagem** ou **SeedVR2**.

Quando uma geração do Qwen tiver o original e a versão pós-processada, **Comparar original e final** abre os dois arquivos. Também é possível abrir a comparação a partir de **Editar região** ou enviar duas imagens pela aba **Comparar**. Cada lado da prancha usa a proporção da segunda imagem e mantém a imagem inteira. O lado maior de cada painel tem até 1600 px.

## Resolução do Qwen

**Criar** começa em **768 × 768**, NF4, uma imagem por execução. O seletor inclui 1024 × 1024, 1536 × 1536, 2048 × 2048 e 2752 × 1536 com opção vertical. Também dá para ajustar largura e altura manualmente. O [model card oficial](https://huggingface.co/Qwen/Qwen-Image-2.1) mostra exemplos em 2048 × 2048 e 2752 × 1536. O máximo prático no Colab depende da GPU, das imagens de referência e da memória da sessão.

A [sondagem do Colab](docs/DIAGNOSTICO.md) usa 512 × 512 e dois passos para localizar falhas de inicialização ou inferência. Ela gera logs em `/content/clonfield_runtime/logs/`.

## Arquivos e integrações

Os grafos visuais em [workflows/](workflows/) podem ser abertos no ComfyUI e exportados como API JSON para execução no Studio. O instalador Civitai verifica SHA-256 quando informado no metadado. Para repetir uma versão, rode `python cf_assets.py --version NUMERO`. Logs e pesos ficam no runtime. Os termos de cada modelo e grafo se aplicam aos respectivos arquivos.
