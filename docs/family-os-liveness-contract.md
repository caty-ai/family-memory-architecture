# family-os Liveness Contract — Heartbeat Consumer Handoff

- **Date**: 2026-07-24 +07
- **Author**: docs lane (Issue #136)
- **Producer side (FMA, merged)**: base heartbeat schema per [docs/jobs-framework.md](jobs-framework.md); additive liveness envelope per PR #119 (#118), emitted optionally by `scripts/job-heartbeat` (`--run-id`, `--origin`, `--started-at`, `--last-progress-at`, `--terminal-reason`, `--error-class`).
- **Consumer side (family-os)**: family-os policy already requires separate heartbeat/progress ages and additive unknown handling (`docs/operations-policy.md` §7), but the inspected renderer at family-os commit `acd549c77c32a081b02ef7473b15708a9ceadf31` still reads only the base heartbeat fields and does not render the envelope. The policy is adopted; the implementation is **baseline-only**. Envelope-aware rendering remains a family-os follow-up. FMA does not implement or fabricate that consumer.

## 1. Base keys (required, all producers)

| Key | Type | Meaning |
|---|---|---|
| `job` | string | Job name reported by the script |
| `last_run` | string | UTC ISO-8601 timestamp, seconds precision, trailing `Z` |
| `status` | enum | `ok` or `fail` |
| `fail_count` | int | Consecutive failures; resets to `0` on `ok` |
| `duration_ms` | int | Runtime duration in milliseconds |
| `docs` | int | Documents/items processed, `0` when not applicable |
| `reason` | string | **Required on `fail` by the producer contract**; short failure reason (producers truncate). The current watchdog does not enforce its presence. |

Serialization: `json.dumps(payload, indent=2, sort_keys=True) + "\n"`, UTF-8, as emitted through `scripts/lib_atomic.atomic_write_json`.

## 2. Additive liveness envelope (optional, all producers)

All envelope fields are independently optional. A producer may emit any subset.

| Key | Type | Meaning |
|---|---|---|
| `run_id` | string | Identifier of the run that produced this heartbeat |
| `origin` | enum | `user` \| `scheduled` \| `continuation` \| `recovery` \| `subagent` |
| `started_at` | string | UTC ISO timestamp, seconds precision, `Z` |
| `last_progress_at` | string | UTC ISO timestamp of the last observed progress inside the run |
| `terminal_reason` | enum | `completed` \| `no-progress` \| `budget` \| `infra` \| `blocked` \| `user-paused` |
| `error_class` | enum | `deterministic` \| `transient` \| `degenerate` \| `context-overflow` |

## 3. Consumer semantics (normative for any consumer, including family-os)

1. **Two ages, displayed separately**:
   - `heartbeat_age = now - last_run` — how long since the job last reported at all.
   - `progress_age = now - last_progress_at` — how long since the run last made progress. Computed only when `last_progress_at` is present; otherwise display `unknown`, never a derived guess.
2. **No proxies**: log-file mtime, percentage-complete fields, or any other side channel must not substitute for `last_run` / `last_progress_at`. If the field is absent, the value is `unknown` — full stop.
3. **Absent optional field = local unknown**: a missing envelope key makes that one display element `unknown`. It must **not** invalidate the heartbeat as a whole, and must not demote a valid base-only heartbeat to invalid.
4. **Unknown additive fields are ignored** (forward compatibility): a consumer must accept and silently ignore envelope keys it does not know. New producer fields must never break old consumers.
5. **Future timestamps / clock skew → `unknown` (or `paused`), never healthy**: a `last_run` or `last_progress_at` in the future, or any unparseable control state, must not be interpreted as healthy or active. Display `unknown`; where a liveness state is required, prefer `paused` over `healthy`.
6. **`stale != fail`**: an overdue heartbeat (`heartbeat_age` beyond the expected period) is a *staleness* signal, distinct from a reported `status: fail`. Display and alert on them differently.
7. **`paused != missing`**: a job reporting `terminal_reason: user-paused` (or quarantined/paused control state) is a known, deliberate state — not an absent heartbeat. Missing heartbeat file and paused job are different display states.

## 4. Watchdog aggregate payload

`scripts/watchdog` aggregates per-host results for consumers in this shape:

| Key | Type | Meaning |
|---|---|---|
| `host` | string | Host id as passed via `--host` (e.g. the manifest host labels) |
| `checked_at` | string | UTC ISO timestamp of the watchdog run |
| `jobs` | array | Per-job entries (job id + evaluation result) |
| `alert_count` | int | Number of jobs currently alerting |

The watchdog's own liveness is a normal heartbeat (`watchdog-<host>.json`) following §1–§2; see [docs/jobs-framework.md](jobs-framework.md) for alert conditions and exit codes.

## 5. Schema example (synthetic placeholders — not real data)

```json
{
  "job": "example-job",
  "last_run": "2026-01-01T00:15:00Z",
  "status": "fail",
  "fail_count": 2,
  "duration_ms": 1234,
  "docs": 0,
  "reason": "example reason placeholder",
  "run_id": "example-run-0001",
  "origin": "scheduled",
  "started_at": "2026-01-01T00:14:30Z",
  "last_progress_at": "2026-01-01T00:14:55Z",
  "terminal_reason": "infra",
  "error_class": "transient"
}
```

A base-only heartbeat (fully valid, envelope absent) is the same object with the six envelope keys removed.

## 6. Compatibility / failure table

The current-family-os cells below were checked against `scripts/refresh-status` at commit `acd549c77c32a081b02ef7473b15708a9ceadf31`, specifically `REQUIRED_HEARTBEAT_KEYS`, `payload_last_run`, and `evaluate_job`. The envelope-aware column is the required follow-up behavior, not a current implementation claim.

| Producer emits | Consumer baseline-only (current family-os) | Consumer envelope-aware (family-os follow-up) |
|---|---|---|
| Base keys only | Renders the existing base view; no envelope elements are rendered — **valid** | Renders base; envelope elements `unknown` — **valid** |
| Base + full envelope | Renders base keys; envelope ignored per §3.4 — **valid** | Renders both ages and envelope elements — **valid** |
| Base + partial envelope | Renders base keys; envelope fields are ignored and not rendered — **valid** | Present elements rendered; absent elements `unknown` — **valid** |
| Base + unknown new field | Ignored — **valid** | Ignored — **valid** |
| Missing/renamed `job`, `last_run`, or `status` | Current renderer marks the heartbeat invalid/`unknown`; watchdog also alerts — **producer defect** | Same — **producer defect** |
| Missing `fail_count`, `duration_ms`, or `docs` | Current renderer can still show its minimal base view; watchdog raises a missing-required-keys alert — **producer defect** | Surface the producer defect without inventing values |
| `last_run` in the future | `unknown`, never healthy (§3.5) | `unknown`, never healthy (§3.5) |
| Unparseable control/heartbeat JSON | Alert per watchdog; display `unknown`/`paused`, never healthy | Same |
| Overdue but `status: ok` | `stale` (not `fail`) — §3.6 | `stale` (not `fail`) — §3.6 |
| `terminal_reason: user-paused` | Envelope ignored; base status still rendered | `paused` state, distinct from missing heartbeat — §3.7 |
| `status: fail` without `reason` | Current renderer still shows base `fail`, and current watchdog does not enforce `reason`; record a **producer contract violation** separately | Reject as a producer contract violation; do not invent a reason |

## 7. Handoff boundary

- FMA owns: producer schema (base + envelope), watchdog semantics, this contract document.
- family-os owns: consumer rendering, including any envelope-aware display. That work is a **family-os follow-up** and is tracked there; nothing in FMA will claim consumer behavior that family-os has not implemented.
- The authoritative rendering policy on the family-os side is family-os `docs/operations-policy.md` §7 (D6/D19 liveness-rendering contract), referenced from DESIGN.md §C6. This document does not restate those rendering rules; it defines the wire contract and the minimal consumer semantics above.
