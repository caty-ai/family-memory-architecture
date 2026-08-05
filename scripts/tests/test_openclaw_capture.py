#!/usr/bin/env python3
"""Node-based tests for extensions/openclaw-capture."""

import shutil
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
NODE_TEST = REPO_ROOT / "scripts" / "tests" / "test_openclaw_capture.mjs"


class OpenClawCaptureTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is required")
    def test_plugin_register_and_handler(self):
        result = subprocess.run(
            ["node", str(NODE_TEST)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
