# V9 — índice de evidências

| Id | Afirmação | Prova | Onde | Ambiente |
|---|---|---|---|---|
| V9-P0-001 | Corrida reproduzida antes do patch | `test_a_second_caller_never_restarts_the_worker_under_a_running_prompt` falhou: pid 1545183→1545196 | `docs/evidence/V9-P0-001-antes.txt` | PC local CPU, worker falso rotulado |
| V9-P0-001 | Corrida eliminada | `tests/test_worker_lock.py` 9 passed (19,2 s) | `docs/evidence/V9-P0-001-depois.txt` | idem |
| V9-P0-001 | `run()` novo funciona com ComfyUI real | `tests/test_comfy_real.py -k latent` 1 passed (18 s) | idem | ComfyUI 0.44 CPU, sem modelo |
| V9-P0-004 | `plan` na rota HTTP | `test_agent_api.py` 5 passed, 1 skip | idem | TestClient, provedor roteirizado |
| V9-P0-005 | 11 pins das fontes (HF `sha` / GitHub HEAD) | `curl` independente bate com os 11 recibos | `docs/sources/` | rede, 23/11 |
| — | `agent_full.py` preservado | cópia do rascunho da sessão 4d6c23af | `tests/agent_eval/agent_full.py` | — |
| — | `plan_eval.py` | **PROVA NÃO RETIDA**: arquivo não existia mais no rascunho em 23/11 | — | — |

| V9-P0-R3/R4 | Corridas do dono eliminadas | 2 testes novos falham com a correção revertida, passam com ela | `tests/test_worker_lock.py` | PC local CPU, worker falso rotulado |
| V9-P1-CINEMA-001 | Retomada após SIGKILL reaproveita planos prontos | `2_resume.reused` = s01–s03 | `docs/evidence/V9-P1-CINEMA-001/demo-report.json` | PC local CPU, FFmpeg 6.1.1 |
| V9-P1-CINEMA-001 | Troca de tomada refaz só ela | `3_swap_s04_to_v2.rendered` = s04 + junção; `same_bytes` 8 planos | idem + `segmentos-sha256.txt` | idem |
| V9-P1-CINEMA-001 | Filme 60 s, 4 áudios nomeados | ffprobe: 1440 quadros, 60,000 s, mix/voz/musica/efeitos | `ffprobe-cut2.txt` | idem |
| V9-P1-CINEMA-001 | Fala inteligível na mix | Whisper base devolve as 5 falas | `whisper-mix-cut2.txt` | idem |
| V9-P1-CINEMA-001 | Silêncio no plano segurado | espectrograma A×B 26–52 s | `escolha-silencio-A-vs-B.png` | idem |

| V9-P1-CINEMA-002 | Pela tela: troca de s04 refaz só s04 + junção; B nada | relatórios das 2 exportações | `docs/evidence/V9-P1-CINEMA-002/tela-*.json` | navegador do app, engine local CPU |
| V9-P1-CINEMA-002 | A/B com imagem idêntica e mesmo volume | `ab.picture_identical` true, −15,9/−15,9 LUFS | idem | idem |
| V9-P1-CINEMA-002 | Tela = API | 9 segmentos com o mesmo SHA-256 da prova pela API | `tela-2-troca-s04-v2.json` × `V9-P1-CINEMA-001/render-cut2-troca-s04.json` | idem |

Arquivos-chave (sha256, 16 hex): `cf_worker.py` 6e308ef81e28ae13 · `cf_workflows.py` e0ed0e44c37faa94 · `cf_jobs.py` 2f96f298e9712105 · `tests/test_worker_lock.py` 989e8aa5e2568658.
