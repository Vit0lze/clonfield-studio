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

Arquivos-chave (sha256, 16 hex): `cf_worker.py` 6e308ef81e28ae13 · `cf_workflows.py` e0ed0e44c37faa94 · `cf_jobs.py` 2f96f298e9712105 · `tests/test_worker_lock.py` 989e8aa5e2568658.
