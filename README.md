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
| Acabamento | Cor e contraste, enquadramento e exportação em PNG, JPEG ou WebP | [Pillow](cf_finish.py) |
| Montagem | Corte, extração de quadro, prancha de cenas e sequência de até oito clipes com ordem e proporção ajustáveis | [FFmpeg](cf_finish.py) |
| Identidade em vídeo | Trocar personagem com referência em um worker H3 preparado. Perfil upstream de classe 96 GB | [OpenJutsu](docs/OPENJUTSU.md) |
| Workflows | Seis grafos de referência e execução de grafos no formato ComfyUI API JSON | [Grafos](workflows/) · [Executor](cf_workflows.py) |
| Biblioteca | Catálogo de LoRAs do Hugging Face e 18 versões fixadas do Civitai | [Catálogo Civitai](assets.json) · [Instalador](cf_assets.py) |

## Rodar no Colab

1. Abra o notebook e selecione um runtime GPU.
2. Cadastre `CIVITAI_TOKEN` e `HF_TOKEN` em Secrets no Colab e dê acesso ao notebook. Use credenciais de leitura.
3. Execute as células na ordem. O notebook atualiza este repo por fast-forward, baixa os recursos Civitai selecionados na célula, prepara o ComfyUI e inicia o Gradio. O Colab mostra a URL e a senha da sessão.
4. Abra **Explorar** e escolha uma ferramenta. Os pesos do Qwen são carregados ao gerar.

## Resolução do Qwen

**Criar** começa em **768 × 768**, NF4, uma imagem por execução. O seletor inclui 1024 × 1024, 1536 × 1536, 2048 × 2048 e 2752 × 1536 com opção vertical. Também dá para ajustar largura e altura manualmente. O [model card oficial](https://huggingface.co/Qwen/Qwen-Image-2.1) mostra exemplos em 2048 × 2048 e 2752 × 1536. O máximo prático no Colab depende da GPU, das imagens de referência e da memória da sessão.

A [sondagem do Colab](docs/DIAGNOSTICO.md) usa 512 × 512 e dois passos para localizar falhas de inicialização ou inferência. Ela gera logs em `/content/clonfield_runtime/logs/`.

## Arquivos e integrações

Os grafos visuais em [workflows/](workflows/) podem ser abertos no ComfyUI e exportados como API JSON para execução no Studio. O instalador Civitai verifica SHA-256 quando informado no metadado. Para repetir uma versão, rode `python cf_assets.py --version NUMERO`. Logs e pesos ficam no runtime. Os termos de cada modelo e grafo se aplicam aos respectivos arquivos.
