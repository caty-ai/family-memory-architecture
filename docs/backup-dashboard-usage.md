# Backup Dashboard Usage

`scripts/backup-dashboard` reads the jobs manifest and the heartbeat JSON files
written by `scripts/watchdog` / `scripts/job-heartbeat`, then writes one static
HTML health dashboard. It has no server-side dependency; serve the generated
file with Tailscale Serve or any ordinary static-file server.

## Data Sources

The dashboard reads `manifests/jobs.yaml` by default. Its default heartbeat
directory is `~/.claude/state/heartbeats` (override with `FMA_HEARTBEAT_DIR` or
`--heartbeat-dir`). The default output is
`~/.claude/state/dashboard/index.html`.

Each optional manifest `repo: owner/name` field renders a GitHub repository
link. Unless `--no-github` is supplied, the generator also best-effort queries
`gh api repos/<owner/name> --jq .pushed_at` and displays the last push time.
GitHub lookup failures never prevent dashboard generation.

## State Meanings

- **FAIL** 🔴: the heartbeat exists, parses, and has `status: "fail"`.
- **STALE** ⚪️: the heartbeat exists and parses, but its `last_run` is older
  than twice the job's `period_hours`. This is exactly the stale rule used by
  `scripts/watchdog`; staleness overrides an otherwise `ok` status.
- **NO_DATA** ◻️: the job's expected heartbeat is missing or unreadable, and
  its host is in the `--aggregated-hosts` allowlist (by default,
  `laptop,desktop`).
- **OK** 🟢: the heartbeat exists, parses, is not failed, and is not stale.

Jobs with a missing or unreadable heartbeat whose host is not in that allowlist
are shown in a separate trailing "not yet aggregated" section. That is neutral
rather than an error; today this is expected for the server until its heartbeat
aggregation is expanded. A server job with a heartbeat file that does exist is
still evaluated normally as FAIL, STALE, or OK.

## CLI Reference

Generate the default dashboard:

```sh
scripts/backup-dashboard
```

Useful options:

```sh
scripts/backup-dashboard --jobs manifests/jobs.yaml
scripts/backup-dashboard --heartbeat-dir ~/.claude/state/heartbeats
scripts/backup-dashboard --out ~/.claude/state/dashboard/index.html
scripts/backup-dashboard --aggregated-hosts laptop,desktop
scripts/backup-dashboard --aggregated-hosts laptop,desktop,server
scripts/backup-dashboard --no-github
scripts/backup-dashboard --dry-run --no-github
```

`--aggregated-hosts` defaults to `laptop,desktop`; pass a comma-separated
list such as `--aggregated-hosts laptop,desktop,server` to override it.

`--dry-run` writes the complete HTML to standard output and does not create or
modify the output path. Normal generation writes atomically, so readers keep
the previous complete dashboard if an output write fails.

## launchd Example

Install deployment wiring separately. A representative launchd plist runs the
generator every 30 minutes through the heartbeat wrapper. It first scp-pulls
the desktop heartbeats so their freshness matches the dashboard cadence —
with only the watchdog's daily 09:00 pull, hourly desktop jobs sat in false
STALE for most of the day (fma #109). The pull is best-effort (`|| true`):
an unreachable desktop must not block dashboard generation.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.agent-a.fma.backup-dashboard</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StartInterval</key>
  <integer>1800</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>scp -o BatchMode=yes -o ConnectTimeout=15 "you@192.0.2.20:.openclaw/state/heartbeats/*.json" /Users/you/.claude/state/heartbeats/ || true; exec /Users/you/family-memory-architecture/scripts/run-with-heartbeat backup-dashboard -- /Users/you/family-memory-architecture/scripts/backup-dashboard</string>
  </array>
  <key>StandardOutPath</key>
  <string>/tmp/fma-backup-dashboard.out</string>
  <key>StandardErrorPath</key>
  <string>/tmp/fma-backup-dashboard.err</string>
</dict>
</plist>
```

Adjust absolute paths for the deployed checkout. The wrapper records the
`backup-dashboard` heartbeat; a failed monitored backup job does not make a
successful dashboard-generation run fail.

## Tailscale Serve

Measured 2026-07-17 on the macOS App Store Tailscale build: `--set-path` with a
**file** target returns HTTP 500 ("an error occurred reading the file or
directory") regardless of file location or permissions — the sandboxed network
extension cannot read the file. Serve through a loopback proxy instead.

1. Run a tiny static server bound to loopback only (launchd `KeepAlive`, no
   heartbeat entry — it is a long-running daemon, not a periodic job):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.agent-a.fma.dashboard-httpd</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>-m</string>
    <string>http.server</string>
    <string>8890</string>
    <string>--bind</string>
    <string>127.0.0.1</string>
    <string>--directory</string>
    <string>/Users/you/.claude/state/dashboard</string>
  </array>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/fma-dashboard-httpd.out</string>
  <key>StandardErrorPath</key>
  <string>/tmp/fma-dashboard-httpd.err</string>
</dict>
</plist>
```

2. Mount it under `/dashboard` (coexists with any existing root proxy — do not
   replace an existing root serve target merely to add the dashboard path):

```sh
tailscale serve --bg --set-path /dashboard http://127.0.0.1:8890
```

The page is then available inside the tailnet at
`https://<host>.<tailnet>.ts.net/dashboard/` (trailing slash), e.g. from an
iPhone. Exposure is tailnet-only; the loopback bind keeps the LAN closed.

## v2 Candidates

- When server heartbeat aggregation is formally expanded (see fma #66), widen the
  `--aggregated-hosts` default to include `server`.
- Monthly restore-drill rotation display for #83.
- History graphs.
