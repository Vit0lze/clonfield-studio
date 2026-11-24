# AssetRef.v1 — contrato congelado (V9-P1-ASSET-001)

Dono do contrato: Opus. Mudança de campo ou rota exige registro aqui antes do código.
Base: `v9/integration` `c314f6a`. Asset Graph é a camada de **ativos e relações**; o executor continua sendo `cf_dag.py` (sem segundo DAG).

## Problema que resolve (o que existe hoje)
- «Usar em» (`portal/js/views/app.js` `sendTo` → `POST /import` em `cf_api.py`) **copia** o resultado para uma pasta nova em `uploads/<32hex>/`. Cada uso = cópia nova, sem identidade, sem versão, sem procedência.
- Elenco (`cf_cast.py`) guarda um PNG por personagem, sobrescrevível por remoção; sem hash nem versão.
- O cache do DAG (`cf_dag.node_hash`, `artifact_hash`) já é por **conteúdo**: uma mídia nova recomputa só os nós descendentes. Isso é reaproveitado, não reescrito.

## Armazenamento (`cf_asset_graph.py`, módulo novo, único dono do formato)
- `<base>/assets/blobs/<sha256>.<ext>`: conteúdo endereçado por hash, **imutável** (gravado uma vez, `chmod 0o444`, nunca sobrescrito). Mesmo SHA = mesmo blob (deduplicação), autoria e versões continuam separadas no índice.
- `<base>/assets/index.json`: `{"assets": {asset_id: Asset}, "versions": {version_id: AssetRef}}`, gravação atômica (`.part` + `replace`) sob `threading.Lock`.
- Ids: `asset_id = "a_" + 16 hex`, `version_id = "v_" + 16 hex` (aleatórios). Nunca expõem caminho de disco.

## AssetRef.v1 (uma versão)
```json
{
  "schema": "AssetRef.v1",
  "asset_id": "a_…", "version_id": "v_…", "number": 1,
  "kind": "image|video|audio|character",
  "mime": "image/png", "sha256": "<64 hex>", "bytes": 12345,
  "storage_ref": "blobs/<sha256>.png",
  "parents": [{"asset_id": "a_…", "version_id": "v_…", "role": "previous|source|reference|character"}],
  "producer": {"kind": "upload|job|cast|import", "job_id": null, "app": null, "capability_id": null, "graph_run_id": null},
  "recipe": {"params": {}, "seed": null, "model_variant": null},
  "media": {"width": null, "height": null, "duration_s": null},
  "metadata": {"title": "…", "name": null, "description": null, "license": null, "consent": null, "note": null},
  "state": "ready",
  "created": 0
}
```
`Asset` = `{"asset_id", "kind", "title", "created", "versions": [version_id, …] (ordem de criação), "current": version_id}`.

## Invariantes (cada um tem teste)
1. Original imutável: publicar não altera o arquivo de origem; o blob é somente leitura; o `sha256` do blob confere sempre (`verify(version_id)`).
2. Nova versão nunca substitui a anterior: `add_version` acrescenta; `current` muda; a versão anterior continua resolvível e selecionável.
3. Referência, não cópia: consumir uma versão resolve para o **mesmo blob** (mesmo caminho, mesmo inode). «Usar em» com ativo não cria pasta em `uploads/`.
4. Deduplicação: publicar um arquivo cujo SHA já é a versão `current` de um ativo do mesmo `kind` devolve esse ativo/versão (idempotente) em vez de criar outro.
5. Validação na entrada: só arquivos dentro de `out_dir`, `uploads/` ou `cast/`; extensão em `cf_jobs.KINDS` (ou `character` a partir do Elenco); tamanho > 0.
6. Cache parcial: um grafo do DAG que lê `{"media": "v_…"}` usa o hash do blob; trocar `v1` por `v2` recomputa só os descendentes daquele insumo (provado com um ramo independente que continua em cache).

## Resolução (um só ponto)
`cf_asset_graph.resolve(base, ident) -> Path | None` aceita `v_<16hex>` (versão exata) e `a_<16hex>` (versão `current` no momento da chamada; o job registra qual versão usou). Os pontos de `cf_api.py` que hoje aceitam só `[0-9a-f]{32}` de `uploads/` passam a aceitar também essas formas via um helper único:
- `resolve_files` (jobs de app), `upload_media` (DAG), `upload_info` (`GET /uploads/{ident}`, usado pelo portal para hidratar miniaturas).

## API (prefixo `/clonfield/api`, mesma autenticação)
| Rota | Corpo / retorno |
|---|---|
| `POST /assets` | `{"from": {"result": "<rel em out_dir>"} \| {"upload": "<32hex>"} \| {"cast": "<id>"}, "title"?, "kind"?}` → `{"asset": Asset, "version": AssetRef, "url": assinada, "deduplicated": bool}` |
| `GET /assets` | lista `Asset` + versão `current` resumida + url assinada |
| `GET /assets/{asset_id}` | `Asset` + todas as versões (AssetRef + url) |
| `POST /assets/{asset_id}/versions` | `{"from": …, "note"?}` → nova versão |
| `GET /assets/versions/{version_id}` | AssetRef + url + `verified: true/false` |
Job: `GET /jobs/{id}` traz `asset_versions` = {id pedido: version_id usada} quando o job leu ativos (procedência; os `params` continuam fora da resposta).
Erros: 400 com motivo (origem fora das pastas, formato), 404 (id desconhecido).

## Portal
- «Usar em» (`sendTo` em `app.js`): `POST /assets {"from":{"result": path}}` e prefill com `{id: version_id, name, kind, url}`; **sem** `/import`. `sendShots` (Storyboard→receita) idem.
- Rota nova `#/assets` («Ativos» no menu): cartões com miniatura, título, nº de versões; dentro, a lista de versões (número, data, sha curto, «atual»), um seletor de versão e o menu «Usar em» com a versão escolhida; «Nova versão» por upload.
- Elenco: botão «Publicar como ativo» por personagem com imagem (`kind: character`, `metadata.name/description`).
- Bump de `?v=N` em `portal/index.html`.

## Fora do escopo desta entrega
Timeline/Cinema, apagar ativos, exportar/backup, ativos de LoRA/GLB/PSD, migração dos uploads antigos, busca por embeddings.
