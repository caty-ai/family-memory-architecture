#!/usr/bin/env python3
"""Tests for scripts/overlap-lint."""

import contextlib
import importlib.machinery
import importlib.util
import io
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
OVERLAP_LINT_SCRIPT = REPO_ROOT / "scripts" / "overlap-lint"


def load_module():
    loader = importlib.machinery.SourceFileLoader("overlap_lint_under_test", str(OVERLAP_LINT_SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class OverlapLintTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_default_memory_md_encodes_current_working_directory(self):
        cases = {
            "/Users/x/claude-workspace": "-Users-x-claude-workspace",
            "/home/x/workspace": "-home-x-workspace",
            "/home/x/project.with_under_score": "-home-x-project-with-under-score",
        }

        for cwd, encoded in cases.items():
            with self.subTest(cwd=cwd), mock.patch.object(self.module.Path, "cwd", return_value=Path(cwd)):
                self.assertEqual(
                    self.module.default_memory_md(),
                    f"~/.claude/projects/{encoded}/memory/MEMORY.md",
                )

    def run_main_and_capture_args(self, argv):
        captured = []

        def fake_build_report(args):
            captured.append(args)
            return "test report", 0

        stdout = io.StringIO()
        with mock.patch.object(self.module, "build_report", side_effect=fake_build_report):
            with contextlib.redirect_stdout(stdout):
                code = self.module.main(argv)
        self.assertEqual(code, 0, stdout.getvalue())
        self.assertEqual(len(captured), 1)
        return captured[0]

    def test_memory_md_default_uses_current_working_directory(self):
        cwd = Path("/home/x/project_root")
        with mock.patch.object(self.module.Path, "cwd", return_value=cwd):
            args = self.run_main_and_capture_args([])

        self.assertEqual(
            args.memory_md,
            "~/.claude/projects/-home-x-project-root/memory/MEMORY.md",
        )

    def test_explicit_memory_md_overrides_derived_default(self):
        with mock.patch.object(self.module.Path, "cwd", return_value=Path("/home/x/project")):
            args = self.run_main_and_capture_args(["--memory-md", "~/custom/MEMORY.md"])

        self.assertEqual(args.memory_md, "~/custom/MEMORY.md")


if __name__ == "__main__":
    unittest.main()
