#!/usr/bin/env python3
"""Tests for scripts/injection-lint."""

import contextlib
import datetime
import importlib.machinery
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INJECTION_LINT_SCRIPT = REPO_ROOT / "scripts" / "injection-lint"


def load_module():
    loader = importlib.machinery.SourceFileLoader("injection_lint_under_test", str(INJECTION_LINT_SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def write_file(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class InjectionLintTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.platform_caps = {
            "platforms": {
                "openclaw": {
                    "per_file_chars": 1000,
                    "context_per_file_chars": None,
                    "total_chars": 1000,
                }
            },
            "warn_ratio": 0.8,
        }

    def manifest(self, max_chars=100, role="memory"):
        return {
            "agent": "agent-g",
            "platform": "openclaw",
            "workspace": "/tmp/workspace",
            "files": [{"path": "MEMORY.md", "role": role, "max_chars": max_chars}],
            "rot": {"as_of_ttl_days": 90, "applies_to_roles": ["memory", "tools"]},
            "report": {"channel": "hot-inbox", "also": "state-file"},
        }

    def lint_text(self, text, manifest=None):
        manifest = manifest or self.manifest()
        return self.module.lint_manifest(
            manifest,
            self.platform_caps,
            today=datetime.date(2026, 7, 8),
            reader=lambda entry, agent_manifest: text,
        )

    def severities(self, result):
        return [item["severity"] for item in result["findings"]]

    def test_japanese_text_counts_chars_not_bytes(self):
        result = self.lint_text("日本語", self.manifest(max_chars=4))
        memory_findings = [item for item in result["findings"] if item["scope"] == "MEMORY.md"]
        self.assertEqual(memory_findings[0]["severity"], "OK")
        self.assertEqual(memory_findings[0]["chars"], 3)
        self.assertNotEqual(len("日本語".encode("utf-8")), memory_findings[0]["chars"])

    def test_astral_text_counts_utf16_code_units(self):
        result = self.lint_text("😀", self.manifest(max_chars=3))
        memory_findings = [item for item in result["findings"] if item["scope"] == "MEMORY.md"]
        self.assertEqual(memory_findings[0]["severity"], "OK")
        self.assertEqual(memory_findings[0]["chars"], 2)
        self.assertNotEqual(len("😀"), memory_findings[0]["chars"])

    def test_budget_violation_when_chars_exceed_max_chars(self):
        result = self.lint_text("abcdef", self.manifest(max_chars=5))
        self.assertIn("VIOLATION", self.severities(result))
        messages = [item["message"] for item in result["findings"]]
        self.assertTrue(any("exceeds max_chars 5" in message for message in messages))

    def test_platform_cap_warning_boundary(self):
        platform_caps = {
            "platforms": {"openclaw": {"per_file_chars": 10, "context_per_file_chars": None, "total_chars": 100}},
            "warn_ratio": 0.8,
        }
        under = self.module.lint_manifest(
            self.manifest(max_chars=10),
            platform_caps,
            today=datetime.date(2026, 7, 8),
            reader=lambda entry, agent_manifest: "x" * 7,
        )
        at = self.module.lint_manifest(
            self.manifest(max_chars=10),
            platform_caps,
            today=datetime.date(2026, 7, 8),
            reader=lambda entry, agent_manifest: "x" * 8,
        )
        over = self.module.lint_manifest(
            self.manifest(max_chars=10),
            platform_caps,
            today=datetime.date(2026, 7, 8),
            reader=lambda entry, agent_manifest: "x" * 9,
        )

        self.assertNotIn("WARNING", [item["severity"] for item in under["findings"] if item["scope"] == "MEMORY.md"])
        self.assertIn("WARNING", [item["severity"] for item in at["findings"] if item["scope"] == "MEMORY.md"])
        self.assertIn("WARNING", [item["severity"] for item in over["findings"] if item["scope"] == "MEMORY.md"])

    def test_missing_file_is_error_finding(self):
        manifest = self.manifest()
        entry = manifest["files"][0]
        result = self.module.lint_manifest(
            manifest,
            self.platform_caps,
            today=datetime.date(2026, 7, 8),
            reader=lambda unused_entry, unused_manifest: (_ for _ in ()).throw(
                self.module.TargetReadError(f"{entry['path']}: No such file or directory")
            ),
        )
        self.assertIn("ERROR", self.severities(result))
        self.assertIn("No such file or directory", result["findings"][0]["message"])

    def test_ssh_failure_is_error_finding(self):
        original_run = self.module.subprocess.run
        manifest = self.manifest()
        manifest["host"] = "user@example.com"

        def fake_run(args, stdout, stderr, check, timeout):
            self.assertEqual(
                args,
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=10",
                    "--",
                    "user@example.com",
                    "cat -- /tmp/workspace/MEMORY.md",
                ],
            )
            self.assertEqual(timeout, 30)
            return subprocess.CompletedProcess(args, 255, stdout=b"", stderr=b"host unreachable")

        self.module.subprocess.run = fake_run
        try:
            result = self.module.lint_manifest(
                manifest,
                self.platform_caps,
                today=datetime.date(2026, 7, 8),
            )
        finally:
            self.module.subprocess.run = original_run

        self.assertIn("ERROR", self.severities(result))
        self.assertIn("host unreachable", result["findings"][0]["message"])

    def test_rot_expiry_boundary(self):
        today = datetime.date(2026, 7, 8)
        text = "\n".join(
            [
                f"fresh (as of {(today - datetime.timedelta(days=89)).isoformat()})",
                f"boundary （as of {(today - datetime.timedelta(days=90)).isoformat()}）",
                f"stale (as of {(today - datetime.timedelta(days=91)).isoformat()})",
            ]
        )
        result = self.module.lint_manifest(
            self.manifest(max_chars=1000),
            self.platform_caps,
            today=today,
            reader=lambda entry, agent_manifest: text,
        )
        stale_findings = [item for item in result["findings"] if item.get("stale_dates")]
        self.assertEqual(len(stale_findings), 1)
        self.assertEqual(stale_findings[0]["stale_dates"], [{"line": 3, "date": "2026-04-08"}])

    def test_bool_max_chars_rejected(self):
        with self.assertRaises(self.module.InjectionLintError):
            self.module.lint_manifest(self.manifest(max_chars=True), self.platform_caps)

    def test_zero_and_negative_max_chars_rejected(self):
        for max_chars in (0, -1):
            with self.subTest(max_chars=max_chars):
                with self.assertRaises(self.module.InjectionLintError):
                    self.module.lint_manifest(self.manifest(max_chars=max_chars), self.platform_caps)

    def test_warn_ratio_bounds_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_dir = Path(tmp)
            for warn_ratio in (0, -0.1, 1.1):
                with self.subTest(warn_ratio=warn_ratio):
                    write_file(
                        manifest_dir / "platform-caps.yaml",
                        f"""platforms:
  openclaw:
    per_file_chars: 100
    context_per_file_chars: null
    total_chars: 1000
warn_ratio: {warn_ratio}
""",
                    )
                    with self.assertRaises(self.module.InjectionLintError):
                        self.module.load_platform_caps(manifest_dir)

    def test_fullwidth_as_of_date_warns_without_crashing(self):
        result = self.lint_text("fact (As  Of ２０２６-０７-０８)")
        messages = [item["message"] for item in result["findings"]]
        self.assertTrue(any("unparseable as-of date" in message for message in messages))
        self.assertFalse(any(item.get("stale_dates") for item in result["findings"]))

    def test_platform_hard_cap_violation(self):
        platform_caps = {
            "platforms": {"openclaw": {"per_file_chars": 10, "context_per_file_chars": None, "total_chars": 100}},
            "warn_ratio": 0.8,
        }
        result = self.module.lint_manifest(
            self.manifest(max_chars=10),
            platform_caps,
            today=datetime.date(2026, 7, 8),
            reader=lambda entry, agent_manifest: "x" * 11,
        )
        platform_findings = [item for item in result["findings"] if item.get("platform_cap_chars") == 10]
        self.assertEqual(platform_findings[0]["severity"], "VIOLATION")
        self.assertIn("exceeds platform cap", platform_findings[0]["message"])

    def test_declared_file_budget_cannot_exceed_platform_cap(self):
        platform_caps = {
            "platforms": {"openclaw": {"per_file_chars": 10, "context_per_file_chars": None, "total_chars": 100}},
            "warn_ratio": 0.8,
        }
        with self.assertRaises(self.module.InjectionLintError):
            self.module.lint_manifest(self.manifest(max_chars=11), platform_caps)

    def test_own_budget_warning_boundary(self):
        result = self.lint_text("x" * 8, self.manifest(max_chars=10))
        own_budget = [item for item in result["findings"] if item.get("max_chars") == 10]
        self.assertEqual(own_budget[0]["severity"], "WARNING")
        self.assertIn("approaching max_chars", own_budget[0]["message"])

    def test_shared_file_excluded_from_total(self):
        manifest = self.manifest(max_chars=100)
        manifest["files"] = [
            {"path": "MEMORY.md", "role": "memory", "max_chars": 100},
            {"path": "shared.md", "role": "memory", "max_chars": 100, "shared": True},
        ]
        platform_caps = {
            "platforms": {"openclaw": {"per_file_chars": 100, "context_per_file_chars": None, "total_chars": 10}},
            "warn_ratio": 0.8,
        }
        result = self.module.lint_manifest(
            manifest,
            platform_caps,
            today=datetime.date(2026, 7, 8),
            reader=lambda entry, agent_manifest: "x" * (7 if entry["path"] == "shared.md" else 6),
        )
        total = [item for item in result["findings"] if item["scope"] == "total"][0]
        self.assertEqual(total["severity"], "OK")
        self.assertEqual(total["chars"], 6)
        self.assertIn("excluded 1 shared file(s) from total", total["message"])

    def test_all_with_zero_agent_manifests_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_dir = Path(tmp)
            state_dir = manifest_dir / "state"
            write_file(
                manifest_dir / "platform-caps.yaml",
                """platforms:
  openclaw:
    per_file_chars: 100
    context_per_file_chars: null
    total_chars: 1000
warn_ratio: 0.8
""",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = self.module.main(
                    ["--all", "--json", "--manifest-dir", str(manifest_dir)],
                    today=datetime.date(2026, 7, 8),
                    output_state_dir=state_dir,
                )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["exit_code"], 2)
            self.assertIn("no agent manifests found", payload["error"])

    def test_manifest_path_with_shell_metachar_rejected_before_read(self):
        manifest = self.manifest()
        manifest["files"][0]["path"] = "foo.md; rm -rf /"
        with self.assertRaises(self.module.InjectionLintError):
            self.module.lint_manifest(
                manifest,
                self.platform_caps,
                reader=lambda entry, agent_manifest: self.fail("reader should not be called"),
            )

    def test_agent_traversal_name_rejected(self):
        manifest = self.manifest()
        manifest["agent"] = "../agent-g"
        with self.assertRaises(self.module.InjectionLintError):
            self.module.lint_manifest(manifest, self.platform_caps)

    def test_oversized_content_is_error_finding(self):
        result = self.module.lint_manifest(
            self.manifest(max_chars=100),
            self.platform_caps,
            today=datetime.date(2026, 7, 8),
            reader=lambda entry, agent_manifest: "x" * (self.module.MAX_CONTENT_BYTES + 1),
        )
        self.assertIn("ERROR", self.severities(result))
        self.assertIn("file too large to lint", result["findings"][0]["message"])

    def test_all_isolates_broken_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_dir = tmp_path / "manifests"
            state_dir = tmp_path / "state"
            write_file(
                manifest_dir / "platform-caps.yaml",
                """platforms:
  openclaw:
    per_file_chars: 100
    context_per_file_chars: 100
    total_chars: 1000
warn_ratio: 0.8
""",
            )
            target = write_file(tmp_path / "workspace" / "MEMORY.md", "small\n")
            write_file(
                manifest_dir / "agent-g.yaml",
                f"""agent: agent-g
platform: openclaw
workspace: {target.parent}
files:
  - path: MEMORY.md
    role: memory
    max_chars: 100
rot:
  as_of_ttl_days: 90
  applies_to_roles: [memory]
report:
  channel: hot-inbox
  also: state-file
""",
            )
            write_file(
                manifest_dir / "broken.yaml",
                """agent: broken
platform: openclaw
workspace: /tmp
""",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = self.module.main(
                    ["--all", "--json", "--manifest-dir", str(manifest_dir)],
                    today=datetime.date(2026, 7, 8),
                    output_state_dir=state_dir,
                )

            self.assertEqual(exit_code, 2)
            payload = json.loads(stdout.getvalue())
            agents = {item["agent"]: item for item in payload["agents"]}
            self.assertIn("agent-g", agents)
            self.assertIn("broken", agents)
            self.assertEqual(agents["agent-g"]["summary"]["ERROR"], 0)
            self.assertEqual(agents["broken"]["summary"]["ERROR"], 1)
            self.assertTrue((state_dir / "agent-g-latest.json").exists())
            self.assertTrue((state_dir / "broken-latest.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
