# Recall CLI

`scripts/recall` queries the family-memory recall facade and writes a full markdown result file to scratch.

```sh
scripts/recall "family-hot" --local-only --limit 3
```

Default layers are `sm,meili,grep`. Use `--local-only` to skip Supermemory, or `--layers meili,grep` to select layers explicitly. Supermemory uses `~/.config/supermemory/env` and reads `SUPERMEMORY_CC_API_KEY`, with surrounding shell quotes stripped before authentication. Matching `capture-shipper`, recall requires that file to be a regular, non-symlink file owned by the current user with mode `0600` (`chmod 600 ~/.config/supermemory/env`); invalid files are rejected before any API call.

The `meili` layer is not a bundled search engine; it shells out to an external search wrapper (see [Overriding defaults](#overriding-defaults) below) that must return JSON on its own. If that wrapper is not set up, the `meili` layer fails gracefully (reported as an errored layer in the output) and `recall` still returns results from the `sm` and `grep` layers.

Human output prints compact per-layer status, top hits, rejected-hit count, and the scratch path. `--json` prints the merged structure as JSON instead.

Scratch files default to `~/.claude/scratch/agent-a/recall/recall-<UTC>.md` and include the raw query for local readability. Stats append one JSONL line to `~/.claude/recall/stats.jsonl`; the raw query is never stored in the stats log, only the first 12 hex characters of its SHA-256 hash. Override these with `--scratch-dir` and `--stats-path`.

## Overriding defaults

The paths and container name below are the author's own environment (baked in as defaults for local convenience) and are very likely wrong for yours — override them via flag or environment variable before relying on `recall`.

| What | Flag | Env var | Default (author's environment) |
|---|---|---|---|
| Scratch output dir | `--scratch-dir` | — | `~/.claude/scratch/agent-a/recall/` |
| Stats log path | `--stats-path` | — | `~/.claude/recall/stats.jsonl` |
| Supermemory container tag | `--sm-container` | — | `personal-agent-a` |
| grep search roots | `--grep-root` (repeatable) | — | `~/.claude/projects/-Users-you-workspace/memory/`, `~/family-vault/`, `~/personal-wiki/` |
| Meilisearch layer wrapper | — | `RECALL_MEM_SEARCH` | `~/.claude/scripts/mem-search` (not shipped in this repo) |

Examples:

```sh
scripts/recall "birthday reminder" --layers meili,grep --limit 5
scripts/recall "policy" --json --local-only --scratch-dir /tmp/recall
scripts/recall "handoff" --grep-root ~/family-vault/ --limit 10
```
