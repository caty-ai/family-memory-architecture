Minimal green fixtures for the shipped worked-example validators.

These smoke checks use a temporary `HOME` because `injection-lint` and
`watchdog` write state files under `~/.claude/`.

Run these commands from the repository root:

```sh
HOME="$(mktemp -d)" python3 scripts/injection-budget-check --manifest manifests/fixtures/fixed-injection.yaml
HOME="$(mktemp -d)" python3 scripts/injection-lint --manifest-dir manifests/fixtures/injection --all
HOME="$(mktemp -d)" python3 scripts/watchdog --jobs-manifest manifests/fixtures/jobs.yaml
```
