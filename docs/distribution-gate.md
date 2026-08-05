# Distribution Gate — Operator-Attended Runbook

- **Date**: 2026-07-24 +07
- **Author**: docs lane (Issue #136), execution authority: the operator only
- **Parent**: #131 §B (operator 同席・配布 gate), §C (post-distribution observation)
- **Status**: TEMPLATE — nothing in this document has been executed. Commands are operator templates, not evidence of execution; every mutating action requires the adjacent Operator GO and local placeholder substitution. No real credential, IP address, hostname, token, or key appears in this document, and none may be discovered, recorded, or pasted into issues/PRs/logs while executing it.

## 0. Ground rules

- **The operator attends every step.** No agent executes any step here autonomously. Each step ends with an explicit `Operator GO` checkbox; an unchecked box means the step did not happen.
- **Placeholder convention**: `<LIKE_THIS>` is a value the operator supplies locally at execution time and never commits. Redacted evidence uses the form `<redacted:CREDENTIAL_KIND>`.
- **Evidence is redacted by construction**: capture command exit codes, counts, timestamps, file modes, and digests — never values.
- **Secret-bearing backups stay local**: a backup that may contain a legacy secret is mode `0600`, host-local, outside synced/shared paths, never uploaded, and retained only through the rollback window. After revocation, remove it under operator supervision and retain only a sanitized deletion timestamp/digest record; do not claim physical secure erasure on copy-on-write storage.
- **Rollback owner** for every step is the operator unless a step explicitly names a different owner. Agents assist; they do not own rollback.
- **Precondition for the whole runbook**: pre-distribution RC readiness per [docs/pre-distribution-rc.md](pre-distribution-rc.md) is declared by Agent A with complete evidence. This runbook does not start before that.

## 1. Credentials: #78 / #47 issue, rotate, revoke

Tracked issues: #78 (LaunchAgent plaintext credential → Keychain/0600 env, rotation) — OPEN; #47 (personal-agent-g Supermemory container) — OPEN, operator gate.

### Step 1.1 — Inventory existing credential placements

- **Precondition**: RC declared. Operator present.
- **Template**:
  ```text
  # List candidate plist/env locations WITHOUT printing values
  ls -la <LAUNCHAGENT_DIR> | grep <AGENT_NAME_PATTERN>
  grep -l '<KEY_NAME_PATTERN>' <LAUNCHAGENT_DIR>/*.plist | wc -l
  ```
- **Evidence to capture (redacted)**: file paths, file modes, count of files containing the key name pattern. Never the values.
- **Rollback point**: read-only step; no rollback needed.
- [ ] **Operator GO**

### Step 1.2 — Issue new credentials / rotate

- **Precondition**: Step 1.1 evidence recorded. Target service console open by the operator (e.g. Supermemory container issuance for #47).
- **Template**:
  ```text
  # The implementation must create a new 0600 container without clobbering an existing file
  <CREATE_SECRET_CONTAINER_CMD> --path <HOST_LOCAL_SECRET_PATH> --mode 0600 --no-clobber
  # The operator pastes the value directly on the host console; one-time-secret links are consumed on the target host only
  ```
- **Evidence to capture (redacted)**: file path, mode `0600`, creation timestamp, `<redacted:SUPERMEMORY_KEY>`-style markers.
- **Rollback point**: old credential still valid until Step 1.4; keep the old placement untouched until then.
- [ ] **Operator GO**

### Step 1.3 — Switch consumers to the new placement

- **Precondition**: Step 1.2 done; consumers identified per target (§3).
- **Template**:
  ```text
  <BACKUP_SERVICE_CONFIG_CMD> --service <SERVICE_ID> --out <BACKUP_PATH> --mode 0600 --no-sync
  <VERIFY_BACKUP_CMD> --path <BACKUP_PATH>
  # These placeholders must resolve to a secret REFERENCE, never a secret value
  <CONFIGURE_SECRET_REFERENCE_CMD> --service <SERVICE_ID> --reference <HOST_LOCAL_SECRET_REF>
  <VALIDATE_CONFIG_CMD> --service <SERVICE_ID> --redact
  <RESTART_SERVICE_CMD> --service <SERVICE_ID>
  ```
- **Evidence to capture (redacted)**: exit codes, service restart timestamps, post-switch health check output with values redacted.
- **Rollback point**: previous plist/unit saved at `<BACKUP_DIR>/<timestamp>/`; restore = copy back + kickstart.
- [ ] **Operator GO**

### Step 1.4 — Revoke old credentials

- **Precondition**: ≥1 clean health check cycle on the new placement for every consumer.
- **Template**: revoke via the service console (the operator, interactive). No shell template applies.
- **Evidence to capture (redacted)**: revocation timestamp, key suffix/fingerprint only (`<redacted:KEY_SUFFIX>`).
- **Rollback / recovery point**: revocation itself is irreversible. Before the operator checks GO, every consumer must be green on the new credential and the issuer's emergency reissue path must be tested without exposing a value. If post-revocation validation fails, stop distribution, issue a replacement credential, update the host-local reference, and revalidate before proceeding.
- [ ] **Operator GO**

## 2. Scheduler ownership switch: LaunchAgent / Keychain / cron / systemd

- **Precondition**: Step 1 complete for the affected host. Current scheduler entries inventoried (who owns each job today vs. who should own it per `manifests/jobs.yaml`).
- **Template**:
  ```text
  <BACKUP_SCHEDULER_CONFIG_CMD> --out <BACKUP_PATH>
  <VERIFY_BACKUP_CMD> --path <BACKUP_PATH>
  <VALIDATE_NEW_SCHEDULER_CMD> --config <NEW_CONFIG_PATH>
  <DISABLE_OLD_SCHEDULER_CMD> --id <OLD_SCHEDULER_ID>
  <ENABLE_NEW_SCHEDULER_CMD> --config <NEW_CONFIG_PATH>
  <VERIFY_SINGLE_OWNER_CMD> --job <JOB_ID> --redact
  ```
- **Evidence to capture (redacted)**: before/after job listings (labels/unit names only), heartbeat files appearing under `FMA_HEARTBEAT_DIR` with `status: ok`.
- **Rollback point**: bootout/disable is reversible; old unit/plist/crontab backups in `<BACKUP_DIR>/<timestamp>/`. Rollback = re-enable old, disable new, confirm old heartbeat resumes.
- [ ] **Operator GO**

## 3. #100 gateway ownership resolution

#100 (agent-b gateway: systemd unit vs. self-managed process contention) — OPEN. Exactly one owner must drive the gateway process per host.

- **Precondition**: contention reproduced or positively ruled out with evidence; chosen owner (systemd unit **or** self-managed process, not both) recorded in the step log.
- **Template**:
  ```text
  <BACKUP_GATEWAY_CONFIG_CMD> --out <BACKUP_PATH>
  <VERIFY_BACKUP_CMD> --path <BACKUP_PATH>
  <QUIESCE_BOTH_GATEWAY_OWNERS_CMD>
  <ENABLE_SELECTED_GATEWAY_OWNER_CMD> --owner <SYSTEMD_OR_SELF_MANAGED>
  <DISABLE_NON_OWNER_CMD> --owner <NON_OWNER>
  <VERIFY_SINGLE_GATEWAY_PID_CMD> --redact
  ```
- **Evidence to capture (redacted)**: single PID/parent for the gateway process, unit state, one wake-path test result.
- **Rollback point**: re-enable the disabled path; both configs backed up under `<BACKUP_DIR>/<timestamp>/`.
- [ ] **Operator GO**

## 4. Target-by-target deploy order

After the pre-distribution agent-a-local canary has passed, deploy in this order; do not start the next target until the current one's health check passes. Order rationale: shared infrastructure first, then always-on hosts, then agent-facing endpoints. The operator may change the order only by recording the dependency and rollback rationale before the run.

1. **Server** (Meilisearch, agent-b-side jobs, systemd/cron)
2. **Desktop (always-on shared machine)** (capture shipper, launchd)
3. **OpenClaw host** (plugin + shipper wiring)
4. **Hermes host** (gateway-dependent items last, after §3)

Per target, the same sub-sequence applies:

- **Precondition**: previous target green; target backup (§5) complete.
- **Template**:
  ```text
  <DEPLOY_CMD> --revision <IMMUTABLE_RC_SHA> --target <TARGET_ID> --dry-run
  <VERIFY_DECLARED_DIFF_CMD> --target <TARGET_ID> --revision <IMMUTABLE_RC_SHA>
  <DEPLOY_CMD> --revision <IMMUTABLE_RC_SHA> --target <TARGET_ID>
  <REMOTE_VALIDATE_CMD> --target <TARGET_ID> --revision <IMMUTABLE_RC_SHA> --redact
  ```
- **Evidence to capture (redacted)**: declared-diff summary, deployed immutable SHA, validation pass/fail counts, heartbeat `status: ok` for the target's jobs.
- **Rollback point**: the target's pre-deploy immutable revision and scheduler backup. Rollback template:
  ```text
  <ROLLBACK_CMD> --target <TARGET_ID> --revision <PREVIOUS_SHA>
  <VERIFY_SINGLE_OWNER_CMD> --job <JOB_ID> --redact
  ```
- [ ] **Operator GO — Server**  [ ] **Operator GO — Desktop**  [ ] **Operator GO — OpenClaw**  [ ] **Operator GO — Hermes**

## 5. Backup, restore / rollback rehearsal

Rehearsal happens **before** Step 4 on each target — a restore that has never been rehearsed is not a rollback point.

- **Precondition**: backup job for the target is green per watchdog/dashboard.
- **Template**:
  ```text
  <BACKUP_CMD> --target <TARGET_NAME> --out <BACKUP_DIR>/<timestamp>/
  # Restore rehearsal into a THROWAWAY path, never over live data:
  <RESTORE_CMD> --from <BACKUP_DIR>/<timestamp>/ --into <SCRATCH_RESTORE_DIR>
  <ASSERT_PATH_EXISTS_CMD> --path <EXPECTED_SAMPLE>
  <ASSERT_PATH_EXISTS_CMD> --path <SCRATCH_RESTORE_DIR>/<SAMPLE_SUBPATH>
  <COMPARE_RESTORE_CMD> --expected <EXPECTED_SAMPLE> --actual <SCRATCH_RESTORE_DIR>/<SAMPLE_SUBPATH> --fail-on-difference
  ```
- **Evidence to capture (redacted)**: backup size/digest; restore, path-assertion, and comparison exit codes; matching expected/actual digests. A missing/unreadable path or comparison error is failure, never an empty-success result.
- **Rollback point**: the rehearsal itself is the proof of the rollback point; record the verified backup path per target.
- [ ] **Operator GO**

## 6. Real-host health checks and stop conditions

- **FMA-supported host health check (server / desktop, after any mutation)**:
  ```text
  scripts/watchdog --host <HOST_ID>          # exit 0 = no alerts
  scripts/family-hot-read --path <VAULT_PATH>/00_index/family-hot.md --check >/dev/null
  ```
- **OpenClaw validation template**:
  ```text
  <OPENCLAW_VALIDATE_CMD> --revision <IMMUTABLE_RC_SHA> --check-injection --check-heartbeat --redact
  ```
- **Hermes validation template**:
  ```text
  <HERMES_VALIDATE_CMD> --revision <IMMUTABLE_RC_SHA> --check-gateway-owner --check-family-hot --redact
  ```
- **Evidence to capture (redacted)**:
  - Server / desktop: watchdog exit code, `family-hot-read --check` exit code, and per-job statuses.
  - OpenClaw: injected artifact digest/pointer, secret-free startup result, and transported heartbeat identity.
  - Hermes: single gateway owner/PID assertion, family-hot integrity result, and heartbeat identity.
  Placeholder validators must be replaced by reviewed target-native commands before the operator can check GO; an unresolved placeholder blocks that target.
- **Evidence publication boundary**: raw paths, usernames, host addresses, and service output stay host-local. Issue/PR evidence uses logical target labels, counts, exit codes, timestamps, and digests only.
- **Stop conditions — halt the runbook and roll back the current step if any of these occur**:
  - watchdog exit code `2` on any already-distributed host
  - any heartbeat with `status: fail` and `fail_count >= 3`
  - any secret value observed in a log, issue, or terminal scrollback (stop, rotate per §1, report)
  - any unexpected diff outside the step's declared file set
- **Rollback owner**: the operator (all steps). An agent may execute a reviewed non-credential command only after the operator explicitly checks GO for that step; credential entry, issuance, and revocation remain operator hands-on.
- [ ] **Operator GO**

## 7. Post-distribution observation (separate phase — starts only after §1–§6 complete)

These are **observation gates, not distribution steps**. None of them have started; there is no distribution to observe yet.

| Gate | Tracked in | Requirement | State |
|---|---|---|---|
| Two-week observation | #45, #46 | both OPEN; any earlier pilot data must be re-attached as commit-addressed evidence before it counts for this RC | **not started for this RC** |
| All-agent injection proof | #131 §C | every agent demonstrably receives its injection on real hosts | **not started** |
| Fleet 7 green days | #120 closure gate | watchdog exit 0 on all hosts for 7 consecutive days | **not started** |
| Real-change backup push | #82 | backup stage C push repaired and verified against a real change | **OPEN, post-observation** |

Observation data feeds the #120 7-day closure gate only; it never back-dates the pre-distribution RC.

## 8. Stale / close candidates and open gates (triage only — close nothing here)

Per #136 stale-triage output: no issue is closed from this document. Close authority stays with the operator; the outputs are comment drafts plus this checklist entry.

- **#113** (grok-build study) — close candidate: artifacts and audit SHAs exist in the internal review archive (not shipped in this repository; merged via #113-linked commits). Action: draft close comment citing artifact/audit SHA evidence; the operator decides.
- **#75 / PR #76** (vault-lint review-pending rule) — supersede/close candidate: conflicts with current-main D11 storage classes and would regress. Action: draft supersede comment with D11 regression diff evidence; the operator decides.
- **#47** — remains OPEN as an operator credential/install gate (§1).
- **#82** — remains OPEN as a post-observation gate (§7).
