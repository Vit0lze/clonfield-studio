# Investigação do encerramento do Qwen

> Histórico. O Qwen não roda mais dentro do processo do Gradio: a geração passa pelo ComfyUI e a sondagem `PROBE_QWEN` foi substituída pelo app **Teste de velocidade** (Sistema). O supervisor `cf_diagnose.py` continua registrando memória e fases do Studio.


## O que os dados antigos mostram

O processo pai registrou `-9`, isto é, o filho morreu com `SIGKILL`. O túnel já estava de pé, o download concluiu 23/23 e a barra de componentes chegou a 5/5. Não há traceback interno do Qwen ou mensagem CUDA antes da morte. A barra avança durante a carga dos componentes, portanto 5/5 não confirma que a construção do objeto da pipeline, a configuração do offload, a preparação do VAE ou a primeira inferência terminaram.

Na versão daquele log, depois de `from_pretrained` vinham `enable_model_cpu_offload` (ligado por padrão), ajustes do VAE e preparação da primeira geração. O offload transfere componentes entre GPU e CPU e pode pressionar RAM. A carga de shards também pode gerar picos de RAM e page cache mesmo com pesos finais em NF4. Em contraste, uma falha comum do alocador CUDA tende a aparecer como `torch.cuda.OutOfMemoryError`. O log apresentado não mostra essa exceção. OOM do sistema é uma hipótese plausível, mas encerramento externo do processo ou do runtime também é compatível com o sinal. Os contadores históricos do cgroup e logs do kernel daquele momento não estão disponíveis.

## Como isolar

Rode a última célula do Colab com `PROBE_QWEN = True` em uma sessão T4. A prova usa Qwen base NF4, 512×512, dois passos, seed fixa e sem LoRA, offload ou upscale. Se concluir, compare com a geração normal mudando uma variável por vez. Guarde o arquivo `diagnostico-*.jsonl` antes de iniciar outro teste ou encerrar o runtime.

O supervisor fica fora do processo do Gradio. Ele registra RSS atual e pico, RSS anônimo e de arquivo, RAM disponível, limite/consumo/pico do cgroup, contadores e amostras de uso de VRAM via `nvidia-smi` quando disponível. Marcos separam retorno de `from_pretrained`, offload, preparação do VAE, primeiro passo e decodificação. A seção entre entrada na pipeline e primeiro passo ainda inclui a codificação do prompt.

| Resultado | Interpretação |
|---|---|
| `sigkill_com_oom_no_cgroup` | Houve um OOM kill no cgroup durante a janela. Com aumento do consumo e morte do filho, é evidência forte de pressão de RAM, embora o contador possa incluir outros processos do mesmo grupo. |
| `sigkill_sem_causa_confirmada` | O sinal foi capturado e não houve aumento observável de `oom_kill`. A evidência não permite atribuir o evento a RAM, VRAM ou runtime. |
| `cuda_oom_reportado` | O PyTorch reportou falta de memória CUDA. Analise a etapa e o uso global observado. |
| `ok` no probe | Carga e uma inferência mínima concluídas nessa máquina. Não extrapole para resoluções maiores ou outros workflows. |

Uma sessão que derruba todo o kernel pode interromper também o supervisor. Nesse caso o último registro amostrado é o limite da observação. Os dados guardados são métricas e marcadores, sem saída bruta, prompt, URLs ou segredos.

Fontes técnicas: [cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html), [alocador CUDA do PyTorch](https://docs.pytorch.org/docs/stable/notes/cuda.html), [pipeline oficial Qwen-Image-2.1](https://huggingface.co/Qwen/Qwen-Image-2.1).
