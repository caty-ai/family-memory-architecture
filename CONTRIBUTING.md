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

## Prerequisites

- **Python 3.9 or later.** The CI floor is Python 3.9. The suite uses only the standard library, so there are no packages to install.
- **Node.js 24.18.1.** CI pins this version before running the suite. There are no npm packages to install; the runtime alone suffices. Without `node`, the openclaw-capture tests self-skip locally, so `make test` still exits 0, while CI's exact-count gate requires zero skips. A no-node local green can therefore still fail CI.
- **GNU make.** This provides the family-standard entry points used below.
- **git.** Enable the bundled secret scan once per clone with `git config core.hooksPath .githooks`.
- **Optional: Docker.** It is needed only to reproduce the environment-dependent SIGTERM-sweep behavior covered by [`scripts/tests/test_hot_inbox_reader.py`](scripts/tests/test_hot_inbox_reader.py); see [issue #31](https://github.com/caty-ai/family-memory-architecture/issues/31).

## Checking your change

Run the whole test suite through the family-standard entry point:

```bash
make test
```

This wraps `python3 scripts/tests/run_tests.py`. `make lint` also exists for parity with family CI and is currently a no-op.

Before opening a pull request, confirm:

- The whole suite passes.
- Every relative link and in-page anchor in changed docs resolves.
- No personal paths, internal host names, IP addresses, credentials, or private repository names appear anywhere in the diff. The pre-commit hook (`.githooks/pre-commit`) runs the bundled secret scan — enable it once per clone with `git config core.hooksPath .githooks`, and leave it enabled.

## Pull requests

- Keep one pull request per issue, and keep branches short-lived.
- List the files you changed and confirm they match what the issue predicted; explain any difference.
- English (`README.md`) is canonical. Please keep the Japanese, Chinese, and Thai translations aligned when you change user-facing text, or note in the pull request that translations need a follow-up.

## Style

- Write for someone who has not met this project before. Short sentences, concrete nouns, no jargon that the page has not already introduced.
- Keep every script standard-library-only; do not add external package dependencies. That constraint is a feature, not an accident.
- Prefer showing the boundary over promising the outcome. What a layer refuses to do is as informative as what it does.
