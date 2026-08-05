#!/usr/bin/env python3
"""Tests for scripts/content-lint."""

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
CONTENT_LINT_SCRIPT = REPO_ROOT / "scripts" / "content-lint"


def load_module():
    loader = importlib.machinery.SourceFileLoader("content_lint_under_test", str(CONTENT_LINT_SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def write_file(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ContentLintTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.today = datetime.date(2026, 7, 14)

    def run_main(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = self.module.main(list(map(str, args)), today=self.today)
        return code, output.getvalue()

    def test_role_matrix_flags_unapproved_heading_as_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_file(Path(tmp) / "IDENTITY.md", "# Tone\n")
            code, output = self.run_main(path)
            self.assertEqual(code, 1)
            self.assertIn("WARNING", output)
            self.assertIn("outside the role matrix", output)

    def test_role_matrix_accepts_allowed_heading_and_prefixed_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_file(Path(tmp) / "claude-identity.md", "# Values\n")
            code, output = self.run_main(path)
            self.assertEqual(code, 0, output)
            self.assertIn("OK=1", output)

    def test_stale_as_of_date_is_warning_and_recent_date_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            stale = write_file(tmp_path / "notes.md", "Status (as of 2026-01-01)\n")
            fresh = write_file(tmp_path / "fresh.md", "Status (as of 2026-07-01)\n")
            stale_code, stale_output = self.run_main(stale)
            fresh_code, fresh_output = self.run_main(fresh)
            self.assertEqual(stale_code, 1)
            self.assertIn("194 days stale", stale_output)
            self.assertEqual(fresh_code, 0, fresh_output)

    def test_byte_caps_report_violations_and_clean_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            large = write_file(tmp_path / "large.md", "abcdef")
            small = write_file(tmp_path / "small.md", "abc")
            per_file_code, per_file_output = self.run_main("--byte-cap", 5, large)
            total_code, total_output = self.run_main("--total-byte-cap", 5, small, small)
            clean_code, clean_output = self.run_main("--byte-cap", 3, small)
            self.assertEqual(per_file_code, 2)
            self.assertIn("VIOLATION", per_file_output)
            self.assertEqual(total_code, 2)
            self.assertIn("total byte cap 5", total_output)
            self.assertEqual(clean_code, 0, clean_output)

    def test_config_errors_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            target = write_file(tmp_path / "clean.md", "plain text\n")
            missing_keys = write_file(tmp_path / "bad1.yaml", "role_matrix: {}\n")
            non_list_values = write_file(
                tmp_path / "bad2.yaml",
                "role_matrix:\n  IDENTITY.md: values_emotional_guide\nheading_categories:\n  values_emotional_guide: values\n",
            )
            unparsable = write_file(tmp_path / "bad3.yaml", "role_matrix: [unclosed\n")
            empty = write_file(tmp_path / "bad4.yaml", "")
            non_utf8 = tmp_path / "bad5.yaml"
            non_utf8.write_bytes(b"role_matrix:\n  \xff\xfe: []\n")
            for config in (missing_keys, non_list_values, unparsable, empty, non_utf8):
                code, output = self.run_main("--config", config, target)
                self.assertEqual(code, 2, output)
                self.assertIn("ERROR", output)

    def test_custom_config_is_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = write_file(
                tmp_path / "matrix.yaml",
                "role_matrix:\n  NOTES.md:\n    - misc\nheading_categories:\n  misc:\n    - scratch\n",
            )
            flagged = write_file(tmp_path / "NOTES.md", "# Values\n")
            code, output = self.run_main("--config", config, flagged)
            self.assertEqual(code, 1, output)
            self.assertIn("outside the role matrix", output)
            clean_path = write_file(tmp_path / "project-notes.md", "# Scratch\n")
            self.assertEqual(self.run_main("--config", config, clean_path)[0], 0)

    def test_unreadable_and_non_utf8_files_are_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            binary = tmp_path / "binary.md"
            binary.write_bytes(b"\xff\xfe\x00broken")
            missing = tmp_path / "does-not-exist.md"
            binary_code, binary_output = self.run_main(binary)
            missing_code, missing_output = self.run_main(missing)
            self.assertEqual(binary_code, 2)
            self.assertIn("cannot decode UTF-8", binary_output)
            self.assertEqual(missing_code, 2)
            self.assertIn("ERROR", missing_output)

    def test_invalid_as_of_date_is_skipped_and_max_days_flag_is_wired(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            malformed = write_file(tmp_path / "malformed.md", "Broken (as of 2026-13-40)\n")
            recent = write_file(tmp_path / "recent.md", "Status (as of 2026-07-01)\n")
            self.assertEqual(self.run_main(malformed)[0], 0)
            code, output = self.run_main("--as-of-max-days", 7, recent)
            self.assertEqual(code, 1, output)
            self.assertIn("13 days stale", output)

    def test_total_byte_cap_ok_path_reports_within_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            small = write_file(Path(tmp) / "small.md", "abc")
            code, output = self.run_main("--total-byte-cap", 100, small, small)
            self.assertEqual(code, 0, output)
            self.assertIn("within total byte cap 100", output)

    def test_future_as_of_date_is_clean_and_multiple_markers_per_line_all_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            future = write_file(tmp_path / "future.md", "Planned (as of 2027-01-01)\n")
            double = write_file(tmp_path / "double.md", "A (as of 2026-01-01) and B (as of 2026-02-01)\n")
            self.assertEqual(self.run_main(future)[0], 0)
            code, output = self.run_main(double)
            self.assertEqual(code, 1)
            self.assertIn("2026-01-01", output)
            self.assertIn("2026-02-01", output)
            self.assertEqual(output.count("days stale"), 2)

    def test_exit_codes_and_json_payload_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            clean = write_file(tmp_path / "clean.md", "plain text\n")
            warning = write_file(tmp_path / "MEMORY.md", "# Tone\n")
            violation = write_file(tmp_path / "large.md", "abcdef")
            self.assertEqual(self.run_main(clean)[0], 0)
            self.assertEqual(self.run_main(warning)[0], 1)
            self.assertEqual(self.run_main("--byte-cap", 1, violation)[0], 2)

            result = subprocess.run(
                [str(CONTENT_LINT_SCRIPT), "--json", str(warning)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertIn("findings", payload)
            self.assertIn("summary", payload)
            self.assertEqual(set(payload["findings"][0]), {"scope", "severity", "message", "line", "heading"})


if __name__ == "__main__":
    unittest.main()
