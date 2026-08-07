#!/usr/bin/env python3
"""Smoke tests for the bundled green fixture manifests."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INJECTION_BUDGET = REPO_ROOT / "scripts" / "injection-budget-check"
INJECTION_LINT = REPO_ROOT / "scripts" / "injection-lint"
WATCHDOG = REPO_ROOT / "scripts" / "watchdog"


class FixtureSmokeTests(unittest.TestCase):
    def run_script(self, script, *args, env=None):
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        return subprocess.run(
            [sys.executable, str(script), *map(str, args)],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=run_env,
            check=False,
        )

    def fixture_env(self):
        temp_home = tempfile.TemporaryDirectory()
        env = {"HOME": temp_home.name}
        return temp_home, env

    def test_injection_budget_fixture_exits_zero(self):
        temp_home, env = self.fixture_env()
        with temp_home:
            result = self.run_script(
                INJECTION_BUDGET,
                "--manifest",
                "manifests/fixtures/fixed-injection.yaml",
                env=env,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("fixture-fixed-source", result.stdout)
        self.assertIn("verdict OK exit 0", result.stdout)

    def test_injection_lint_fixture_exits_zero(self):
        temp_home, env = self.fixture_env()
        with temp_home:
            result = self.run_script(
                INJECTION_LINT,
                "--manifest-dir",
                "manifests/fixtures/injection",
                "--all",
                env=env,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Agent fixture-agent: OK=", result.stdout)
        self.assertIn("AGENTS.md: OK:", result.stdout)

    def test_watchdog_fixture_exits_zero(self):
        temp_home, env = self.fixture_env()
        with temp_home:
            result = self.run_script(
                WATCHDOG,
                "--jobs-manifest",
                "manifests/fixtures/jobs.yaml",
                env=env,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("fixture-watchdog: skipped (exempt)", result.stdout)
        self.assertIn("0 ok, 0 alert", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
