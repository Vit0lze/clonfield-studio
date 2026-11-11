# V7.1 — status por fonte (estados: encontrado → examinado → baixado → sandbox → executado → comparado → produção)

Ambiente desta rodada: CPU, 4 núcleos, 3 GB RAM, sem GPU, sem T4. Nada abaixo foi medido em GPU.

## See-through V3 — camadas de anime → PSD
| Item | Estado | Evidência |
|---|---|---|
| shitagaki-lab/see-through `df019de` | examinado, baixado | Apache-2.0 (LICENSE). README: BF16 ~12-16 GB; group offload ~10 GB; NF4 ~8 GB; block swap ~8 GB (alegações do autor, não medidas aqui) |
| jtydhr88/ComfyUI-See-through `98d754b` (0.5.0) | baixado, instalado em sandbox, **executado até o loader** | MIT só em `pyproject.toml` (sem arquivo LICENSE; registrar). Carrega no ComfyUI 0.44 CPU: 7 nós `SeeThrough_*` em `/object_info` |
| Pesos `layerdifforg/seethroughv0.0.2_layerdiff3d` (~10 GB) | examinado (API do HF) | **OpenRAIL++** — restrições de uso valem para pesos, distinto da licença do código |
| Integração ClonField | integrado | `cf_seethrough.py` (grafo, perfis, pacote PSD/ZIP), `prepare_seethrough.py` (clone fixado), app `seethrough`, passo no notebook (`PREPARE_SEETHROUGH`), ícone |
| Testes | 5 passam | grafo por perfil aceito pelo ComfyUI 0.44 real (validação de tipos/links/combos); PSD gerado com psd-tools e relido (ordem, tamanho, pixel); job completo via API real chega ao loader e falha com "No GPU found" no NF4 (esperado sem CUDA) |
| Camadas reais geradas / PSD do modelo / VRAM / tempo / fidelidade | **NÃO TESTADO** | exige GPU; perfis NF4, BF16+offload, BF16 e block swap seguem pendentes na T4 |
| Block swap | não integrado | só os 3 perfis acima; block swap existe no repo upstream (CLI), não no wrapper ComfyUI |

Observação: o nó `SeeThrough_SavePSD` só grava PNGs + `layers.json` (o PSD vem do navegador via ag-psd);
o ClonField monta o PSD no servidor com psd-tools a partir desses arquivos. Número de camadas varia por imagem.

## Outras fontes
Clonados e licenças lidas: JevRouter `b1cdf80` (MIT), scenario-labs/skills `b96506d` (MIT).
Restante dos 93 links: **encontrado apenas**, nada examinado em profundidade nesta rodada.
