#!/usr/bin/env python3
"""Tests for scripts/vault-lint."""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
VAULT_LINT_SCRIPT = REPO_ROOT / "scripts" / "vault-lint"
SECRET_VALUE = "sm_1234567890ABCDEFGHIJ"  # secret-scan: allow


def load_module():
    loader = importlib.machinery.SourceFileLoader("vault_lint_under_test", str(VAULT_LINT_SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def write_file(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class VaultLintTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def run_main(self, argv, env):
        old_env = os.environ.copy()
        os.environ.clear()
        os.environ.update(env)
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = self.module.main(argv)
        finally:
            os.environ.clear()
            os.environ.update(old_env)
        return code, stdout.getvalue(), stderr.getvalue()

    def env_for(self, tmp_path):
        return {
            "FMA_HEARTBEAT_DIR": str(tmp_path / "heartbeats"),
            "FMA_VAULT_LINT_DIR": str(tmp_path / "reports"),
        }

    def run_json(self, vault, tmp_path, *extra):
        code, stdout, stderr = self.run_main(
            ["--vault-root", str(vault), "--json", *extra],
            self.env_for(tmp_path),
        )
        report = json.loads(stdout)
        return code, report, stderr

    def details_for(self, report, rule):
        return [item["detail"] for item in report["findings"] if item["rule"] == rule]

    def paths_for(self, report, rule):
        return {item["path"] for item in report["findings"] if item["rule"] == rule}

    def findings_for(self, report, rule):
        return [item for item in report["findings"] if item["rule"] == rule]

    def test_dead_link_variants_and_code_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "target.md", "# Target\n")
            write_file(vault / "dir-a" / "same.md", "# Same A\n")
            write_file(vault / "dir-b" / "same.md", "# Same B\n")
            write_file(vault / "assets" / "photo.png", "png")
            write_file(
                vault / "source.md",
                "\n".join(
                    [
                        "[[missing-basic]]",
                        "[[missing-alias|Alias]]",
                        "[[target#Heading]]",
                        "```",
                        "[[missing-fenced]]",
                        "```",
                        "Inline `[[missing-inline]]` skipped.",
                        "[[same]]",
                        "![[assets/photo.png]]",
                        "![[missing-asset.png]]",
                    ]
                ),
            )

            code, report, stderr = self.run_json(vault, root, "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        details = "\n".join(self.details_for(report, "dead-link"))
        self.assertIn("missing-basic", details)
        self.assertIn("missing-alias", details)
        self.assertIn("missing-asset.png", details)
        self.assertNotIn("target#Heading", details)
        self.assertNotIn("missing-fenced", details)
        self.assertNotIn("missing-inline", details)
        self.assertNotIn("[[same]]", details)

    def test_orphan_flags_and_exemptions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "orphan.md", "# Orphan\n")
            write_file(vault / "00_index" / "not-orphan.md", "# Index\n")
            write_file(vault / "40_journals" / "2026-07-06.md", "# Journal\n")
            write_file(vault / "ok.md", "---\norphan-ok: true\n---\n# OK\n")
            write_file(vault / "linked.md", "# Linked\n")
            write_file(vault / "readme-linked.md", "# README linked\n")
            write_file(vault / "underscore-linked.md", "# Underscore linked\n")
            write_file(vault / "index.md", "[[linked]]\n")
            write_file(vault / "README.md", "[[readme-linked]]\n")
            write_file(vault / "area" / "area_index.md", "[[underscore-linked]]\n")

            code, report, stderr = self.run_json(vault, root, "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        orphan_paths = {item["path"] for item in report["findings"] if item["rule"] == "orphan"}
        self.assertIn("orphan.md", orphan_paths)
        self.assertNotIn("00_index/not-orphan.md", orphan_paths)
        self.assertNotIn("40_journals/2026-07-06.md", orphan_paths)
        self.assertNotIn("ok.md", orphan_paths)
        self.assertNotIn("linked.md", orphan_paths)
        self.assertNotIn("readme-linked.md", orphan_paths)
        self.assertNotIn("underscore-linked.md", orphan_paths)

    def test_root_orphan_flags_unclassified_root_entries_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "00_index" / "clean.md", "# Clean\n")
            write_file(vault / "20_people" / "person.md", "# Person\n")
            write_file(vault / "README.md", "# Vault\n")
            write_file(vault / ".obsidian" / "app.json", "{}\n")
            write_file(vault / ".hidden", "hidden\n")
            write_file(vault / "loose.md", "# Loose\n")
            write_file(vault / "01_notes.md", "# Numbered file\n")
            write_file(vault / "misc" / "nested.md", "# Nested\n")
            target = write_file(root / "outside-target.md", "# Target\n")
            os.symlink(target, vault / ".hidden-link")

            code, report, stderr = self.run_json(vault, root, "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        root_orphans = self.findings_for(report, "root-orphan")
        self.assertEqual({item["path"] for item in root_orphans}, {"loose.md", "01_notes.md", "misc", ".hidden-link"})
        self.assertTrue(all(item["severity"] == "warning" for item in root_orphans), root_orphans)

    def test_root_orphan_does_not_recurse_into_allowed_buckets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "10_assets" / "loose.bin", "asset\n")
            write_file(vault / "README.md", "# Vault\n")

            code, report, stderr = self.run_json(vault, root, "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        self.assertNotIn("10_assets/loose.bin", self.paths_for(report, "root-orphan"))
        self.assertNotIn("10_assets", self.paths_for(report, "root-orphan"))

    def test_stale_claims_and_review_pending_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "draft.md", "---\nstatus: draft\n---\n# Draft\n")
            write_file(vault / "expired.md", "---\nexpires: 2000-01-01\n---\n# Expired\n")
            warn_path = write_file(vault / "25_review-pending" / "forty.md", "# Forty\n")
            fail_path = write_file(vault / "25_review-pending" / "hundred.md", "# Hundred\n")
            now = datetime.now(timezone.utc)
            forty = (now - timedelta(days=40)).timestamp()
            hundred = (now - timedelta(days=100)).timestamp()
            os.utime(warn_path, (forty, forty))
            os.utime(fail_path, (hundred, hundred))

            code, report, stderr = self.run_json(vault, root, "--no-heartbeat")

        self.assertEqual(code, 2, stderr)
        stale = [item for item in report["findings"] if item["rule"] == "stale-claim"]
        details = "\n".join(item["detail"] for item in stale)
        self.assertIn("status is draft", details)
        self.assertIn("expires date is in the past", details)
        self.assertIn("older than 30 days", details)
        self.assertIn("older than 90 days", details)
        self.assertEqual([item["severity"] for item in stale if item["path"].endswith("hundred.md")], ["fail"])

    def test_secret_finding_is_fail_and_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "secret.md", f"token: {SECRET_VALUE}\n")

            code, report, stderr = self.run_json(vault, root, "--no-heartbeat")

        self.assertEqual(code, 2, stderr)
        secrets = [item for item in report["findings"] if item["rule"] == "secret"]
        self.assertEqual(len(secrets), 1)
        self.assertEqual(secrets[0]["severity"], "fail")
        self.assertIn("supermemory-token", secrets[0]["detail"])
        self.assertNotIn(SECRET_VALUE, secrets[0]["detail"])

    def test_secret_scan_covers_non_markdown_and_skips_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "notes.txt", "TAILSCALE_AUTHKEY=tskey-auth-kp1234567890abcdef\n")  # secret-scan: allow
            write_file(vault / "config.json", '{"MEILI_MASTER_KEY": "aBcDeF1234567890aBcDeF1234567890"}\n')  # secret-scan: allow
            binary = vault / "blob.bin"
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_bytes(b"\0\xff\x00not utf8")

            code, report, stderr = self.run_json(vault, root, "--no-heartbeat")

        self.assertEqual(code, 2, stderr)
        secret_paths = {item["path"] for item in report["findings"] if item["rule"] == "secret"}
        self.assertIn("notes.txt", secret_paths)
        self.assertIn("config.json", secret_paths)
        self.assertNotIn("Traceback", stderr)

    def test_oversize_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            large = "x" * (1_048_576 + 1)
            write_file(vault / "large.md", large)

            code, report, stderr = self.run_json(vault, root, "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        oversize = [item for item in report["findings"] if item["rule"] == "oversize"]
        self.assertEqual(len(oversize), 1)
        self.assertEqual(oversize[0]["rule"], "oversize")
        self.assertEqual(oversize[0]["severity"], "warning")

    def test_oversize_covers_non_markdown_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            archive = root / "archive"
            large = "x" * (1_048_576 + 1)
            write_file(archive / "recent.bin", "archived\n")
            write_file(vault / "large.json", large)

            code, report, stderr = self.run_json(vault, root, "--archive-dir", str(archive), "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        oversize_paths = self.paths_for(report, "oversize")
        binary_oversize = self.findings_for(report, "binary-oversize")
        binary_oversize_paths = {item["path"] for item in binary_oversize}
        self.assertNotIn("large.json", oversize_paths)
        self.assertIn("large.json", binary_oversize_paths)
        self.assertEqual(len([item for item in report["findings"] if item["path"] == "large.json" and item["rule"] == "binary-oversize"]), 1)
        self.assertFalse([item for item in report["findings"] if item["path"] == "large.json" and item["rule"] == "oversize"])
        self.assertTrue(all(item["severity"] == "warning" for item in binary_oversize), binary_oversize)

    def test_binary_oversize_negative_for_small_non_markdown_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "small.bin", "small\n")

            code, report, stderr = self.run_json(vault, root, "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        self.assertNotIn("small.bin", self.paths_for(report, "binary-oversize"))

    def test_archive_unused_reports_once_when_binary_exit_candidates_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            archive = root / "missing-archive"
            large = "x" * (1_048_576 + 1)
            write_file(vault / "10_assets" / "large.bin", large)
            write_file(vault / "10_assets" / "large-2.bin", large)

            code, report, stderr = self.run_json(
                vault,
                root,
                "--archive-dir",
                str(archive),
                "--archive-stale-days",
                "90",
                "--no-heartbeat",
            )

        self.assertEqual(code, 0, stderr)
        archive_unused = [item for item in report["findings"] if item["rule"] == "archive-unused"]
        self.assertEqual(len(archive_unused), 1)
        self.assertEqual(archive_unused[0]["path"], str(archive))
        self.assertIn("90+ days", archive_unused[0]["detail"])
        self.assertEqual(archive_unused[0]["severity"], "warning")

    def test_archive_unused_reports_when_archive_dir_exists_but_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            archive = root / "archive"
            archive.mkdir()
            large = "x" * (1_048_576 + 1)
            write_file(vault / "10_assets" / "large.bin", large)

            code, report, stderr = self.run_json(vault, root, "--archive-dir", str(archive), "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        archive_unused = self.findings_for(report, "archive-unused")
        self.assertEqual([item["path"] for item in archive_unused], [str(archive)])
        self.assertTrue(all(item["severity"] == "warning" for item in archive_unused), archive_unused)

    def test_archive_unused_skips_dangling_symlink_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            archive = root / "archive"
            archive.mkdir()
            large = "x" * (1_048_576 + 1)
            write_file(vault / "10_assets" / "large.bin", large)
            os.symlink(archive / "missing.bin", archive / "dangling.bin")

            code, report, stderr = self.run_json(vault, root, "--archive-dir", str(archive), "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.paths_for(report, "archive-unused"), {str(archive)})
        self.assertIn("warning: archive-unused entry skipped:", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_archive_stale_days_controls_archive_unused_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            archive_recent = root / "archive-recent"
            archive_old = root / "archive-old"
            large = "x" * (1_048_576 + 1)
            write_file(vault / "10_assets" / "large.bin", large)
            recent_entry = write_file(archive_recent / "recent.bin", "archived\n")
            old_entry = write_file(archive_old / "old.bin", "archived\n")
            now = datetime.now(timezone.utc)
            recent_time = (now - timedelta(hours=12)).timestamp()
            old_time = (now - timedelta(days=2)).timestamp()
            os.utime(recent_entry, (recent_time, recent_time))
            os.utime(old_entry, (old_time, old_time))

            recent_code, recent_report, recent_stderr = self.run_json(
                vault,
                root / "recent-state",
                "--archive-dir",
                str(archive_recent),
                "--archive-stale-days",
                "1",
                "--no-heartbeat",
            )
            old_code, old_report, old_stderr = self.run_json(
                vault,
                root / "old-state",
                "--archive-dir",
                str(archive_old),
                "--archive-stale-days",
                "1",
                "--no-heartbeat",
            )

        self.assertEqual(recent_code, 0, recent_stderr)
        self.assertEqual(old_code, 0, old_stderr)
        self.assertEqual(self.paths_for(recent_report, "archive-unused"), set())
        self.assertEqual(self.paths_for(old_report, "archive-unused"), {str(archive_old)})

    def test_archive_unused_treats_dot_only_archive_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            archive = root / "archive"
            large = "x" * (1_048_576 + 1)
            write_file(vault / "10_assets" / "large.bin", large)
            write_file(archive / ".DS_Store", "fresh dotfile\n")

            code, report, stderr = self.run_json(vault, root, "--archive-dir", str(archive), "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.paths_for(report, "archive-unused"), {str(archive)})

    def test_archive_unused_reports_expanded_absolute_archive_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_home = root / "home"
            vault = root / "vault"
            archive = fake_home / "archive"
            large = "x" * (1_048_576 + 1)
            write_file(vault / "10_assets" / "large.bin", large)
            env = self.env_for(root / "state")
            env["HOME"] = str(fake_home)

            code, stdout, stderr = self.run_main(
                [
                    "--vault-root",
                    str(vault),
                    "--archive-dir",
                    "~/archive",
                    "--json",
                    "--no-heartbeat",
                ],
                env,
            )
            report = json.loads(stdout)

        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.paths_for(report, "archive-unused"), {str(archive)})

    def test_archive_unused_suppressed_without_binary_exit_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            archive = root / "missing-archive"
            write_file(vault / "10_assets" / "small.bin", "small\n")

            code, report, stderr = self.run_json(vault, root, "--archive-dir", str(archive), "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.paths_for(report, "archive-unused"), set())

    def test_archive_unused_suppressed_when_archive_recently_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            archive = root / "archive"
            large = "x" * (1_048_576 + 1)
            write_file(vault / "10_assets" / "large.bin", large)
            write_file(archive / "recent.bin", "archived\n")

            code, report, stderr = self.run_json(vault, root, "--archive-dir", str(archive), "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.paths_for(report, "archive-unused"), set())

    def test_archive_unused_reports_when_archive_top_level_entries_are_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            archive = root / "archive"
            large = "x" * (1_048_576 + 1)
            write_file(vault / "10_assets" / "large.bin", large)
            stale_entry = write_file(archive / "old.bin", "archived\n")
            stale_time = (datetime.now(timezone.utc) - timedelta(days=120)).timestamp()
            os.utime(stale_entry, (stale_time, stale_time))

            code, report, stderr = self.run_json(vault, root, "--archive-dir", str(archive), "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        archive_unused = self.findings_for(report, "archive-unused")
        self.assertEqual({item["path"] for item in archive_unused}, {str(archive)})
        self.assertTrue(all(item["severity"] == "warning" for item in archive_unused), archive_unused)

    def test_archive_stale_days_rejects_non_positive_values(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                self.module.parse_args(["--archive-stale-days", "0"])

        self.assertIn("--archive-stale-days", stderr.getvalue())

    def test_light_mode_suppresses_old_paths_but_uses_full_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            old_source = write_file(vault / "old-source.md", "[[missing-old]]\n")
            recent_source = write_file(vault / "recent-source.md", "[[missing-recent]]\n[[old-target]]\n")
            old_target = write_file(vault / "old-target.md", "# Old target\n")
            old_time = (datetime.now(timezone.utc) - timedelta(days=20)).timestamp()
            os.utime(old_source, (old_time, old_time))
            os.utime(old_target, (old_time, old_time))

            code, report, stderr = self.run_json(vault, root, "--mode", "light", "--since-days", "8", "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        dead_details = "\n".join(self.details_for(report, "dead-link"))
        self.assertIn("missing-recent", dead_details)
        self.assertNotIn("missing-old", dead_details)
        self.assertNotIn("old-target", dead_details)
        self.assertEqual(report["mode"], "light")
        self.assertEqual(report["files_scanned"], 3)

    def test_light_mode_always_reports_old_secret_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            secret = write_file(vault / "old-secret.txt", f"token: {SECRET_VALUE}\n")
            old_time = (datetime.now(timezone.utc) - timedelta(days=20)).timestamp()
            os.utime(secret, (old_time, old_time))

            code, report, stderr = self.run_json(vault, root, "--mode", "light", "--since-days", "8", "--no-heartbeat")

        self.assertEqual(code, 2, stderr)
        secret_paths = {item["path"] for item in report["findings"] if item["rule"] == "secret"}
        self.assertIn("old-secret.txt", secret_paths)

    def test_light_mode_keeps_structural_lifecycle_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            archive = root / "missing-archive"
            root_orphan = write_file(vault / "loose.md", "# Loose\n")
            large_binary = write_file(vault / "10_assets" / "large.bin", "x" * (1_048_576 + 1))
            old_time = (datetime.now(timezone.utc) - timedelta(days=20)).timestamp()
            os.utime(root_orphan, (old_time, old_time))
            os.utime(large_binary, (old_time, old_time))

            code, report, stderr = self.run_json(
                vault,
                root,
                "--mode",
                "light",
                "--since-days",
                "8",
                "--archive-dir",
                str(archive),
                "--no-heartbeat",
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("loose.md", self.paths_for(report, "root-orphan"))
        self.assertIn("10_assets/large.bin", self.paths_for(report, "binary-oversize"))
        self.assertEqual(self.paths_for(report, "archive-unused"), {str(archive)})
        self.assertNotIn("warning: light filter stat failed:", stderr)

    def test_mutable_state_files_fail_including_dot_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "00_index" / "clean.md", "# Clean\n")
            write_file(vault / "runtime" / ".lock", "")
            write_file(vault / "runtime" / "cache.db", "")

            code, report, stderr = self.run_json(vault, root, "--mode", "light", "--no-heartbeat")

        self.assertEqual(code, 2, stderr)
        findings = self.findings_for(report, "mutable-state")
        self.assertEqual({item["path"] for item in findings}, {"runtime/.lock", "runtime/cache.db"})
        self.assertTrue(all(item["severity"] == "fail" for item in findings), findings)
        self.assertEqual(report["severity_counts"]["fail"], 2)

    def test_mutable_state_ignores_configured_archive_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            archive = vault / "archive"
            write_file(vault / "00_index" / "clean.md", "# Clean\n")
            write_file(archive / "quarantine.lock", "")
            write_file(archive / "previous.sqlite-wal", "")

            code, report, stderr = self.run_json(
                vault, root, "--archive-dir", str(archive), "--no-heartbeat"
            )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.findings_for(report, "mutable-state"), [])

    def test_mutable_state_ignores_tooling_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "00_index" / "clean.md", "# Clean\n")
            write_file(vault / ".stfolder" / "reader.cursor", "")
            write_file(vault / ".stversions" / "lock.mdb", "")
            write_file(vault / ".obsidian" / "workspace.db", "")
            write_file(vault / ".git" / "index.lock", "")

            code, report, stderr = self.run_json(vault, root, "--no-heartbeat")

        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.findings_for(report, "mutable-state"), [])

    def test_mutable_state_tmp_files_are_age_gated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "runtime" / "fresh.tmp", "")
            stale = write_file(vault / "runtime" / "stale.tmp", "")
            stale_time = time.time() - self.module.STALE_TMP_SECONDS - 60
            os.utime(stale, (stale_time, stale_time))

            code, report, stderr = self.run_json(vault, root, "--no-heartbeat")

        self.assertEqual(code, 2, stderr)
        self.assertEqual(self.paths_for(report, "mutable-state"), {"runtime/stale.tmp"})

    def test_mutable_state_widened_patterns_and_bare_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            mutable_names = {
                "data.mdb",
                "lock.mdb",
                "state.ldb",
                "render.cache",
                "sync.counter",
                "reader.offset",
                "Cursor",
                "COUNTER",
                "cache",
            }
            for name in mutable_names:
                write_file(vault / "runtime" / name, "")
            for name in ("cursor.md", "counter.md", "cache.md", "database.md"):
                write_file(vault / "00_index" / name, "# Legitimate markdown\n")

            code, report, stderr = self.run_json(vault, root, "--no-heartbeat")

        self.assertEqual(code, 2, stderr)
        self.assertEqual(
            self.paths_for(report, "mutable-state"),
            {f"runtime/{name}" for name in mutable_names},
        )

    def test_mutable_state_relative_archive_dir_is_vault_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "archive" / "archived.lock", "")
            write_file(vault / "runtime" / "active.lock", "")

            code, report, stderr = self.run_json(
                vault, root, "--archive-dir", "archive", "--no-heartbeat"
            )

        self.assertEqual(code, 2, stderr)
        self.assertEqual(self.paths_for(report, "mutable-state"), {"runtime/active.lock"})

    def test_mutable_state_invalid_archive_root_or_ancestor_does_not_disable_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "runtime" / "active.lock", "")

            for index, archive in enumerate((vault, root)):
                code, report, stderr = self.run_json(
                    vault,
                    root / f"state-{index}",
                    "--archive-dir",
                    str(archive),
                    "--no-heartbeat",
                )
                self.assertEqual(code, 2, stderr)
                self.assertEqual(self.paths_for(report, "mutable-state"), {"runtime/active.lock"})
                self.assertIn("warning: invalid --archive-dir for mutable-state scan:", stderr)
                self.assertIn("archive exemption disabled", stderr)

    def test_mutable_state_legacy_allow_exempts_exact_paths_and_globs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "legacy" / "cursor", "")
            write_file(vault / "legacy" / "cache.db", "")
            write_file(vault / "runtime" / "active.lock", "")

            code, report, stderr = self.run_json(
                vault,
                root,
                "--legacy-allow",
                "legacy/cursor",
                "--legacy-allow",
                "legacy/*.db",
                "--no-heartbeat",
            )

        self.assertEqual(code, 2, stderr)
        self.assertEqual(self.paths_for(report, "mutable-state"), {"runtime/active.lock"})

    def test_inbox_post_summary_names_mutable_state_only_failure(self):
        args = self.module.parse_args(["--inbox-post"])
        report = {
            "severity_counts": {"warning": 0, "fail": 1},
            "findings": [
                self.module.finding("mutable-state", "runtime/cache.db", "host-local only", "fail")
            ],
        }
        completed = mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(self.module.subprocess, "run", return_value=completed) as run:
            self.module.maybe_post_inbox(args, report)

        command = run.call_args.args[0]
        summary = command[command.index("--summary") + 1]
        self.assertEqual(summary, "vault-lint: 1 mutable-state finding(s)")

    def test_is_recent_warns_on_stat_error(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = self.module.is_recent("missing.md", Path("/tmp/vault-lint-missing"), datetime.now(timezone.utc))

        self.assertFalse(result)
        self.assertIn("warning: light filter stat failed:", stderr.getvalue())

    def test_exit_code_mapping_zero_one_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clean_vault = root / "clean"
            write_file(clean_vault / "00_index" / "clean.md", "# Clean\n")
            clean_code, clean_report, clean_stderr = self.run_json(clean_vault, root / "clean-state", "--no-heartbeat")
            self.assertEqual(clean_code, 0, clean_stderr)
            self.assertEqual(clean_report["severity_counts"]["fail"], 0)

            missing_code, stdout, stderr = self.run_main(
                ["--vault-root", str(root / "missing"), "--json"],
                self.env_for(root / "missing-state"),
            )
            self.assertEqual(missing_code, 1, stderr)
            self.assertIn("vault root not found", stderr)
            self.assertIn("error", json.loads(stdout))

            fail_vault = root / "fail"
            old_fail = write_file(fail_vault / "25_review-pending" / "old.md", "# Old\n")
            old_time = (datetime.now(timezone.utc) - timedelta(days=100)).timestamp()
            os.utime(old_fail, (old_time, old_time))
            fail_code, fail_report, fail_stderr = self.run_json(fail_vault, root / "fail-state", "--no-heartbeat")
            self.assertEqual(fail_code, 2, fail_stderr)
            self.assertEqual(fail_report["severity_counts"]["fail"], 1)

    def test_heartbeat_fail_count_increments_and_resets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fail_vault = root / "fail-vault"
            fail_file = write_file(fail_vault / "25_review-pending" / "old.md", "# Old\n")
            old_time = (datetime.now(timezone.utc) - timedelta(days=100)).timestamp()
            os.utime(fail_file, (old_time, old_time))
            clean_vault = root / "clean-vault"
            write_file(clean_vault / "00_index" / "clean.md", "# Clean\n")
            env = self.env_for(root / "state")

            code, _, stderr = self.run_main(["--vault-root", str(fail_vault), "--json"], env)
            self.assertEqual(code, 2, stderr)
            heartbeat_path = root / "state" / "heartbeats" / "vault-lint-deep.json"
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["job"], "vault-lint-deep")
            self.assertEqual(heartbeat["status"], "fail")
            self.assertEqual(heartbeat["fail_count"], 1)
            self.assertEqual(heartbeat["mode"], "deep")

            code, _, stderr = self.run_main(["--vault-root", str(fail_vault), "--json"], env)
            self.assertEqual(code, 2, stderr)
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["fail_count"], 2)

            code, _, stderr = self.run_main(["--vault-root", str(clean_vault), "--json"], env)
            self.assertEqual(code, 0, stderr)
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["status"], "ok")
            self.assertEqual(heartbeat["fail_count"], 0)

    def test_report_file_and_json_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "00_index" / "clean.md", "# Clean\n")

            code, stdout, stderr = self.run_main(
                ["--vault-root", str(vault), "--json", "--no-heartbeat"],
                self.env_for(root / "state"),
            )

            self.assertEqual(code, 0, stderr)
            report = json.loads(stdout)
            self.assertEqual(report["files_scanned"], 1)
            reports = list((root / "state" / "reports").glob("report-deep-*.json"))
            self.assertEqual(len(reports), 1)
            file_report = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual(file_report["files_scanned"], 1)

    def test_secret_details_are_redacted_in_json_and_report_file(self):
        meili_secret = "aBcDeF1234567890" + "aBcDeF1234567890"  # secret-scan: allow
        tailscale_secret = "ts" + "key-auth-" + "kp1234567890abcdef"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(
                vault / "secrets.env",
                f"MEILI_MASTER_KEY={meili_secret}\nTAILSCALE_AUTHKEY={tailscale_secret}\n",  # secret-scan: allow
            )

            code, stdout, stderr = self.run_main(
                ["--vault-root", str(vault), "--json", "--no-heartbeat"],
                self.env_for(root / "state"),
            )

            self.assertEqual(code, 2, stderr)
            stdout_report = json.loads(stdout)
            reports = list((root / "state" / "reports").glob("report-deep-*.json"))
            self.assertEqual(len(reports), 1)
            file_report = json.loads(reports[0].read_text(encoding="utf-8"))

        for report in (stdout_report, file_report):
            details = [item["detail"] for item in report["findings"] if item["rule"] == "secret"]
            self.assertTrue(any("meili-key" in detail and "aBcD..." in detail for detail in details), details)
            self.assertTrue(any("tailscale-authkey" in detail and "tske..." in detail for detail in details), details)
            self.assertFalse(any(meili_secret in detail for detail in details), details)
            self.assertFalse(any(tailscale_secret in detail for detail in details), details)


if __name__ == "__main__":
    unittest.main()
