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

    def test_yaml_subset_accepts_realistic_content_config(self):
        parsed = self.module.parse_yaml_subset(
            """# A content-lint role matrix using both supported list forms.
role_matrix:
  IDENTITY.md: [values_emotional_guide, "tone # literal"] # inline comment
  NOTES.md:
    - misc
heading_categories:
  values_emotional_guide:
    - values
    - 'emotional guide'
  misc: [scratch]
"""
        )

        self.assertEqual(
            parsed,
            {
                "role_matrix": {
                    "IDENTITY.md": ["values_emotional_guide", "tone # literal"],
                    "NOTES.md": ["misc"],
                },
                "heading_categories": {
                    "values_emotional_guide": ["values", "emotional guide"],
                    "misc": ["scratch"],
                },
            },
        )

    def test_yaml_subset_preserves_unquoted_hashes(self):
        parsed = self.module.parse_yaml_subset(
            """one: foo#bar
two: see#fragment
three:
  - b#c
"""
        )

        self.assertEqual(
            parsed,
            {"one": "foo#bar", "two": "see#fragment", "three": ["b#c"]},
        )

    def test_yaml_subset_accepts_mid_token_quotes_as_plain_text(self):
        parsed = self.module.parse_yaml_subset(
            """one: don't panic
two: a"b
three: [don't panic, a"b, b#c]
"""
        )

        self.assertEqual(
            parsed,
            {"one": "don't panic", "two": 'a"b', "three": ["don't panic", 'a"b', "b#c"]},
        )

    def test_yaml_subset_accepts_indentless_sequences_under_mapping_keys(self):
        parsed = self.module.parse_yaml_subset(
            """a:
- x
- y
b: z
root:
  child:
  - x
  - y
  sibling: z
"""
        )

        self.assertEqual(
            parsed,
            {
                "a": ["x", "y"],
                "b": "z",
                "root": {"child": ["x", "y"], "sibling": "z"},
            },
        )

        with self.assertRaises(self.module.YamlSubsetError) as raised:
            self.module.parse_yaml_subset("a:\n    - x\n")
        self.assertIn("line 2: unexpected indentation", str(raised.exception))
        self.assertNotIn("mix", str(raised.exception))

    def test_yaml_subset_rejects_empty_list_items_before_same_indent_siblings(self):
        rejected = (
            "root:\n  -\n  - x\n",
            "root:\n  -\n  - key: value\n",
        )

        for text in rejected:
            with self.subTest(text=text):
                with self.assertRaises(self.module.YamlSubsetError) as raised:
                    self.module.parse_yaml_subset(text)
                self.assertIn("line 2: empty block-list item", str(raised.exception))

    def test_yaml_subset_accepts_quoted_mapping_keys(self):
        parsed = self.module.parse_yaml_subset(
            """root:
  '日本語 file.md': one
  "a:b#c": two
  'it''s.md': three
"""
        )

        self.assertEqual(
            parsed,
            {"root": {"日本語 file.md": "one", "a:b#c": "two", "it's.md": "three"}},
        )

        with self.assertRaises(self.module.YamlSubsetError) as raised:
            self.module.parse_yaml_subset('"same": one\nsame: two\n')
        self.assertIn("line 2: duplicate mapping key 'same'", str(raised.exception))

    def test_yaml_subset_rejects_excessive_nesting_with_subset_error(self):
        nesting_limit = 100
        text = "\n".join(
            f"{'  ' * depth}level_{depth}:"
            for depth in range(nesting_limit + 1)
        )

        with self.assertRaises(self.module.YamlSubsetError) as raised:
            self.module.parse_yaml_subset(text)
        self.assertIn(
            f"line {nesting_limit + 1}: nesting depth exceeds limit",
            str(raised.exception),
        )

    def test_yaml_subset_rejects_non_ascii_whitespace_on_the_split_line_number(self):
        with self.assertRaises(self.module.YamlSubsetError) as raised:
            self.module.parse_yaml_subset("root: value\r\n  bad\N{NO-BREAK SPACE}key: value\n")

        self.assertIn("line 2: non-ASCII whitespace U+00A0", str(raised.exception))

    def test_yaml_subset_rejects_unsupported_or_malformed_constructs_with_line_numbers(self):
        rejected = {
            "tabs": "root:\n\tchild: value\n",
            "anchor": "root: &base value\n",
            "spaced anchor": "root: & base\n",
            "alias": "root: *base\n",
            "tag": "root: !str value\n",
            "flow mapping": "root: {child: value}\n",
            "document marker": "root: value\n---\nother: value\n",
            "odd indentation": "root:\n   child: value\n",
            "indentation jump": "root:\n    child: value\n",
            "duplicate": "root: first\nroot: second\n",
            "quote": 'root: "unterminated\n',
            "inline list": "root: [one,, two]\n",
            "tilde null": "root: ~\n",
            "YAML yes": "root: yes\n",
            "YAML NO": "root: NO\n",
            "YAML On": "root: On\n",
            "YAML OFF": "root: OFF\n",
            "YAML True": "root: True\n",
            "YAML NULL": "root: NULL\n",
            "special float": "root: .nan\n",
            "infinite float": "root: -.Inf\n",
            "exponent": "root: 1e3\n",
            "ISO date": "root: 2026-08-07\n",
            "leading-zero integer": "root: 012\n",
            "hex integer": "root: 0x10\n",
            "underscored integer": "root: 1_000\n",
            "oversized integer": "root: " + "9" * 5000 + "\n",
            "leading-dot float": "root: .5\n",
            "trailing-dot float": "root: 1.\n",
            "NUL": "root: value\x00\n",
            "control character": "root: value\nother: \x01bad\n",
        }
        expected_lines = {
            "tabs": 2,
            "anchor": 1,
            "spaced anchor": 1,
            "alias": 1,
            "tag": 1,
            "flow mapping": 1,
            "document marker": 2,
            "odd indentation": 2,
            "indentation jump": 2,
            "duplicate": 2,
            "quote": 1,
            "inline list": 1,
            "tilde null": 1,
            "YAML yes": 1,
            "YAML NO": 1,
            "YAML On": 1,
            "YAML OFF": 1,
            "YAML True": 1,
            "YAML NULL": 1,
            "special float": 1,
            "infinite float": 1,
            "exponent": 1,
            "ISO date": 1,
            "leading-zero integer": 1,
            "hex integer": 1,
            "underscored integer": 1,
            "oversized integer": 1,
            "leading-dot float": 1,
            "trailing-dot float": 1,
            "NUL": 1,
            "control character": 2,
        }

        for label, text in rejected.items():
            with self.subTest(label=label):
                with self.assertRaises(self.module.YamlSubsetError) as raised:
                    self.module.parse_yaml_subset(text)
                self.assertIn(f"line {expected_lines[label]}:", str(raised.exception))

    def test_load_config_preserves_parser_line_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = write_file(
                Path(tmp) / "ambiguous.yaml",
                "role_matrix:\n  IDENTITY.md: yes\nheading_categories: {}\n",
            )
            with self.assertRaises(self.module.ContentLintError) as raised:
                self.module.load_config(config)
            self.assertIn("line 2:", str(raised.exception))

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
