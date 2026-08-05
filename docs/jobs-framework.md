# Jobs Framework

This issue adds the common heartbeat and watchdog base for DESIGN §C6 automation jobs.

## Heartbeat JSON

Heartbeat files are byte-compatible with the standard writer shape used by `scripts/meili-ingest`: JSON is written as `json.dumps(payload, indent=2, sort_keys=True) + "\n"` using UTF-8, and timestamps are UTC ISO seconds ending in `Z`.

| Field | Required | Meaning |
|---|---:|---|
| `job` | yes | Job name reported by the script. |
| `last_run` | yes | UTC ISO timestamp, seconds precision, trailing `Z`. |
| `status` | yes | `ok` or `fail`. |
| `fail_count` | yes | Consecutive failure count. Resets to `0` on `ok`; increments on `fail`. |
| `duration_ms` | yes | Runtime duration in milliseconds. |
| `docs` | yes | Number of documents/items processed, or `0` when not applicable. |
| `reason` | only on fail | Short failure reason, truncated by emitters. |
| `schema_version` | no | Optional explicit schema tag. The current value is `job-heartbeat/v1`; absence remains the legacy v1 shape. Any other value is fail-closed as an unknown version. |

Shell jobs can emit this schema with:

```sh
scripts/job-heartbeat <job-name> ok
scripts/job-heartbeat <job-name> fail --reason "short reason"
```

The default heartbeat directory is `~/.claude/state/heartbeats`; `FMA_HEARTBEAT_DIR` or `--heartbeat-dir` can override it.

## Jobs Manifest

`manifests/jobs.yaml` is the watchdog input. Removing a job there removes it from monitoring.

| Field | Required | Meaning |
|---|---:|---|
| `id` | yes | Stable job id. |
| `desc` | yes | Human description. |
| `host` | yes | Execution host: `laptop`, `server`, or `desktop` (desktop heartbeats are scp-pulled to laptop every 30 min by the dashboard launchd job and daily at 09:00 by the watchdog plist; fma #66/#109). |
| `owner` | yes | Responsible owner: `agent-a`, `agent-b`, or `agent-c`. |
| `period_hours` | yes | Expected cadence in hours, or `null` for on-demand jobs. |
| `heartbeat` | yes | Filename relative to the heartbeat directory. |
| `alert` | yes | Alert route list: `stderr`, `notify`, and/or `inbox`. |
| `note` | no | Free-text enforcement or deviation note. |
| `exempt` | no | Defaults to false. True means watchdog skips alert checks entirely. |

## Watchdog Semantics

`scripts/watchdog` checks jobs matching `--host` and skips `exempt: true` jobs. A job alerts when any of these conditions is true:

1. The heartbeat file is missing.
2. The heartbeat parses and `period_hours` is numeric, but `now - last_run` is greater than `2 * period_hours`.
3. The heartbeat parses, `status == "fail"`, and `fail_count >= 3`.

Corrupt control state is not a stale alert. If a heartbeat is unparseable, has
an unknown explicit schema version, lacks a required field, or has invalid
required values, the watchdog atomically creates
`<heartbeat-dir>/.paused/<heartbeat-filename>.pause.json` and reports the job
as `PAUSED`. Reasons use distinct `corrupt`, `unknown-version`, and
`missing-required-field` codes. The original heartbeat is read-only evidence:
the watchdog never repairs, replaces, renames, or quarantines it.

A pause marker is persistent scheduling state. Later valid-looking heartbeat
content cannot make the job runnable, and `scripts/job-heartbeat` refuses to
replace the heartbeat while the marker exists. Scheduling integrations must
treat `paused` as ineligible. The watchdog's own heartbeat write is also
suppressed when its pause marker exists, so a corrupt
`watchdog-<host>.json` is preserved.

After inspecting and manually correcting or replacing the evidence, the
operator re-arms one job explicitly with:

```sh
scripts/watchdog --host <host> --resume <job-id>
```

This removes only that job's pause marker and immediately checks the heartbeat.
If the heartbeat is still invalid, the same run pauses it again. There is no
automatic re-arm or guessed repair path. Re-arm is host-owned: `--host` must
match the job's manifest `host`; a wrong-host request is rejected without
removing the pause marker. This persistent `paused-never-scheduled` state is the
control-plane fail-closed response, rather than guessing a runnable state from
damaged evidence.

For `period_hours: null` on-demand jobs, the watchdog never alerts only because the heartbeat is old; only fail-count and invalid-heartbeat checks apply.

Alert routes:

- `stderr`: represented by the normal human output or `--json` output.
- `notify`: `--notify` sends a macOS notification when alerts exist.
- `inbox`: `--inbox-post` posts a caution event through `scripts/hot-inbox-post`.

Exit codes:

- `0`: no alerts.
- `2`: one or more monitored jobs alert or are paused.
- `1`: internal watchdog error, such as an unreadable manifest.

Human and JSON output count `paused` and `stale` separately. Paused jobs still
flow through their configured alert routes so the operator-visible reason is
not lost.

The watchdog writes its own `watchdog-<host>.json` heartbeat (for example, `watchdog-laptop.json` or `watchdog-desktop.json`) at the end of every run, using the `--host` value passed in. Alerts about other jobs still count as an `ok` watchdog run; internal watchdog errors write `status: fail`. The `watchdog-<host>` manifest entry for each host means the next run for that host monitors the previous watchdog run for the same host.

## Hot-Inbox Corrupt-Record Handling

`scripts/hot-inbox-reader` strictly accepts UTF-8 JSON events using
`family-hot-event/v0` and the required producer fields. A malformed or unknown
event is never dispatched. The reader skips it, continues with later events,
and writes a create-once host-local copy at
`<state-dir>/quarantine/<event-name>.corrupt`.

The event bytes are passed to `scripts/secret-scan --redact` in memory before
that copy is written. Clean UTF-8 input is preserved verbatim. A secret finding,
binary/invalid UTF-8 input, scanner error, or scanner timeout produces a
metadata-only JSON copy containing size and SHA-256, never the raw bytes.
Corrupt copies expire after seven days; the separate quarantine marker remains
while the source event is present, preventing repeated dispatch or repeated
copy creation. Its mtime is refreshed while the source remains, and it is
garbage-collected after the source has been continuously absent for seven days.
The `.corrupt` copy has its own independent seven-day retention based on its
mtime, even if the source remains present. These files are Class 3 host-local
mutable state under DESIGN §D11 and must not be placed in the shared vault.

The only record-reading leniency remains the existing first-party append-only
JSONL behavior: one torn final record may be skipped without invalidating
earlier complete records. Hot-inbox event files are one JSON object each and do
not receive that exception.

## Corrupt-State Recovery And Rollback

For a paused job, first inspect the reason with:

```sh
scripts/watchdog --host <host> --json
```

Then preserve the heartbeat and its `.paused/*.pause.json` marker in a restricted
host-local incident directory. Repair or replace the heartbeat from a known-good
producer, and re-arm it with the matching manifest host:

```sh
scripts/watchdog --host <host> --resume <job-id>
```

Success removes the marker and reports the job healthy; invalid replacement
state recreates the marker in that same run. To roll back a mistaken re-arm,
stop or disable that job's scheduler first, then atomically restore the saved
pause marker (write a temporary file in `.paused/`, then rename it over the
marker path) and rerun the watchdog to confirm `PAUSED`. Never restore the old
behavior by merely deleting a marker or allowing a heartbeat writer to bypass
it.

For a quarantined hot-inbox event, treat the source plus `.corrupt` artifact as
forensic input, not as a retry queue. Recover from a false positive by validating
the source offline and publishing a new valid event with a new event id and
filename; do not delete the marker to dispatch the old bytes. Rollback of the
reader deployment must leave quarantine markers and host-local artifacts in
place for their independent retention rules: the marker ages only after source
absence, while the `.corrupt` copy ages from its own mtime. Metadata-only
artifacts cannot recover raw content; use the original shared source under
incident controls if investigation requires it, and never copy secret-bearing
raw bytes into quarantine or logs.

## Per-Host Operation

`laptop` jobs are intended to run under launchd. Actual plist deployment wiring is out of scope for this issue and should land separately.

`server` jobs are intended to run under cron. Actual crontab deployment wiring is also out of scope for this issue.

## How To Add A Job

1. Have the job script call `scripts/job-heartbeat <job-name> ok|fail ...` at the end of its run.
2. Add an entry to `manifests/jobs.yaml` with the correct host, owner, period, heartbeat filename, and alert routes.
3. Run `scripts/watchdog --host <host>` and confirm the job is picked up.

When a job is retired, remove its entry from `manifests/jobs.yaml` as part of the closeout checklist. The closeout policy reference is `policies/closeout-rollover.md` §4.

## family-hot-generate Heartbeat

`family-hot-generate` emits a standard `job-heartbeat` JSON on every run. The generator's `main()` calls `generate()` and then, in a `finally` block, emits the heartbeat with `status: ok` or `status: fail` plus `docs`/`duration_ms` (skipped only for `--dry-run`/`--check` invocations). The heartbeat write is best-effort: if it fails, a warning goes to stderr but the generator's own exit status is unaffected. `manifests/jobs.yaml` lists `family-hot-generate` as a normal monitored job (`alert: [inbox]`, no `exempt: true`); the watchdog checks it like any other job.

## Personal Hot Lint Deviation

`~/personal-wiki/wiki/hot.md` is hand-curated by the wiki save flow, unlike a hypothetical auto-regenerated hot cache. This issue applies the same cap, lint, and observability discipline as other hot-cache tooling without auto-regeneration. Auto-regeneration is deliberately out of scope.

This follows DESIGN.md 原則4: machine-enforceable boundaries should be enforced, but discipline that cannot be mechanized must be described honestly as a norm rather than overstated as enforcement. Here, size, staleness, dead-link checks, secret-scan, and heartbeat emission are mechanized; curation remains a human workflow.
