# Agent Guide — installing Family Memory Architecture

**You are (probably) an AI agent.** A human handed you this repository and asked you to set it up. This page is written for you: follow it top to bottom, then report back to your human in plain words. Humans reading along are welcome — the [front page](../README.md) has the friendly version, and the [getting-started guide](getting-started.md) has the full procedure (in Japanese; translate for your human as needed).

The single most important rule of this guide: **the core is yours to set up; every optional layer is your human's decision.** Steps 1–3 are free, local, and reversible — proceed. From Step 4 on, each layer must be presented to the human with its role and cost, and installed only after they choose it.

---

## What you are installing

FMA gives multiple AI agents one shared memory surface: a single short Markdown page (`family-hot.md`) that everyone reads at session start, fed through a drop box (`hot-inbox/`) with exactly one writer program. It is **additive**: it creates a vault folder and appends one clearly-marked line to your instruction file. It never touches your personality, system prompt, or local memory, and nothing here edits global configuration without your human's explicit approval.

Your write boundary for this installation:

- ✅ the clone directory, and the vault directory the human designates
- ✅ appending one marked block to the workspace's instruction file — after showing it to the human
- ⛔ global config, cron/launchd, network services, or installing third-party software — only in Steps 4–5, only with the human's explicit OK
- ⛔ secrets never go into the vault, the repo, or any file — the posting script scans for secret-like strings and will reject them, but do not rely on it as your only guard

## Step 0 — check the ground

Run these read-only checks and note the results for your final report:

```sh
git --version
command -v python3     # required — core scripts are stdlib-only Python 3
                       # (only the two guard lints, content-lint and injection-lint, need PyYAML)
```

If `python3` is missing, stop and point the human at their platform's Python 3 install. Nothing else is required for the core.

## Step 1 — clone and prove the loop

```sh
git clone https://github.com/caty-ai/family-memory-architecture
cd family-memory-architecture
```

Run the four demo commands from the [front page](../README.md#get-started) (post → generate → lint → read against a `demo-vault`). All four must exit 0. This proves the whole loop on this machine in under a minute. Delete `demo-vault` afterwards.

> Run from a normal home-directory location when possible. The default permission self-check now tolerates temp directories whose inherited group differs (for example `/tmp` on macOS) because the generator forces the artifacts back to `0600`; only a pinned `FMA_EXPECT_OWNER` deployment still refuses owner/group mismatches.

## Step 2 — create the real vault

Ask the human where the shared folder should live (default: `~/family-vault`), then:

```sh
mkdir -p ~/family-vault/00_index/hot-inbox
```

That is the entire data layer: a folder of Markdown and JSON files. The vault is the canonical store; everything else in this guide is a convenience layer on top of it.

## Step 3 — wire session-start reading (show the human first)

Participation in FMA means one thing: **read the shared page at session start, verified.** Append one marked block to the instruction file of the runtime you are running in right now — after showing it to the human:

| You are | Instruction file |
| --- | --- |
| Claude Code | `CLAUDE.md` (workspace or user level) |
| Codex CLI / Kimi Code CLI / OpenClaw | `AGENTS.md` |
| Hermes Agent | profile system-instructions file |

The block:

```markdown
<!-- fma session-start read -->
At session start, run `<clone>/scripts/family-hot-read --path ~/family-vault/00_index/family-hot.md --check`
and treat its output as the family's current shared state. If the check fails, say so instead of guessing.
```

To post events, use `scripts/hot-inbox-post`; to transcribe the inbox into the shared page, run `scripts/family-hot-generate --vault-root ~/family-vault` (on one machine, run it manually or per the schedule in the getting-started guide). **The core is now complete** — one machine, one shared page, zero dependencies, no accounts.

## Step 4 — optional layers: present, ask, then install

Everything below is optional. **For each layer the human shows interest in: explain the role, what changes, and the cost — then wait for their choice.** Do not install a layer they did not pick. This table is your script for that conversation; "how we use it" describes the authors' own production family, as one working reference.

| Layer | Role | What changes when installed | Needs / cost | How we use it | Install if / skip if |
| --- | --- | --- | --- | --- | --- |
| [Syncthing](https://syncthing.net/) | Mirrors the vault folder between machines | A second machine reads the same shared page; multi-agent across devices becomes real | Free OSS, runs as a local service | The vault syncs continuously between a laptop, an always-on desktop, and a server | **Install** from the second machine on. **Skip** on a single machine |
| [Tailscale](https://tailscale.com/) | Private network between your machines — no ports opened to the internet | Remote machines talk to each other (and to Meilisearch) safely | Free tier is enough for a family | All machines and the search endpoint sit behind it; nothing is publicly bound | **Install** before any cross-machine service if machines are in different places. **Skip** on a single machine |
| [Meilisearch](https://www.meilisearch.com/) | Local full-text search over the vault and shared-page archive | Ingest is restricted by an allow-list manifest ([meili-ingest-usage.md](meili-ingest-usage.md)); wiring the results into `recall` needs an external search wrapper set via `RECALL_MEM_SEARCH` (not bundled — `recall`'s grep layer works without it) | Free OSS; one binary on `localhost:7700` or a private server | A family endpoint runs on the server bound to a private IP; the laptop keeps a local dev instance | **Install** when history has grown enough that grep feels slow. **Skip** at the start — `recall`'s ripgrep layer covers a young vault |
| [Supermemory](https://supermemory.ai/) | Cloud long-term memory joined into `recall` | Fuzzy, cross-session context appears alongside local results | Paid plan, or the [self-hosted OSS version](https://github.com/supermemoryai/supermemory); needs an API key handled per [policies/supermemory-allocation.md](../policies/supermemory-allocation.md) | A shared plan with per-agent quotas and fail-closed rules | **Install** only if the human wants cloud memory and accepts key management. **Skip** freely — `recall --local-only` is a first-class mode |
| [Obsidian](https://obsidian.md/) | The human's window into the vault | The human browses and edits the shared folder comfortably; agents gain nothing | Free for personal use | Humans read the vault in Obsidian; agents never open it | **Install** for the human's comfort. Never required |

Questions to ask before touching any of these:

1. **How many machines** will run agents? (1 → skip Syncthing and Tailscale entirely for now)
2. **Cloud memory** — paid, self-hosted, or none? (none is a fully supported answer)
3. **Search layer** — now, or after the vault has some history?
4. If more than one machine: **which one is always on?** That machine hosts the transcriber schedule (and later, the [failure watch](jobs-framework.md)).

For the chosen layers, follow the corresponding steps in the [getting-started guide](getting-started.md); where each tool should live in a bigger stack is mapped in the Family OS [recommended stack](https://github.com/caty-ai/family-os/blob/main/docs/recommended-stack.md).

## Step 5 — multi-machine operation (needs the human's OK)

Only relevant when machines ≥ 2 and only with explicit approval, because it wires schedules (cron/launchd) on the always-on machine: periodic `family-hot-generate`, and optionally the watchdog from [jobs-framework.md](jobs-framework.md) with a `manifests/jobs.yaml` adapted to the human's fleet. If the human defers this, that is a valid state — say clearly in your report what is wired and what isn't.

## Step 6 — report back to your human

Use plain words, no jargon. A good report covers:

```text
Set up complete. Here's what that means:

- Your agents now share one page of current state at <vault path>. Anything posted
  to the drop box appears there after transcription, with its origin recorded.
- I verified the whole loop end to end: post → transcribe → lint → verified read.
- Optional layers: you chose <X, Y>; I skipped <Z> as you decided. Each can be
  added later without redoing anything.
- Nothing was replaced: I created the vault folder and added one marked block
  to <instruction file>. Removing that block and the folder undoes everything.
- Your personality settings and my local memory were not touched — this only
  shares the short status page.
```

---

## Troubleshooting

| Symptom | Meaning | Do |
| --- | --- | --- |
| `generated artifact permission self-check failed: … owner is …` | The artifact uid is wrong, or a pinned `FMA_EXPECT_OWNER` deployment saw an owner/group mismatch | Re-run as the expected user, or fix the pinned owner/group setting |
| `family-hot lint` fails after someone edited `family-hot.md` by hand | The single-writer contract caught a hand edit — working as designed | Re-run `family-hot-generate`; never hand-edit the generated page |
| `hot-inbox-post` exits refusing your event | The secret scan matched a credential-like string | Remove the secret-like content; post a pointer instead of the value |
| Clone fails with auth error | The repo is private and this account isn't invited | Tell the human; they need access before you can proceed |

Contracts and deeper semantics: [family-hot-usage.md](family-hot-usage.md) (shared page), [hot-inbox-usage.md](hot-inbox-usage.md) (drop box), [recall-usage.md](recall-usage.md) (search), [DESIGN.md](DESIGN.md) (design and failure modes).
