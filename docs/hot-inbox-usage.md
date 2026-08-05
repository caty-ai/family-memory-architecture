# Hot Inbox Usage

Post one immutable JSON event per 投函. These examples write to the default inbox unless
`FAMILY_HOT_INBOX` or `--inbox-dir` overrides it.

Decision:

```sh
scripts/hot-inbox-post --kind decision --title "Phase A merged" --summary "Phase A merged; budget gate and overlap lint are weekly." --canonical-path "family-vault/30_decisions/phase-a-merged.md" --priority P1 --related "#5"
```

Project:

```sh
scripts/hot-inbox-post --kind project --title "Hot inbox agent-a side" --summary "Agent A is posting create-once family-hot events for Agent B to generate." --canonical-path "family-vault/20_projects/hot-inbox-agent-a.md" --owner agent-a --priority P1 --related "#5"
```

Blocker:

```sh
scripts/hot-inbox-post --kind blocker --title "Generator contract awaiting Agent B" --summary "Reader checksum verification is ready but generator output is not yet registered." --canonical-path "family-vault/20_projects/family-hot.md" --owner agent-b --priority P1 --related "#5"
```

Caution:

```sh
scripts/hot-inbox-post --kind caution --title "Do not edit family-hot manually" --summary "Manual edits invalidate body_sha256 and will be skipped by the reader." --canonical-url "https://github.com/caty-ai/family-memory-architecture/issues/5" --promotion-pending --priority P2
```

Expire:

```sh
scripts/hot-inbox-post --kind expire --target-event-id "20260704T091500Z__agent-a__decision__phase-a-merged__a1b2c3d4"
```

## 滞留 expire 運用

- Trigger: act when `overflow: N events pending` appears in `family-hot.md`, or the generator heartbeat reports `status=fail`.
- Owner: the event's own `o:` expires their stale events first. The deploy-boundary owner (Agent B) may compact any event when capacity is blocked family-wide.
- Action: post an `expire` event targeting the stale `event_id`. Optionally re-post a compacted replacement: a shorter summary pointing to the canonical issue/URL instead of carrying full detail. This is the pattern Agent B used on 2026-07-10 (expire x4 + compacted x2) to unblock the two-day outage.
- Cadence: check on the overflow marker or heartbeat-fail signal, not on a fixed timer.

Reader hook wiring is approved and in production. On Claude Code it is registered as a
`SessionStart` hook in `~/.claude/settings.json` (verified live on 2026-08-04):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "command": "python3 \"<repo>/scripts/family-hot-read\" --path <vault>/00_index/family-hot.md --check"
      }
    ]
  }
}
```

Other runtimes follow the same pattern: run `family-hot-read` at session start and inject
its stdout into the session context. OpenClaw adopted the same session-start read on
2026-07-26 (documented separately in the operator's internal handbook). A new agent
joining the vault adds this wiring on its own runtime; nothing else needs to change on
the generator side.

> History note: until 2026-07 this section froze hook registration pending the
> operator's GO. That GO was given and the rollout happened; the freeze is lifted.

Generator interop contract for `body_sha256`: read the generated file as raw bytes, split
with `bytes.splitlines(keepends=True)`, join all lines except line 2, meaning 0-indexed
`lines[1]`, then compute `hashlib.sha256(body_bytes).hexdigest()` over that joined byte
sequence.
