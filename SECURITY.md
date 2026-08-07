# Security Policy

Family Memory Architecture ships local scripts that use only Python 3's standard library. It runs no daemon of its own and opens no network ports; the scripts read and write local files and, when the optional layers are configured, talk to a Meilisearch endpoint and a cloud memory API using keys you supply. Its security surface is what those scripts touch and what this repository might accidentally carry. Security reports are welcome for:

- Leaked credentials, tokens, or personal information anywhere in the repository or its git history
- A way to make the transcriber, ingest, or posting scripts write outside their declared targets (path traversal, symlink tricks, manifest injection)
- A pattern that slips past the bundled secret scan and would land a real credential in the shared page or the search index
- A described practice in the docs that would lead a reader to expose credentials, weaken the single-writer boundary, or grant an agent authority the document does not intend

Vulnerabilities inside the optional layers themselves (Syncthing, Meilisearch, Obsidian, Supermemory, Tailscale) belong to their own projects and security policies. If you are unsure, report it here and we will route it.

## Reporting a Vulnerability

Please report security issues privately via **GitHub's private vulnerability reporting** on this repository (Security → Report a vulnerability). If that is unavailable, open a GitHub issue *without sensitive details* and ask a maintainer to establish a private channel.

We aim to acknowledge reports within 7 days. Please do not disclose the issue publicly until it has been addressed.

## Supported Versions

Only the `main` branch is maintained.
