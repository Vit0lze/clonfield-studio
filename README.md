# ClonField Studio

Estúdio Gradio para Colab com Qwen-Image-2.1, Wan, SeedVR2, Real-ESRGAN, acabamento de imagem, montagem de vídeo e execução de grafos ComfyUI.

[![Abrir no Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Vit0lze/clonfield-studio/blob/main/ClonField_Colab.ipynb)

1. Abra o notebook e selecione um runtime GPU.
2. Cadastre `CIVITAI_TOKEN` e `HF_TOKEN` em Secrets no Colab e dê acesso ao notebook. Use credenciais novas, de leitura.
3. Execute as células na ordem. O notebook clona ou atualiza este repo com fast-forward, baixa as versões Civitai solicitadas para a pasta de trabalho, prepara o ComfyUI e inicia o Gradio.
4. O modo de diagnóstico da última célula roda uma geração mínima do Qwen e registra os eventos em `/content/clonfield_runtime/logs/diagnostico-*.jsonl`.

## Componentes

- [Workflows](workflows/) reúne os seis grafos de referência com nomes neutros nos slots de mídia. Abra os arquivos visuais no ComfyUI e exporte como API JSON quando quiser enviá-los pelo Studio.
- [Catálogo Civitai](assets.json) fixa as 18 versões pedidas. O instalador baixa o artefato compatível divulgado no metadado de cada versão e confere SHA-256 quando fornecido. LoRAs reconhecidas vão para `loras/`. Os demais arquivos ficam em `civitai/models/` ou `civitai/workflows/`. Para repetir só uma versão use `python cf_assets.py --version NUMERO`.
- [OpenJutsu](docs/OPENJUTSU.md) usa o código upstream preservado em `vendor/openjutsu/`, com adaptador local e licenças incluídas. O perfil H3 do upstream foi validado na classe de 96 GB.
- [Diagnóstico do Qwen](docs/DIAGNOSTICO.md) explica o que se pode concluir do encerramento anterior e como reproduzir com evidência.

O compartilhamento do Gradio usa senha aleatória da sessão. Logs e pesos ficam no runtime. Os termos dos modelos e dos grafos de terceiros se aplicam aos respectivos arquivos.
