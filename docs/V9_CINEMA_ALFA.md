# Cinema alfa — Timeline.v1 e «A última luz» (V9-P1-CINEMA-001)

Dono do contrato: Opus. Base: `v9/integration` `7c303a0`. Motor: `cf_cinema.py` (CPU, FFmpeg). Sem GPU, sem Remotion.

## Contrato Timeline.v1
```json
{
  "schema": "Timeline.v1", "name": "a-ultima-luz", "title": "A última luz", "fps": 24, "size": [1280, 720],
  "video": [{"id": "s02", "src": "v_…", "dur": 6.0, "speed": 0.5, "loop": false, "pingpong": false, "in": 0,
             "crop": [x, y, w, h], "push": 0.04, "look": "none|dusk|memory", "fade_in": 1.5, "fade_out": 0, "note": "…"},
            {"id": "s01", "src": {"color": "black"}, "dur": 3.0}],
  "audio": {"voice": [{"src": "v_…", "at": 4.0, "in": 0, "dur": null, "gain_db": 0, "fade_in": 0, "fade_out": 0, "loop": false}],
            "music": […], "sfx": […]},
  "mix": {"voice": 0, "music": -3, "sfx": -3, "duck": true}
}
```
- **Toda mídia é uma versão fixada do Asset Graph** (`v_…`). `a_…` é recusado: a versão «atual» mudaria debaixo do corte.
- `crop` em frações do quadro de origem (para onde a câmera olha); `push` = aproximação lenta ao longo do plano; `speed < 1` desacelera com mistura de quadros (`framerate`).
- `id` e `note` não entram na chave: renomear ou anotar um plano não refaz nada.

## Render (o que fica em cache e por quê)
| Passo | Chave (digest do Content Factory) | Sai em |
|---|---|---|
| Plano | versão do render + fps/tamanho + campos do plano + sha256 do blob | `<base>/cinema/cache/segments/<chave>.mp4` |
| Imagem | lista de chaves dos planos | `picture-<chave>.mp4` (concat demuxer, cópia sem recodificar) |
| Trilha voz / música / efeitos | clipes da trilha + sha256 dos blobs + duração total | `stems/<trilha>-<chave>.wav` (float 32) |
| Mix | ganhos + nomes das 3 trilhas + alvo de loudness | `stems/mix-<chave>.wav` |
| Filme | (sempre refeito: só multiplexação, segundos) | `<saída>/<name>.mp4` |

- Cada passo grava em `.part`, move e só então carimba (`mark`). Um render morto nunca deixa carimbo em arquivo pela metade.
- O cache é compartilhado entre timelines: trocar de tomada e voltar reaproveita até a junção antiga.
- Mix: música abaixa sob a voz (`sidechaincompress`), loudness em duas passadas para **−16 LUFS / −1,5 dBTP** (entrega web/celular; transmissão EBU seria −23).
- MP4 final: 1 vídeo H.264 + 4 áudios AAC: `mix` (padrão), `voz`, `musica`, `efeitos` (nome no `handler_name`, que o MP4 guarda). As três trilhas também saem em WAV.

## API
- `POST /clonfield/api/cinema/validate {"timeline": …}` → `{ok, duration_s, shots, versions}` ou 400 com o motivo.
- `POST /clonfield/api/cinema/render {"timeline": …}` → job na fila de **CPU**; resultados: MP4, 3 WAV, timeline, `render.json`; `asset_versions` no job.
- Ainda **sem tela no portal** (a timeline é editada como JSON). Próximo passo de interface.

## «A última luz» — 60 s
Uma filha lembra do farol que o pai acendia; hoje a cidade acende sozinha; ela ainda olha o mar.

| Plano | Tempo | Tomada (todas geradas pelo Studio na T4) | Som |
|---|---|---|---|
| s01 | 0–3 | preto | só o mar |
| s02 | 3–9 | farol no píer, pôr do sol (agente → Wan 2.2 5B), 0,5×, aproximação | voz 1, música entra |
| s03 | 9–16 | feixe girando (Wan 2.2 A14B Q4, loop) | voz 2 |
| s04 | 16–21 | **lembrança, rosto** (v1: Wan 5B Q6 vertical → v2: Wan A14B Q4 LightX2V) | voz 3 |
| s05 | 21–25 | jaqueta verde, mãos (Wan 5B Q6) | — |
| s06 | 25–31 | poste acendendo (agente → Wan 5B) | relé do poste, voz 4 |
| s07 | 31–43 | **farol no azul, luz pulsando, segurado 12 s** (receita Loop → A14B) | **a música sai; o mar sobe** |
| s08 | 43–52 | feixe dourado de novo, apaga em 3 s | voz 5 |
| s09 | 52–60 | preto | buzina de nevoeiro ao longe, o mar some |

Voz: Kokoro-82M int8 pt-BR (`pf_dora`), pelo provider vendorizado da Fábrica. Música e efeitos: **sintetizados em FFmpeg** (marcados como tal), porque o app «Áudio» do Studio (Stable Audio 3) é GPU.

**Escolha que deu força ao filme.** O primeiro corte tinha a música e o mar no mesmo plano; o espectrograma mostrou que o mar cobria a música o filme inteiro, e a saída dela no plano segurado não se ouvia: A e B eram quase iguais. Refiz só o áudio: o mar fica baixo sob a música; quando a última fala do presente termina («Ninguém mais sobe a escada»), a música sai e o mar ocupa o lugar, enquanto o farol azul pulsa sozinho por 12 s, sem voz. A última fala volta no quadro dourado, e o filme acaba em 8 s de preto com uma buzina distante. O que deve ficar é a luz que pulsa sem ninguém e o som que chama no escuro. Comparação: `docs/evidence/V9-P1-CINEMA-001/escolha-silencio-A-vs-B.png` (A = assinado; B = música até o fim, que custou refazer só música, efeitos e mix: 17,4 s, imagem inteira reaproveitada).

**Pendente:** exibição do corte inteiro, com som, por uma pessoa. Revisei por quadros (tira a cada 2,5 s), espectrograma, loudness e transcrição; não assisti.

## Limites conhecidos
- Tomadas de 2–3 s esticadas com 0,5× e loops: o loop de 2 s em s07 repete 6 vezes (lido como pulso do farol, mas é repetição).
- O rosto (s04) é um recorte de 480 px de largura ampliado 2,7×: suave. Upscale (SeedVR2) fica para a T4.
- Whisper base transcreve «acende» como «ascendia» uma vez e inventa «E aí!» aos 50 s sobre o mar (a trilha de voz está em silêncio ali).
- Sem tela no portal; sem exportação OpenTimelineIO (entra quando houver fluxo de edição externo).
