# V9-P1-CINEMA-001 — recibos das fontes

Data: 2026-11-24. Estudo completo (só leitura): `docs/sources/research/V9-CINEMA-FONTES-ESTUDO.md` (Haiku; não executou nada).

## Incorporadas ao Cinema (código usado)
| Fonte | Revisão | Arquivo / função | Licença | Teste |
|---|---|---|---|---|
| Content Factory (jutsuhq/content-factory), já vendorizado | `0ea76329ce23201d11fcfcebc9b236a9e3f58b93` | `engine/factory/core/cache.py`: `digest`, `fresh`, `mark`, **importados**, sem cópia | MIT | `tests/test_cinema.py` (troca de tomada, cancelamento, morte por SIGKILL) |
| Content Factory + adição ClonField | idem | `engine/factory/providers/tts/kokoro_onnx.py` (`load`, `ensure_models`, SHA-256 dos pesos) para a narração pt-BR | código MIT; pesos Kokoro-82M Apache-2.0 (`kokoro-v1.0.int8.onnx` sha256 `6e742170…`) | `tests/demo/cinema_voice.py`; inteligibilidade conferida com Whisper base (`whisper-mix-cut2.txt`) |
| `kokoro-onnx` (PyPI) | 0.6.1 | dependência do provider acima, instalada no venv local | MIT | idem |
| FFmpeg | 6.1.1 (Ubuntu) | concat demuxer, `framerate`, `zoompan`, `sidechaincompress`, `loudnorm` (2 passadas), `ebur128`, `aevalsrc`/`anoisesrc` | LGPL/GPL (binário do sistema, já dependência do Studio) | `tests/test_cinema.py` |
| ClonField Asset Graph | `7b6f043` | `cf_asset_graph.publish/add_version/resolve/get_version/verify` | do projeto | troca s04 v1→v2, v1 continua verificável |
| `faster-whisper` (PyPI) | 1.2.1, modelo `Systran/faster-whisper-base` | só verificação (transcrever a mix) | MIT | `whisper-mix-cut2.txt` |

## Estudadas e não incorporadas
| Fonte | Revisão | Licença | Decisão / cena futura |
|---|---|---|---|
| ComfyArt | `5ce7609` | MIT | Snapshots de projeto no canvas. Futuro: versões de máscara e referência por tomada, quando o Cinema tiver tela |
| Creativefield | `e8caee9` | **GPL-3.0** (só ideias) | `previs-to-video`, `flux2-klein-angles`. Futuro: plano de bloqueio (grey-block) antes de gerar uma cena com ação |
| ComfyUI-Panorama-Stickers | `732146a` | MIT | `core/cache.py` (LRU limitado em bytes) é o próximo passo do nosso cache, que hoje não tem limite de disco. Futuro: plano de estabelecimento girando no mesmo cenário |
| Imagination Studio | `16f00b4` | código Apache-2.0; pesos citados não comerciais | `app/shot.py` (checagem de quadros-chave e cortes). Futuro: roteiro → planos → versões, quando o Storyboard alimentar a timeline |
| Paint a Plate | `d95292c` | Apache-2.0 | Correção no 1º quadro propagada; pede GPU de 32 GB+. Futuro: limpar um objeto indesejado de uma tomada boa |
| Depth Pro 2 (apple/DepthPro2 + conversões) | ver estudo | **apple-amlr: só pesquisa não comercial**, inclusive derivados | **DESCARTADO** para integração. Não foi testado aqui. Prévia 2.5D fica sem modelo até achar pesos com licença aberta |
| OpenTimelineIO | v0.18.1 | Apache-2.0 | Exportar a timeline quando existir edição fora do Studio |
| Remotion | — | licença própria | Fora deste lote (decisão do dono) |

## Não lidos / não encontrados
- O vídeo `youtube.com/watch?v=ddirEBVYVno`: só título e descrição; não foi assistido nem transcrito.
- `comfy.org/open-source-higgsfield#challenge-content`: a âncora não existe na página; a lista do estudo veio da seção de vencedores.
- O índice maior dos «milhares de repositórios» continua sem endereço.
