# vault-lint usage

`scripts/vault-lint` checks the family vault for broken Obsidian links, orphaned notes, stale review claims, secrets, oversized files, and lifecycle drift.

## CLI

```sh
scripts/vault-lint [--vault-root PATH] [--mode light|deep] [--since-days N] [--archive-dir PATH] [--archive-stale-days N] [--report-dir PATH] [--json] [--no-heartbeat] [--inbox-post]
```

Flags:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--vault-root PATH` | `~/family-vault` | Vault root to scan. |
| `--mode light|deep` | `deep` | `deep` reports findings from the full vault; `light` builds the full graph and runs the full secret scan, always reports secret and structural lifecycle findings, and windows other findings to recently modified files. |
| `--since-days N` | `8` | Light-mode mtime window, compared against UTC wall time. |
| `--archive-dir PATH` | `~/archive` | Archive directory used to check whether binary exit candidates have a recent destination. |
| `--archive-stale-days N` | `90` | Archive inactivity threshold used by `archive-unused`; must be at least `1`. |
| `--report-dir PATH` | unset | Override JSON report directory. Takes precedence over `FMA_VAULT_LINT_DIR`. |
| `--json` | off | Print the JSON report to stdout instead of the human summary. Nothing else is printed to stdout in JSON mode. |
| `--no-heartbeat` | off | Skip heartbeat writing. |
| `--inbox-post` | off | Post a caution event only when fail-severity findings exist. |

## Modes

Both modes walk regular files under the vault root, skipping paths with dot-directory components such as `.git` or `.obsidian`. Link-graph, orphan, and stale-claim checks are markdown-only. Secret and oversize checks cover all regular files; the underlying secret scanner skips binary and non-UTF-8 files. Root structure checks inspect only direct children of the vault root, and root-level symlinks are reported as `root-orphan` even when their names start with `.`. Archive usage checks inspect only direct non-dot children of the archive directory.

`deep` reports all findings.

`light` still builds the full wikilink graph from all markdown files so old files can resolve links and inbound references correctly, and it runs a full-vault secret scan every time. Secret and structural lifecycle findings are always reported. Other findings are windowed by `--since-days`. For example, a recent note linking to a deleted note reports a `dead-link`; an old note with the same broken link is suppressed.

## Rules and severities

| Rule | Severity | Description |
| --- | --- | --- |
| `dead-link` | `warning` | Missing `[[wikilink]]`, `[[target|alias]]`, or `[[target#heading]]` target. Inline code spans and fenced code blocks are ignored. Existing non-markdown embed assets are valid; missing embeds are reported. |
| `orphan` | `warning` | Markdown file has zero inbound wikilinks and is not referenced by an `index.md`, `README.md`, or `_index`-named file. Files under top-level `00_index/` and `40_journals/`, and files with `orphan-ok: true`, are exempt. |
| `stale-claim` | `warning` | Frontmatter has `status: draft`, `status: draft-for-*`, or a past `review-by:` / `expires:` date. Top-level `25_review-pending/` files older than 30 days are also warnings. |
| `stale-claim` | `fail` | Top-level `25_review-pending/` files older than 90 days. |
| `secret` | `fail` | Redacted finding emitted by `scripts/secret-scan`. Raw file contents are not included by vault-lint. |
| `oversize` | `warning` | Markdown file is larger than 1 MiB (`1048576` bytes). |
| `root-orphan` | `warning` | Direct vault-root entry is not a numbered top-level directory, `README.md`, or a dot entry; root-level symlinks are always findings. |
| `binary-oversize` | `warning` | Non-markdown file is larger than 1 MiB (`1048576` bytes); move candidates belong in the archive flow. |
| `archive-unused` | `warning` | One or more `binary-oversize` findings exist, but the archive directory is missing, empty after ignoring dot entries, or its newest non-dot top-level entry has an mtime strictly earlier than `now - --archive-stale-days`. An entry exactly at the cutoff or newer suppresses the finding. |

Known limitation: `archive-unused` uses top-level entry mtime as the activity signal, so moves that preserve mtime or updates only inside nested directories can misjudge archive activity; this is acceptable for a weekly warning rule.

Exit codes:

| Exit code | Meaning |
| --- | --- |
| `0` | No findings, or warning-only findings. |
| `1` | Internal error such as a missing vault root or scanner failure. vault-lint still attempts report and heartbeat writes. |
| `2` | One or more `fail` findings. Only `secret` and `stale-claim` for `25_review-pending/` files older than 90 days can produce `fail`. |

Light and deep modes use the same exit-code mapping. Light mode can exit `0` when fail-level stale-claim findings exist only in files outside the recent mtime window, because windowed findings outside the window are not reported. Secret and structural lifecycle findings are never windowed.

## Reports

Every run writes a JSON report, including `--json` runs:

```text
~/.claude/state/vault-lint/report-<mode>-<UTC yyyymmddTHHMMSSZ>.json
```

Set `FMA_VAULT_LINT_DIR` to change the default directory, or pass `--report-dir PATH` for that run. The report shape is:

```json
{
  "mode": "deep",
  "vault_root": "/path/to/family-vault",
  "since_days": 8,
  "files_scanned": 123,
  "counts": {"dead-link": 1},
  "severity_counts": {"warning": 1, "fail": 0},
  "findings": []
}
```

## Heartbeat

Unless `--no-heartbeat` is passed, vault-lint writes:

```text
~/.claude/state/heartbeats/vault-lint-<mode>.json
```

Set `FMA_HEARTBEAT_DIR` to override the heartbeat directory. The heartbeat schema is:

| Key | Meaning |
| --- | --- |
| `job` | `vault-lint-light` or `vault-lint-deep`. |
| `last_run` | UTC ISO timestamp. |
| `status` | `ok` for exit `0`; `fail` for exit `1` or `2`. |
| `fail_count` | Consecutive fail count; resets to `0` on a clean/warning-only run. |
| `duration_ms` | Run duration in milliseconds. |
| `docs` | Number of markdown files scanned. |
| `mode` | `light` or `deep`. |
| `reason` | Present only when `status` is `fail`. |

## Inbox posting

`--inbox-post` is opt-in. When enabled and fail-severity findings exist, vault-lint invokes `scripts/hot-inbox-post --kind caution`.

The posted event summary includes only rule names and counts, for example `vault-lint: 3 secret finding(s), 1 stale-claim(90d+) finding(s)`. It does not include secret excerpts, file contents, or paths of secret findings. If posting fails, vault-lint logs a warning to stderr and keeps its own computed exit code.

## Cadence

Recommended cadence:

| Cadence | Command shape | Owner | Note |
| --- | --- | --- | --- |
| Weekly | `scripts/vault-lint --mode light` | Server cron managed by Agent B. | Runs a full-vault secret scan and full markdown link graph every time; only non-secret findings are subject to the `--since-days` report window. |
| Monthly | `scripts/vault-lint --mode deep` | Server cron managed by Agent B. | Reports all findings from full-vault secret/oversize checks and markdown link-graph checks. |
| Optional local check | `scripts/vault-lint --mode light --json` | Mac launchd can be added later if useful. | Same full-vault secret scan as weekly light mode; expected cost is measured in seconds. |

This document describes the intended cadence only; it does not configure cron or launchd.
