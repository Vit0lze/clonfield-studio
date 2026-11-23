# AUDITORIA PRÉ-OPUS — ClonField Studio (23/11/2026)

Evidência, não autoelogio. Cada afirmação aponta a fonte (arquivo, linha, commit, transcrição). Onde o artefato sumiu está escrito **PROVA NÃO RETIDA**.
Regras seguidas: nenhuma feature nova, nenhuma suíte completa, nenhuma GPU, nenhum push, nenhum segredo (links e senhas de sessão nunca aparecem; o `.env` fica fora do repositório).
Datas: as das transcrições (`~/.claude/projects/-home-lze-Documents-ClonField/*.jsonl`) estão em UTC; as dos arquivos em disco, no fuso local (UTC−3).

---

## 1. Estado do git (transcrito)

```
HEAD                 71be0ab7a7f5689bc6bb7f5afa2725a0c7ed3e4e
origin/main          71be0ab7a7f5689bc6bb7f5afa2725a0c7ed3e4e   (ahead/behind: 0 / 0)
git status --short   (vazio)
git log -10 --oneline
  71be0ab CLAUDE.md: commands, architecture and the memory rules measured on the Colab T4
  03eddfb docs: detailed changelog of the GPU validation (27 commits since the V8 changelog)
  201a9e1 Agent jobs expose their plan (capability + params of each step) on /jobs/{id}
  e466560 docs: GPU validation report updated with the 12.7 GB lessons ...
  65eaaae Restart the ComfyUI worker before any GPU job when it holds more than 7 GB ...
  99ae52e The Studio restarts the ComfyUI worker itself (only the process on its port) ...
  603b5a9 Wan family is per model: switching 5B -> A14B frees ComfyUI first ...
  60cba8b /system reports the ComfyUI worker's resident memory (worker_rss_gb) ...
  a38526f Validation refuses a graph whose required param is empty ...
  272dc32 Agent: shortcut ids in the system prompt ..., 14 steps; the validator requires a job
git stash list       stash@{0}: WIP on main: e466560 docs: GPU validation report updated ...
```

- **Tudo está no GitHub.** Não existe commit local à frente de `origin/main`.
- **Só existe localmente:** (a) o **stash `stash@{0}`**, que contém o prompt novo do agente: `cf_agent.py`, +5 linhas (`git stash show --stat`), regras de prompt em inglês, cena × movimento e palavras ambíguas; **nunca foi medido nem commitado**; (b) as pastas `tests/gpu/out*/` e `tests/gpu/a14b-q4-loop.mp4` (ignoradas pelo git: `.gitignore` `tests/gpu/out*/` e `tests/gpu/*.mp4`).
- **`plan_eval.py` EXISTE**: `/tmp/claude-1000/-home-lze-Documents-ClonField/4d6c23af-8df8-4bd0-9039-47ced3e612de/scratchpad/plan_eval.py` (2731 bytes, 23/11 08:54), com `agent_full.py`, `agent-full.log`, `plan-antes.log`, `plan-antes2.log` na mesma pasta. **Não está no repositório**: é rascunho em `/tmp` e some num reinício. As pastas de rascunho da sessão anterior (`f9114512…`), onde estavam os logs de quase todas as rodadas de GPU, **não existem mais**.
- O resultado de `plan_eval.py`: `ANTES TOTAL img 0/6 vid 0/6` com **todos os prompts vazios**. **É INVÁLIDO como linha de base**: o `llama-server` estava fora do ar (`/llm: available False`), o agente não respondeu e nenhum plano foi lido. Não existe, portanto, medida do prompt antigo nem do novo.

---

## 2. Cada afirmação `TESTADO GPU` de `docs/VALIDACAO_GPU.md` → prova

Hardware em todas: Colab, Tesla T4 15 GB, 12,7 GB de RAM (`case_system` → «GPU Tesla T4 · VRAM 15.0 GB · RAM 12.7 GB · worker ok»). Comando-base: `python tests/gpu/validate_remote.py --only <caso> --out tests/gpu/<pasta>` (lê `api=` e `bearer=` do `../.env`, troca a senha por token em `/clonfield/connect`, baixa e confere cada arquivo). **Casos que NÃO passaram pelo validador** (rodados por scripts avulsos de rascunho, hoje apagados): o `animate` manual com campos omitidos, o A14B direto (`a14b_q.py`), a comparação 5B × A14B (`anim_cmp*.py`), o acompanhamento do job do agente (`agent_full.py`, este existe), a Fábrica (`factory_run.py`). O **código desses scripts não foi retido** (exceto `agent_full.py` e `plan_eval.py`); os **arquivos de mídia que eles geraram foram retidos**.

SHA-256 abaixo são os 16 primeiros hex (os completos estão no Apêndice A). `ffprobe` = `validate_remote.check_file` mais o `ffprobe` que rodei nesta auditoria.

| Afirmação | Caso / script | Data (UTC) | JSON bruto | Mídia e SHA-256 | ffprobe | Falhas observadas / ressalva |
|---|---|---|---|---|---|---|
| Qwen 2.1 Turbo 95–344 s | `create_turbo` | 15/11 a 22/11 | `out/…020403`, `out2…`, `out3…154817`, `out4`, `out7`, `out9`–`out14` | `out/create_turbo/…` `cb0ecb5b2dd1e5e2` e outras 10 | 768×768 | **O intervalo do doc está errado**: dos 11 resultados OK, min **93,4 s**, max **372,2 s** (`[93.4, 95.5, 102.7, 102.9, 123.7, 237.5, 250.5, 257.1, 300.2, 343.9, 372.2]`). Mesmo nome de arquivo (`15d47e0c576550d5.png`) em rodadas diferentes tem SHA diferente: o nome não identifica o conteúdo |
| Qwen padrão 284 s | `create_std` | 15/11 | `out/results-20261115-020403.json` | `out/create_std/00-63285e61fb01c563.png` `9efe7ace02fcbb3f` | 768×768 | uma única medida |
| Upscale RealESRGAN 21,6 s | `upscale_gpu` | 15/11 | idem | `out/upscale_gpu/…` `8e425dba71d8e47f` | 1536×1536 | o «4x UltraSharp 457 s» do agente **só existe na saída de uma ferramenta na transcrição** (`4d6c23af`, 22/11), sem arquivo: PROVA NÃO RETIDA |
| «Melhor de N sementes», «Cenários em matriz», «Animatic» | `recipe_seeds`, `recipe_matrix`, `recipe_animatic` | 15/11 | idem | `out/recipe_seeds/00-image.png` `c953d3253a99793a`; `recipe_matrix` `a3c0cdaf6fcd93c7`, `6be559787461bb3a`; `recipe_animatic` `…/01-video.mp4` `e8fbbd16ff10a722` | 1536², 1002×542 e 768², 1280×720 24 fps 2,00 s, movimento 74,86 | **«sementes por item geram imagens distintas» NÃO tem prova em arquivo**: só a melhor imagem foi salva; a outra semente não |
| Remover fundo 7 s | `case_cpu_apps_all` (app `removebg`) | 22/11 | `out19/results-20261122-215315.json` | `out19/cpuapp_removebg/…` `2f18b040aa3ee08a` | 640×480 | no Colab o app mediu **8,8 s**. O «7 s» veio de um job manual (`manual_jobs.py`): PROVA NÃO RETIDA (resta `out-extra/removebg/…` `daa25229dc4c6fd3`, 768×768) |
| Wan 5B 350–478 s | `anim_cmp.py` (avulso), fora do validador | 22/11 | **não há JSON** | `out-cmp/5b-q6/…` `536a892844cd2e24` (832×480); `out-cmp3`, `out-cmp4`, `out-cmp5` (480×832, 3,04 s) `d42dc1bc69271a95`, `b38ddc6f974df13d`, `8c775d24f5e53a49` | 24 fps, 3,04 s | **os tempos (349,8 / 353,5 / 459,5 / 478,6 s) só existem na transcrição** (saída de monitor); logs apagados. Movimento medido 5,26–7,08 |
| «Planos em filme», «Storyboard em filme» | `recipe_shots_film`, `recipe_story` | 20/11 | `out3/results-20261120-154817.json` | `out3/recipe_shots_film/…` `a09566a883aeb4cb`; `out3/recipe_story/…` `f45d71150031e19f` | 1280×720 24 fps 4,08 s; movimento 13,43 e 85,23 | a falha anterior dos dois (`out2`) foi o Studio caído (404), não bug da receita |
| «Personagem pronto» | `recipe_character` | 20/11 | `out4/…163544.json`, `out5/…171526.json` | `out4/recipe_character/…` `b8acc1dfc2bdb5f7` (entrada: farol); `out5/recipe_character/…` `7c4135db0a060148` (entrada: `out5/character_source/…` `45172cc8b38db4f2`) | 2700×1084 | `out3` registra a mesma receita com **timeout de 1500 s** (cancelada pelo validador). A «identidade mantida» é julgamento visual meu, sem métrica |
| Fábrica de vídeo 1381 s | `cpu_apps_all` e `factory_run.py` | 22/11 | `out19/…215315.json` (1435,8 s no caso, fábrica 1381,7 s) | `out19/cpuapp_factory/00-fabrica-194380526e20.mp4` e `out-factory/factory/00-fabrica-ddf66ed9fc10.mp4`, **mesmo SHA-256 `c29711044d57d50e`** | h264 1080×1920 30 fps + aac, 31,80 s; volume médio −17,2 dB | duas execuções independentes (~1385 s cada) geraram **bytes idênticos**: pipeline determinístico **ou** artefato reaproveitado; **não verifiquei qual**. O QC acusou «MILLIONS OF YEARS» com 17 caracteres (máx. 12) |
| A14B Q6_K «não cabe, morreu 4×» | `recipe_loop` | 20/11 | `out7`, `out9`, `out10`, `out11` (worker morto), `out12` (Studio perdido, 404) | sem mídia | n/a | **Atribuição corrigida:** os 4 «worker morreu» são Q6_K (`out7`: LLM residente; `out9`: LLM dormindo; `out10`: variável `CLONFIELD_COMFY_EXTRA` **não aplicada** (log com `fast_disk=False`); `out11`: `--fast-disk` aplicado; e `out12`, com `--disable-pinned-memory`, que derrubou o Studio inteiro). `out13` (22/11) é **Q4_K_S em um prompt só e também falhou**; o único sucesso do Q4_K_S em um prompt foi o app direto `a14b_q.py` (arquivo `out-a14b-a14b-q4/…` `92c78aa3ae416b5d`, 832×480 16 fps 2,06 s, **o log foi apagado**) |
| A14B Q4_K_S em dois prompts, 361 s | `recipe_loop` | 22/11 | `out14/results-20261122-185014.json` | `out14/recipe_loop/00-video.mp4` `f358ed4aecc5f68b` | 832×480 16 fps 2,06 s, **movimento 1,01** | «Entre dois quadros»: o vídeo quase não se mexe |
| A14B depois do 5B, 537,7 s, worker 8,4 → 4,4 GB | `anim_cmp5.py` (avulso) | 23/11 | **não há JSON** | `out-cmp5/a14b-q4-fast/…` `8604d4854947f2fd` | 480×832 16 fps 3,06 s, movimento 5,41 | **tempo e leituras de RSS só na transcrição** (`4d6c23af`); log apagado |
| LLM no CUDA | colagem do usuário | 20/11 17:40 | **PROVA NÃO RETIDA como arquivo** | n/a | n/a | única prova: mensagem do usuário na transcrição `f9114512…jsonl`, linha 2027 («`CUDA0: Tesla T4 (14912 MiB, 14807 MiB free)`»), colada do `llama-server --list-devices` |
| Agente monta a cadeia, 907 s | `agent_full.py` + `agent-full.log` | 23/11 | log em `scratchpad/…/agent-full.log` (existe) | `out-agent/agent_job/00-result.mp4` `96e95966e083efff` | 832×480 24 fps 3,04 s, movimento 8,78 | **o conteúdo não bateu com o pedido** (seção 4). Os 907 s e o RSS 8,12 GB vêm desse log |
| LLM acorda em 37–48 s | `agent_full.py` | 22–23/11 | só `WAKE 48 s` no `agent-full.log` | n/a | n/a | os 37 s e 42 s **só na transcrição** |
| `POST /jobs` aceita campos omitidos | job manual + teste | 22/11 | **PROVA NÃO RETIDA** (job manual) | n/a | n/a | o que existe: `tests/test_agent_api.py::test_job_submit_fills_omitted_fields_with_the_form_defaults` (CPU, local) |
| Validação recusa parâmetro obrigatório vazio | `agent_chain` (`out17`/`out18`/`out19`) | 22/11 | `out17`: «não montou … `limite de passos`»; `out18`, `out19`: `compose_chain` repetido | n/a | n/a | **as mensagens de recusa não foram guardadas**; só o rastro mostra `compose_chain` várias vezes. A prova forte é o teste local `tests/test_dag.py` (10 passed na sessão) |
| Reinício do worker (5B → A14B passa) | `anim_cmp5.py` | 23/11 | sem JSON | `out-cmp5/…` acima | acima | números de RSS só na transcrição; sem log retido |

**Correções às minhas declarações anteriores, achadas nesta auditoria**
1. `docs/VALIDACAO_GPU.md` diz «`/free` não devolve a RAM». **Foi um exagero.** O `agent-full.log` (linha `FIM`) mostra o worker indo de **8,12 GB para 3,83 GB** depois do `/free` que antecede o despertar do LLM. O que as medidas sustentam: `/free` devolve **parte**; sozinho não bastou para o A14B (morreu depois de um 5B); só o processo novo chegou a ~1,2–1,3 GB.
2. O intervalo do Turbo no doc está errado (acima).
3. «Sementes por item geram imagens distintas» não tem prova em arquivo.
4. A atribuição das falhas do Q6_K (acima).

---

## 3. Últimas mudanças sem suíte completa

Última suíte completa de verdade (uma invocação de pytest): **408 passed, 0 failed, 19 skipped, 118,17 s**, 20/11 22:26 UTC, na sessão `f9114512`. O **419** do relatório GPU **não é uma invocação**: é a **soma que o meu script fez de 43 arquivos rodados um a um** (`/tmp/run-tests.sh`), 22/11, sobre a árvore de `0d75d05`. Nenhum relatório cobre `99ae52e`, `65eaaae`, `201a9e1` com a suíte inteira.

| Commit | Teste focal executado (e quando) | Lacuna |
|---|---|---|
| `99ae52e` `cf_worker.py` | `tests/test_worker_restart.py`: **5 passed em 7,8 s**, 23/11, uma execução (saída só na transcrição). **Agora**, ad hoc: dois workers falsos em portas diferentes; `restart(A)` mudou o pid de A (1534768 → 1534773) e **B ficou intacto** (1534769 = 1534769, ainda respondendo); nada sobrou nas portas | (1) o teste `test_a_look_alike_on_another_port_is_never_found` **é fraco**: só consulta uma porta onde não há processo, passa trivialmente (a prova de verdade é o ad hoc acima, que **não está no repositório**); (2) o caminho «reviver um worker morto» (`ensure_up`) foi testado só com o falso, **nunca na T4**; (3) o reinício **real** na T4 só foi exercitado pelos gatilhos do A14B (5B→A14B passou) |
| `65eaaae` reinício antes de qualquer job de GPU acima de 7 GB | **nenhum teste focal.** Só `py_compile` | **Nunca disparou na T4**: o único job depois do commit (`agent_full.py`) começou com RSS 1,16 GB. O gatilho `restart_if_bloated(SERVER, 7)` em `cf_workflows.py:340` nunca foi exercitado com worker acima do limite; o valor 7 GB é uma escolha minha baseada em 2 medidas (6,48 e 8,38 GB) |
| `201a9e1` campo `plan` em `/jobs/{id}` | agora, ad hoc: um `Manager` real recebeu um job com `params={"run","plan"}`, gravou em `jobs/<id>.json` e **um segundo `Manager` sobre a mesma pasta restaurou o `plan` idêntico** (`True`/`True`, status `concluído`) | **a rota HTTP `/jobs/{id}` nunca foi chamada com um job do agente**, nem local (sem teste) nem na T4 (a linha de base saiu com o LLM fora do ar). `cf_api.py:140-142` (`public_job`) só foi lido |
| dependentes | `603b5a9` família por modelo (`cf_apps.py`): `py_compile` + `test_wan.py` (38 passed, antes) — não reexecutado depois; `60cba8b` `worker_rss_gb`: verificado na T4 (valores 1,19, 6,48, 9,13…); `a38526f` validação: `test_dag.py` 10 passed; `272dc32`: `test_agent*` 16 passed | `a38526f` altera `cf_dag.validate` para **todas** as receitas: foi checado contra as 11 receitas e 10 apps de CPU **na T4** (`out19`), não pelo pytest completo |

**Como comprovar «reinicia só o processo autorizado e sem interromper jobs concorrentes»**
- **Só o processo autorizado:** provado agora (dois workers, uma porta cada; `cf_worker.find(port)` filtra por `--port`). Resta o teste forte virar teste do repositório.
- **Sem interromper jobs concorrentes — NÃO É GARANTIDO.** O reinício acontece dentro de `workflows.run`, chamado pela **única** thread de GPU do `Manager` (`cf_jobs.py`, thread `cf-gpu`), então dois jobs de GPU do Studio não se sobrepõem. Mas: **`cf_lab_ui.py:283` e `studio_app.py:211, 375, 390` chamam `workflows.run` fora do `Manager`** (modo clássico do Gradio). Se alguém usar o modo clássico enquanto um job do Studio roda, o `restart_if_bloated`/`ensure_up` daquela chamada pode matar o worker no meio do job do Studio. A prova mínima: um teste com worker falso que **mantém uma requisição aberta** enquanto uma segunda `workflows.run` dispara o reinício, verificando que a primeira morre. **Não existe.**
- **`plan` persiste de verdade:** persistência no `Manager` provada agora; exposição HTTP não.

---

## 4. O caso farol/ondas → poste de rua

**O que está retido e o que não está**
- Pedido (de `agent_full.py`, em disco): «crie uma imagem de um farol ao entardecer, depois amplie 2x e faça um vídeo curto dela com as ondas se movendo».
- Saída: `out-agent/agent_job/00-result.mp4` (`96e95966e083efff`, 832×480, 24 fps, 3,04 s, movimento 8,78). Os quadros mostram **um poste de rua com lâmpada acesa ao entardecer, árvores e casas ao fundo, sem mar nem ondas**.
- Rastro de ferramentas desse caso (`agent-full.log`): `compose_chain, inspect_capability ×3, compose_chain, compose_chain`, `stop: job de GPU iniciado`, job `job_3294437207674cfe`.
- **Os parâmetros efetivos de cada etapa, o `capability_id` exato, o modelo e a seed DESSA execução NÃO FORAM RETIDOS.** O campo `plan` só passou a existir depois (`201a9e1`); o rastro da sessão (no Colab) guarda os argumentos cortados em 300 caracteres e foi perdido quando a GPU foi desligada. **Seed: nunca registrada** (padrão do app é −1, aleatória).

**O que as transcrições mostram de execuções vizinhas do mesmo pedido** (`4d6c23af…jsonl`):
- linha 2403 (23/11 00:09 UTC): tentativa do agente com `app.create` `{"model": "realistic-v4", "prompt": "farol ao entardecer"}` e `upscale {"mode": "4x UltraSharp (nitidez)"…}`: **a validação recusou** (modelo inventado).
- linha 3590 (23/11 11:50 UTC): `compose_chain` com `app.create` `{"prompt": "farol ao entardecer, ondas no mar, luz dourada, atmosfera mágica", …}` (truncado em 300 caracteres; o prompt do vídeo está **fora** do trecho).
- job `job_…8585413b` (22/11, pedido sem «ondas»): `app.create {"model": "flux2", "prompt": "farol ao entardecer"}` (364 s), `upscale {"mode": "4x UltraSharp (nitidez)", "scale": 2}` (457 s), `app.animate {"prompt": "farol ao entardecer", "model": "5b-q6", "seconds": 3}`.

**Onde o sentido se perdeu (inferência, não prova):** em todos os planos observados o prompt está **em português, curto e sem desambiguar «farol»**; o `flux2` é um modelo pequeno (klein 4B) que pode ter lido «farol» como poste de luz. Os dois trechos que tenho do prompt de **vídeo** repetem a cena («farol ao entardecer») em vez de descrever **movimento**. O que **não sei**: se o prompt de vídeo do caso das ondas continha «ondas».

**A/B:** **não foi feito.** O que existe: `plan_eval.py` (3 pedidos × 2 tentativas, orçamento fixo, lendo `plan`) + o stash com o prompt novo. A linha de base falhou (LLM fora do ar). Regra para o A/B correto: mesmo LLM carregado, mesmos 6 pedidos, mesma sessão do Colab, ler o plano e **separar** «plano correto» (prompt de imagem com *lighthouse*, prompt de vídeo com *wave*) de «vídeo visualmente correto» (olhar os quadros; um plano certo pode gerar um poste).

---

## 5. As 93 fontes

Fontes de dados: `~/Downloads/CLONFIELD_STUDIO_V7_1_PROMPT_PLANO_E_FONTES_2026-11-10/CLONFIELD_STUDIO_REGISTRO_COMPLETO_LINKS_2026-11-10_v7.md` (93 URLs exatas), `docs/BACKLOG_CAPACIDADES_APPS.md` (matriz), código e as 8 transcrições. **A tabela completa, uma linha por fonte, está no Apêndice B** (gerada por script).

**O que o script encontrou**
- 93 URLs no registro; 81 têm linha na matriz e **12 não aparecem na matriz** (`NÃO ACHADO NA MATRIZ`).
- Estados **declarados** na matriz: NÃO INICIADO 20, CÓDIGO ESCRITO 21, TESTADO CPU 16, ESTUDADO 12 (inviável na T4 / dispensado / sem código), TESTADO API REAL 3, TESTADO GPU 3, BLOQUEADO_GPU 2, baseline 4.
- **Só 15 das 93 têm prova de busca/leitura real** (WebFetch, WebSearch, `curl`, `git clone`…) nas transcrições; e nenhuma dessas provas distingue leitura de README de leitura de código linha a linha. **As outras 78 estão «só listadas»** do ponto de vista do que eu posso comprovar. `docs/V7_STATUS.md:21` já dizia: «Restante dos 93 links: **encontrado apenas**, nada examinado em profundidade».
- 36 fontes são citadas em código ou docs (arquivo:linha no Apêndice B); 19 têm licença registrada; **só 8 têm pin de versão/commit no código**.
- **Ferramentas web nas transcrições deste projeto:** 6 consultas **distintas** em 8 arquivos (as sessões bifurcadas repetem as mesmas): 2 `WebSearch` (FLUX.2 Klein; o erro `metadata_errors`), 3 `WebFetch` (blog.comfy.org sobre o Klein, a página do FLUX.2-klein-9B no Hugging Face, o FAQ do Colab) e 1 subagente de QA. As 15 fontes com «prova» do script vêm de outra via: comandos `curl`/`git` na sessão `86ce2124` e `5095613a` (V8). O resto do que o repositório declara «lido» **não tem prova localizável aqui** (as sessões de 10–13/11, onde o V7 foi montado, têm transcrição em outras pastas de `~/.claude/projects/` que a busca também varreu sem achar mais consultas).

**As 20 `NÃO INICIADO`** (todas listadas no Apêndice B com o que a própria matriz diz): portal público `clonfield-studio-portal.vercel.app`; 2 vídeos do YouTube («não assistido»); doc do MCP do Comfy; 3 projetos do ecossistema See-through («depende das camadas reais»); 1 Space de demo; 7 workflows/LoRAs do Civitai e 2 do Comfy Hub («abrir o JSON e comparar»); um workflow de `comfy.icu`; o perfil `PrunaAI`; a variante INT8 do Klein. **Motivos, segundo a matriz:** «não aberto», «não assistido», «depende das camadas reais». Não há outro motivo registrado e eu não vou inventar um.

**Inconsistências de status achadas:**
- `docs/V7_STATUS.md:20-30` ainda diz «Provedor Jev remoto: **integrado e testado ao vivo**», mas o Jev/TypeSafe foi **removido** (HANDOFF: «Sem Jev/TypeSafe (removido em 2026-11-13)»). Status enganoso.
- A matriz marca `FLUX.2 klein` e 2 URLs vizinhas como `TESTADO GPU` com a evidência «512², 4 passos, 280 s com download» (anterior à validação desta semana). **PROVA NÃO RETIDA** dessa execução; na semana passada o FLUX.2 klein rodou de fato no `recipe_story` (`out3/recipe_story/…`, 922 s com 7,2 GB de download).
- A matriz não foi atualizada com os resultados da T4 desta semana (ex.: Wan 2.2 5B e A14B, llama.cpp, Qwen 2.1 constam com estados anteriores).

---

## 6. Lacunas de execução (feito / parcial / não feito)

| Item | Estado | Evidência | Próxima prova mínima |
|---|---|---|---|
| `LoraLoader` real (LoRA do usuário em `cf_model_lab.py:196`) | **não feito** | `grep -in lora tests/gpu/validate_remote.py` → **zero ocorrências**; nenhum caso do validador usa LoRA | um `create` com uma LoRA, ~100–300 s (tempo do Turbo) e comparar com e sem |
| `LoraLoaderModelOnly` (LightX2V, `cf_wan.py:208-209`) | **parcial** | executou nas rodadas do A14B rápido (`out14`, `out-cmp5/a14b-q4-fast`: o job concluiu com os nós `60/61` no grafo) | A/B com e sem o modo rápido; **o efeito da LoRA nunca foi medido** |
| See-through → PSD real | **não feito na GPU** | `tests/test_seethrough.py`: 3 testes, 2 skips; sem caso no validador | 1 job `seethrough` na T4 e abrir o PSD |
| Stable Audio 3 gerando WAV | **não feito** | `tests/test_audio.py`: 7 testes (3 tocam o ComfyUI de CPU, sem gerar áudio); sem caso no validador | 1 job de áudio e `ffprobe` do WAV |
| Vídeo FaceFusion / FaceSwap | **proibido no Colab** (`PREPARE_FACEFUSION=False`); `tests/test_faceswap.py` **excluído de todas as rodadas** (precisa de instalação) | «TESTADO CPU» só no changelog V8 (15/11); **prova de execução não retida** | rodar `tests/test_faceswap.py` localmente com FaceFusion instalado, **não no Colab** |
| 3D GLB | **não feito** | `tests/test_3d.py` 8 testes (2 tocam ComfyUI de CPU), sem geração | 1 job «Imagem→3D» e validar o GLB |
| Apps com offload (SCAIL-2, Animate 2, OpenJutsu) | **não feito** | nenhum caso | 1 job por app (24 GB de pesos: **não cabe** em 12,7 GB de RAM; testar só a mensagem de aviso) |
| `run_eval.py --chains` com o Qwen real | **não feito** | `tests/agent_eval/run_eval.py:133` define a flag; **nunca rodou** com o modelo; o `agent_chain` do validador é 1 pedido, não a avaliação | `run_eval.py --chains` com o LLM no ar, só LLM (sem GPU pesada) |
| Legendas automáticas | **não feito** | não há implementação | sem modelo de transcrição para 3 GB de RAM local |

---

## 7. Relatórios de teste, janela por janela

| Janela / relatório | HEAD testado | Resultado | Excluídos / observações |
|---|---|---|---|
| V8, pytest completo | árvore de `f349e71` + mudanças locais (sessão de 14–15/11) | **383 passed, 0 failed, 19 skipped**, 72,7 s (15/11 02:26 e 02:54 UTC) | excluídos: `test_comfy_real`, `test_faceswap`, `test_live`, `test_resilience_live` |
| V8, Playwright | idem | **185 passed** (15/11 03:01 e 03:14 UTC), Chromium + engine real | **não reexecutado desde então**; relato de 1 flake em 1 rodada e 3 reexecuções limpas (changelog), causa não identificada |
| Depois do `d6a72b7` | árvore de `bbeb8ae` | **391 passed, 19 skipped**, 83,2 s (15/11 13:22 UTC) | mesmos excluídos |
| Depois do LLM dormindo | árvore de `4b55197` | **408 passed, 19 skipped**, 118,17 s (20/11 22:26 UTC) | mesmos excluídos; **a última invocação completa** |
| «419» do relatório GPU | árvore de `0d75d05` | **soma de 43 arquivos rodados individualmente** (417 antes do despertar, 419 depois) | não é uma invocação de pytest; 0 falhas |
| Depois | `272dc32`, `a38526f`, `60cba8b`, `603b5a9`, `99ae52e`, `65eaaae`, `201a9e1` | só arquivos isolados: `test_dag` 10, `test_llm_release` 14, `test_agent` 16, `test_agent_api` 4+1 skip, `test_worker_restart` 5, `test_comfy_real` (32 passed, 22/11) | **sem suíte completa** |

- **Skipped = 19 estável desde 14/11.** Causas estáticas (marcadores): sem rede; sem `llama-server` (`test_agent*`, `test_chat`); sem colibri; sem `HF_TOKEN`/`CIVITAI_TOKEN`; sem `ffmpeg`; `CLONFIELD_SLOW` ausente (`test_factory.py:48`); FaceFusion não instalado; ComfyUI de CPU ausente. **Quais dos 19 são quais: não listei** (exigiria rodar).
- **Crashes da máquina:** 9 ocorrências de `Exit code 137` em `tool_result` nas transcrições (11/11, 13/11, 14/11 ×2, 15/11, 22/11 18:35 e 23:42 UTC), fora as 3 quedas do PC relatadas pelo usuário (algumas coincidem com as acima).
- **`CLONFIELD_FAKE_VRAM=15` não é prova de T4.** Ele só faz `cf_tiers` fingir uma placa de 15 GB; os testes locais não carregam modelo. A única prova de T4 é o que passou pelo `validate_remote.py` ou por mídia baixada do Colab. `tests/test_comfy_real.py` valida grafos contra o registro de nós de um ComfyUI real em CPU e executa **cadeias de nós minúsculas** (ex.: `SaveLatent`/`LoadLatent` de um latente vazio): **não é execução de modelo**.

---

## 8. O que preservar e o que corrigir

**Decisões arquiteturais que se sustentam (com evidência):**
- Registro de capacidades tipado + executor de DAG (`cf_capabilities.py`, `cf_dag.py`): exercitado na T4 pelas 11 receitas de CPU, 6 receitas de GPU e o agente; `test_dag.py`, `test_capabilities.py`.
- Cache por hash e reexecução parcial: testes locais (`test_dag*`); **não medido na T4**.
- Fila de jobs com uma faixa de GPU e persistência (`cf_jobs.py`): persistência provada agora; a faixa serial é o que impede dois jobs de GPU de colidir.
- Agente local sobre ferramentas (`cf_agent.py`): montou a cadeia e iniciou o job na T4 (`out18`, `out19`, `agent_full`).
- Catálogos por arquivo com revisão, tamanho e SHA fixados (`cf_wan.py`, `cf_llama.py`, `assets.json`): download de ~17,5 GB em ~3 min com verificação.
- A14B em dois prompts + reinício (`cf_wan.split_a14b`, `cf_apps.run_a14b_staged`, `cf_worker.py`): funcionou na T4 depois de 5B.
- Validação remota por API real (`tests/gpu/validate_remote.py`): detectou 7 defeitos reais.

**Antipadrões ainda presentes (caminho:linha)**
| Antipadrão | Onde | Observação |
|---|---|---|
| Motor duplicado / caminho fora da fila | `cf_lab_ui.py:283`; `studio_app.py:211, 375, 390` | o modo clássico chama `workflows.run` sem passar pelo `Manager`: sem faixa serial, sem `before_gpu`, e agora **pode matar o worker de um job do Studio** (seção 3). O README ainda anuncia «o Gradio antigo continua no link raiz» |
| Status enganoso | `cf_jobs.py:178-180` | `files = runner(ctx) or []` → `status="concluído"` mesmo com **lista vazia**: um job «concluído» sem arquivo |
| Status enganoso | `docs/V7_STATUS.md` (Jev «integrado e testado ao vivo», removido depois); matriz de 93 fontes sem os resultados da T4; `docs/VALIDACAO_GPU.md` («`/free` não devolve») | ver seções 2 e 5 |
| Fallback silencioso | `cf_api.py:84-90` (`except Exception: pass` ao capturar o worker); `cf_worker.py:53`; `cf_wan.py:83-93` (`total_ram_gb` devolve 0.0 e `memory_problem` **deixa passar** o Q6_K se não conseguir ler a RAM); `cf_llama.py:215-217` (`gpu_loaded` devolve `False` sem `nvidia-smi`); `cf_apps.py:720-723` (se `cf_worker.restart` falha, cai para `/free` **sem avisar o usuário**); `cf_workflows.py:340` (o retorno de `restart_if_bloated` é **ignorado**: se o reinício falha o job segue contra um worker possivelmente morto) | vários **são meus**, dos últimos dias |
| Fallback silencioso (pré-existente) | `cf_workflows.py:114,125,132`; `cf_apps.py:491`; `cf_civitai.py:384,441,464`; `cf_diagnose.py:42,57` | `except …: pass` de «melhor esforço» |
| Conteúdo genérico/visualmente ruim | vídeos medidos: A14B em loop com movimento 1,01 (`out14`); Wan 5B quase parado (~5); filme do farol com objetos flutuando; folha de personagem com faixas cinza (`out5`); Fábrica com texto de 17 caracteres (máx. 12) | julgamento visual meu; **sem métrica de aderência ao pedido** |
| Placeholder, UI sem mídia, botão sem ação | `grep` de `TODO/FIXME/stub/NotImplemented/em breve` em `cf_*.py`, `studio_app.py`, `portal/js`: **só** `cf_comfy_check.py:4` (placeholder de arquivo para validação) e o objeto `placeholder` de upload em `portal/js/views/app.js:390-397` (legítimo) | **«botão sem ação» e «UI sem mídia real» NÃO foram auditados**: exigem abrir a interface; o e2e (185) cobre rotas e fluxos, não a geração real |
| Retrabalho | A14B: 7 rodadas (`out7`–`out13`) até chegar ao desenho final; prompt do agente reescrito 3× | custo de GPU/tempo, não defeito de código |

---

## 9. Matriz de lacunas (para o Opus distribuir)

Duração = medida onde existe; «não medida» onde não.

| # | Lacuna | Severidade | Por que importa ao usuário | Reprodução mais barata | Dono sugerido | Dependências | Duração |
|---|---|---|---|---|---|---|---|
| 1 | Agente ignora detalhes do pedido (farol/ondas) | **Alta** | entrega algo diferente do pedido | `plan_eval.py` com LLM no ar, **sem GPU** (cancela o job) | Sonnet (prompt + medição) | LLM no Colab; `git stash pop` | ~100 s por tentativa (medido) |
| 2 | Linha de base/A-B do prompt inexistente | **Alta** | sem ela «prompt melhor» é opinião | rodar `plan_eval.py` antes e depois, 6 pedidos | Sonnet | #1 | ~10–15 min (6 × ~100 s) |
| 3 | Suíte completa pós-`99ae52e`…`201a9e1` nunca rodou | **Alta** | regressão invisível | `pytest` arquivo a arquivo **no Colab (CPU, 12,7 GB)**, não no PC de 3,7 GB | Haiku | repo clonado no Colab | ~2 min (a soma local foi 118 s) |
| 4 | Modo clássico pode matar o worker (`cf_lab_ui.py:283`, `studio_app.py:211,375,390`) | Média | job do Studio morre por uso do modo antigo | teste com worker falso mantendo requisição aberta | Sonnet (decidir: remover ou passar pelo Manager) | — | CPU, segundos |
| 5 | `plan` via HTTP nunca chamado | Média | o A/B depende dele | `TestClient` com job com `plan` (padrão de `test_agent_api.py`) | Haiku | — | CPU, segundos |
| 6 | `65eaaae` nunca disparou na T4 | Média | pode reiniciar à toa ou nunca | 5B seguido de `create`, ler `worker_rss_gb` antes/depois | Sonnet | Colab com GPU | ~10 min (5B ~350 s + create ~100 s) |
| 7 | Job «concluído» sem arquivo (`cf_jobs.py:178-180`) | Média | usuário vê sucesso vazio | teste CPU com runner que devolve `[]` | Haiku | — | segundos |
| 8 | Revive de worker morto (`ensure_up`) nunca na T4 | Média | era a promessa de não rodar a célula 6 | `pkill` do ComfyUI e um `create` | Sonnet | Colab com GPU | ~2–4 min |
| 9 | e2e (Playwright) não rodou desde 15/11 | Média | portal pode ter regredido (cache-bust, rotas) | `tests/e2e/run.sh` | Sonnet | Node 24; **máquina com mais RAM** | não medida |
| 10 | A14B 20 passos, Q3_K_S, Q6_K em dois estágios | Baixa/Média | qualidade vs. memória | 1 job cada | Sonnet | Colab; Q6_K baixa ~24 GB | 20 passos: passou de 1073 s (cortado) |
| 11 | LoRA do usuário, See-through, áudio, 3D, MOSS | Média | apps que existem sem prova de GPU | 1 job por app | Sonnet (1 por vez) | downloads de pesos | não medida |
| 12 | `run_eval.py --chains` com Qwen real | Média | mede o agente além de 1 caso | só LLM | Sonnet | LLM no ar | N tarefas × ~100 s |
| 13 | Qualidade: movimento fraco (5B, A14B), artefatos, faixas cinza, QC da Fábrica | Média | resultado fraco | olhar quadros / medir | Sonnet | #10 | não medida |
| 14 | Docs com status desatualizado (V7_STATUS, matriz de 93, `VALIDACAO_GPU.md`) | Baixa (honestidade) | decisões sobre dado velho | edição de texto | Haiku | #3 | minutos |
| 15 | Legendas automáticas | n/a | recurso pedido | — | — | modelo de transcrição | não feito |
| 16 | Provar o determinismo da Fábrica (SHA idêntico em 2 execuções) | Baixa | cache silencioso? | rodar de novo e comparar | Haiku | — | ~23 min (1382 s) |

---

## 10. Fechamento

### O QUE PROVEI AGORA (nesta auditoria, com comando)
- Estado do git: `HEAD = origin/main = 71be0ab`, árvore limpa, 1 stash (só `cf_agent.py`, +5 linhas), `plan_eval.py` existe em `/tmp`.
- Inventário de **todos** os artefatos de GPU que sobraram no disco, com **SHA-256 e `ffprobe` calculados agora** (Apêndice A): 23 arquivos `results-*.json`, 89 mídias.
- Duas rodadas que produziram a **mesma Fábrica byte a byte** (`c29711044d57d50e…`).
- O intervalo real do Turbo (93,4–372,2 s, n=11) e a falha de atribuição das mortes do Q6_K × Q4_K_S.
- `plan` persiste num `Manager` real e sobrevive a um segundo `Manager` na mesma pasta.
- O reinício do worker só atinge a porta dele: dois workers falsos, A reiniciado, B intacto, nada sobrou nas portas.
- A existência do caminho que roda `workflows.run` **fora** do `Manager` (`cf_lab_ui.py:283`, `studio_app.py:211,375,390`) e que ele agora aciona o reinício.
- Que o `cf_jobs.py:178-180` marca `concluído` com resultado vazio.
- Que a matriz das 93 fontes tem 78 fontes sem prova de leitura localizável e 12 URLs fora da matriz.
- Quais relatórios de teste existem, com data, e que o «419» é uma soma, não uma invocação.

### O QUE OS RELATÓRIOS ANTIGOS ALEGAM (e eu não consigo reproduzir de arquivo)
- Tempos do Wan 5B, do A14B depois do 5B, os valores de RSS do worker e os 37/42 s do despertar do LLM (só em saída de ferramenta na transcrição; logs apagados).
- `--list-devices` → `CUDA0: Tesla T4` (só na mensagem do usuário, `f9114512…jsonl` linha 2027).
- `POST /jobs` com campos omitidos concluindo na T4 e as recusas de validação que o agente corrigiu (log apagado).
- «Sementes por item geram imagens distintas».
- A matriz das 93: `TESTADO GPU` do FLUX.2 klein «512², 280 s» (execução antiga sem arquivo) e todos os `CÓDIGO ESCRITO` / `TESTADO CPU` / `TESTADO API REAL` das fontes (autodeclarados).
- `FaceFusion` / FaceSwap «TESTADO CPU» (15/11, sem artefato retido; teste excluído de todas as rodadas).
- 185 Playwright (15/11; não reexecutado).
- Qualquer afirmação sobre a qualidade visual (julgamento meu, sem métrica).

### O QUE NÃO POSSO COMPROVAR
- Que o prompt novo do agente (stash) melhora qualquer coisa: **nunca foi medido**; a linha de base saiu vazia.
- O plano exato do caso farol/ondas, o modelo e a seed (não retidos).
- Que `65eaaae` (reinício acima de 7 GB) funciona na T4 (nunca disparou).
- Que `ensure_up` revive um worker morto na T4.
- Que a rota HTTP `/jobs/{id}` devolve `plan`.
- Que a suíte completa passa no HEAD atual.
- Que o reinício do worker nunca interrompe um job concorrente (há um caminho que pode).
- Qualquer item da seção 6 (LoRA do usuário, See-through, áudio, 3D, offload, `--chains`, legendas).
- Que as outras 78 fontes foram lidas.

**Provas que custam GPU (aguardar distribuição pelo Opus):** #6, #8, #10, #11 da seção 9. As demais são CPU, texto ou LLM sem GPU.

---

*Apêndices A (inventário com SHA-256 completo) e B (93 fontes, uma linha cada) foram gerados por script e anexados abaixo.*

---

## Apêndice A. Inventário bruto dos artefatos de GPU (gerado agora)

23 arquivos `results-*.json` e 89 arquivos de mídia sob `tests/gpu/` (exclui `frames.png`, miniaturas que eu criei para olhar). SHA-256 completo, dimensões/duração por `ffprobe` (vídeo/áudio) ou Pillow (imagem).

### A.1 Resultados por `results-*.json` (caso, status, segundos, nota)

| JSON | caso | status | s | nota (resumida) |
|---|---|---|---|---|
| `out/results-20261115-012500.json` | parada | PARADO | None | 401: o bearer foi recusado. Parei para não gerar bloqueio; confira a senha da sessão no .e |
| `out/results-20261115-012551.json` | parada | PARADO | None | 401: o bearer foi recusado. Parei para não gerar bloqueio; confira a senha da sessão no .e |
| `out/results-20261115-012625.json` | system | OK | 0.2 | GPU Tesla T4 · VRAM 15.0 GB · RAM 12.7 GB · worker ok |
| `out/results-20261115-012625.json` | llm | OK | 0.3 | {"available": true, "model": "qwen3.5-local", "backend": "llama-server (local)", "url": "h |
| `out/results-20261115-012625.json` | cpu_recipe | OK | 6.0 | 4.4s |
| `out-cpu/results-20261115-013135.json` | cpu_recipes_all | OK | 75.8 | polir_lote ok 4.4s (2 arq.); looks_lado_a_lado ok 4.5s (2 arq.); folha_de_quadros ok 4.5s  |
| `out/results-20261115-020403.json` | create_turbo | OK | 346.7 | 343.9s |
| `out/results-20261115-020403.json` | create_std | OK | 312.0 | 284.1s |
| `out/results-20261115-020403.json` | upscale_gpu | OK | 70.7 | 21.6s · modo RealESRGAN_x4plus (fotografia) |
| `out/results-20261115-020403.json` | animate | FALHOU | 0.4 | ValueError: job falhou: KeyError: 'mode' |
| `out/results-20261115-020403.json` | recipe_seeds | OK | 497.1 | 409.3s (2 sementes → conferir → melhor → ampliar) |
| `out/results-20261115-020403.json` | recipe_matrix | OK | 102.8 | 39.0s |
| `out/results-20261115-020403.json` | recipe_loop | FALHOU | 866.0 | ValueError: job falhou: O worker ComfyUI parou de responder. Últimas linhas:   0%/         |
| `out/results-20261115-020403.json` | recipe_animatic | OK | 45.0 | 9.1s |
| `out/results-20261115-020403.json` | recipe_shots_film | FALHOU | 0.4 | ValueError: job falhou: O modo rápido (LightX2V, 4 passos) só existe para os modelos A14B. |
| `out/results-20261115-020403.json` | recipe_character | FALHOU | 4.7 | ValueError: job falhou: Worker ComfyUI local indisponível. Inicie a célula do ComfyUI no C |
| `out/results-20261115-020403.json` | recipe_story | FALHOU | 0.4 | ValueError: job falhou: Worker ComfyUI local indisponível. Inicie a célula do ComfyUI no C |
| `out/results-20261115-020403.json` | agent_chain | FALHOU | 0.7 | ValueError: o agente respondeu sem usar nenhuma ferramenta. ferramentas: nenhuma |
| `out-cpuapps/results-20261115-022508.json` | cpu_apps_all | FALHOU | 95.6 | ValueError: factory: job falhou: Falha na fábrica de vídeo: open() got an unexpected keywo |
| `out2/results-20261120-135135.json` | create_turbo | OK | 373.7 | 372.2s |
| `out2/results-20261120-135135.json` | recipe_shots_film | FALHOU | 145.8 | HTTPError: 404 Client Error: Not Found for url: <oculto>/clonfield/api/jobs/job_74050a99a7 |
| `out2/results-20261120-135135.json` | recipe_character | FALHOU | 0.2 | JSONDecodeError: Expecting value: line 2 column 1 (char 1) |
| `out2/results-20261120-135135.json` | recipe_story | FALHOU | 0.3 | JSONDecodeError: Expecting value: line 2 column 1 (char 1) |
| `out3/results-20261120-145457.json` | system | OK | 0.3 | GPU Tesla T4 · VRAM 15.0 GB · RAM 12.7 GB · worker ok |
| `out3/results-20261120-145457.json` | llm | OK | 0.2 | {"available": true, "model": "qwen3.5-local", "backend": "llama-server (local)", "url": "h |
| `out3/results-20261120-154817.json` | create_turbo | OK | 258.6 | 257.1s |
| `out3/results-20261120-154817.json` | recipe_shots_film | OK | 385.6 | 384.5s |
| `out3/results-20261120-154817.json` | recipe_character | FALHOU | 1501.8 | ValueError: passou de 1500s; cancelei o job |
| `out3/results-20261120-154817.json` | recipe_story | OK | 925.2 | 922.3s |
| `out3/results-20261120-154817.json` | agent_chain | OK | 121.8 | ferramentas: list_capabilities, list_capabilities, inspect_capability, list_capabilities,  |
| `out4/results-20261120-163544.json` | create_turbo | OK | 104.3 | 102.9s |
| `out4/results-20261120-163544.json` | recipe_character | OK | 2240.1 | 2238.9s · conjunto turnaround |
| `out5/results-20261120-171526.json` | recipe_character | OK | 2358.8 | 2231.9s · conjunto turnaround |
| `out7/results-20261120-174946.json` | create_turbo | OK | 104.0 | 102.7s |
| `out7/results-20261120-174946.json` | recipe_loop | FALHOU | 1097.1 | ValueError: job falhou: O worker ComfyUI parou de responder. Últimas linhas: [32m[INFO][ |
| `out9/results-20261120-195106.json` | create_turbo | OK | 252.6 | 250.5s |
| `out9/results-20261120-195106.json` | recipe_loop | FALHOU | 581.7 | ValueError: job falhou: O worker ComfyUI parou de responder. Últimas linhas:   0%/         |
| `out10/results-20261120-204523.json` | create_turbo | OK | 240.0 | 237.5s |
| `out10/results-20261120-204523.json` | recipe_loop | FALHOU | 497.4 | ValueError: job falhou: O worker ComfyUI parou de responder. Últimas linhas:   0%/         |
| `out11/results-20261120-210143.json` | create_turbo | OK | 95.9 | 93.4s |
| `out11/results-20261120-210143.json` | recipe_loop | FALHOU | 173.1 | ValueError: job falhou: O worker ComfyUI parou de responder. Últimas linhas:   0%/         |
| `out12/results-20261120-211205.json` | create_turbo | OK | 117.0 | 95.5s |
| `out12/results-20261120-211205.json` | recipe_loop | FALHOU | 174.0 | HTTPError: 404 Client Error: Not Found for url: <oculto>/clonfield/api/jobs/job_19867dfe5c |
| `out13/results-20261122-174406.json` | create_turbo | OK | 302.6 | 300.2s |
| `out13/results-20261122-174406.json` | recipe_loop | FALHOU | 542.8 | ValueError: job falhou: O worker ComfyUI parou de responder. Últimas linhas:   0%/         |
| `out13/results-20261122-174406.json` | agent_chain | FALHOU | 165.2 | ValueError: Não consegui concluir com o agente (A GPU está ocupada com um job; o modelo de |
| `out14/results-20261122-185014.json` | create_turbo | OK | 125.9 | 123.7s |
| `out14/results-20261122-185014.json` | recipe_loop | OK | 363.3 | 361.6s |
| `out15/results-20261122-185120.json` | agent_chain | FALHOU | 39.7 | ValueError: Não consegui concluir com o agente (O llama-server não respondeu: ('Connection |
| `out16/results-20261122-204037.json` | agent_chain | OK | 85.3 | ferramentas: list_capabilities, list_capabilities, list_capabilities, list_capabilities, l |
| `out17/results-20261122-204734.json` | agent_chain | FALHOU | 53.6 | ValueError: o agente não montou nem executou a cadeia (parou por «limite de passos»). ferr |
| `out18/results-20261122-210427.json` | agent_chain | OK | 101.3 | ferramentas: compose_chain, inspect_capability, inspect_capability, inspect_capability, co |
| `out19/results-20261122-215315.json` | system | OK | 0.2 | GPU Tesla T4 · VRAM 15.0 GB · RAM 12.7 GB · worker ok |
| `out19/results-20261122-215315.json` | llm | OK | 0.2 | {"available": true, "model": "qwen3.5-local", "backend": "llama-server (local)", "url": "h |
| `out19/results-20261122-215315.json` | cpu_recipes_all | OK | 54.3 | polir_lote ok 4.4s (2 arq.); looks_lado_a_lado ok 0.2s (2 arq.); folha_de_quadros ok 4.4s  |
| `out19/results-20261122-215315.json` | cpu_apps_all | OK | 1435.8 | ok: upscale 4.5s, factory 1381.7s, removebg 8.8s, look 0.3s, frame 0.3s, clip 0.3s, still  |
| `out19/results-20261122-215315.json` | agent_chain | OK | 175.9 | ferramentas: compose_chain, inspect_capability, inspect_capability, compose_chain, compose |

### A.2 Mídia (SHA-256 completo)

| arquivo | SHA-256 | ffprobe/Pillow |
|---|---|---|
| `tests/gpu/a14b-q4-loop.mp4` | `92c78aa3ae416b5dbfff4583f6d7b6d658726aab2338c525167c44ed5176c6b0` | 832x480 16/1fps 2.06s |
| `tests/gpu/out-a14b-a14b-q4/a14b/00-aeee381d504f8e0b.mp4` | `92c78aa3ae416b5dbfff4583f6d7b6d658726aab2338c525167c44ed5176c6b0` | 832x480 16/1fps 2.06s |
| `tests/gpu/out-agent/agent_job/00-result.mp4` | `96e95966e083efff9e8621fe8acc931f05cbe3483fc2771c8d7adf477d2a5fbd` | 832x480 24/1fps 3.04s |
| `tests/gpu/out-cmp/5b-q6/00-81bea9ba2eb44114.mp4` | `536a892844cd2e24f4f3bdb52f99be097adb7836e26851aa1b42fe6e0d22b282` | 832x480 24/1fps 3.04s |
| `tests/gpu/out-cmp3/5b-q6-vertical/00-aeee381d504f8e0b.mp4` | `d42dc1bc69271a95bb52f4d7664afe6954727c40a594313d5a6d57d72cb5f4ee` | 480x832 24/1fps 3.04s |
| `tests/gpu/out-cmp4/5b-q6-vertical/00-81bea9ba2eb44114.mp4` | `b38ddc6f974df13da5a73f1e6ef268e16bb828e9771bbf138ae77d9432996918` | 480x832 24/1fps 3.04s |
| `tests/gpu/out-cmp5/5b-q6-vertical/00-783f471a4d7ff7af.mp4` | `8c775d24f5e53a491b91f99f87651a10f7dca28f2d296a1da7abb9704d125735` | 480x832 24/1fps 3.04s |
| `tests/gpu/out-cmp5/a14b-q4-fast/00-fc03abfba03b420d.mp4` | `8604d4854947f2fded69ef2bc86a7dbd00a508adf386dc9aff4d91a9c5cbd7ef` | 480x832 16/1fps 3.06s |
| `tests/gpu/out-cpu/cpu_animatic_do_storyboard/00-image.png` | `3e0d57080a8a986be5200560208190eb7cb5e8a873febccdc3721ea54b87e184` | 1748x542 |
| `tests/gpu/out-cpu/cpu_animatic_do_storyboard/01-video.mp4` | `939cc5332e9e92ffd75fd564bef83241f2bb2cb7c0c6ed3da3ceaa87c59fda88` | 1280x720 24/1fps 4.00s |
| `tests/gpu/out-cpu/cpu_apresentacao_de_imagens/00-video.mp4` | `41ad2f0271fb86aca4f5b0efbdf7974379a2094aca90ec70cbd98e37f6ab0773` | 1280x720 24/1fps 4.00s |
| `tests/gpu/out-cpu/cpu_boomerang_de_clipes/00-video.mp4` | `c9fe3c25aba3c384af7628738e732ee9e189ca2a12364f3c6f90c82b3376b304` | 1280x720 24/1fps 8.00s |
| `tests/gpu/out-cpu/cpu_clipes_em_sequencia/00-video.mp4` | `94de9ee915287899276106adaeec9f036f594798e71dbb12e66d3ef45382a04b` | 1280x720 24/1fps 4.00s |
| `tests/gpu/out-cpu/cpu_conferir_e_consertar/00-image.png` | `9b9e253d5a15e262abe8245c2f8ce8b851fcd14dcb7be838b809495c85e481b3` | 1080x1920 |
| `tests/gpu/out-cpu/cpu_folha_de_quadros/00-image.png` | `28a126dc7f9475a7edce71e07cca923ad92f4850d9867aa120d78cb5b0206276` | 1322x542 |
| `tests/gpu/out-cpu/cpu_folha_de_quadros/01-image.png` | `720702ddb8d307cdd8b4d792221e42fdfd982092876e38c986d9bb495329efe4` | 320x240 |
| `tests/gpu/out-cpu/cpu_looks_lado_a_lado/00-image.png` | `a7497b4c8bf6338672e821bfab1ab234b464333d0853daf972aefd71d0b29d4e` | 2630x542 |
| `tests/gpu/out-cpu/cpu_looks_lado_a_lado/01-image.png` | `fecaaa1857ca93519684f8dfa8fca253a301f32146bfcc7118d893cc0faa09d4` | 640x480 |
| `tests/gpu/out-cpu/cpu_melhores_do_lote/00-image.png` | `190bf59ca5fcb468a51accf93b776652e931b715a7492b5c540dacc1e8dac095` | 1322x542 |
| `tests/gpu/out-cpu/cpu_melhores_do_lote/01-image.png` | `64cc145937d7504e842bd8ea28488e2255dcd9929ac9c8f5ee57585c4db7d750` | 640x480 |
| `tests/gpu/out-cpu/cpu_polir_lote/00-image.png` | `7281654466c8782336747c7d4ca435e1c1ff2ff12722c92e18e5c05c87c2e929` | 582x542 |
| `tests/gpu/out-cpu/cpu_polir_lote/01-image.png` | `ec90576a682bf0e4d6a99abe85fe3a4314895b1dbf44c132f9ae6694c5c6f5b0` | 1080x1920 |
| `tests/gpu/out-cpu/cpu_recortes_em_lote/00-image.png` | `7b292161bf227ad4b9e2169e61aef427766d6bc946fa0c3acf1371bbeaf3c254` | 1322x542 |
| `tests/gpu/out-cpu/cpu_varredura_de_intensidade/00-image.png` | `86b45992c64a599f899d0fde3034ddfc3c39e81da55d880005cf8746b5e5fc34` | 2630x1070 |
| `tests/gpu/out-cpu/cpu_varredura_de_intensidade/01-image.png` | `5aa71778bbce69b2eead731123f7079e47a8e11e47c5aabbac9560d08c04fb67` | 640x480 |
| `tests/gpu/out-cpuapps/cpuapp_board/00-prancha-c9de3b04c142.png` | `8e8991341d96ded66ed3d152556282f8e6b2e502b438f3d67438df3d2c922f48` | 960x448 |
| `tests/gpu/out-cpuapps/cpuapp_clip/00-clipe-a9b3f729a5cd.mp4` | `d557ffea08c1f8f74d4c527d2a9875f585e76d8e63e1931201dc875773b7ea04` | 320x240 12/1fps 2.00s |
| `tests/gpu/out-cpuapps/cpuapp_compare/00-comparacao-92f12397a1fd.png` | `dcb630740a3b5376b60169d3fd4e2a267b74d77df9a154d876bd9795aa3388df` | 1284x480 |
| `tests/gpu/out-cpuapps/cpuapp_frame/00-imagem-e4cefc879833.png` | `9c7d9fb3eea7008daa85efc83ef3996e024643d249d8fe1177b39ac14eba287d` | 1080x1920 |
| `tests/gpu/out-cpuapps/cpuapp_look/00-imagem-5bab885abbd0.png` | `8ef6098c004004e232e3dd08ed65d4a844e5e1f7a4d568230143ff40d3d9424d` | 640x480 |
| `tests/gpu/out-cpuapps/cpuapp_removebg/00-sem-fundo-673cebefa003.png` | `2f18b040aa3ee08a18ccb111b5a30182ffc6f71faf0c793949af5b0759bb9006` | 640x480 |
| `tests/gpu/out-cpuapps/cpuapp_sequence/00-sequencia-5e2b41e25ea3.mp4` | `2aefe8422b6cdf00329e45f8613343788c3c339182178a280ffa6da48648efe6` | 1280x720 24/1fps áudio aac 4.00s |
| `tests/gpu/out-cpuapps/cpuapp_still/00-quadro-a43c362d23a4.png` | `720702ddb8d307cdd8b4d792221e42fdfd982092876e38c986d9bb495329efe4` | 320x240 |
| `tests/gpu/out-cpuapps/cpuapp_upscale/00-upscale-e8e7d8d4b76c.png` | `2a1b595452e00166a81d55c40b5a7e4895ec8bdc063b7f60ce17f816de81f70d` | 1280x960 |
| `tests/gpu/out-extra/removebg/00-sem-fundo-c7f3bca739a6.png` | `daa25229dc4c6fd3579c0c0ffe1bc46e31c2b568ad071b44c199b9ef5fd47719` | 768x768 |
| `tests/gpu/out-factory/factory/00-fabrica-ddf66ed9fc10.mp4` | `c29711044d57d50e6d49d02e9b18460c6ea049d7482e2ddc72a18b760d9b2389` | 1080x1920 30/1fps áudio aac 31.80s |
| `tests/gpu/out/cpu_recipe/00-video.mp4` | `82581176bd33ed7d6468cb3cb1c0c1f49691087ef73aa5174d255b87b1bca785` | 720x720 24/1fps 3.00s |
| `tests/gpu/out/create_std/00-63285e61fb01c563.png` | `9efe7ace02fcbb3fe794d8444f39cd5f56b7320ef412c96a4af7886c563d1534` | 768x768 |
| `tests/gpu/out/create_turbo/00-15d47e0c576550d5.png` | `cb0ecb5b2dd1e5e296e922ae683cf746ef97c59d5f28dd66d11a1d65be8c431d` | 768x768 |
| `tests/gpu/out/recipe_animatic/00-image.png` | `662081950a006f68a53ef006591133c3e9be6e59ca73664200d0affb7c0207e7` | 1748x542 |
| `tests/gpu/out/recipe_animatic/01-video.mp4` | `e8fbbd16ff10a7229f309ed783461d046d9843ec448f12e843c90e1bd860aad0` | 1280x720 24/1fps 2.00s |
| `tests/gpu/out/recipe_matrix/00-image.png` | `a3c0cdaf6fcd93c72a82a1e9bc3ef7e75d8e21d398bc11f0c98a100fc1b0e3c0` | 1002x542 |
| `tests/gpu/out/recipe_matrix/01-image.png` | `6be559787461bb3ac9220b8e790baa354d547f33a6ea8333db356a2e6b358a9b` | 768x768 |
| `tests/gpu/out/recipe_seeds/00-image.png` | `c953d3253a99793a0d150cd64976d99deae1ff4cfa82d3ace86e44bae8469549` | 1536x1536 |
| `tests/gpu/out/upscale_gpu/00-upscale-22a55fc1d43f.png` | `8e425dba71d8e47fff1ef6b4c5d07c9c3e1c88323d6bdcd7bdda2e35e209e7f9` | 1536x1536 |
| `tests/gpu/out10/create_turbo/00-15d47e0c576550d5.png` | `f3f575bab46749c9b5a6b0dbafed27a3539e984e7a432ec4410dcdaacbecce57` | 768x768 |
| `tests/gpu/out11/create_turbo/00-2a9d271cdb29e257.png` | `dda3a8a1771734978a978dbce29f4020c764395c1e4353c8e23d8286b70b5667` | 768x768 |
| `tests/gpu/out12/create_turbo/00-4125f31ee6be5d60.png` | `c94fe5733fa0a9b5df0dbd5044a054a48bcf21a8bff5cd17337c44095db59bc6` | 768x768 |
| `tests/gpu/out13/create_turbo/00-15d47e0c576550d5.png` | `de9a24293a1ff781c363be7185a63ddb451208fa40b20ee6f87e5f52e52d83e7` | 768x768 |
| `tests/gpu/out14/create_turbo/00-2a9d271cdb29e257.png` | `0032fcfa1770bc540ad27013d131964e38d8df20efc4d7416ef79a89805b57a6` | 768x768 |
| `tests/gpu/out14/recipe_loop/00-video.mp4` | `f358ed4aecc5f68b5d68323586fa2412a5629f70f66cdc0d33b6a436b4e36871` | 832x480 16/1fps 2.06s |
| `tests/gpu/out19/cpu_animatic_do_storyboard/00-image.png` | `3e0d57080a8a986be5200560208190eb7cb5e8a873febccdc3721ea54b87e184` | 1748x542 |
| `tests/gpu/out19/cpu_animatic_do_storyboard/01-video.mp4` | `939cc5332e9e92ffd75fd564bef83241f2bb2cb7c0c6ed3da3ceaa87c59fda88` | 1280x720 24/1fps 4.00s |
| `tests/gpu/out19/cpu_apresentacao_de_imagens/00-video.mp4` | `41ad2f0271fb86aca4f5b0efbdf7974379a2094aca90ec70cbd98e37f6ab0773` | 1280x720 24/1fps 4.00s |
| `tests/gpu/out19/cpu_boomerang_de_clipes/00-video.mp4` | `c9fe3c25aba3c384af7628738e732ee9e189ca2a12364f3c6f90c82b3376b304` | 1280x720 24/1fps 8.00s |
| `tests/gpu/out19/cpu_clipes_em_sequencia/00-video.mp4` | `94de9ee915287899276106adaeec9f036f594798e71dbb12e66d3ef45382a04b` | 1280x720 24/1fps 4.00s |
| `tests/gpu/out19/cpu_conferir_e_consertar/00-image.png` | `9b9e253d5a15e262abe8245c2f8ce8b851fcd14dcb7be838b809495c85e481b3` | 1080x1920 |
| `tests/gpu/out19/cpu_folha_de_quadros/00-image.png` | `28a126dc7f9475a7edce71e07cca923ad92f4850d9867aa120d78cb5b0206276` | 1322x542 |
| `tests/gpu/out19/cpu_folha_de_quadros/01-image.png` | `720702ddb8d307cdd8b4d792221e42fdfd982092876e38c986d9bb495329efe4` | 320x240 |
| `tests/gpu/out19/cpu_looks_lado_a_lado/00-image.png` | `a7497b4c8bf6338672e821bfab1ab234b464333d0853daf972aefd71d0b29d4e` | 2630x542 |
| `tests/gpu/out19/cpu_looks_lado_a_lado/01-image.png` | `fecaaa1857ca93519684f8dfa8fca253a301f32146bfcc7118d893cc0faa09d4` | 640x480 |
| `tests/gpu/out19/cpu_melhores_do_lote/00-image.png` | `190bf59ca5fcb468a51accf93b776652e931b715a7492b5c540dacc1e8dac095` | 1322x542 |
| `tests/gpu/out19/cpu_melhores_do_lote/01-image.png` | `64cc145937d7504e842bd8ea28488e2255dcd9929ac9c8f5ee57585c4db7d750` | 640x480 |
| `tests/gpu/out19/cpu_polir_lote/00-image.png` | `7281654466c8782336747c7d4ca435e1c1ff2ff12722c92e18e5c05c87c2e929` | 582x542 |
| `tests/gpu/out19/cpu_polir_lote/01-image.png` | `ec90576a682bf0e4d6a99abe85fe3a4314895b1dbf44c132f9ae6694c5c6f5b0` | 1080x1920 |
| `tests/gpu/out19/cpu_recortes_em_lote/00-image.png` | `7b292161bf227ad4b9e2169e61aef427766d6bc946fa0c3acf1371bbeaf3c254` | 1322x542 |
| `tests/gpu/out19/cpu_varredura_de_intensidade/00-image.png` | `86b45992c64a599f899d0fde3034ddfc3c39e81da55d880005cf8746b5e5fc34` | 2630x1070 |
| `tests/gpu/out19/cpu_varredura_de_intensidade/01-image.png` | `5aa71778bbce69b2eead731123f7079e47a8e11e47c5aabbac9560d08c04fb67` | 640x480 |
| `tests/gpu/out19/cpuapp_board/00-prancha-d98826c624d0.png` | `8e8991341d96ded66ed3d152556282f8e6b2e502b438f3d67438df3d2c922f48` | 960x448 |
| `tests/gpu/out19/cpuapp_clip/00-clipe-58e6c7a0cc8f.mp4` | `d557ffea08c1f8f74d4c527d2a9875f585e76d8e63e1931201dc875773b7ea04` | 320x240 12/1fps 2.00s |
| `tests/gpu/out19/cpuapp_compare/00-comparacao-0132743c0860.png` | `dcb630740a3b5376b60169d3fd4e2a267b74d77df9a154d876bd9795aa3388df` | 1284x480 |
| `tests/gpu/out19/cpuapp_factory/00-fabrica-194380526e20.mp4` | `c29711044d57d50e6d49d02e9b18460c6ea049d7482e2ddc72a18b760d9b2389` | 1080x1920 30/1fps áudio aac 31.80s |
| `tests/gpu/out19/cpuapp_frame/00-imagem-27523cfe9567.png` | `9c7d9fb3eea7008daa85efc83ef3996e024643d249d8fe1177b39ac14eba287d` | 1080x1920 |
| `tests/gpu/out19/cpuapp_look/00-imagem-c3ac16b11a43.png` | `8ef6098c004004e232e3dd08ed65d4a844e5e1f7a4d568230143ff40d3d9424d` | 640x480 |
| `tests/gpu/out19/cpuapp_removebg/00-sem-fundo-bf8e32d084dc.png` | `2f18b040aa3ee08a18ccb111b5a30182ffc6f71faf0c793949af5b0759bb9006` | 640x480 |
| `tests/gpu/out19/cpuapp_sequence/00-sequencia-d21519d0a9b2.mp4` | `2aefe8422b6cdf00329e45f8613343788c3c339182178a280ffa6da48648efe6` | 1280x720 24/1fps áudio aac 4.00s |
| `tests/gpu/out19/cpuapp_still/00-quadro-dd4965d06cad.png` | `720702ddb8d307cdd8b4d792221e42fdfd982092876e38c986d9bb495329efe4` | 320x240 |
| `tests/gpu/out19/cpuapp_upscale/00-upscale-ab9022653b52.png` | `2a1b595452e00166a81d55c40b5a7e4895ec8bdc063b7f60ce17f816de81f70d` | 1280x960 |
| `tests/gpu/out2/create_turbo/00-15d47e0c576550d5.png` | `7f542d64ec87e0eacd07c929ed2e1ccd3067af58079768683e69871d5ffba6dc` | 768x768 |
| `tests/gpu/out3/agent_chain/00-result.mp4` | `0bccc2e271b50b9d15c341ed01e69d6b1c6cc9d225767ba198bd1f4fe2d69160` | 832x480 24/1fps 3.04s |
| `tests/gpu/out3/create_turbo/00-15d47e0c576550d5.png` | `601dcc2e1e890cfa6457c809be51870714b43df9a55a768e8a7ccd1d8becba1f` | 768x768 |
| `tests/gpu/out3/recipe_shots_film/00-video.mp4` | `a09566a883aeb4cbf50a60f9f7edd6ec0d18f9e814a16a1a91e7a9be7fc08481` | 1280x720 24/1fps 4.08s |
| `tests/gpu/out3/recipe_story/00-video.mp4` | `f45d71150031e19ffbb81954773d9fdb71284d1e00a8a39c5eac31cd09c9a415` | 1280x720 24/1fps 4.08s |
| `tests/gpu/out4/create_turbo/00-2a9d271cdb29e257.png` | `6ae34ff4259c944cbc1ad3f9ea5288b74de936da7c11c6cff1c3460c727b09a3` | 768x768 |
| `tests/gpu/out4/recipe_character/00-image.png` | `b8acc1dfc2bdb5f78278ae2791affc05843611e0336c9fc1d184402a8e103c8d` | 2700x1084 |
| `tests/gpu/out5/character_source/00-4125f31ee6be5d60.png` | `45172cc8b38db4f2b926b63ddd8dc09b8eb94b91b026d0a9b8e6fe268fd2e51e` | 576x768 |
| `tests/gpu/out5/recipe_character/00-image.png` | `7c4135db0a0601485692939d18c839031b123f2b78dbf5b6727f5c3bd02f63bb` | 2700x1084 |
| `tests/gpu/out7/create_turbo/00-f586dd2772c64881.png` | `f6e9055906e2e19a01a685eb31230ed6fdfda97446893eec54559c1d302f1e8d` | 768x768 |
| `tests/gpu/out9/create_turbo/00-15d47e0c576550d5.png` | `ace24c1482c3356acb837f6452dcee413992e03b95b56b1f7000afb79a095b3d` | 768x768 |

---

## Apêndice B. As 93 fontes (uma linha por URL do registro; gerado por script)

Colunas: **URL exata** (do registro `…REGISTRO_COMPLETO_LINKS_2026-11-10_v7.md`) · **estado declarado** na matriz `docs/BACKLOG_CAPACIDADES_APPS.md` · **prova de busca/leitura** nas transcrições (sessão:ferramenta; `—` = nenhuma localizável) · **código/docs que a citam** (arquivo:linha) · **pin** (commit/revisão encontrado perto da citação) · **licença registrada** · **evidência/pendência** (texto da matriz). Os níveis `listado / README lido / código lido / baixado / integrado / executado / testado` não são distinguidos por script: **só `listado` e «prova de busca» são comprováveis aqui**; os demais valem o que a matriz declara.

| # | URL | estado declarado | prova de busca/leitura | citada em | pin | licença | evidência/pendência (matriz) |
|---|---|---|---|---|---|---|---|
| 1 | https://civitai.com/ | TESTADO API REAL | 5095613a:Bash, 86ce2124:Bash | cf_assets.py:13, cf_lab_ui.py:312 | — | não registrada | Lote 1: variantes por arquivo, entrega conferida, capas em cache |
| 2 | https://clonfield-studio-portal.vercel.app/ | NÃO INICIADO | — | — | — | não registrada | não aberto |
| 3 | https://github.com/Comfy-Org/workflow_templates | CÓDIGO ESCRITO | — | cf_templates.py:1, cf_3d.py:3 | — | MIT (cf_templates.py:1) | lido como referência para Wan 2.2; templates de vídeo ainda não carregados |
| 4 | https://github.com/Vit0lze/clonfield-studio | baseline (não é capacidade) | 5095613a:Bash | ClonField_Colab.ipynb:41, docs/HANDOFF.md:34 | — | não registrada | código lido e alterado; 8 commits do Lote 1 + Lote 2 em main/local |
| 5 | https://github.com/Vit0lze/clonfield-studio/blob/main/cf_apps.py | baseline (não é capacidade) | 5095613a:Bash | ClonField_Colab.ipynb:41, docs/HANDOFF.md:34 | — | não registrada | código lido e alterado; 8 commits do Lote 1 + Lote 2 em main/local |
| 6 | https://github.com/Vit0lze/clonfield-studio/blob/main/cf_model_lab.py | baseline (não é capacidade) | 5095613a:Bash | ClonField_Colab.ipynb:41, docs/HANDOFF.md:34 | — | não registrada | código lido e alterado; 8 commits do Lote 1 + Lote 2 em main/local |
| 7 | https://github.com/Vit0lze/clonfield-studio/blob/main/cf_workflows.py | baseline (não é capacidade) | 5095613a:Bash | ClonField_Colab.ipynb:41, docs/HANDOFF.md:34 | — | não registrada | código lido e alterado; 8 commits do Lote 1 + Lote 2 em main/local |
| 8 | https://huggingface.co/models | TESTADO API REAL | — | — | — | não registrada | busca HF real; HF só descobre, não instala |
| 9 | https://youtu.be/VefUJLzxQWg | NÃO INICIADO | — | — | — | não registrada | não assistido |
| 10 | https://youtu.be/aetuL154-pE | NÃO INICIADO | — | — | — | não registrada | não assistido |
| 11 | https://docs.comfy.org/agent-tools/mcp | NÃO INICIADO | — | — | — | não registrada | não aberto |
| 12 | https://github.com/BillionsBobby/JevRouter | TESTADO API REAL | — | cf_router.py:3 | — | MIT (cf_router.py:3) | 30/30 no gabarito próprio (V7); substituído como padrão pelo agente |
| 13 | https://github.com/Comfy-Org/comfy-mcp | ESTUDADO — SEM CÓDIGO | — | — | — | não registrada | README lido (AGPL-3.0 ou comercial: nada de código copiado): 41 ferramentas; ideias úteis  |
| 14 | https://github.com/hndrr/ComfyUI-Jev | ESTUDADO — DISPENSADO | — | docs/V7_STATUS.md:60 | — | MIT (docs/V7_STATUS.md:60) | nó da Jev (TypeSafe), removida do Studio |
| 15 | https://github.com/kantan-kanto/ComfyUI-ScriptFlow | ESTUDADO — DISPENSADO | — | docs/V7_STATUS.md:59 | — | GPL-3 (docs/V7_STATUS.md:59) | nó de script que consulta a Jev (TypeSafe), removida do Studio; nada a reaproveitar |
| 16 | https://github.com/thinkany-ai/autojev | ESTUDADO — DISPENSADO | — | docs/V7_STATUS.md:61 | — | MIT (docs/V7_STATUS.md:61) | ligado à Jev (TypeSafe), removida do Studio |
| 17 | https://github.com/scenario-labs/skills | TESTADO CPU | — | cf_refine.py:3, docs/V7_STATUS.md:20 | — | MIT (cf_refine.py:3) | ver linhas por skill |
| 18 | https://github.com/scenario-labs/skills/blob/main/skills/scenario-asset-analysis/SKILL.md | CÓDIGO ESCRITO | — | cf_refine.py:3, docs/V7_STATUS.md:20 | — | MIT (cf_refine.py:3) | inspect_artifact mede dimensões e gate técnico; sem análise semântica |
| 19 | https://github.com/scenario-labs/skills/blob/main/skills/scenario-consistency/SKILL.md | ESTUDADO — SEM CÓDIGO | — | cf_refine.py:3, docs/V7_STATUS.md:20 | — | MIT (cf_refine.py:3) | lido: consistência vem de prompt-base + delta, imagens de referência e (depois) modelo tre |
| 20 | https://github.com/scenario-labs/skills/blob/main/skills/scenario-formats/SKILL.md | TESTADO CPU | — | cf_refine.py:3, docs/V7_STATUS.md:20 | — | MIT (cf_refine.py:3) | capacidade frame com 4 proporções |
| 21 | https://github.com/scenario-labs/skills/blob/main/skills/scenario-model-comparison/SKILL.md | TESTADO CPU | — | cf_refine.py:3, docs/V7_STATUS.md:20 | — | MIT (cf_refine.py:3) | app «Comparar modelos» (cf_compare.py): mesma entrada em 2-3 modelos, tempo frio/quente, s |
| 22 | https://github.com/scenario-labs/skills/blob/main/skills/scenario-quality-gate/SKILL.md | TESTADO CPU | — | cf_refine.py:3, docs/V7_STATUS.md:20 | — | MIT (cf_refine.py:3) | tests/test_capabilities.py, test_refine_router.py |
| 23 | https://github.com/scenario-labs/skills/blob/main/skills/scenario-refine-loop/SKILL.md | TESTADO CPU | — | cf_refine.py:3, docs/V7_STATUS.md:20 | — | MIT (cf_refine.py:3) | test_refine_router.py |
| 24 | https://github.com/scenario-labs/skills/blob/main/skills/scenario-workflows/SKILL.md | TESTADO CPU | — | cf_refine.py:3, docs/V7_STATUS.md:20 | — | MIT (cf_refine.py:3) | tests/test_dag.py (cache por hash, retomada) |
| 25 | https://arxiv.org/abs/2602.03749 | CÓDIGO ESCRITO | — | — | — | não registrada | método lido para a escolha de perfis |
| 26 | https://github.com/852wa/Anime2.5DRig | NÃO INICIADO | — | — | — | não registrada | depende das camadas reais |
| 27 | https://github.com/MangoLion/stretchystudio | NÃO INICIADO | — | — | — | não registrada | depende das camadas reais |
| 28 | https://github.com/jtydhr88/ComfyUI-See-through | BLOQUEADO_GPU | — | cf_seethrough.py:3, docs/CHANGELOG_V7.md:44 | 98d754b | MIT (cf_seethrough.py:3) | grafo aceito pelo ComfyUI 0.44; nunca gerou camadas na T4 |
| 29 | https://github.com/kazuya-bros/PachiPakuGen | NÃO INICIADO | — | — | — | não registrada | depende das camadas reais |
| 30 | https://github.com/shitagaki-lab/see-through | BLOQUEADO_GPU | — | cf_seethrough.py:4, docs/CHANGELOG_V7.md:44 | 98d754b | Apache-2.0 (cf_seethrough.py:4) | pesos NF4/BF16 só na T4 |
| 31 | https://huggingface.co/spaces/24yearsold/see-through-demo | NÃO INICIADO | — | — | — | não registrada | não aberto |
| 32 | https://github.com/floomhq/opencut | ESTUDADO — SEM CÓDIGO | — | — | — | não registrada | README lido: motor de vídeo em Remotion/TypeScript (timeline por código); outra pilha, só  |
| 33 | https://github.com/gyoridavid/short-video-maker | ESTUDADO — SEM CÓDIGO | — | — | — | não registrada | README lido: TTS + legendas + vídeos de fundo + música, REST/MCP; sem geração de vídeo; na |
| 34 | https://github.com/harry0703/MoneyPrinterTurbo | ESTUDADO — SEM CÓDIGO | — | — | — | não registrada | README lido: tema → roteiro → material → legenda → música → vídeo (stock footage, não gera |
| 35 | https://github.com/jutsuhq/content-factory | TESTADO CPU | — | cf_factory.py:3, vendor/content_factory/VENDORED.md:1 | 0ea76329ce23 | MIT (cf_factory.py:3) | render narrado real em CPU (V6); modo «states» ligado ao gerador local pelo hook `private` |
| 36 | https://github.com/wexloops/openfield | CÓDIGO ESCRITO | — | cf_director.py:3, cf_cast.py:8 | — | MIT (cf_director.py:3) | README e catálogo lidos (MIT, concorrente «Higgsfield» do Comfy): a Direção virou campos d |
| 37 | https://higgsfield.ai/blog/higgsfield-introduces-content-factory | CÓDIGO ESCRITO | — | — | — | não registrada | inspirou o fluxo; sem cópia de código |
| 38 | https://civitai.red/models/1817819/wan-22-image-to-video | NÃO INICIADO | — | — | — | não registrada | abrir o JSON e comparar com o grafo oficial |
| 39 | https://civitai.red/models/1852904/wan-22-video-sound-workflow-optimized-for-rtx-3060-12-gb-vram-gpu | NÃO INICIADO | — | — | — | não registrada | — |
| 40 | https://civitai.red/models/2881362/minimax-h3-seed-hunter-latent-upscaler-seamless-video-continuation-dialogue-gen-tool-speedups-ref-mods | NÃO ACHADO NA MATRIZ | — | — | — | não registrada |  |
| 41 | https://civitai.red/models/2967375/qwen-image-21-outpaint-lora-extend-any-side?modelVersionId=3362269 | CÓDIGO ESCRITO | — | — | — | não registrada | receita da página e do cartão HF seguida (canvas #808080 ×32 ≤2 MP, instrução-gatilho, 25  |
| 42 | https://civitai.red/models/2975820/qwen-image-21-edit-super-duper-stable-nsfw-workflow | NÃO INICIADO | — | assets.json:84 | — | não registrada | — |
| 43 | https://civitai.red/models/2983159/qwen-image-21-outfit-swap-consistency-lora?modelVersionId=3381922 | CÓDIGO ESCRITO | — | assets.json:42 | — | não registrada | prompt oficial, pessoa=imagem 1, roupa=imagem 2; testado em CPU; geração BLOQUEADO_GPU |
| 44 | https://civitai.red/models/2986253/qwen-image-21-character-sheet-designer-image-generation | CÓDIGO ESCRITO | — | assets.json:112 | — | não registrada | app «Folha de personagem» (cf_character.py): receita própria com o modo edição do Qwen 2.1 |
| 45 | https://civitai.red/models/2988187/minimax-h3-character-swap-workflow | NÃO ACHADO NA MATRIZ | — | — | — | não registrada |  |
| 46 | https://civitai.red/models/2989697/qwen-image-21-restore-lora?modelVersionId=3390033 | CÓDIGO ESCRITO | — | — | — | não registrada | prompts oficiais, ~2 MP, força 1,0 ou 0,5 (foto desfocada); testado em CPU; geração BLOQUE |
| 47 | https://civitai.red/models/3004026/flux-3-image-klein-multi-image-edit-or-up-to-6-pictures | ESTUDADO — SEM CÓDIGO | — | — | — | não registrada | página lida: usa nós AusBoss e o modelo gated da BFL (não consegui ler o cartão); o preset |
| 48 | https://civitai.red/models/3010615/moss-image-inpainting-workflow | NÃO INICIADO | — | — | — | não registrada | a máscara a partir de caixas já existe (bbox_mask) |
| 49 | https://civitai.red/models/3020564/artfat-moss-bbox-studio-or-generate-edit-llm-prompter-50-presets-dlss5-enhancer | CÓDIGO ESCRITO | 86ce2124:Bash | — | — | não registrada | CORREÇÃO: eu tinha escrito que o MOSS não tinha versão quantizada: tem (Comfy-Org/MOSS-Ima |
| 50 | https://civitai.red/models/3028227/qwen-character-asset-generator-emotionactionangle-workflows | CÓDIGO ESCRITO | — | — | — | não registrada | parcial: ângulos e expressões saem do app «Folha de personagem»; ações não foram feitas; o |
| 51 | https://civitai.red/models/3038333/workflow-action-transfer-dance | NÃO INICIADO | — | — | — | não registrada | — |
| 52 | https://civitai.red/models/453194/swapping-deepfake-training-face-model-and-upscaling | NÃO INICIADO | — | — | — | não registrada | — |
| 53 | https://civitai.red/models/736681/flux-realistic-amateurs | NÃO INICIADO | — | — | — | não registrada | — |
| 54 | https://comfy.icu/files/qwenImage21Person_v10.json | NÃO INICIADO | — | — | — | não registrada | — |
| 55 | https://comfy.org/hub/workflows/?category=swap-faces-and-characters | NÃO INICIADO | — | — | — | não registrada | — |
| 56 | https://comfy.org/hub/workflows/wan2-2-animate-character-animation-and-replacement-c2c4b45b7df5/ | NÃO INICIADO | — | — | — | não registrada | — |
| 57 | https://blog.comfy.org/p/wan22-animate-and-qwen-image-edit-2509 | TESTADO CPU | — | — | — | não registrada | templates com subgrafos convertidos por `cf_ui2api.flatten`; o ComfyUI 0.44 real em CPU AC |
| 58 | https://docs.facefusion.io/usage/cli-arguments/face-selector | TESTADO CPU | — | — | — | não registrada | opções usadas conferidas contra o `--help` real |
| 59 | https://github.com/Gourieff/comfyui-reactor | ESTUDADO — DISPENSADO | — | — | — | não registrada | troca de rosto já coberta pelo FaceFusion (app «Trocar rosto», troca real em CPU); README  |
| 60 | https://github.com/PrunaAI | NÃO INICIADO | — | — | — | não registrada | — |
| 61 | https://github.com/facefusion/facefusion | TESTADO CPU | 86ce2124:Bash | cf_faceswap.py:17 | decc6c9d8f8e | não registrada | troca real em CPU com o programa real: mudou só a região do rosto (tests/test_faceswap.py) |
| 62 | https://huggingface.co/Alissonerdx/BFS-Best-Face-Swap | CÓDIGO ESCRITO | 86ce2124:Bash | cf_loras.py:20 | 009a44a895ef | não registrada | LoRAs catalogadas e classificáveis; sem app de swap |
| 63 | https://huggingface.co/Alissonerdx/BFS-Best-Face-Swap/blob/main/README.md | CÓDIGO ESCRITO | 86ce2124:Bash | cf_loras.py:20 | 009a44a895ef | não registrada | LoRAs catalogadas e classificáveis; sem app de swap |
| 64 | https://huggingface.co/Alissonerdx/BFS-Best-Face-Swap/blob/main/docs/qwen-image-2.1-body.md | CÓDIGO ESCRITO | 86ce2124:Bash | cf_loras.py:20 | 009a44a895ef | não registrada | LoRAs catalogadas e classificáveis; sem app de swap |
| 65 | https://huggingface.co/PrunaAI/P-Q-Image-2.1-Comfy | CÓDIGO ESCRITO | — | — | — | não registrada | a variante rápida do Qwen 2.1 entregue é o modelo Turbo INT8 oficial do ComfyUI (8 passos) |
| 66 | https://blog.comfy.org/p/stable-audio-3-day-0-support | TESTADO CPU | 86ce2124:Bash | — | — | não registrada | os 9 grafos (3 modelos × 3 formatos) são ACEITOS pelo ComfyUI 0.44 real; grafo conferido c |
| 67 | https://blog.comfy.org/p/trellis2-and-pixal3d-are-now-native | CÓDIGO ESCRITO | 86ce2124:Bash | — | — | não registrada | o template oficial (66 nós) é convertido mecanicamente com o /object_info do worker, o int |
| 68 | https://design.minimax.io/h3 | NÃO ACHADO NA MATRIZ | — | — | — | não registrada |  |
| 69 | https://docs.comfy.org/tutorials/video/wan/wan2_2 | TESTADO CPU | 86ce2124:Bash | cf_wan.py:7 | — | não registrada | app de vídeo com A14B Q6_K (T2V/I2V) e 5B Q6/Q8/FP16, segundos/FPS/tamanho; os 8 grafos (4 |
| 70 | https://github.com/Comfy-Org/docs/blob/main/tutorials/video/minimax/minimax-h3-native.mdx | NÃO ACHADO NA MATRIZ | — | — | — | não registrada |  |
| 71 | https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_fun_controlnet_union.json | CÓDIGO ESCRITO | — | cf_templates.py:1, cf_3d.py:3 | — | MIT (cf_templates.py:1) | lido como referência para Wan 2.2; templates de vídeo ainda não carregados |
| 72 | https://github.com/MiniMax-AI/awesome-minimax-h3-integration | NÃO ACHADO NA MATRIZ | — | — | — | não registrada |  |
| 73 | https://github.com/ModelTC/LightX2V | CÓDIGO ESCRITO | — | — | — | não registrada | Wan A14B «Rápido»: LoRAs LightX2V de 4 passos no empacotamento do ComfyUI (Comfy-Org/Wan-2 |
| 74 | https://github.com/Stability-AI/stable-audio-3 | TESTADO CPU | — | — | — | não registrada | os 9 grafos (3 modelos × 3 formatos) são ACEITOS pelo ComfyUI 0.44 real; grafo conferido c |
| 75 | https://github.com/barelymining/ComfyUI-MiniMax-H3-FastVideo | NÃO ACHADO NA MATRIZ | — | — | — | não registrada |  |
| 76 | https://huggingface.co/Comfy-Org/MiniMax-H3 | NÃO ACHADO NA MATRIZ | — | prepare_openjutsu.py:17 | 1c41cfca8ebb | não registrada |  |
| 77 | https://huggingface.co/Lightricks/LTX-Video | TESTADO CPU | — | cf_ltxv.py:3 | — | não registrada | 2 grafos aceitos pelo ComfyUI 0.44 real; pesos (6,3 GB + codificador T5 fp8 de 5,2 GB, NÃO |
| 78 | https://huggingface.co/MiniMaxAI/MiniMax-H3 | NÃO ACHADO NA MATRIZ | — | — | — | não registrada |  |
| 79 | https://huggingface.co/VideoRebirthAI/hyperflow-h3-flash | NÃO ACHADO NA MATRIZ | — | — | — | não registrada |  |
| 80 | https://huggingface.co/alibaba-pai/MiniMax-H3-Fun-Controlnet-Union-2.0 | NÃO ACHADO NA MATRIZ | — | — | — | não registrada |  |
| 81 | https://huggingface.co/collections/FastVideo/fasth3-omni | NÃO ACHADO NA MATRIZ | — | — | — | não registrada |  |
| 82 | https://huggingface.co/lightx2v | CÓDIGO ESCRITO | 86ce2124:Bash | cf_wan.py:64, cf_apps.py:1316 | — | não registrada | Wan2.2-Distill/Lightning: usados via os mesmos LoRAs repacotados do ComfyUI; o LoRA «Qwen- |
| 83 | https://ia.seenupdigital.com/noticias/criador-mostra-como-rodar-o-minimax-h3-mais-rapido-com-versoes-lora-e-prompts-ce302c | NÃO ACHADO NA MATRIZ | — | — | — | não registrada |  |
| 84 | https://bfl.ai/models/flux-2-klein | TESTADO GPU | — | cf_model_lab.py:85 | — | não registrada | única evidência de GPU: 512², 4 passos, 280 s com download (Colab antigo) |
| 85 | https://github.com/Blueforcer/ComfyUI-DLSS5-Enhancer | ESTUDADO — INVIÁVEL NA T4 | — | — | — | não registrada | README lido: roda num worker nativo D3D12 (ReShade + RenoDX + NGX) só no Windows com GPU R |
| 86 | https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_2_1_image_edit.json | TESTADO CPU | — | cf_templates.py:1, cf_3d.py:3 | — | MIT (cf_templates.py:1) | grafo do preset qwen21 validado contra /object_info (V7); GPU não medida |
| 87 | https://github.com/Niko1221/Strata | ESTUDADO — SEM CÓDIGO | — | — | — | não registrada | README lido: app desktop de LLM local (GGUF); mesmo território do colibri/llama.cpp já int |
| 88 | https://github.com/artfat-creator/ComfyUI-Artfat-MOSS-BBox | TESTADO CPU | 86ce2124:Bash | — | — | não registrada | código lido; receita reimplementada com nós do núcleo e validada no ComfyUI real |
| 89 | https://github.com/black-forest-labs/flux2 | TESTADO GPU | — | — | — | não registrada | mesma evidência acima |
| 90 | https://github.com/black-forest-labs/flux2/blob/main/model_licenses/LICENSE-FLUX-NON-COMMERICAL | TESTADO GPU | — | — | — | não registrada | mesma evidência acima |
| 91 | https://huggingface.co/OpenMOSS-Team/MOSS-Image-Base | CÓDIGO ESCRITO | — | — | — | não registrada | tamanhos e SHA conferidos na API do HF |
| 92 | https://huggingface.co/OpenMOSS-Team/MOSS-Image-SFT | CÓDIGO ESCRITO | — | — | — | não registrada | tamanhos e SHA conferidos na API do HF |
| 93 | https://huggingface.co/vistralis/FLUX.2-klein-4b-INT8-transformer | NÃO INICIADO | — | — | — | não registrada | — |
