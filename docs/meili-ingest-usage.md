# Meilisearch Ingest Usage

`scripts/meili-ingest` ingests only manifest-approved indexes for the family search surface.

## Commands

`--vault-root` defaults to `~/family-vault`; pass it explicitly if your vault lives elsewhere (as in the examples below).

Local development (requires Meilisearch running at `http://localhost:7700`):

```sh
scripts/meili-ingest family-vault --endpoint local-dev --vault-root ~/family-vault
scripts/meili-ingest family-hot --endpoint local-dev --vault-root ~/family-vault
scripts/meili-ingest family-vault --endpoint local-dev --vault-root ~/family-vault --dry-run --limit 5
scripts/meili-ingest family-hot --endpoint local-dev --vault-root ~/family-vault --dry-run
```

Family endpoint:

```sh
FAMILY_MEILI_WRITE_KEY_FAMILY_VAULT=<set-me> scripts/meili-ingest family-vault --endpoint family --vault-root ~/family-vault
FAMILY_MEILI_WRITE_KEY_FAMILY_HOT=<set-me> scripts/meili-ingest family-hot --endpoint family --vault-root ~/family-vault
```

Optional endpoint variables:

```sh
FAMILY_MEILI_URL=<set-me>
MEILI_LOCAL_KEY=<set-me>
```

Required family write key variable names:

- `FAMILY_MEILI_WRITE_KEY_FAMILY_VAULT`
- `FAMILY_MEILI_WRITE_KEY_FAMILY_HOT`

## Manifest Gate

The script loads `manifests/meilisearch-indexes.yaml` by default, resolved relative to the script location. A requested uid is ingestable only when the manifest entry has `status: active` and `ingest.script: scripts/meili-ingest`.

There is no override flag. Unknown, reserved, and `active-existing` indexes are refused before any HTTP work.

## Endpoint Ownership

`local-dev` uses `http://localhost:7700` and may auto-create missing indexes with the manifest-declared primary key, searchable attributes, and filterable attributes.

`family` uses `endpoints.family.url` from the manifest unless `FAMILY_MEILI_URL` is set. It requires the matching `FAMILY_MEILI_WRITE_KEY_*` variable. On the family endpoint, index creation, deletion, and orphan-document cleanup are Agent B-owned drift-check operations; this script only adds documents.

## Heartbeat

Each run writes a heartbeat to:

```text
~/.claude/state/heartbeats/meili-ingest-<uid>.json
```

Set `FMA_HEARTBEAT_DIR` to write heartbeats elsewhere.

Shape:

```json
{
  "job": "meili-ingest-<uid>",
  "last_run": "<UTC ISO8601>",
  "status": "ok",
  "fail_count": 0,
  "duration_ms": 123,
  "docs": 10,
  "endpoint": "local-dev"
}
```

Failed runs use `"status": "fail"` and include a short `"reason"` string.
