# Contributing

Thanks for your interest in improving Family Memory Architecture (FMA).

## What belongs here

FMA is a reference architecture with working code: the shared page (family-hot), the drop box (hot-inbox), cross-layer search (`recall`), search-index ingest, and the failure watch (jobs framework). This repository owns those scripts, their tests, the manifests that ship as worked examples, and the documents that explain them.

- **Belongs here:** a bug in a script under `scripts/`, a contract described one way in docs and enforced another way in code, a broken link, a worked-example manifest that does not validate, a newcomer taking a wrong turn because of how something is worded.
- **Belongs elsewhere:** bugs in the optional layers themselves (Syncthing, Meilisearch, Obsidian, Supermemory, Tailscale) or in sibling projects such as Caty Agent Harness and Sitter. Each owns its own issues.

If you are unsure which side a report falls on, open it here and we will move it.

## Ground rules

- **Issue first.** Open a GitHub issue before starting non-trivial work. State *why* the change is needed, *what "done" looks like* (checkable conditions), and *which files you expect to touch*. One-line fixes such as typos are exempt.
- **Respect the single-writer contract.** Only the transcriber writes the shared page. Changes that add a second write path to any generated artifact need a design discussion in the issue first.
- **Fail closed.** Guards, lints, and checks in this repo treat "cannot verify" as failure. Keep that direction: a change that turns an error into a silent pass needs an explicit argument for why that is safe.
- **Do not invent numbers or results.** Every measured value in docs and manifests is real. If you have not run it, do not write it as fact.
- **Honest completion.** A change is done when its stated done-conditions pass with evidence, not when it looks done. Pull requests should list which conditions passed and how they were checked.

## Checking your change

The test suite needs only Python 3 — plus PyYAML for the content-lint tests (`content-lint` and `injection-lint` are the only two scripts with a dependency beyond the standard library):

```bash
python3 scripts/tests/run_tests.py          # aggregate suite
python3 scripts/tests/test_write_guard.py    # run individually as needed
python3 scripts/tests/test_injection_lint.py
```

Before opening a pull request, confirm:

- The suite passes (`failed=0 errors=0`), plus any individually-run test files you touched.
- Every relative link and in-page anchor in changed docs resolves.
- No personal paths, internal host names, IP addresses, credentials, or private repository names appear anywhere in the diff. The pre-commit hook (`.githooks/pre-commit`) runs the bundled secret scan — enable it once per clone with `git config core.hooksPath .githooks`, and leave it enabled.

## Pull requests

- Keep one pull request per issue, and keep branches short-lived.
- List the files you changed and confirm they match what the issue predicted; explain any difference.
- English (`README.md`) is canonical. Please keep the Japanese, Chinese, and Thai translations aligned when you change user-facing text, or note in the pull request that translations need a follow-up.

## Style

- Write for someone who has not met this project before. Short sentences, concrete nouns, no jargon that the page has not already introduced.
- Core scripts stay standard-library-only; `content-lint` and `injection-lint` (PyYAML) are the two sanctioned exceptions — do not add more. That constraint is a feature, not an accident.
- Prefer showing the boundary over promising the outcome. What a layer refuses to do is as informative as what it does.
