# Contratos do Studio

Um formato para tudo que o Studio lista, busca, instala e usa. Código: `cf_contracts.py` (regras), `cf_library.py` (provedores),
`portal/js/catalog.js` (cartão único), `portal/js/views/library.js` (página). Testes: `tests/test_contracts.py`.

## CatalogItem
Todo cartão da Biblioteca vem deste formato, seja receita, LoRA, VAE, encoder, upscaler ou arquivo do CivitAI/Hugging Face.

| Campo | Regra |
|---|---|
| `kind` | `model` `lora` `vae` `encoder` `upscaler` |
| `source` | `receita` `embutido` `civitai` `huggingface` `worker` |
| `status` | `encontrado` < `descoberto` < `compatível` < `instalado` < `validado`. **Só `validado` (testado neste worker) significa executável**; `descoberto` nunca promete nada |
| `size` | bytes inteiros ou `null`. Nunca estimado. Desconhecido fica «tamanho não informado» |
| `size_parts` | lista `{label, size, shared_with[], installed}`: o total é a soma das partes. Um arquivo que várias receitas usam (mesmo nome na pasta) é baixado **uma vez** e declara `shared_with` |
| `compat` | `{family, note, validated}` |
| `favorite` | `{kind, id, meta}`, id = `<source>:<id>`. A estrela é do cartão, no canto, igual em todo lugar |
| `actions` | lista de ações (abaixo). A UI **renderiza** ações, nunca deduz da fonte |
| `adult` | marca conteúdo adulto; o filtro «Ocultar adulto» é do usuário |

## Action
`id` ∈ `install` `use` `open` `cancel`; `enabled` e, se desabilitada, `reason` obrigatório (o botão mostra o motivo).
Uma ação traz **um** destino: `call {method, path, body, follow}` (cria um job que a UI acompanha), `prefill {app, values}` (abre um app já preenchido) ou `href`.

## Categoria e visões
`CATEGORIES` define cada tipo, as fontes aceitas e se filtra por modelo compatível. Toda categoria tem as mesmas três visões:
**Recomendados** (o que o projeto cura), **Instalados** (o que já está no worker ou no inventário), **Explorar** (CivitAI, Hugging Face, no worker; upscalers também «Já no Studio»).

## Instalação (mesmos estados para qualquer tipo)
`na fila → baixando → verificando (SHA-256) → registrando → instalado` ou `falhou` / `cancelado`. Um arquivo que não confere é apagado.

## Regras que os provedores seguem (validadas em teste)
1. Item inválido nunca sai do servidor (`check()`).
2. Um favorito = um id, em qualquer tela.
3. Nada vira `validado` sem prova em GPU.
4. Hugging Face só descobre: instalar fica desabilitado com motivo.
5. Antes de baixar, o tamanho que falta é mostrado e os arquivos compartilhados são explicados.

## Como adicionar um tipo novo
Adicione uma entrada em `CATEGORIES`, um ramo em `cf_library.library`, e as ações que ele realmente tem. A UI não muda.
