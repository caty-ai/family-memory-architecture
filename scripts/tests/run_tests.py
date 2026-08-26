#!/usr/bin/env python3
"""Stdlib unittest runner for Issue #2 scripts."""

import hashlib
import importlib.machinery
import importlib.util
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import test_content_lint
import test_injection_lint
import test_model_catalog


REPO_ROOT = Path(__file__).resolve().parents[2]
INJECTION_SCRIPT = REPO_ROOT / "scripts" / "injection-budget-check"
OVERLAP_SCRIPT = REPO_ROOT / "scripts" / "overlap-lint"
HOT_INBOX_POST_SCRIPT = REPO_ROOT / "scripts" / "hot-inbox-post"
FAMILY_HOT_GENERATE_SCRIPT = REPO_ROOT / "scripts" / "family-hot-generate"
FAMILY_HOT_LINT_SCRIPT = REPO_ROOT / "scripts" / "family-hot-lint"
FAMILY_HOT_READ_SCRIPT = REPO_ROOT / "scripts" / "family-hot-read"


def write_file(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ScriptTests(unittest.TestCase):
    def run_script(self, script, *args, env=None):
        return subprocess.run(
            [sys.executable, str(script), *map(str, args)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )

    def manifest_text(self, source_body, target=1000):
        return f"""# test manifest
version: 1
agent: agent-a
generated_at: "2026-07-04"
target_total_bytes: {target}

sources:
{source_body}
"""

    def test_manifest_parse_happy_path_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_file = write_file(tmp_path / "claude.md", "small fixed source\n")
            manifest = write_file(
                tmp_path / "manifest.yaml",
                self.manifest_text(
                    f"""  - id: agent-a
    path: "{source_file}"
    kind: hand-edited
    max_bytes: 100
"""
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("agent-a", result.stdout)
            self.assertIn("verdict OK exit 0", result.stdout)

    def test_malformed_manifest_missing_kind_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_file = write_file(tmp_path / "claude.md", "small fixed source\n")
            manifest = write_file(
                tmp_path / "manifest.yaml",
                self.manifest_text(
                    f"""  - id: agent-a
    path: "{source_file}"
    max_bytes: 100
"""
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("missing required kind", result.stderr)

    def test_hand_edited_source_over_cap_blocks_with_trim_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_file = write_file(tmp_path / "claude.md", "x" * 20)
            manifest = write_file(
                tmp_path / "manifest.yaml",
                self.manifest_text(
                    f"""  - id: claude-md-user
    path: "{source_file}"
    kind: hand-edited
    max_bytes: 5
"""
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            combined = result.stdout + result.stderr
            self.assertEqual(result.returncode, 2, combined)
            self.assertIn("claude-md-user", combined)
            self.assertIn("trim", combined)

    def test_dynamic_no_path_without_measured_is_unmeasured_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_file(
                Path(tmp) / "manifest.yaml",
                self.manifest_text(
                    """  - id: dyn
    kind: dynamic
    max_bytes: 50
    measure_hint: "count the dynamic hook output"
"""
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("UNMEASURED", result.stdout)
            self.assertIn("count the dynamic hook output", result.stdout)

    def test_measured_dynamic_value_is_applied_to_cap_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_file(
                Path(tmp) / "manifest.yaml",
                self.manifest_text(
                    """  - id: dyn
    kind: dynamic
    max_bytes: 10
    measure_hint: "count the dynamic hook output"
"""
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest, "--measured", "dyn=12")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("dyn", result.stdout)
            self.assertIn("12", result.stdout)
            self.assertIn("WARNING", result.stdout)
            self.assertIn("warning only", result.stdout)

    def test_unknown_measured_id_warns_without_changing_clean_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_file(
                Path(tmp) / "manifest.yaml",
                self.manifest_text(
                    """  - id: dyn
    kind: dynamic
    max_bytes: 10
    measure_hint: "count the dynamic hook output"
"""
                ),
            )

            result = self.run_script(
                INJECTION_SCRIPT,
                "--manifest",
                manifest,
                "--measured",
                "dyn=8",
                "--measured",
                "bogus=123",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Warning: --measured specified unknown source id(s): bogus", result.stderr)
            self.assertIn("verdict OK exit 0", result.stdout)

    def test_dynamic_source_with_segment_keys_is_manifest_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_file(
                Path(tmp) / "manifest.yaml",
                self.manifest_text(
                    """  - id: dyn-segmented
    kind: dynamic
    max_bytes: 10
    segment_boundary: "MARKERTEXT"
    enforced_segment: after
    max_bytes_enforced_segment: 5
"""
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("Source 'dyn-segmented' has kind: dynamic", result.stderr)
            self.assertIn("segment_boundary, enforced_segment, max_bytes_enforced_segment", result.stderr)
            self.assertIn("dynamic sources cannot be segmented", result.stderr)

    def test_tilde_manifest_path_expands_to_home_for_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_home = tmp_path / "home"
            source_file = write_file(fake_home / "fixture" / "source.md", "home bytes\n")
            manifest = write_file(
                tmp_path / "manifest.yaml",
                self.manifest_text(
                    """  - id: home-source
    path: "~/fixture/source.md"
    kind: hand-edited
    max_bytes: 100
"""
                ),
            )
            env = os.environ.copy()
            env["HOME"] = str(fake_home)

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("home-source", result.stdout)
            self.assertIn(str(len(source_file.read_bytes())), result.stdout)
            self.assertNotIn("missing", result.stdout + result.stderr)

    def test_segmented_source_under_enforced_segment_cap_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_file = write_file(tmp_path / "claude.md", "MARKERTEXTabcde")
            manifest = write_file(
                tmp_path / "manifest.yaml",
                self.manifest_text(
                    f"""  - id: segmented
    path: "{source_file}"
    kind: hand-edited
    max_bytes: 100
    segment_boundary: "MARKERTEXT"
    enforced_segment: after
    max_bytes_enforced_segment: 10
"""
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("segmented", result.stdout)
            self.assertIn("before=10 after=5", result.stdout)
            self.assertNotIn("BLOCKING", result.stdout)

    def test_segmented_source_over_enforced_segment_cap_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_file = write_file(tmp_path / "claude.md", "MARKERTEXT" + ("x" * 12))
            manifest = write_file(
                tmp_path / "manifest.yaml",
                self.manifest_text(
                    f"""  - id: segmented
    path: "{source_file}"
    kind: hand-edited
    max_bytes: 100
    segment_boundary: "MARKERTEXT"
    enforced_segment: after
    max_bytes_enforced_segment: 10
"""
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            combined = result.stdout + result.stderr
            self.assertEqual(result.returncode, 2, combined)
            self.assertIn("after segment", combined)
            self.assertIn("trim", combined)

    def test_segmented_source_missing_boundary_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_file = write_file(tmp_path / "claude.md", "no marker here")
            manifest = write_file(
                tmp_path / "manifest.yaml",
                self.manifest_text(
                    f"""  - id: segmented
    path: "{source_file}"
    kind: hand-edited
    max_bytes: 100
    segment_boundary: "MARKERTEXT"
    enforced_segment: after
    max_bytes_enforced_segment: 10
"""
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            combined = result.stdout + result.stderr
            self.assertEqual(result.returncode, 2, combined)
            self.assertIn("segment_boundary", combined)
            self.assertIn("not found", combined)
            self.assertIn("manifest/file mismatch", combined)

    def test_alert_only_over_cap_warns_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_file = write_file(tmp_path / "claude.md", "x" * 12)
            manifest = write_file(
                tmp_path / "manifest.yaml",
                self.manifest_text(
                    f"""  - id: alert-source
    path: "{source_file}"
    kind: hand-edited
    enforcement: alert-only
    max_bytes: 10
"""
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("alert-source", result.stdout)
            self.assertIn("WARNING", result.stdout)
            self.assertIn("warning only", result.stdout)

    def test_unknown_flat_string_source_field_is_tolerated(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_file = write_file(tmp_path / "claude.md", "small fixed source\n")
            manifest = write_file(
                tmp_path / "manifest.yaml",
                self.manifest_text(
                    f"""  - id: agent-a
    path: "{source_file}"
    kind: hand-edited
    max_bytes: 100
    future_field: "some text"
"""
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("verdict OK exit 0", result.stdout)

    def test_generated_over_cap_is_generator_bug_exit_two(self):
        # GLM impl-review M1: generated over cap must stay exit 2.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_file = write_file(tmp_path / "hot.md", "x" * 50 + "\n")
            manifest = write_file(
                tmp_path / "manifest.yaml",
                self.manifest_text(
                    f"""  - id: hot
    path: "{source_file}"
    kind: generated
    max_bytes: 10
"""
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("generator bug", result.stdout)

    def test_generated_under_cap_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_file = write_file(tmp_path / "hot.md", "small\n")
            manifest = write_file(
                tmp_path / "manifest.yaml",
                self.manifest_text(
                    f"""  - id: hot
    path: "{source_file}"
    kind: generated
    max_bytes: 100
"""
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_aggregate_over_target_warns_without_blocking(self):
        # GLM impl-review M2: per-source OK but sum > target_total_bytes -> exit 1.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_a = write_file(tmp_path / "a.md", "x" * 30)
            file_b = write_file(tmp_path / "b.md", "y" * 30)
            manifest = write_file(
                tmp_path / "manifest.yaml",
                self.manifest_text(
                    f"""  - id: agent-a
    path: "{file_a}"
    kind: hand-edited
    max_bytes: 100
  - id: beta
    path: "{file_b}"
    kind: hand-edited
    max_bytes: 100
""",
                    target=50,
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("verdict WARNING exit 1", result.stdout)

    def test_aggregate_warning_does_not_mask_blocking_source(self):
        # GLM impl-review M2: blocking source + aggregate over -> still exit 2.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_a = write_file(tmp_path / "a.md", "x" * 30)
            file_b = write_file(tmp_path / "b.md", "y" * 30)
            manifest = write_file(
                tmp_path / "manifest.yaml",
                self.manifest_text(
                    f"""  - id: agent-a
    path: "{file_a}"
    kind: hand-edited
    max_bytes: 10
  - id: beta
    path: "{file_b}"
    kind: hand-edited
    max_bytes: 100
""",
                    target=50,
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_segmented_whole_file_over_but_enforced_segment_under_warns_only(self):
        # GLM impl-review M3: whole-file cap is warning-only for segmented sources
        # (protects the manifest's intent: OMC-region growth must not block Agent A).
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            content = "HEAD MARKERTEXT" + "x" * 50
            source_file = write_file(tmp_path / "claude.md", content)
            manifest = write_file(
                tmp_path / "manifest.yaml",
                self.manifest_text(
                    f"""  - id: segmented
    path: "{source_file}"
    kind: hand-edited
    max_bytes: 40
    segment_boundary: "MARKERTEXT"
    enforced_segment: after
    max_bytes_enforced_segment: 60
"""
                ),
            )

            result = self.run_script(INJECTION_SCRIPT, "--manifest", manifest)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("warning only for segmented source", result.stdout)
            self.assertNotIn("BLOCKING", result.stdout)

    def test_overlap_exact_match_across_two_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shared = "Family archive source of truth lives in the memory index."
            claude = write_file(tmp_path / "claude.md", f"- {shared}\n")
            memory = write_file(tmp_path / "memory.md", f"## {shared}\n")

            result = self.run_script(OVERLAP_SCRIPT, "--claude-md", claude, "--memory-md", memory)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("EXACT", result.stdout)
            self.assertIn("claude-md:1", result.stdout)
            self.assertIn("memory-md:1", result.stdout)

    def test_overlap_containment_across_two_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            short = "The calendar archive is authoritative for birthday reminders."
            long = f"Note: {short} Use aliases only in search helpers."
            claude = write_file(tmp_path / "claude.md", short + "\n")
            memory = write_file(tmp_path / "memory.md", long + "\n")

            result = self.run_script(OVERLAP_SCRIPT, "--claude-md", claude, "--memory-md", memory)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("CONTAINS", result.stdout)

    def test_overlap_punctuation_variants_are_detected_as_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            left = "家族アーカイブ・索引（2026）『固定メモリー』は一次情報です。"
            right = "家族アーカイブ索引(2026)固定メモリ-は一次情報です"
            claude = write_file(tmp_path / "claude.md", left + "\n")
            memory = write_file(tmp_path / "memory.md", right + "\n")

            result = self.run_script(OVERLAP_SCRIPT, "--claude-md", claude, "--memory-md", memory)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("EXACT", result.stdout)

    def test_overlap_punctuation_normalization_does_not_merge_different_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            claude = write_file(
                tmp_path / "claude.md",
                "Family archive v1/a requires source labels for every claim.\n",
            )
            memory = write_file(
                tmp_path / "memory.md",
                "Family archive v1a requires source labels for every claim.\n",
            )

            result = self.run_script(OVERLAP_SCRIPT, "--claude-md", claude, "--memory-md", memory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("\nEXACT\n", result.stdout)
            self.assertIn("total overlaps: 0", result.stdout)

    def test_overlap_same_file_duplicates_are_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repeated = "The family archive requires explicit source labels for every claim."
            claude = write_file(tmp_path / "claude.md", repeated + "\n" + repeated + "\n")
            memory = write_file(tmp_path / "memory.md", "short\n")

            result = self.run_script(OVERLAP_SCRIPT, "--claude-md", claude, "--memory-md", memory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("total overlaps: 0", result.stdout)

    def test_overlap_exit_code_not_fooled_by_report_like_content(self):
        # Regression: exit code must come from structural match counts, not from
        # string-matching the rendered report ("total overlaps: 0" inside a unit).
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            poisoned = "This duplicated line contains total overlaps: 0 as literal text."
            claude = write_file(tmp_path / "claude.md", poisoned + "\n")
            memory = write_file(tmp_path / "memory.md", poisoned + "\n")

            result = self.run_script(OVERLAP_SCRIPT, "--claude-md", claude, "--memory-md", memory)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("EXACT", result.stdout)

    def test_overlap_without_supermemory_prints_skipped_and_still_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            claude = write_file(tmp_path / "claude.md", "Claude policy mentions compact session routing only.\n")
            memory = write_file(tmp_path / "memory.md", "Memory index records durable source locations separately.\n")

            result = self.run_script(OVERLAP_SCRIPT, "--claude-md", claude, "--memory-md", memory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("SKIPPED: supermemory export not provided", result.stdout)

    def make_family_hot_bytes(self, body_bytes):
        marker = b"<!-- GENERATED-FILE: family-hot.md; DO NOT EDIT BY HAND -->\n"
        placeholder_meta = (
            b"<!-- generator: family-hot-generator v0; sources_sha256: "
            + (b"0" * 64)
            + b"; body_sha256: "
            + (b"0" * 64)
            + b" -->\n"
        )
        placeholder = marker + placeholder_meta + body_bytes
        lines = placeholder.splitlines(keepends=True)
        body_sha256 = hashlib.sha256(b"".join(lines[:1] + lines[2:])).hexdigest()
        meta = (
            b"<!-- generator: family-hot-generator v0; sources_sha256: "
            + (b"0" * 64)
            + b"; body_sha256: "
            + body_sha256.encode("ascii")
            + b" -->\n"
        )
        return marker + meta + body_bytes

    def load_script_module(self, name, script):
        loader = importlib.machinery.SourceFileLoader(name, str(script))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def load_hot_inbox_post_module(self):
        return self.load_script_module("hot_inbox_post", HOT_INBOX_POST_SCRIPT)

    def test_family_hot_secret_patterns_stay_in_sync(self):
        modules = [
            self.load_script_module("hot_inbox_post_sync", HOT_INBOX_POST_SCRIPT),
            self.load_script_module("family_hot_generate_sync", FAMILY_HOT_GENERATE_SCRIPT),
            self.load_script_module("family_hot_lint_sync", FAMILY_HOT_LINT_SCRIPT),
        ]
        patterns = [[pattern.pattern for pattern in module.SECRET_PATTERNS] for module in modules]
        self.assertEqual(patterns[0], patterns[1])
        self.assertEqual(patterns[0], patterns[2])
        self.assertIn(r"github_pat_[A-Za-z0-9_]{8,}", patterns[0])
        self.assertIn(r"AIza[A-Za-z0-9_-]{8,}", patterns[0])
        self.assertIn(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{8,}", patterns[0])
        # GLM: kind/class matrix must stay in sync across writer/generator/lint like the secret list
        matrices = [module.KIND_CLASS_ALLOWED for module in modules]
        self.assertEqual(matrices[0], matrices[1])
        self.assertEqual(matrices[0], matrices[2])

    def test_hot_inbox_post_writes_valid_decision_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "hot-inbox"
            result = self.run_script(
                HOT_INBOX_POST_SCRIPT,
                "--kind",
                "decision",
                "--title",
                "Phase A merged",
                "--summary",
                "Phase A merged for SessionStart.",
                "--canonical-path",
                "family-vault/30_decisions/phase-a.md",
                "--inbox-dir",
                inbox,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            files = list(inbox.glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertRegex(
                files[0].name,
                r"^\d{8}T\d{6}Z__agent-a__decision__phase-a-merged__[0-9a-f]{8}\.json$",
            )
            data = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], "family-hot-event/v0")
            self.assertEqual(data["event_id"], files[0].stem)
            self.assertEqual(data["created_by"], "agent-a")
            self.assertEqual(data["class"], 5)
            self.assertEqual(data["kind"], "decision")
            self.assertEqual(data["title"], "Phase A merged")
            self.assertEqual(data["summary"], "Phase A merged for SessionStart.")
            self.assertEqual(data["canonical_path"], "family-vault/30_decisions/phase-a.md")
            self.assertEqual(data["owner"], "agent-a")
            self.assertEqual(data["priority"], "P2")
            self.assertEqual(data["related"], [])

    def test_hot_inbox_post_create_once_collision_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = self.load_hot_inbox_post_module()
            fixed_now = datetime(2026, 7, 4, 9, 15, tzinfo=timezone.utc)
            args = module.parse_args(
                [
                    "--kind",
                    "decision",
                    "--title",
                    "Phase A merged",
                    "--summary",
                    "Phase A merged for SessionStart.",
                    "--canonical-path",
                    "family-vault/30_decisions/phase-a.md",
                    "--inbox-dir",
                    tmp,
                ]
            )
            event = module.build_event(args, now=fixed_now, uuid8="a1b2c3d4")
            destination = Path(tmp) / f"{event['event_id']}.json"
            original = "keep this existing file\n"
            destination.write_text(original, encoding="utf-8")

            # Deterministic collision: pre-create the exact event_id path, then call the atomic writer.
            with self.assertRaises(module.HotInboxError):
                module.write_event_file(tmp, event)
            self.assertEqual(destination.read_text(encoding="utf-8"), original)

    def test_hot_inbox_post_class_five_requires_vault_path_or_promotion_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_script(
                HOT_INBOX_POST_SCRIPT,
                "--kind",
                "decision",
                "--title",
                "Needs promotion",
                "--summary",
                "Decision lacks canonical vault path.",
                "--canonical-url",
                "https://example.com/decision",
                "--inbox-dir",
                tmp,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("--promotion-pending", result.stderr)
            self.assertIn("--canonical-url with github.com host", result.stderr)

    def test_hot_inbox_post_expire_target_shape_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = self.run_script(
                HOT_INBOX_POST_SCRIPT,
                "--kind", "expire",
                "--agent", "agent-a",
                "--target-event-id", "not-a-valid-event-id",
                "--inbox-dir", tmp,
            )
            self.assertEqual(bad.returncode, 2, bad.stdout + bad.stderr)
            self.assertIn("target", bad.stderr.lower())
            good = self.run_script(
                HOT_INBOX_POST_SCRIPT,
                "--kind", "expire",
                "--agent", "agent-a",
                "--target-event-id", "20260704T091500Z__agent-a__decision__phase-a-merged__a1b2c3d4",
                "--inbox-dir", tmp,
            )
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)

    def test_hot_inbox_post_class_overrides_reject_generator_mismatches(self):
        module = self.load_hot_inbox_post_module()
        fixed_now = datetime(2026, 7, 4, 9, 15, tzinfo=timezone.utc)

        class_nine_args = module.parse_args(
            [
                "--kind",
                "decision",
                "--class-num",
                "9",
                "--title",
                "Temporary decision note",
                "--summary",
                "Decision routed into class nine.",
                "--canonical-path",
                "family-vault/notes/temporary.md",
            ]
        )
        with self.assertRaisesRegex(module.HotInboxError, "kind decision is not valid for class 9"):
            module.build_event(class_nine_args, now=fixed_now, uuid8="a1b2c3d4")

        too_late_args = module.parse_args(
            [
                "--kind",
                "caution",
                "--class-num",
                "9",
                "--title",
                "Too long",
                "--summary",
                "Class nine cap must apply at the boundary.",
                "--canonical-url",
                "https://github.com/org/repo/issues/20",
                "--expires-at",
                "2026-07-18T09:15:01Z",
            ]
        )
        with self.assertRaisesRegex(module.HotInboxError, "14 days"):
            module.build_event(too_late_args, now=fixed_now, uuid8="a1b2c3d4")

        class_five_args = module.parse_args(
            [
                "--kind",
                "caution",
                "--class-num",
                "5",
                "--title",
                "Caution promoted to class five",
                "--summary",
                "Class five rules must apply despite caution kind.",
                "--canonical-url",
                "https://github.com/org/repo/issues/20",
            ]
        )
        with self.assertRaisesRegex(module.HotInboxError, "kind caution is not valid for class 5"):
            module.build_event(class_five_args, now=fixed_now, uuid8="a1b2c3d4")

    def test_hot_inbox_post_class_nine_expiry_boundary(self):
        module = self.load_hot_inbox_post_module()
        fixed_now = datetime(2026, 7, 4, 9, 15, tzinfo=timezone.utc)

        exact_args = module.parse_args(
            [
                "--kind",
                "caution",
                "--title",
                "Exact boundary",
                "--summary",
                "Fourteen days exactly is valid.",
                "--canonical-url",
                "https://github.com/org/repo/issues/20",
                "--expires-at",
                "2026-07-18T09:15:00Z",
            ]
        )
        event = module.build_event(exact_args, now=fixed_now, uuid8="a1b2c3d4")
        self.assertEqual(event["expires_at"], "2026-07-18T09:15:00Z")

        late_args = module.parse_args(
            [
                "--kind",
                "caution",
                "--title",
                "One second late",
                "--summary",
                "Fourteen days plus one second is invalid.",
                "--canonical-url",
                "https://github.com/org/repo/issues/20",
                "--expires-at",
                "2026-07-18T09:15:01Z",
            ]
        )
        with self.assertRaisesRegex(module.HotInboxError, "14 days"):
            module.build_event(late_args, now=fixed_now, uuid8="a1b2c3d4")

    def test_hot_inbox_post_class_five_boundary_strict_canonical_pointer(self):
        module = self.load_hot_inbox_post_module()
        fixed_now = datetime(2026, 7, 4, 9, 15, tzinfo=timezone.utc)

        for bad_path in (
            "family-vault/30_decisions_evil/foo.md",
            "foo/30_decisions_evil/bar.md",
            "/tmp/20_projects/x.md",
            "other-vault/30_decisions/x.md",
            "family-vault/30_decisions/../x.md",
        ):
            args = module.parse_args(
                [
                    "--kind",
                    "decision",
                    "--title",
                    "Boundary path",
                    "--summary",
                    "Path segment must match exactly.",
                    "--canonical-path",
                    bad_path,
                ]
            )
            with self.subTest(bad_path=bad_path):
                with self.assertRaisesRegex(module.HotInboxError, "class 5"):
                    module.build_event(args, now=fixed_now, uuid8="a1b2c3d4")

        for bad_url in (
            "https://github.com.evil/x",
            "https://evil-github.com/x",
            "https://notgithub.com/x",
            # GLM N2: classic userinfo evasion — hostname resolves to evil.com, must be rejected
            "https://github.com@evil.com/x",
        ):
            args = module.parse_args(
                [
                    "--kind",
                    "decision",
                    "--title",
                    "Boundary url",
                    "--summary",
                    "GitHub host must match exactly.",
                    "--canonical-url",
                    bad_url,
                    "--promotion-pending",
                ]
            )
            with self.subTest(bad_url=bad_url):
                with self.assertRaisesRegex(module.HotInboxError, "--canonical-url with github.com host"):
                    module.build_event(args, now=fixed_now, uuid8="a1b2c3d4")

        for args_list in (
            [
                "--kind",
                "decision",
                "--title",
                "Vault path",
                "--summary",
                "Exact segment accepted.",
                "--canonical-path",
                "family-vault/30_decisions/x.md",
            ],
            [
                "--kind",
                "decision",
                "--title",
                "GitHub URL",
                "--summary",
                "GitHub host accepted.",
                "--canonical-url",
                "https://github.com/org/repo",
                "--promotion-pending",
            ],
            [
                "--kind",
                "decision",
                "--title",
                "GitHub URL with query",
                "--summary",
                "Query and fragment do not affect host acceptance.",
                "--canonical-url",
                "https://github.com/org/repo?tab=readme#anchor",
                "--promotion-pending",
            ],
        ):
            args = module.parse_args(args_list)
            event = module.build_event(args, now=fixed_now, uuid8="a1b2c3d4")
            self.assertEqual(event["class"], 5)

    def test_hot_inbox_post_missing_title_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_script(
                HOT_INBOX_POST_SCRIPT,
                "--kind",
                "decision",
                "--summary",
                "No title given.",
                "--canonical-path",
                "family-vault/30_decisions/x.md",
                "--inbox-dir",
                tmp,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("require --title", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_hot_inbox_post_non_caution_expires_at_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_script(
                HOT_INBOX_POST_SCRIPT,
                "--kind",
                "decision",
                "--title",
                "Bad expiry",
                "--summary",
                "Garbage expiry must be rejected.",
                "--canonical-path",
                "family-vault/30_decisions/x.md",
                "--expires-at",
                "garbage",
                "--inbox-dir",
                tmp,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual(list(Path(tmp).glob("*.json")), [])

            too_late = (datetime.now(timezone.utc) + timedelta(days=31)).isoformat().replace("+00:00", "Z")
            result = self.run_script(
                HOT_INBOX_POST_SCRIPT,
                "--kind",
                "decision",
                "--title",
                "Too late",
                "--summary",
                "Non-class-nine expiry keeps the thirty-day sanity cap.",
                "--canonical-path",
                "family-vault/30_decisions/x.md",
                "--expires-at",
                too_late,
                "--inbox-dir",
                tmp,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("30 days", result.stderr)

            future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat().replace("+00:00", "Z")
            result = self.run_script(
                HOT_INBOX_POST_SCRIPT,
                "--kind",
                "decision",
                "--title",
                "Valid expiry",
                "--summary",
                "Valid future expiry is normalized.",
                "--canonical-path",
                "family-vault/30_decisions/x.md",
                "--expires-at",
                future,
                "--inbox-dir",
                tmp,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(next(Path(tmp).glob("*.json")).read_text(encoding="utf-8"))
            self.assertTrue(data["expires_at"].endswith("Z"))

    def test_family_hot_read_interop_fixture_with_hardcoded_sha(self):
        # Interop contract regression guard: sha256 computed INDEPENDENTLY of the
        # reader's compute_body_sha256 (body = line 1 + lines 3.., i.e. only the
        # generator-meta line 2 is excluded). If the reader's algorithm drifts,
        # this hardcoded digest stops matching.
        line1 = "<!-- GENERATED-FILE: family-hot.md; DO NOT EDIT BY HAND -->\n"
        body_rest = "## Family Hot\n- [P1] interop fixture — https://example.invalid/x\n"
        hardcoded_sha = "89b6152b6f49957f9a948163255fb54532b8522ec2a08852cb4daba4a11524d5"
        meta = (
            "<!-- generator: family-hot-generator v0; sources_sha256: "
            + "0" * 64
            + "; body_sha256: "
            + hardcoded_sha
            + " -->\n"
        )
        content = line1 + meta + body_rest
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "family-hot.md"
            path.write_text(content, encoding="utf-8")
            result = self.run_script(
                FAMILY_HOT_READ_SCRIPT,
                env=dict(os.environ, FAMILY_HOT_PATH=str(path)),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout, content)

    def test_hot_inbox_post_caution_rejects_past_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            result = self.run_script(
                HOT_INBOX_POST_SCRIPT,
                "--kind",
                "caution",
                "--title",
                "Already expired",
                "--summary",
                "This caution is already expired.",
                "--canonical-url",
                "https://github.com/caty-ai/family-memory-architecture/issues/5",
                "--expires-at",
                past,
                "--inbox-dir",
                tmp,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("must be in the future", result.stderr)
            self.assertEqual(list(Path(tmp).glob("*.json")), [])

    def test_hot_inbox_post_caution_defaults_and_rejects_long_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.now(timezone.utc)
            result = self.run_script(
                HOT_INBOX_POST_SCRIPT,
                "--kind",
                "caution",
                "--title",
                "Temporary caution",
                "--summary",
                "Temporary caution for SessionStart.",
                "--canonical-url",
                "https://github.com/caty-ai/family-memory-architecture/issues/5",
                "--inbox-dir",
                tmp,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(next(Path(tmp).glob("*.json")).read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
            expected = now + timedelta(days=7)
            self.assertLess(abs((expires_at - expected).total_seconds()), 120)
            self.assertIn("defaulting to 7 days", result.stderr)

            too_late = (datetime.now(timezone.utc) + timedelta(days=14, seconds=1)).isoformat().replace("+00:00", "Z")
            result = self.run_script(
                HOT_INBOX_POST_SCRIPT,
                "--kind",
                "caution",
                "--title",
                "Too long",
                "--summary",
                "This expiry is too long.",
                "--canonical-url",
                "https://github.com/caty-ai/family-memory-architecture/issues/5",
                "--expires-at",
                too_late,
                "--inbox-dir",
                tmp,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("14 days", result.stderr)

    def test_hot_inbox_post_allowed_pairs_round_trip_through_generator(self):
        allowed = {
            "decision": (5,),
            "project": (2, 3, 6),
            "blocker": (4, 6, 10),
            "caution": (9,),
        }
        with tempfile.TemporaryDirectory() as vault:
            inbox = Path(vault) / "00_index" / "hot-inbox"
            expected_titles = []
            for kind, classes in allowed.items():
                for class_num in classes:
                    title = f"{kind[0]}{class_num}"
                    expected_titles.append(title)
                    args = [
                        "--kind",
                        kind,
                        "--class-num",
                        str(class_num),
                        "--title",
                        title,
                        "--summary",
                        "ok",
                        "--inbox-dir",
                        inbox,
                    ]
                    if kind == "decision":
                        args.extend(["--canonical-path", f"family-vault/30_decisions/{kind[0]}{class_num}.md"])
                    elif kind == "caution":
                        args.extend(
                            [
                                "--canonical-url",
                                "https://github.com/a/b",
                                "--expires-at",
                                (datetime.now(timezone.utc) + timedelta(days=7)).isoformat().replace("+00:00", "Z"),
                            ]
                        )
                    else:
                        args.extend(["--canonical-path", f"family-vault/20_projects/{kind[0]}{class_num}.md"])

                    posted = self.run_script(HOT_INBOX_POST_SCRIPT, *args)
                    self.assertEqual(posted.returncode, 0, posted.stdout + posted.stderr)

            generated = self.run_script(FAMILY_HOT_GENERATE_SCRIPT, "--vault-root", vault)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            self.assertNotIn("skip", generated.stderr)
            text = (Path(vault) / "00_index" / "family-hot.md").read_text(encoding="utf-8")
            for title in expected_titles:
                self.assertIn(title, text)

            linted = self.run_script(FAMILY_HOT_LINT_SCRIPT, "--vault-root", vault)
            self.assertEqual(linted.returncode, 0, linted.stdout + linted.stderr)

        disallowed = [
            ("decision", 9),
            ("caution", 5),
            ("project", 4),
            ("blocker", 5),
        ]
        for kind, class_num in disallowed:
            with self.subTest(kind=kind, class_num=class_num), tempfile.TemporaryDirectory() as tmp:
                result = self.run_script(
                    HOT_INBOX_POST_SCRIPT,
                    "--kind",
                    kind,
                    "--class-num",
                    class_num,
                    "--title",
                    "Bad pair",
                    "--summary",
                    "This pair is not renderable.",
                    "--canonical-url",
                    "https://github.com/caty-ai/family-memory-architecture/issues/4",
                    "--promotion-pending",
                    "--inbox-dir",
                    tmp,
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("not valid for class", result.stderr)

    def test_hot_inbox_post_expire_requires_target_and_writes_expire_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = self.run_script(HOT_INBOX_POST_SCRIPT, "--kind", "expire", "--inbox-dir", tmp)
            self.assertEqual(missing.returncode, 2, missing.stdout + missing.stderr)
            self.assertIn("--target-event-id", missing.stderr)

            malformed = self.run_script(
                HOT_INBOX_POST_SCRIPT,
                "--kind",
                "expire",
                "--target-event-id",
                "not-a-real-id",
                "--inbox-dir",
                tmp,
            )
            self.assertEqual(malformed.returncode, 2, malformed.stdout + malformed.stderr)
            self.assertIn("does not match event_id shape", malformed.stderr)

            result = self.run_script(
                HOT_INBOX_POST_SCRIPT,
                "--kind",
                "expire",
                "--target-event-id",
                "20260704T091500Z__agent-a__decision__phase-a-merged__a1b2c3d4",
                "--inbox-dir",
                tmp,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(next(Path(tmp).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(
                set(data),
                {"schema_version", "event_id", "created_at", "created_by", "kind", "target_event_id"},
            )
            self.assertEqual(data["kind"], "expire")
            self.assertNotIn("class", data)

    def test_hot_inbox_post_secret_scan_nested_dicts_lists_and_new_prefixes(self):
        module = self.load_hot_inbox_post_module()

        with self.assertRaisesRegex(module.HotInboxError, "a\\.b"):
            module.scan_secrets({"a": {"b": "github_pat_" + "x" * 20}})
        with self.assertRaisesRegex(module.HotInboxError, r"a\[0\]\.b"):
            module.scan_secrets({"a": [{"b": "AIza" + "x" * 20}]})
        # GLM N1: a secret smuggled as a dict KEY must be caught, not only values
        with self.assertRaisesRegex(module.HotInboxError, r"\(key\)"):
            module.scan_secrets({"a": {"github_pat_" + "x" * 20: "v"}})

        module.scan_secrets({"a": {"b": "ordinary text"}, "items": [{"summary": "safe"}]})
        # audit F4 regression guard: widened sk- charset must NOT match ordinary prose
        module.scan_secrets({"summary": "task-management plan and risk-analysis for Q3"})
        with self.assertRaises(module.HotInboxError):
            module.scan_secrets({"summary": "token sk-proj-abc123def456"})

    def test_hot_inbox_post_caution_freeze_defaults_three_days_and_explicit_wins(self):
        module = self.load_hot_inbox_post_module()
        fixed_now = datetime(2026, 7, 4, 9, 15, tzinfo=timezone.utc)

        freeze_args = module.parse_args(
            [
                "--kind",
                "caution",
                "--title",
                "Freeze deployment until review",
                "--summary",
                "Temporary operational caution.",
                "--canonical-url",
                "https://github.com/org/repo/issues/20",
            ]
        )
        freeze_stderr = io.StringIO()
        with contextlib.redirect_stderr(freeze_stderr):
            freeze_event = module.build_event(freeze_args, now=fixed_now, uuid8="a1b2c3d4")
        self.assertEqual(freeze_event["expires_at"], "2026-07-07T09:15:00Z")
        self.assertIn("freeze pattern matched", freeze_stderr.getvalue())

        standard_args = module.parse_args(
            [
                "--kind",
                "caution",
                "--title",
                "Temporary caution",
                "--summary",
                "Temporary operational caution.",
                "--canonical-url",
                "https://github.com/org/repo/issues/20",
            ]
        )
        standard_stderr = io.StringIO()
        with contextlib.redirect_stderr(standard_stderr):
            standard_event = module.build_event(standard_args, now=fixed_now, uuid8="a1b2c3d4")
        self.assertEqual(standard_event["expires_at"], "2026-07-11T09:15:00Z")
        self.assertIn("standard default", standard_stderr.getvalue())

        explicit_args = module.parse_args(
            [
                "--kind",
                "caution",
                "--title",
                "Freeze deployment until review",
                "--summary",
                "Explicit expiry wins.",
                "--canonical-url",
                "https://github.com/org/repo/issues/20",
                "--expires-at",
                "2026-07-14T09:15:00Z",
            ]
        )
        explicit_stderr = io.StringIO()
        with contextlib.redirect_stderr(explicit_stderr):
            explicit_event = module.build_event(explicit_args, now=fixed_now, uuid8="a1b2c3d4")
        self.assertEqual(explicit_event["expires_at"], "2026-07-14T09:15:00Z")
        self.assertEqual(explicit_stderr.getvalue(), "")

    def test_hot_inbox_post_secret_scan_rejects_without_echoing_secret(self):
        secret = "ghp_abcdefghi"
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_script(
                HOT_INBOX_POST_SCRIPT,
                "--kind",
                "project",
                "--title",
                "Secret test",
                "--summary",
                f"Do not leak {secret}",
                "--canonical-path",
                "family-vault/20_projects/secret-test.md",
                "--inbox-dir",
                tmp,
            )

            combined = result.stdout + result.stderr
            self.assertEqual(result.returncode, 2, combined)
            self.assertIn("field 'summary'", result.stderr)
            self.assertNotIn(secret, combined)
            self.assertEqual(list(Path(tmp).glob("*.json")), [])

    def test_family_hot_read_missing_file_is_silent_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "family-hot.md"
            result = self.run_script(FAMILY_HOT_READ_SCRIPT, "--path", missing)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout, "")

    def test_family_hot_read_accepts_valid_hash_fixture_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = self.make_family_hot_bytes(b"# Family Hot\n\n- Valid item\n")
            path = Path(tmp) / "family-hot.md"
            path.write_bytes(content)

            result = self.run_script(FAMILY_HOT_READ_SCRIPT, "--path", path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout, content.decode("utf-8"))

    def test_family_hot_read_refuses_tampered_body_with_default_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = self.make_family_hot_bytes(b"# Family Hot\n\n- Valid item\n")
            tampered = content.replace(b"Valid", b"Talid", 1)
            path = Path(tmp) / "family-hot.md"
            path.write_bytes(tampered)

            result = self.run_script(FAMILY_HOT_READ_SCRIPT, "--path", path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("integrity check failed (body-sha256-mismatch)", result.stdout)
            self.assertIn("fallback:", result.stdout)

    def test_family_hot_read_refuses_oversized_file_even_with_valid_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = self.make_family_hot_bytes(("# Family Hot\n" + ("x" * 2100) + "\n").encode("utf-8"))
            self.assertGreater(len(content), 2048)
            path = Path(tmp) / "family-hot.md"
            path.write_bytes(content)

            result = self.run_script(FAMILY_HOT_READ_SCRIPT, "--path", path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("integrity check failed (size-exceeds-2048-bytes)", result.stdout)

    def test_family_hot_read_check_mode_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            missing = self.run_script(FAMILY_HOT_READ_SCRIPT, "--check", "--path", tmp_path / "missing.md")
            self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)

            valid_path = tmp_path / "valid.md"
            content = self.make_family_hot_bytes(b"# Family Hot\n\n- Valid item\n")
            valid_path.write_bytes(content)
            valid = self.run_script(FAMILY_HOT_READ_SCRIPT, "--check", "--path", valid_path)
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
            self.assertEqual(valid.stdout, content.decode("utf-8"))

            invalid_path = tmp_path / "invalid.md"
            invalid_path.write_bytes(content.replace(b"Valid", b"Talid", 1))
            invalid = self.run_script(FAMILY_HOT_READ_SCRIPT, "--check", "--path", invalid_path)
            self.assertEqual(invalid.returncode, 2, invalid.stdout + invalid.stderr)
            self.assertIn("body-sha256-mismatch", invalid.stdout)


if __name__ == "__main__":
    import test_capture_shipper
    import test_backup_dashboard
    import test_fixture_smoke
    import test_family_hot_generate
    import test_hot_inbox_reader
    import test_job_heartbeat
    import test_jobs_framework
    import test_lib_atomic
    import test_meili_ingest
    import test_openclaw_capture
    import test_overlap_lint
    import test_recall
    import test_secret_scan
    import test_suite_census
    import test_vault_lint
    import test_write_guard

    suite = unittest.TestSuite(
        [
            unittest.defaultTestLoader.loadTestsFromTestCase(ScriptTests),
            unittest.defaultTestLoader.loadTestsFromModule(test_backup_dashboard),
            unittest.defaultTestLoader.loadTestsFromModule(test_content_lint),
            unittest.defaultTestLoader.loadTestsFromModule(test_capture_shipper),
            unittest.defaultTestLoader.loadTestsFromModule(test_fixture_smoke),
            unittest.defaultTestLoader.loadTestsFromModule(test_family_hot_generate),
            unittest.defaultTestLoader.loadTestsFromModule(test_hot_inbox_reader),
            unittest.defaultTestLoader.loadTestsFromModule(test_injection_lint),
            unittest.defaultTestLoader.loadTestsFromModule(test_job_heartbeat),
            unittest.defaultTestLoader.loadTestsFromModule(test_jobs_framework),
            unittest.defaultTestLoader.loadTestsFromModule(test_lib_atomic),
            unittest.defaultTestLoader.loadTestsFromModule(test_meili_ingest),
            unittest.defaultTestLoader.loadTestsFromModule(test_model_catalog),
            unittest.defaultTestLoader.loadTestsFromModule(test_openclaw_capture),
            unittest.defaultTestLoader.loadTestsFromModule(test_overlap_lint),
            unittest.defaultTestLoader.loadTestsFromModule(test_recall),
            unittest.defaultTestLoader.loadTestsFromModule(test_secret_scan),
            unittest.defaultTestLoader.loadTestsFromModule(test_suite_census),
            unittest.defaultTestLoader.loadTestsFromModule(test_vault_lint),
            unittest.defaultTestLoader.loadTestsFromModule(test_write_guard),
        ]
    )
    runner = unittest.TextTestRunner(verbosity=2)
    outcome = runner.run(suite)
    passed = outcome.testsRun - len(outcome.failures) - len(outcome.errors) - len(outcome.skipped)
    print(
        f"Final summary: passed={passed} failed={len(outcome.failures)} "
        f"errors={len(outcome.errors)} skipped={len(outcome.skipped)} total={outcome.testsRun}"
    )
    sys.exit(0 if outcome.wasSuccessful() else 1)
