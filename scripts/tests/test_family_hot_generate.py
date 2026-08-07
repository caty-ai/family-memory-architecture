#!/usr/bin/env python3
"""Tests for the family-hot generator/linter pair."""

import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FAMILY_HOT_GENERATE_SCRIPT = REPO_ROOT / "scripts" / "family-hot-generate"
FAMILY_HOT_LINT_SCRIPT = REPO_ROOT / "scripts" / "family-hot-lint"
FAMILY_HOT_READ_SCRIPT = REPO_ROOT / "scripts" / "family-hot-read"


class FamilyHotGenerateTests(unittest.TestCase):
    def run_script(self, script, *args, env=None):
        return subprocess.run(
            [sys.executable, str(script), *map(str, args)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=env,
        )

    def load_script_module(self, name, script):
        loader = importlib.machinery.SourceFileLoader(name, str(script))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def mutated_stat_result(self, stat_result, *, mode=None, uid=None, gid=None):
        values = list(stat_result)
        if mode is not None:
            values[0] = (stat_result.st_mode & ~0o777) | mode
        if uid is not None:
            values[4] = uid
        if gid is not None:
            values[5] = gid
        return os.stat_result(values)

    def inbox(self, vault):
        path = Path(vault) / "00_index" / "hot-inbox"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_event(
        self,
        vault,
        *,
        kind="project",
        class_num=6,
        title="Project event",
        summary="One short summary.",
        created_at="2026-07-04T00:00:00Z",
        event_slug="project-event",
        canonical_path="family-vault/20_projects/project-event.md",
        canonical_url=None,
        owner="agent-a",
        priority="P2",
        expires_at=None,
        promotion_pending=False,
        next_review_at=None,
        target_event_id=None,
        uuid8="00000001",
    ):
        event_id = f"{created_at.replace('-', '').replace(':', '')[:15]}Z__agent-a__{kind}__{event_slug}__{uuid8}"
        if kind == "expire":
            event = {
                "schema_version": "family-hot-event/v0",
                "event_id": event_id,
                "created_at": created_at,
                "created_by": "agent-a",
                "kind": "expire",
                "target_event_id": target_event_id,
            }
        else:
            event = {
                "schema_version": "family-hot-event/v0",
                "event_id": event_id,
                "created_at": created_at,
                "created_by": "agent-a",
                "class": class_num,
                "kind": kind,
                "title": title,
                "summary": summary,
                "owner": owner,
                "priority": priority,
                "promotion_pending": promotion_pending,
                "related": ["#4"],
            }
            if canonical_path:
                event["canonical_path"] = canonical_path
            if canonical_url:
                event["canonical_url"] = canonical_url
            if expires_at:
                event["expires_at"] = expires_at
            if next_review_at:
                event["next_review_at"] = next_review_at
        path = self.inbox(vault) / f"{event_id}.json"
        path.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return event_id, path

    def generate(self, vault, now="2026-07-04T01:00:00Z"):
        env = os.environ.copy()
        env["FMA_HEARTBEAT_DIR"] = str(Path(vault) / "heartbeats")
        return self.run_script(FAMILY_HOT_GENERATE_SCRIPT, "--vault-root", vault, "--now", now, env=env)

    def lint(self, vault, now="2026-07-04T01:00:00Z"):
        return self.run_script(FAMILY_HOT_LINT_SCRIPT, "--vault-root", vault, "--now", now)

    def test_generate_all_renderable_classes_and_reader_accepts(self):
        with tempfile.TemporaryDirectory() as vault:
            self.write_event(vault, kind="project", class_num=2, title="Today headline", event_slug="headline", uuid8="00000002")
            self.write_event(vault, kind="project", class_num=3, title="Family focus", event_slug="focus", uuid8="00000003")
            self.write_event(vault, kind="blocker", class_num=4, title="Active ask", event_slug="ask", uuid8="00000004")
            self.write_event(
                vault,
                kind="decision",
                class_num=5,
                title="Decision landed",
                event_slug="decision",
                canonical_path="family-vault/30_decisions/decision.md",
                uuid8="00000005",
            )
            self.write_event(vault, kind="project", class_num=6, title="Cross project", event_slug="cross-project", uuid8="00000006")
            self.write_event(
                vault,
                kind="caution",
                class_num=9,
                title="Short caution",
                event_slug="caution",
                canonical_url="https://github.com/caty-ai/family-memory-architecture/issues/4",
                canonical_path=None,
                expires_at="2026-07-08T00:00:00Z",
                uuid8="00000009",
            )
            self.write_event(vault, kind="blocker", class_num=10, title="Blocking lint", event_slug="lint", uuid8="0000000a")

            generated = self.generate(vault)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            output_path = Path(vault) / "00_index" / "family-hot.md"
            ledger_path = Path(vault) / "00_index" / "family-hot.sources.json"
            self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(ledger_path.stat().st_mode), 0o600)
            text = output_path.read_text(encoding="utf-8")
            for class_num in (2, 3, 4, 5, 6, 9, 10):
                self.assertIn(f"[class:{class_num} ", text)

            reader = self.run_script(FAMILY_HOT_READ_SCRIPT, "--check", "--path", output_path)
            self.assertEqual(reader.returncode, 0, reader.stdout + reader.stderr)
            linted = self.lint(vault)
            self.assertEqual(linted.returncode, 0, linted.stdout + linted.stderr)

    def test_tamper_body_rejected_by_reader_and_lint(self):
        with tempfile.TemporaryDirectory() as vault:
            self.write_event(vault, title="Tamper decision")
            self.assertEqual(self.generate(vault).returncode, 0)
            output_path = Path(vault) / "00_index" / "family-hot.md"
            raw = output_path.read_bytes()
            output_path.write_bytes(raw.replace(b"Tamper", b"Damper", 1))

            reader = self.run_script(FAMILY_HOT_READ_SCRIPT, "--check", "--path", output_path)
            self.assertEqual(reader.returncode, 2, reader.stdout + reader.stderr)
            self.assertIn("body-sha256-mismatch", reader.stdout)
            linted = self.lint(vault)
            self.assertEqual(linted.returncode, 2, linted.stdout + linted.stderr)

    def test_promotion_pending_sla_boundaries(self):
        cases = [
            ("under", "2026-07-04T23:59:59Z", 0, "00000011", False, None),
            ("over24", "2026-07-05T00:00:01Z", 1, "00000012", False, "promotion-pending-over-24h"),
            ("over72", "2026-07-07T00:00:01Z", 2, "00000013", False, "promotion-pending-over-72h"),
            ("over72-owned", "2026-07-07T00:00:01Z", 1, "00000014", True, "promotion-pending-over-24h"),
        ]
        for name, now, expected_code, uuid8, with_review, expected_text in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as vault:
                self.write_event(
                    vault,
                    kind="decision",
                    class_num=5,
                    title=f"Pending {name}",
                    event_slug=f"pending-{name}",
                    canonical_path=None,
                    canonical_url="https://github.com/caty-ai/family-memory-architecture/issues/4",
                    owner="agent-a" if with_review else "",
                    promotion_pending=True,
                    next_review_at="2026-07-08T00:00:00Z" if with_review else None,
                    uuid8=uuid8,
                )
                self.assertEqual(self.generate(vault, now="2026-07-04T01:00:00Z").returncode, 0)
                linted = self.lint(vault, now=now)
                self.assertEqual(linted.returncode, expected_code, linted.stdout + linted.stderr)
                if expected_text:
                    self.assertIn(expected_text, linted.stdout)

    def test_caution_ttl_defaults_short_window_too_long_and_expired_warning(self):
        with tempfile.TemporaryDirectory() as vault:
            default_id, _ = self.write_event(
                vault,
                kind="caution",
                class_num=9,
                title="Default TTL",
                event_slug="default-ttl",
                canonical_url="https://github.com/caty-ai/family-memory-architecture/issues/4",
                canonical_path=None,
                uuid8="00000021",
            )
            short_id, _ = self.write_event(
                vault,
                kind="caution",
                class_num=9,
                title="Short freeze",
                event_slug="short-freeze",
                canonical_url="https://github.com/caty-ai/family-memory-architecture/issues/4",
                canonical_path=None,
                expires_at="2026-07-07T00:00:00Z",
                uuid8="00000022",
            )
            generated = self.generate(vault, now="2026-07-06T00:00:00Z")
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            self.assertIn(default_id, text)
            self.assertIn(short_id, text)
            linted = self.lint(vault, now="2026-07-06T00:00:00Z")
            self.assertEqual(linted.returncode, 1, linted.stdout + linted.stderr)
            self.assertIn("caution-missing-expires-at", linted.stdout)

            self.write_event(
                vault,
                kind="caution",
                class_num=9,
                title="Too long",
                event_slug="too-long",
                canonical_url="https://github.com/caty-ai/family-memory-architecture/issues/4",
                canonical_path=None,
                expires_at="2026-07-25T00:00:00Z",
                uuid8="00000023",
            )
            linted = self.lint(vault, now="2026-07-06T00:00:00Z")
            self.assertEqual(linted.returncode, 2, linted.stdout + linted.stderr)
            self.assertIn("caution-ttl-too-long", linted.stdout)

        with tempfile.TemporaryDirectory() as vault:
            expired_id, _ = self.write_event(
                vault,
                kind="caution",
                class_num=9,
                title="Expired default",
                event_slug="expired-default",
                canonical_url="https://github.com/caty-ai/family-memory-architecture/issues/4",
                canonical_path=None,
                uuid8="00000024",
            )
            generated = self.generate(vault, now="2026-07-12T00:00:01Z")
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            self.assertNotIn(expired_id, text)
            linted = self.lint(vault, now="2026-07-12T00:00:01Z")
            self.assertEqual(linted.returncode, 1, linted.stdout + linted.stderr)
            self.assertIn("expired-caution-still-present", linted.stdout)

    def test_freeze_caution_default_ttl_vs_non_freeze_and_explicit_expiry(self):
        with tempfile.TemporaryDirectory() as vault:
            freeze_id, _ = self.write_event(
                vault,
                kind="caution",
                class_num=9,
                title="Freeze shared calendar edits",
                summary="Do not touch until Agent A confirms.",
                event_slug="freeze-calendar",
                canonical_url="https://github.com/caty-ai/family-memory-architecture/issues/4",
                canonical_path=None,
                uuid8="00000025",
            )
            non_freeze_id, _ = self.write_event(
                vault,
                kind="caution",
                class_num=9,
                title="Routine caution",
                summary="Watch for duplicate notes.",
                event_slug="routine-caution",
                canonical_url="https://github.com/caty-ai/family-memory-architecture/issues/4",
                canonical_path=None,
                uuid8="00000026",
            )
            explicit_id, _ = self.write_event(
                vault,
                kind="caution",
                class_num=9,
                title="Do not touch migration plan",
                summary="Explicit expiry should win.",
                event_slug="explicit-freeze",
                canonical_url="https://github.com/caty-ai/family-memory-architecture/issues/4",
                canonical_path=None,
                expires_at="2026-07-14T00:00:00Z",
                uuid8="00000027",
            )

            generated = self.generate(vault, now="2026-07-06T00:00:00Z")
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            self.assertIn(freeze_id, text)
            self.assertIn(non_freeze_id, text)
            self.assertIn(explicit_id, text)
            linted = self.lint(vault, now="2026-07-06T00:00:00Z")
            self.assertEqual(linted.returncode, 1, linted.stdout + linted.stderr)
            self.assertIn("caution-missing-expires-at", linted.stdout)
            self.assertNotIn("expired-caution-still-present", linted.stdout)

            generated = self.generate(vault, now="2026-07-08T00:00:01Z")
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            self.assertNotIn(freeze_id, text)
            self.assertIn(non_freeze_id, text)
            self.assertIn(explicit_id, text)
            linted = self.lint(vault, now="2026-07-08T00:00:01Z")
            self.assertEqual(linted.returncode, 1, linted.stdout + linted.stderr)
            self.assertIn("expired-caution-still-present", linted.stdout)
            self.assertIn(freeze_id, linted.stdout)
            self.assertNotIn(f"expired caution still present in inbox without expire event: {non_freeze_id}", linted.stdout)
            self.assertNotIn(f"expired caution still present in inbox without expire event: {explicit_id}", linted.stdout)

    def test_lint_detects_ledger_output_sources_sha_mismatch(self):
        with tempfile.TemporaryDirectory() as vault:
            self.write_event(vault, kind="project", class_num=6, title="Ledger source", uuid8="00000028")
            generated = self.generate(vault)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            clean_lint = self.lint(vault)
            self.assertEqual(clean_lint.returncode, 0, clean_lint.stdout + clean_lint.stderr)

            ledger_path = Path(vault) / "00_index" / "family-hot.sources.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["sources_sha256"] = "f" * 64
            ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            linted = self.lint(vault)
            self.assertEqual(linted.returncode, 2, linted.stdout + linted.stderr)
            self.assertIn("ledger-output-mismatch", linted.stdout)

    def test_lint_reports_malformed_inbox_event_as_warning(self):
        with tempfile.TemporaryDirectory() as vault:
            bad = self.inbox(vault) / "20260704T000000Z__agent-a__project__bad__00000029.json"
            bad.write_text("{not valid json", encoding="utf-8")
            generated = self.generate(vault)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)

            linted = self.lint(vault)
            self.assertEqual(linted.returncode, 1, linted.stdout + linted.stderr)
            self.assertIn("inbox-invalid-event", linted.stdout)
            self.assertIn(bad.name, linted.stdout)

    def test_lint_reports_secret_bearing_inbox_event_as_failure(self):
        with tempfile.TemporaryDirectory() as vault:
            event_id = "20260704T000000Z__agent-a__project__secret__0000002a"
            event = {
                "schema_version": "family-hot-event/v0",
                "event_id": event_id,
                "created_at": "2026-07-04T00:00:00Z",
                "created_by": "agent-a",
                "class": 6,
                "kind": "project",
                "title": "Secret fixture",
                "summary": "fake token github_pat_" + ("x" * 20),
                "canonical_path": "family-vault/20_projects/secret.md",
            }
            path = self.inbox(vault) / f"{event_id}.json"
            path.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            generated = self.generate(vault)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            self.assertIn("secret-like pattern detected", generated.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            self.assertNotIn(event_id, text)

            linted = self.lint(vault)
            self.assertEqual(linted.returncode, 2, linted.stdout + linted.stderr)
            self.assertIn("secret-in-inbox", linted.stdout)
            self.assertIn(path.name, linted.stdout)

    def test_lint_warns_for_caution_missing_expires_at(self):
        with tempfile.TemporaryDirectory() as vault:
            caution_id, _ = self.write_event(
                vault,
                kind="caution",
                class_num=9,
                title="Missing expiry",
                event_slug="missing-expiry",
                canonical_url="https://github.com/caty-ai/family-memory-architecture/issues/4",
                canonical_path=None,
                uuid8="0000002b",
            )
            generated = self.generate(vault)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            linted = self.lint(vault)
            self.assertEqual(linted.returncode, 1, linted.stdout + linted.stderr)
            self.assertIn("caution-missing-expires-at", linted.stdout)
            self.assertIn(caution_id, linted.stdout)

    def test_size_overflow_degrades_output_and_preserves_ledger(self):
        with tempfile.TemporaryDirectory() as vault:
            output_path = Path(vault) / "00_index" / "family-hot.md"
            ledger_path = Path(vault) / "00_index" / "family-hot.sources.json"
            event_ids = []
            for index in range(6):
                event_id, _ = self.write_event(
                    vault,
                    kind="project",
                    class_num=6,
                    title=f"C6 event {index}",
                    summary="lower-priority " + ("x" * 260),
                    created_at=f"2026-07-04T00:0{index}:00Z",
                    event_slug=f"c6-event-{index}",
                    uuid8=f"0000010{index}",
                )
                event_ids.append(event_id)
            for index in range(5):
                event_id, _ = self.write_event(
                    vault,
                    kind="decision",
                    class_num=5,
                    title=f"C5 event {index}",
                    summary="higher-priority " + ("y" * 260),
                    created_at=f"2026-07-04T00:1{index}:00Z",
                    event_slug=f"c5-event-{index}",
                    canonical_path=f"family-vault/30_decisions/c5-event-{index}.md",
                    uuid8=f"0000011{index}",
                )
                event_ids.append(event_id)

            generated = self.generate(vault, now="2026-07-04T01:00:00Z")
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            raw = output_path.read_bytes()
            text = raw.decode("utf-8")
            rendered_ids = [
                event_id for event_id in event_ids
                if f"id:{event_id}]" in text
            ]
            dropped_count = 10 - len(rendered_ids)
            self.assertLessEqual(len(raw), 2048)
            self.assertGreater(dropped_count, 0)
            self.assertIn(f"overflow: {dropped_count} events pending", text)
            self.assertIn("C5 event 4", text)
            self.assertNotIn("C6 event 1", text)

            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(set(ledger["accepted_event_ids"]), set(event_ids))
            reader = self.run_script(FAMILY_HOT_READ_SCRIPT, "--check", "--path", output_path)
            self.assertEqual(reader.returncode, 0, reader.stdout + reader.stderr)
            linted = self.lint(vault)
            self.assertEqual(linted.returncode, 0, linted.stdout + linted.stderr)
            heartbeat = json.loads((Path(vault) / "heartbeats" / "family-hot-generate.json").read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["docs"], len(rendered_ids))

    def test_non_overflow_output_keeps_pre_change_format(self):
        with tempfile.TemporaryDirectory() as vault:
            event_id, event_path = self.write_event(vault, title="Stable format", uuid8="00000120")
            generated = self.generate(vault)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            output_path = Path(vault) / "00_index" / "family-hot.md"
            raw = output_path.read_bytes()

            file_hash = hashlib.sha256(event_path.read_bytes()).hexdigest()
            source_lines = f"{event_path.name}:{file_hash}\npinned:#4\n"
            sources_sha256 = hashlib.sha256(source_lines.encode("utf-8")).hexdigest()
            body = (
                "# Family Hot\n\n"
                "## C6 Family-crossing projects and blockers\n"
                f"- [class:6 id:{event_id}] Stable format | One short summary. | "
                "ptr: family-vault/20_projects/project-event.md; o: agent-a; p: P2; "
                "at: 2026-07-04T00:00:00Z\n\n"
                "---\n"
                "- [class:1 id:generator-heartbeat] at: 2026-07-04T01:00:00Z; "
                "gen: family-hot-generator v0; pinned: #4\n"
            )
            marker = "<!-- GENERATED-FILE: family-hot.md; DO NOT EDIT BY HAND -->"
            placeholder = (
                f"{marker}\n"
                f"<!-- generator: family-hot-generator v0; sources_sha256: {sources_sha256}; "
                f"body_sha256: {'0' * 64} -->\n"
                f"{body}"
            ).encode("utf-8")
            lines = placeholder.splitlines(keepends=True)
            body_sha256 = hashlib.sha256(b"".join(lines[:1] + lines[2:])).hexdigest()
            expected = (
                f"{marker}\n"
                f"<!-- generator: family-hot-generator v0; sources_sha256: {sources_sha256}; "
                f"body_sha256: {body_sha256} -->\n"
                f"{body}"
            ).encode("utf-8")
            self.assertEqual(raw, expected)
            self.assertNotIn(b"overflow:", raw)

    def test_default_write_emits_success_and_failure_heartbeats(self):
        with tempfile.TemporaryDirectory() as vault, tempfile.TemporaryDirectory() as heartbeat_dir:
            self.write_event(vault, title="Heartbeat success", uuid8="00000121")
            env = os.environ.copy()
            env["FMA_HEARTBEAT_DIR"] = heartbeat_dir
            succeeded = self.run_script(
                FAMILY_HOT_GENERATE_SCRIPT,
                "--vault-root", vault,
                "--now", "2026-07-04T01:00:00Z",
                env=env,
            )
            self.assertEqual(succeeded.returncode, 0, succeeded.stdout + succeeded.stderr)
            heartbeat_path = Path(heartbeat_dir) / "family-hot-generate.json"
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["status"], "ok")
            self.assertEqual(heartbeat["docs"], 1)

            ledger_path = Path(vault) / "00_index" / "family-hot.sources.json"
            ledger_path.unlink()
            ledger_path.mkdir()
            failed = self.run_script(
                FAMILY_HOT_GENERATE_SCRIPT,
                "--vault-root", vault,
                "--now", "2026-07-04T01:00:00Z",
                env=env,
            )
            self.assertEqual(failed.returncode, 2, failed.stdout + failed.stderr)
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["status"], "fail")
            self.assertTrue(heartbeat.get("reason"))
            self.assertLessEqual(len(heartbeat["reason"]), 300)

    def test_dry_run_and_check_do_not_emit_heartbeat(self):
        for mode in ("--dry-run", "--check"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as vault, tempfile.TemporaryDirectory() as heartbeat_dir:
                self.write_event(vault, title="No heartbeat", uuid8="00000122")
                env = os.environ.copy()
                env["FMA_HEARTBEAT_DIR"] = heartbeat_dir
                result = self.run_script(
                    FAMILY_HOT_GENERATE_SCRIPT,
                    "--vault-root", vault,
                    "--now", "2026-07-04T01:00:00Z",
                    mode,
                    env=env,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse((Path(heartbeat_dir) / "family-hot-generate.json").exists())

    def test_heartbeat_side_failure_never_breaks_generation(self):
        failures = {
            "timeout": subprocess.TimeoutExpired(cmd=["job-heartbeat"], timeout=10),
            "unexpected": RuntimeError("heartbeat exploded"),
        }
        for label, error in failures.items():
            with self.subTest(failure=label), tempfile.TemporaryDirectory() as vault:
                self.write_event(vault, title="Artifact survives", uuid8="00000123")
                module = self.load_script_module(f"family_hot_generate_hb_{label}", FAMILY_HOT_GENERATE_SCRIPT)

                def raise_heartbeat_error(*_args, **_kwargs):
                    raise error

                # Swap the module-local `subprocess` binding only; mutating the
                # shared subprocess module would leak into every other test.
                module.subprocess = mock.Mock(
                    run=raise_heartbeat_error,
                    DEVNULL=subprocess.DEVNULL,
                    PIPE=subprocess.PIPE,
                )
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    result = module.main(["--vault-root", vault, "--now", "2026-07-04T01:00:00Z"])
                self.assertEqual(result, 0, stderr.getvalue())
                self.assertTrue((Path(vault) / "00_index" / "family-hot.md").exists())
                self.assertIn("warning: heartbeat write failed", stderr.getvalue())

    def test_unexpected_exception_emits_truncated_failure_heartbeat(self):
        with tempfile.TemporaryDirectory() as vault, tempfile.TemporaryDirectory() as heartbeat_dir:
            module = self.load_script_module("family_hot_generate_unexpected_failure", FAMILY_HOT_GENERATE_SCRIPT)

            def fail_unexpectedly(_args):
                raise RuntimeError("x" * 400)

            module.generate = fail_unexpectedly
            stderr = io.StringIO()
            with mock.patch.dict(os.environ, {"FMA_HEARTBEAT_DIR": heartbeat_dir}), contextlib.redirect_stderr(stderr):
                result = module.main(["--vault-root", vault, "--now", "2026-07-04T01:00:00Z"])
            self.assertEqual(result, 2, stderr.getvalue())
            heartbeat = json.loads(
                (Path(heartbeat_dir) / "family-hot-generate.json").read_text(encoding="utf-8")
            )
            self.assertEqual(heartbeat["status"], "fail")
            self.assertEqual(len(heartbeat["reason"]), 300)
            self.assertTrue(heartbeat["reason"].startswith("runtime error:"))

    def test_default_permission_check_accepts_gid_mismatch(self):
        module = self.load_script_module("family_hot_generate_default_gid", FAMILY_HOT_GENERATE_SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "family-hot.md"
            path.write_text("ok\n", encoding="utf-8")
            current_gid = os.getgid()
            secondary_gid = next((gid for gid in os.getgroups() if gid != current_gid), None)
            with mock.patch.object(module.os, "geteuid", return_value=1):
                if secondary_gid is not None:
                    try:
                        os.chown(path, -1, secondary_gid)
                    except OSError:
                        secondary_gid = None
                if secondary_gid is not None:
                    issues = module.enforce_generated_artifact_permissions([path])
                else:
                    fake_gid = current_gid + 1
                    original_getgrgid = module.grp.getgrgid

                    def fake_getgrgid(gid):
                        if gid == fake_gid:
                            return type("GrpEntry", (), {"gr_name": "expected-group"})
                        return original_getgrgid(gid)

                    with mock.patch.object(module.os, "getgid", return_value=fake_gid):
                        with mock.patch.object(module.grp, "getgrgid", side_effect=fake_getgrgid):
                            issues = module.enforce_generated_artifact_permissions([path])
            self.assertEqual(issues, [])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_default_permission_check_rejects_uid_mismatch(self):
        module = self.load_script_module("family_hot_generate_default_uid", FAMILY_HOT_GENERATE_SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "family-hot.md"
            path.write_text("ok\n", encoding="utf-8")
            fake_uid = os.getuid() + 1
            original_getpwuid = module.pwd.getpwuid

            def fake_getpwuid(uid):
                if uid == fake_uid:
                    return type("PwdEntry", (), {"pw_name": "expected-user"})
                return original_getpwuid(uid)

            with mock.patch.object(module.os, "geteuid", return_value=1):
                with mock.patch.object(module.os, "getuid", return_value=fake_uid):
                    with mock.patch.object(module.pwd, "getpwuid", side_effect=fake_getpwuid):
                        issues = module.enforce_generated_artifact_permissions([path])
            self.assertEqual(len(issues), 1)
            self.assertIn("owner is", issues[0])
            self.assertIn("expected expected-user", issues[0])

    def test_default_permission_check_rejects_non_0600_mode(self):
        module = self.load_script_module("family_hot_generate_default_mode", FAMILY_HOT_GENERATE_SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "family-hot.md"
            path.write_text("ok\n", encoding="utf-8")
            actual_stat = path.stat()
            wrong_mode_stat = self.mutated_stat_result(actual_stat, mode=0o640)
            original_path_stat = Path.stat

            def fake_stat(self):
                if self == path:
                    return wrong_mode_stat
                return original_path_stat(self)

            with mock.patch.object(module.os, "geteuid", return_value=1):
                with mock.patch("pathlib.Path.stat", autospec=True, side_effect=fake_stat):
                    issues = module.enforce_generated_artifact_permissions([path])
            self.assertEqual(issues, [f"{path}: mode is 0640, expected 0600"])

    def test_pinned_permission_check_still_rejects_group_mismatch(self):
        module = self.load_script_module("family_hot_generate_pinned_gid", FAMILY_HOT_GENERATE_SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "family-hot.md"
            path.write_text("ok\n", encoding="utf-8")
            current_uid = path.stat().st_uid
            current_gid = path.stat().st_gid
            expected_gid = current_gid + 1
            fake_pwd = type("PwdEntry", (), {"pw_uid": current_uid})
            fake_grp = type("GrpEntry", (), {"gr_gid": expected_gid})
            with mock.patch.object(module.os, "geteuid", return_value=1):
                with mock.patch.dict(module.os.environ, {"FMA_EXPECT_OWNER": "artifact-user:artifact-group"}, clear=False):
                    with mock.patch.object(module.pwd, "getpwnam", return_value=fake_pwd):
                        with mock.patch.object(module.grp, "getgrnam", return_value=fake_grp):
                            issues = module.enforce_generated_artifact_permissions([path])
            self.assertEqual(len(issues), 1)
            self.assertIn("owner is", issues[0])
            self.assertIn("expected artifact-user:artifact-group", issues[0])

    def test_ledger_write_failure_preserves_prior_output(self):
        with tempfile.TemporaryDirectory() as vault:
            self.write_event(vault, kind="project", class_num=6, title="Small valid", uuid8="00000034")
            valid = self.generate(vault)
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
            output_path = Path(vault) / "00_index" / "family-hot.md"
            ledger_path = Path(vault) / "00_index" / "family-hot.sources.json"
            before_output = output_path.read_bytes()

            ledger_path.unlink()
            ledger_path.mkdir()
            self.write_event(
                vault,
                kind="project",
                class_num=6,
                title="New valid event",
                created_at="2026-07-04T00:01:00Z",
                event_slug="new-valid-event",
                uuid8="00000035",
            )
            failed = self.generate(vault)
            self.assertEqual(failed.returncode, 2, failed.stdout + failed.stderr)
            self.assertEqual(output_path.read_bytes(), before_output)

    def test_output_write_failure_preserves_prior_output_after_ledger_update(self):
        with tempfile.TemporaryDirectory() as vault:
            self.write_event(vault, kind="project", class_num=6, title="Small valid", uuid8="00000036")
            valid = self.generate(vault)
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
            output_path = Path(vault) / "00_index" / "family-hot.md"
            ledger_path = Path(vault) / "00_index" / "family-hot.sources.json"
            before_output = output_path.read_bytes()
            before_ledger = ledger_path.read_bytes()

            self.write_event(
                vault,
                kind="project",
                class_num=6,
                title="Ledger only event",
                created_at="2026-07-04T00:01:00Z",
                event_slug="ledger-only-event",
                uuid8="00000037",
            )
            module = self.load_script_module("family_hot_generate_output_failure", FAMILY_HOT_GENERATE_SCRIPT)
            original_write_atomic = module.write_atomic

            def fail_output_write(path, data):
                if Path(path).name == "family-hot.md":
                    raise OSError("forced output write failure")
                return original_write_atomic(path, data)

            module.write_atomic = fail_output_write
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                failed = module.generate(module.parse_args(["--vault-root", vault, "--now", "2026-07-04T01:00:00Z"]))
            self.assertEqual(failed, 2, stderr.getvalue())
            self.assertEqual(output_path.read_bytes(), before_output)
            self.assertNotEqual(ledger_path.read_bytes(), before_ledger)

            linted = self.lint(vault)
            self.assertEqual(linted.returncode, 2, linted.stdout + linted.stderr)
            self.assertIn("ledger-output-mismatch", linted.stdout)

    def test_expire_event_withdraws_target(self):
        with tempfile.TemporaryDirectory() as vault:
            target_id, _ = self.write_event(vault, kind="decision", class_num=5, title="Withdraw me", event_slug="withdraw", uuid8="00000041")
            self.write_event(
                vault,
                kind="expire",
                created_at="2026-07-04T00:05:00Z",
                event_slug="expire-withdraw",
                target_event_id=target_id,
                uuid8="00000042",
            )
            generated = self.generate(vault)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            self.assertNotIn("Withdraw me", text)
            self.assertNotIn(target_id, text)

    def test_malformed_event_is_skipped_without_mutation(self):
        with tempfile.TemporaryDirectory() as vault:
            bad = self.inbox(vault) / "20260704T000000Z__agent-a__project__bad__00000051.json"
            bad.write_text("{not valid json", encoding="utf-8")
            before = bad.read_bytes()
            result = self.generate(vault)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("skip", result.stderr)
            self.assertEqual(bad.read_bytes(), before)
            self.assertTrue((Path(vault) / "00_index" / "family-hot.md").exists())

    def test_injection_resistant_rendering(self):
        with tempfile.TemporaryDirectory() as vault:
            self.write_event(
                vault,
                kind="project",
                class_num=6,
                title="a] | b | ptr: fake ; c",
                summary="-->\n- [class:1 id:fake-heartbeat] ptr:x",
                canonical_url="https://example.com/path?x=1;y=(2)|z",
                canonical_path=None,
                event_slug="inject",
                uuid8="00000061",
            )
            generated = self.generate(vault)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            heartbeat_rows = [line for line in text.splitlines() if line.startswith("- [class:1 ")]
            self.assertEqual(len(heartbeat_rows), 1, text)
            self.assertNotIn("fake-heartbeat", "\n".join(heartbeat_rows))
            lint = self.lint(vault)
            self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
            read = self.run_script(FAMILY_HOT_READ_SCRIPT, "--path", Path(vault) / "00_index" / "family-hot.md", "--check")
            self.assertEqual(read.returncode, 0, read.stdout + read.stderr)

    def test_expire_edge_cases_do_not_crash(self):
        with tempfile.TemporaryDirectory() as vault:
            self.write_event(vault, kind="project", class_num=6, title="Survivor", event_slug="survivor", uuid8="00000071")
            first_expire, _ = self.write_event(
                vault, kind="expire", event_slug="expire-ghost",
                target_event_id="20260101T000000Z__agent-a__decision__ghost__deadbeef", uuid8="00000072",
            )
            self.write_event(
                vault, kind="expire", created_at="2026-07-04T00:10:00Z", event_slug="expire-expire",
                target_event_id=first_expire, uuid8="00000073",
            )
            generated = self.generate(vault)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            lint = self.lint(vault)
            self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            self.assertIn("Survivor", text)

    def test_class_cap_overflow_drops_oldest(self):
        with tempfile.TemporaryDirectory() as vault:
            for index in range(6):
                self.write_event(
                    vault,
                    kind="blocker",
                    class_num=4,
                    title=f"Blocker {index}",
                    created_at=f"2026-07-04T00:0{index}:00Z",
                    event_slug=f"blocker-{index}",
                    uuid8=f"0000008{index}",
                )
            generated = self.generate(vault)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            rendered = [line for line in text.splitlines() if line.startswith("- [class:4 ")]
            self.assertEqual(len(rendered), 5, text)
            self.assertNotIn("Blocker 0", text)
            self.assertIn("Blocker 5", text)
            lint = self.lint(vault)
            self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)

    def test_whitespace_only_title_is_rejected(self):
        with tempfile.TemporaryDirectory() as vault:
            self.write_event(vault, kind="project", class_num=6, title="   ", event_slug="blank", uuid8="00000091")
            result = self.generate(vault)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("skip", result.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            self.assertNotIn("blank", text)

    def test_lint_warns_on_inbox_event_missing_from_ledger(self):
        with tempfile.TemporaryDirectory() as vault:
            self.write_event(vault, kind="project", class_num=6, title="First", event_slug="first", uuid8="000000a1")
            generated = self.generate(vault)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            self.write_event(
                vault, kind="project", class_num=6, title="Late arrival",
                created_at="2026-07-04T00:30:00Z", event_slug="late", uuid8="000000a2",
            )
            lint = self.lint(vault)
            self.assertEqual(lint.returncode, 1, lint.stdout + lint.stderr)
            self.assertIn("inbox-not-in-ledger", lint.stdout)

    def test_future_event_is_not_rendered_and_lint_warns(self):
        with tempfile.TemporaryDirectory() as vault:
            future_id, _ = self.write_event(
                vault,
                kind="caution",
                class_num=9,
                title="Future caution",
                event_slug="future-caution",
                created_at="2099-01-01T00:00:00Z",
                canonical_url="https://github.com/caty-ai/family-memory-architecture/issues/4",
                canonical_path=None,
                expires_at="2099-01-08T00:00:00Z",
                uuid8="000000b1",
            )
            generated = self.generate(vault, now="2026-07-04T01:00:00Z")
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            self.assertIn("created_at is more than 5 minutes in the future", generated.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            self.assertNotIn(future_id, text)

            linted = self.lint(vault, now="2026-07-04T01:00:00Z")
            self.assertEqual(linted.returncode, 1, linted.stdout + linted.stderr)
            self.assertIn("event-created-in-future", linted.stdout)

    def test_event_id_timestamp_mismatch_is_skipped_and_lint_warns(self):
        with tempfile.TemporaryDirectory() as vault:
            event_id, path = self.write_event(
                vault,
                kind="project",
                class_num=6,
                title="Mismatch",
                event_slug="mismatch",
                created_at="2026-07-04T00:00:00Z",
                uuid8="000000b2",
            )
            event = json.loads(path.read_text(encoding="utf-8"))
            event["created_at"] = "2026-07-04T00:00:01Z"
            path.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            generated = self.generate(vault)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            self.assertIn("event_id timestamp does not match created_at", generated.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            self.assertNotIn(event_id, text)

            linted = self.lint(vault)
            self.assertEqual(linted.returncode, 1, linted.stdout + linted.stderr)
            self.assertIn("event-timestamp-mismatch", linted.stdout)

    def test_created_at_allows_exactly_five_minutes_skew(self):
        with tempfile.TemporaryDirectory() as vault:
            allowed_id, _ = self.write_event(
                vault,
                kind="project",
                class_num=6,
                title="Skew allowed",
                event_slug="skew-allowed",
                created_at="2026-07-04T01:05:00Z",
                uuid8="000000b3",
            )
            generated = self.generate(vault, now="2026-07-04T01:00:00Z")
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            self.assertIn(allowed_id, text)

    def test_lint_checks_promotion_sla_for_cap_evicted_decisions(self):
        with tempfile.TemporaryDirectory() as vault:
            stale_id, _ = self.write_event(
                vault,
                kind="decision",
                class_num=5,
                title="Stale pending decision",
                event_slug="stale-pending",
                created_at="2026-07-01T00:00:00Z",
                canonical_path=None,
                canonical_url="https://github.com/caty-ai/family-memory-architecture/issues/4",
                owner="",
                promotion_pending=True,
                uuid8="000000c0",
            )
            for index in range(5):
                self.write_event(
                    vault,
                    kind="decision",
                    class_num=5,
                    title=f"New decision {index}",
                    event_slug=f"new-decision-{index}",
                    created_at=f"2026-07-02T00:0{index}:00Z",
                    canonical_path=f"family-vault/30_decisions/new-{index}.md",
                    uuid8=f"000000c{index + 1}",
                )

            generated = self.generate(vault, now="2026-07-03T23:59:59Z")
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            self.assertNotIn(stale_id, text)

            linted = self.lint(vault, now="2026-07-04T00:00:01Z")
            self.assertEqual(linted.returncode, 2, linted.stdout + linted.stderr)
            self.assertIn("promotion-pending-over-72h-not-rendered", linted.stdout)

    def load_generator(self):
        loader = importlib.machinery.SourceFileLoader(
            "family_hot_generate_hb_test", str(FAMILY_HOT_GENERATE_SCRIPT)
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def write_heartbeat(self, directory, name, *, status="ok", hours_ago=0.0, raw=None):
        path = Path(directory) / name
        if raw is not None:
            path.write_text(raw, encoding="utf-8")
            return path
        from datetime import datetime, timedelta, timezone

        last_run = (
            (datetime.now(timezone.utc) - timedelta(hours=hours_ago))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        path.write_text(
            json.dumps(
                {
                    "job": name.removesuffix(".json"),
                    "last_run": last_run,
                    "status": status,
                    "fail_count": 0,
                    "duration_ms": 1,
                    "docs": 0,
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_heartbeat_summary_none_without_env(self):
        module = self.load_generator()
        with mock.patch.dict(os.environ):
            os.environ.pop("FMA_HEARTBEAT_DIR", None)
            self.assertIsNone(module.heartbeat_summary())

    def test_heartbeat_summary_counts_ok_fail_stale_and_invalid(self):
        module = self.load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            self.write_heartbeat(tmp, "fresh-ok.json", status="ok", hours_ago=1)
            self.write_heartbeat(tmp, "fresh-fail.json", status="fail", hours_ago=1)
            self.write_heartbeat(tmp, "stale-ok.json", status="ok", hours_ago=30)
            self.write_heartbeat(tmp, "broken.json", raw="not json")
            with mock.patch.dict(os.environ, {"FMA_HEARTBEAT_DIR": tmp}):
                self.assertEqual(module.heartbeat_summary(), "hb: 1ok/2fail/1stale")

    def test_heartbeat_summary_none_for_missing_dir(self):
        module = self.load_generator()
        with mock.patch.dict(os.environ, {"FMA_HEARTBEAT_DIR": "/nonexistent/hb-dir"}):
            self.assertIsNone(module.heartbeat_summary())

    def test_heartbeat_summary_naive_or_bad_last_run_is_stale_not_crash(self):
        module = self.load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            self.write_heartbeat(
                tmp,
                "naive.json",
                raw=json.dumps({"job": "naive", "last_run": "2026-07-13T00:00:00", "status": "ok"}),
            )
            self.write_heartbeat(
                tmp,
                "garbage-ts.json",
                raw=json.dumps({"job": "garbage-ts", "last_run": "yesterday", "status": "ok"}),
            )
            self.write_heartbeat(
                tmp,
                "numeric-ts.json",
                raw=json.dumps({"job": "numeric-ts", "last_run": 12345, "status": "ok"}),
            )
            with mock.patch.dict(os.environ, {"FMA_HEARTBEAT_DIR": tmp}):
                self.assertEqual(module.heartbeat_summary(), "hb: 0ok/0fail/3stale")

    def test_size_capped_output_carries_hb_summary_end_to_end(self):
        module = self.load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            self.write_heartbeat(tmp, "fresh-ok.json", status="ok", hours_ago=1)
            with mock.patch.dict(os.environ, {"FMA_HEARTBEAT_DIR": tmp}):
                raw_output, _ = module.build_size_capped_output(
                    [], "2026-07-13T00:00:00Z", "0" * 64
                )
            text = raw_output.decode("utf-8") if isinstance(raw_output, bytes) else raw_output
            self.assertIn("; hb: 1ok/0fail/0stale", text)
            self.assertLessEqual(len(text.encode("utf-8")), module.SIZE_CAP_BYTES)

    def test_heartbeat_summary_empty_dir_is_all_zero(self):
        module = self.load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"FMA_HEARTBEAT_DIR": tmp}):
                self.assertEqual(module.heartbeat_summary(), "hb: 0ok/0fail/0stale")

    def test_heartbeat_summary_non_dict_json_counts_fail_not_crash(self):
        module = self.load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            self.write_heartbeat(tmp, "array.json", raw="[]")
            self.write_heartbeat(tmp, "null.json", raw="null")
            self.write_heartbeat(tmp, "string.json", raw='"x"')
            self.write_heartbeat(tmp, "fresh-ok.json", status="ok", hours_ago=1)
            with mock.patch.dict(os.environ, {"FMA_HEARTBEAT_DIR": tmp}):
                self.assertEqual(module.heartbeat_summary(), "hb: 1ok/3fail/0stale")

    def test_footer_default_line_is_byte_identical_golden(self):
        module = self.load_generator()
        body = module.render_body([], "2026-07-13T00:00:00Z", "0" * 64)
        expected = (
            f"- [class:1 id:generator-heartbeat] at: 2026-07-13T00:00:00Z; "
            f"gen: {module.GENERATOR_VERSION}; pinned: {module.PINNED_FALLBACK_ID}"
        )
        footer_lines = [line for line in body.splitlines() if "generator-heartbeat" in line]
        self.assertEqual(footer_lines, [expected])

    def test_footer_heartbeat_line_with_and_without_summary(self):
        module = self.load_generator()
        plain = module.render_body([], "2026-07-13T00:00:00Z", "0" * 64)
        self.assertIn("- [class:1 id:generator-heartbeat] at: 2026-07-13T00:00:00Z;", plain)
        self.assertNotIn("; hb:", plain)
        with_summary = module.render_body(
            [], "2026-07-13T00:00:00Z", "0" * 64, 0, "hb: 1ok/0fail/0stale"
        )
        self.assertIn("pinned: ", with_summary)
        self.assertIn("; hb: 1ok/0fail/0stale", with_summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
