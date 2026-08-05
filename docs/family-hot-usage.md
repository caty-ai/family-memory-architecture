# Family Hot Generator Usage

`scripts/family-hot-generate` reads immutable JSON events from
`~/family-vault/00_index/hot-inbox/` and writes the generated
`~/family-vault/00_index/family-hot.md` plus
`family-hot.sources.json`.

Run manually after deploy and after any schema or boundary change:

```sh
scripts/family-hot-generate --vault-root ~/family-vault
scripts/family-hot-lint --vault-root ~/family-vault
scripts/family-hot-read --path ~/family-vault/00_index/family-hot.md --check
```

Server cron should run every 15 minutes with a single-run guard:

```cron
*/15 * * * * flock -n /tmp/family-hot-generate.lock /srv/family-memory-architecture/scripts/family-hot-generate --vault-root /srv/shared/family-vault >/tmp/family-hot-generate.out 2>/tmp/family-hot-generate.err
```

Reader fallback points to this usage document (the default `--fallback-pointer` of `family-hot-read`); point it at your own operations page per deployment if you keep one.

Lint exit codes:

- `0` means ok: marker, checksums, ledger, caps, pointers, and source hashes are valid.
- `1` means warning: the file is readable, but a temporary item needs attention. Current warnings are promotion-pending decisions older than 24 hours, or expired cautions still present in the inbox without an expire event.
- `2` means fail: do not trust the generated file. Failures include missing marker, bad metadata, body checksum mismatch, mutated or missing ledger source, missing canonical pointer, class cap overflow, file size over 2048 bytes, secret-like output, promotion-pending decisions older than 72 hours without owner plus next review, or caution TTL longer than 14 days.

The generator never deletes, renames, or rewrites inbox files. If generation would
fail because of overflow, secret-like content, lint failure, or self-check failure,
it exits without overwriting the last valid `family-hot.md` or ledger.

## Failure semantics

The generator writes `family-hot.sources.json` first, then `family-hot.md`.

The injected surface only changes after the ledger has been durably persisted.
If the ledger write fails, the previously served `family-hot.md` remains
byte-identical. If the output write fails after the ledger update, the old valid
output keeps serving and lint reports `ledger-output-mismatch`; the next
successful cron run rewrites both files from current inbox state.

If a `promotion_pending` class-5 item goes stale beyond Agent B's 72h SLA without
owner plus next review, generation hard-fails and writes nothing. This preserves
the last valid output and treats stale promotion as blocking instead of silently
rendering it.

## Operational invariants — file permissions (issue #28 quick win)

Agreed with Agent B's feasibility note on issue #28 (2026-07-06):

1. The generator runs as a single writer account on the server.
2. Generated artifacts MUST remain mode `0600` and owned by the expected
   owner after every generation: `00_index/family-hot.md` and
   `00_index/family-hot.sources.json`. By default the expected owner is
   whichever user runs the generator (the current process owner), which keeps
   the self-check portable across machines. A deployment that runs the
   generator under a dedicated account pins this invariant explicitly with
   `FMA_EXPECT_OWNER="user:group"`; an unrecognized user/group name then fails
   closed instead of silently weakening the check. If the generator ever
   creates these files fresh, it must restore `0600` (and the expected
   owner) before exiting. Verifying this after each run is part of the
   generator's self-check surface (see `scripts/family-hot-generate`).
3. `00_index/` directory tightening (currently `0775`, group-writable, which
   still allows rename/replace of the generated files by group members) is a
   candidate hardening — pending confirmation that no other local writer
   needs group write. Tracked on issue #28.
4. Syncthing send-only for `00_index` is NOT a one-line change (the synced
   folder is the whole `/srv/shared`); it requires splitting `00_index` into
   its own Syncthing folder or an equivalent override policy. This ships as
   an explicit config PR + runbook, tracked separately on issue #28.

These are protocol/OS-level mitigations; signing (HMAC/minisign) remains the
v1 goal of issue #28.

## Threat model (v0)

Checksums detect corruption and accidental edits; they do not detect malicious
writers who can rewrite the generated file and recompute public hashes. The
single-writer rule is a protocol constraint, not a security boundary; signing
and OS hardening are tracked separately in issue #28.

Reader and lint are intentionally separated. The reader blocks marker and
`body_sha256` failures at SessionStart, while ledger and provenance failures are
lint-only by design for speed. After the ledger-first write order, the ledger is
always at least as new as the output.

Canonical pointers are string-validated only in v0. Existence and provenance
checks for referenced Family Vault paths or GitHub issues are future work.
