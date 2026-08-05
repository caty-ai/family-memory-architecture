# Secret Scan Usage

Enable the pre-commit hook once per clone:

```sh
git config core.hooksPath .githooks
```

The hook runs `scripts/secret-scan --staged`, which scans only added staged lines. The script can also scan files or directories directly:

```sh
scripts/secret-scan manifests docs policies scripts README.md
```

For repository-wide verification with Gitleaks, run the following commands from the repository root, use the checked-in `.gitleaks.toml`, and force full redaction in terminal output. Subdirectory-only invocation is intentionally outside the approved-path contract and may fail closed on a marked fixture. The config requires Gitleaks `>=8.30.1`; the RC canonical verification version for this workflow is Gitleaks `8.30.1`.

```sh
git fetch --prune origin '+refs/heads/*:refs/remotes/origin/*' &&
  test "$(git rev-parse --is-shallow-repository)" = false &&
  gitleaks git --no-banner --redact=100 --report-format json --report-path /tmp/gitleaks-git.json . &&
  gitleaks dir --no-banner --redact=100 .
```

The history result is only as complete as the fetched refs. CI must use a full-history checkout (`fetch-depth: 0`) and fetch every branch ref included in the publication review before running the canonical command.

## Rules

- `meili-key`: Meilisearch key-like identifiers such as `MEILI_MASTER_KEY` assigned to a real-looking value.
- `supermemory-token`: Supermemory credential assignments or bare `sm_...` tokens.
- `tailscale-authkey`: Tailscale auth keys beginning with `tskey-`.
- `op-uri`: assigned 1Password `op://...` references that look like real vault item paths.
- `bearer-token`: `Authorization: Bearer ...` headers with real-looking token values.
- `high-entropy`: long base64-like or hex-like values that look random, excluding commit/hash contexts such as sha256 manifest fields.

## Allow Pragma

Put `secret-scan: allow` on the same line as the literal being exempted. Use it only when the value is known to be a harmless fixture, fake example, or intentionally documented non-secret. Prefer fake placeholders over allow pragmas when possible.

Gitleaks uses the same marker, but only inside `scripts/tests/test_secret_scan.py` and `scripts/tests/test_vault_lint.py`, and only when the marker appears on the same line as the synthetic fixture. That allowlist is intentionally narrow: it does not suppress entire files, commits, or general unmarked lines. New unmarked fixtures are not allowed. Generated `scripts/tests/__pycache__/...` bytecode is excluded structurally so post-test local verification does not fail on compiler-generated `.pyc` content outside the source files; source-file marker handling and generated-bytecode exclusion are intentionally separate controls.

Review every new marker addition in those two files as a security-sensitive change. A marker must never be used to exempt a live credential; prefer a clearly synthetic fixture whenever the test permits it.

## Historical Findings

`.gitleaksignore` is reserved for exact Gitleaks `Fingerprint` entries that refer to immutable history which cannot be rewritten safely in repository refs. The canonical `gitleaks git` command uses Gitleaks' default all-ref history traversal, so an exact entry may cover a fetched ref that is not an ancestor of the current `HEAD`; the entry is inert in a clone where that ref is absent. Gitleaks treats this mechanism as experimental, so keep it narrow and re-review every stored fingerprint on every Gitleaks version upgrade. Do not add path globs, generic regex suppressions, baseline JSON snapshots, recent-commit restrictions, helper-shape exemptions, or current-source findings there.

Before adding a new ignore entry:

- run a fully redacted `gitleaks git` scan and save the JSON report to a local file;
- confirm the finding is only a known historical occurrence and not present in current source;
- confirm the file, rule, commit, line, and fixture are already understood and reviewed across the repository refs scanned by the canonical command;
- confirm the current Gitleaks version is still the reviewed version, or re-review all stored fingerprints before trusting an upgraded scanner;
- add only the exact fingerprint value for that reviewed historical finding.

## Bypass

`git commit --no-verify` bypasses all pre-commit hooks, including this scanner. That disables the safety net: secrets could leak into history. Use bypasses rarely, deliberately, and with review instead of making them routine.

Scanner internal errors exit with code 1 and also block commits by design. This fail-closed behavior is intentional because a broken scanner cannot prove the staged content is safe.
