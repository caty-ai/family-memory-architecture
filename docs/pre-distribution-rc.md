# Pre-Distribution RC — Definition and Truth Table

- **Date**: 2026-07-24 +07
- **Author**: docs lane (Issue #136), integration truth owned by Agent A
- **Parent**: #131 ([EPIC] pre-distribution RC — clean-room + agent-a synthetic canary)
- **Status**: DRAFT — not an RC declaration. Final truth sync (README / DESIGN / jobs-framework / handoff) is blocked until mechanisms and #135 evidence stabilize.

## 1. What "pre-distribution RC" means

Pre-distribution RC is a **readiness claim about reproducibility**, not a release. It means exactly:

- Every RC mechanism passes in a **clean room** (no real host, no real credential, no real data) **and** in an **agent-a-local synthetic canary** (synthetic fixtures on the agent-a host only).
- Nothing else. It does **not** mean public release, family distribution, real credential operations, real restore, or fleet observation — those are explicitly out of scope (#131 Non-goals) and are gated separately in [docs/distribution-gate.md](distribution-gate.md).

An RC claim with no commit-addressed evidence is not a claim; it is a placeholder. Every row in the truth table below must map to a commit/PR/test artifact or be marked outstanding.

## 2. Truth table (verified 2026-07-24 +07 via `gh issue view`; re-verify before any RC declaration)

| Item | Scope | State | Evidence | Verdict |
|---|---|---|---|---|
| #123 D9: corrupt control state → paused-never-scheduled | mechanism | OPEN, owner WIP | branch `issue-123-corrupt-paused`, commit `9c331f5` plus declared uncommitted work; pre-spawn sentinel proof is still absent | **OUTSTANDING / owner-held** |
| #124 D17: job owner registry + duplicate-writer lint | mechanism | OPEN | none in repo | **OUTSTANDING** |
| #125 D1: pre-destruction flush-extract (extract-only) | mechanism | OPEN | none in repo | **OUTSTANDING** |
| #128 family-hot-generate → `scripts/lib_atomic` migration | mechanism | OPEN | `lib_atomic` itself merged (PR #126, #121); migration not done | **OUTSTANDING** |
| #54 mechanism side: stdlib clean-room, failure classes, canonical test discovery | mechanism | OPEN | content-lint v1 merged (PR #107); the manifest/config parser and unconditional lint test discovery landed in `2ee4de1` (hardened in `1a23069`); clean-room and remaining failure-class evidence are still outstanding | **PARTIAL** |
| #132 gitleaks fixture allowlist + negative machine gate | mechanism | OPEN | draft PR #137 open, unmerged | **OUTSTANDING** |
| #133 stdlib manifest parser + lint failure classification | mechanism | IMPLEMENTED IN REPO | `scripts/lib_yamlsubset.py`, both lint integrations, and their unconditional tests landed in `2ee4de1` (parser hardened in `1a23069`) | **COMPLETE — implementation present; RC evidence tracked separately** |
| #134 Python 3.9 CLI compatibility + canonical all-tests runner | mechanism | OPEN | none in repo | **OUTSTANDING** |
| #135 hermetic clean-room E2E + agent-a local synthetic canary | RC proof | OPEN | none in repo | **OUTSTANDING** |
| #120 EPIC hardening wave 1 — implementation-ready checkpoint | checkpoint | OPEN | partially addressed: D10 `lib_atomic` (PR #126), D11 storage classes (PR #127), W3 liveness envelope (PR #119, #118) | **PARTIAL — checkpoint not reached** |

If a commit or merged PR lands that addresses a row, update the row's Evidence column with the SHA/PR and flip the verdict only with that evidence attached. Absence of evidence in this table is itself a finding — do not "fix" it by editing the wording.

## 3. Mechanism defects vs. target configuration violations

Two different failure classes must never be conflated (per #131 failure classification contract):

- **`mechanism_defect`** — the code/contract itself is broken: parser/schema crash, undeclared dependency, scanner/tool unavailable, internal state write failure, inconsistent registry. Blocks the RC.
- **`target_config_violation`** — the mechanism is sound but a *destination* is not ready: target file missing/unreachable, budget/rot/role violation, undistributed launcher, host-specific credential/permission. Blocks distribution **to that target only**.
- **`clean`** — no findings.

A target configuration violation must not be recorded as a broken RC mechanism, and an undistributed target must not be recorded as an implementation gap. Record each finding under exactly one class with its evidence.

## 4. #120 checkpoint vs. 7-day closure — two separate gates

- **Implementation-ready checkpoint (pre-distribution)**: #120's hardening items are code-complete, reviewed, and evidenced in clean room + synthetic canary. This is part of RC readiness. It requires **zero** real-host days.
- **7-day post-distribution closure**: fleet 7 green days **after** real distribution (#131 §C). This is a closure gate for #120, **not** an RC input. The RC must not wait for it, and the closure must not be claimed from canary data.

These gates are tracked separately; merging them either hides undistributed state behind "implementation incomplete" or mislabels implemented mechanisms as broken because fleet observation has not run.

## 5. Commit-addressed evidence fields

Every RC evidence entry must carry all of these fields (no empty cells):

| Field | Content |
|---|---|
| `claim` | One sentence: what is asserted to work |
| `commit_sha` / `pr` | The change that implements or fixes it |
| `test_ref` | Test file / command / CI output reference |
| `environment` | `clean-room` or `agent-a-synthetic-canary` (never "real host") |
| `date` | When the evidence was produced |
| `reviewer` | Independent reviewer identity (not the implementer) |
| `failure_class` | `clean` / `mechanism_defect` / `target_config_violation` |

## 6. Validation checklist (placeholder — NOT executed)

The following is the executable validation checklist skeleton for #135. **No item below has passed.** There is no clean-room E2E or canary evidence in this repository as of 2026-07-24. Items are checked only with evidence attached per §5.

- [ ] paused-job sentinel body is not spawned (clean-room evidence)
- [ ] duplicate/foreign writer fixture fails; current registry passes with declared transports
- [ ] `hot-inbox-post → family-hot-generate → family-hot-read --check` passes from an empty vault
- [ ] secret event fails closed without echoing the value
- [ ] `recall --local-only` returns synthetic results and reads no network credential
- [ ] heartbeat → watchdog → consumer payload; corrupt control → quarantine/paused
- [ ] #125 writes no shared area other than via `hot-inbox-post`; retry/crash produces no duplicate/clobber
- [ ] write/crash injection observes only old-complete or new-complete file versions
- [ ] Python 3.9 + current Python, macOS (+ Linux equivalent where possible), Node plugin tests: all green, unexpected skips = 0
- [ ] gitleaks (working tree + git history) green with narrow fixture allowlist; unmarked/unapproved synthetic secrets are detected
- [ ] agent-a local synthetic canary succeeds with real host/key/data/LaunchAgent untouched
- [ ] independent review (two independent models + one non-implementing model): BLOCKER/NO-GO = 0
- [ ] all PRs mergeable, awaiting operator merge; no self-approve / self-merge

## 7. Explicit prohibitions

Within the RC lane, the following are prohibited without exception:

- **No real credentials** — no issuing, rotating, revoking, reading, or storing of production credentials.
- **No IP/token logging** — no real IP addresses, hostnames, tokens, or keys in issues, PRs, logs, docs, or test fixtures (approved synthetic fixtures excepted, per #132's allowlist).
- **No deployment** — no changes to real LaunchAgents, Keychain entries, crontabs, systemd units, or gateway processes.
- **No public release** and **no family distribution** — RC readiness is an internal reproducibility claim only.
- **No self-approval / self-merge** — all PRs require independent review and operator merge.

## 8. Relation to other documents

- Operator-attended distribution steps: [docs/distribution-gate.md](distribution-gate.md)
- Heartbeat/liveness consumer contract handed to family-os: [docs/family-os-liveness-contract.md](family-os-liveness-contract.md)
- Base heartbeat schema (producer side): [docs/jobs-framework.md](jobs-framework.md) — blocked from edits while #123 WIP is live
