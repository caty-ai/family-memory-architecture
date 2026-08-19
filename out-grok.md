# Review — family-memory-architecture PR #40 (issue #29)

Seat: Grok 4.6 (independent, read-only)
Head: `4665a55` (`feat/29-contributing-status`)
Base: `80c359f` (`main`)
Diff: CONTRIBUTING.md + README.md / README.ja.md / README.zh.md / README.th.md (+48/−25)

## VERDICT: NO-GO

One MAJOR. No CRITICAL.

---

## Findings

### F1 — MAJOR — Prerequisites omit Node, which CI requires for `skipped=0`

- **File:** `CONTRIBUTING.md:22-27` (new Prerequisites section)
- **Contract:** Done when #1 (name required tools/versions) and named worst failure mode “Prerequisites honesty: every named tool actually needed and **sufficient**”.
- **Evidence:**
  - New Prerequisites list only Python 3.9+, GNU make, git, and optional Docker.
  - `.github/workflows/full-suite.yml:42-45` installs Node.js `24.18.1` before running the suite.
  - `.github/workflows/full-suite.yml:61` exact-count gate is `grep -Fx 'Final summary: passed=469 failed=0 errors=0 skipped=0 total=469'` — any skip fails CI.
  - `scripts/tests/test_openclaw_capture.py:15-16` is `@unittest.skipUnless(shutil.which("node"), "node is required")`, and `run_tests.py:1337,1359` loads that module into the aggregate suite.
  - `run_tests.py:1374` exits 0 on skips (`wasSuccessful()` ignores skips). A contributor who follows Prerequisites and has no `node` will see `make test` succeed with `skipped=1`, then get a red exact-count gate on the PR.
  - Docker *is* correctly marked optional because the #31 skip is environment-dependent and CI’s `ubuntu-latest` still records `skipped=0`. Node is the opposite: missing Node skips on every host, including the host CI is trying to keep at `skipped=0`.
- **Not a stdlib lie:** Python scripts are stdlib-only (`lib_yamlsubset`, no `requirements.txt`, no third-party imports). `extensions/openclaw-capture/package.json` has no npm dependencies. The gap is the **Node runtime**, not a pip/npm package.
- **Suggested fix:** Add a required Node bullet, e.g. “**Node.js.** Needed for the OpenClaw capture test (`scripts/tests/test_openclaw_capture.py`). CI uses Node 24.18.1; no npm packages to install.” Keep the stdlib/no-pip claim. Do not write `469` or any measured count.

---

### F2 — MINOR — “Verified environments” lists macOS, which is not in the CI matrix

- **File:** `README.md:245` (and ja/zh/th counterparts)
- **Contract:** Named worst failure mode “environments row must match the CI matrix and the #31 self-skip behavior”.
- **Evidence:**
  - `full-suite.yml:24-33` matrix is `runs-on: ubuntu-latest` × Python `3.9.25` / `3.14.6` only. No macOS runner.
  - The row says `macOS (development hosts) and ubuntu-latest (CI)`. The qualifier avoids claiming CI-on-macOS, but the row title is still “Verified environments” and the machine-backed OS is only `ubuntu-latest`.
  - The #31 clause itself is accurate: `test_hot_inbox_reader.py:509-543` `skipTest`s only when `/proc/<pid>/stat` shows state `Z` (zombie under non-reaping PID 1). That matches “containers without a reaping init, one test self-skips”.
- **Suggested fix:** Either drop macOS from this row, or say it is a development host and not a CI matrix OS. Keep the #31 sentence.

---

### F3 — NIT — Checking-your-change still special-cases two old individual files

- **File:** `CONTRIBUTING.md:37`
- **Evidence:** “the aggregate suite includes the write-guard and injection-lint tests” is true (`run_tests.py` loads both) but leftover from the deleted individual-run commands. A newcomer can read it as those two being the suite.
- **Suggested fix:** Drop the two names. “This wraps `python3 scripts/tests/run_tests.py`.” is enough.

---

## What passed (checked against the named worst failure modes)

**Overclaiming (CI row):** Matches `full-suite.yml`. Triggers are unfiltered `push` + `pull_request` (plus unused `workflow_dispatch`). Matrix is Python 3.9 and 3.14. Exact-count gate exists. Local command is `make test` → `python3 scripts/tests/run_tests.py` (`Makefile:6-7`). Live badge URL matches the workflow. This PR’s own full-suite runs succeeded (push `32243767562`, pull_request `32243773245`).

**Hand-written measured numbers/dates in the diff:** None. `git diff main` on the five files has no `passed=`, `failed=`, `469`, or `2026-`. Stale `failed=0 errors=0` and individual-run lines were removed from CONTRIBUTING (carried PR #37 finding). Exact-count gate and badge remain the only status sources.

**Prerequisites honesty (except F1):**
- `make test` / `make lint` exist; `make lint` is `@true` (no-op), as stated.
- `git config core.hooksPath .githooks` is correct; `.githooks/pre-commit` exists, is executable, and runs `scripts/secret-scan --staged`.
- Docker is optional and only for the #31 SIGTERM-sweep repro; link target `scripts/tests/test_hot_inbox_reader.py` exists; issue #31 exists.
- Python floor 3.9 matches the workflow comment and matrix. GNU make: `Makefile` has no GNU-only features, but macOS Xcode `make` is GNU Make 3.81, so the name is not a trap.

**Anchor/TOC:** `<a id="status"></a>` kept in all four READMEs. TOC entries retitled and still point at `#status`. `docs/pre-distribution-rc.md` exists (DRAFT, as stated). No new dead relative links.

**Language symmetry:** en/ja/zh/th share the same skeleton (localized `## Project status` heading, live badge, four rows in the same order, existing evidence table, existing Note). Meanings match. Localized headings (`プロジェクトの状況` / `项目状态` / `สถานะโครงการ`) are natural; `#status` anchor is the stable TOC target.

**Scope:** Only the five predicted files. README hunks are TOC link text + status section only. Lines 1–14 (header badges) are byte-identical to `main` on all four READMEs. `<!-- family:generated:family-footer -->` blocks are identical to `main`. No other-language CONTRIBUTING exists.

**Issue contract coverage:**
1. Prerequisites section added; tools/versions named (incomplete: F1).
2. README test-run guidance is only `make test` (old standalone paragraph removed).
3. Four-row status + live badge present in four languages, aligned from the old “What works today” section; table + Note kept.
4. Evidence table/Note kept; stale individual-run text removed.

---

## Out of scope (not a finding against this diff)

`README.md:96` (untouched “What you need” table) still says “3.9 measured with one test failure” and “3.13 and below unverified”. That now contradicts the new CI row and `full-suite.yml`. Editing it would be scope creep on #29; it wants a follow-up, not a hitchhike.

---

## What I actually verified

- `git diff main` (full text) and `git diff --name-only` / `--stat`
- `gh issue view 29`, `gh pr view 40`, `gh issue view 31`
- `.github/workflows/full-suite.yml` (triggers, matrix, Node setup, exact-count line)
- `Makefile`, `CONTRIBUTING.md`, all four README status sections + TOC
- Header lines 1–14 and family-footer blocks vs `main` (`diff -q`)
- `scripts/tests/test_hot_inbox_reader.py` skip path; `test_openclaw_capture.py` / `.mjs`; `run_tests.py` loader and summary; `test_secret_scan.py` git `skipUnless`; `test_suite_census.py`
- `.githooks/pre-commit`, `docs/pre-distribution-rc.md`, `LICENSE` (MIT)
- Grep of the five-file diff for `passed=`, `failed=`, `469`, `2026-`, `run individually`
- `ls CONTRIBUTING*` (English only)
- `gh run list` for `full-suite.yml` (this branch green on push and pull_request)
- Did **not** re-run `make test` (docs-only diff; no source/test files changed)

---

requested: Grok 4.6
actual: Grok 4.6
effort: high
verdict: NO-GO
