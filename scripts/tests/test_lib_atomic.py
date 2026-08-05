#!/usr/bin/env python3
"""Tests for shared atomic state-file writers."""

import importlib.machinery
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from unittest import mock
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_ATOMIC = REPO_ROOT / "scripts" / "lib_atomic.py"


class LibAtomicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("lib_atomic_under_test", str(LIB_ATOMIC))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.lib_atomic = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.lib_atomic)

    def test_text_and_json_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            text_path = root / "nested" / "state.txt"
            json_path = root / "state.json"

            self.lib_atomic.atomic_write_text(text_path, "hello\nworld\n")
            self.lib_atomic.atomic_write_json(json_path, {"z": 1, "a": [True]})

            self.assertEqual(text_path.read_text(encoding="utf-8"), "hello\nworld\n")
            self.assertEqual(json_path.read_text(encoding="utf-8"), json.dumps({"z": 1, "a": [True]}, indent=2, sort_keys=True) + "\n")
            self.assertEqual(set(root.iterdir()), {text_path.parent, json_path})
            self.assertEqual(set(text_path.parent.iterdir()), {text_path})

    def test_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.txt"
            path.write_text("old", encoding="utf-8")

            self.lib_atomic.atomic_write_text(path, "new")

            self.assertEqual(path.read_text(encoding="utf-8"), "new")

    def test_failure_removes_temp_file_and_preserves_existing_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "state.txt"
            path.write_text("old", encoding="utf-8")

            with mock.patch.object(self.lib_atomic.os, "fsync", side_effect=OSError("disk error")):
                with self.assertRaisesRegex(OSError, "disk error"):
                    self.lib_atomic.atomic_write_text(path, "new")

            self.assertEqual(path.read_text(encoding="utf-8"), "old")
            self.assertEqual(set(root.iterdir()), {path})

    def test_new_file_mode_honors_umask(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original_umask = os.umask(0o022)
            try:
                first_path = root / "group-readable.txt"
                self.lib_atomic.atomic_write_text(first_path, "first")
                self.assertEqual(stat.S_IMODE(first_path.stat().st_mode), 0o644)

                os.umask(0o077)
                second_path = root / "owner-only.txt"
                self.lib_atomic.atomic_write_text(second_path, "second")
                self.assertEqual(stat.S_IMODE(second_path.stat().st_mode), 0o600)
            finally:
                os.umask(original_umask)

    def test_stale_temp_file_does_not_interfere_with_real_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "state.txt"
            stale_temp = root / ".tmp-interrupted-write"
            stale_temp.write_text("partial", encoding="utf-8")

            self.lib_atomic.atomic_write_text(path, "complete")

            self.assertEqual(path.read_text(encoding="utf-8"), "complete")
            self.assertEqual(stale_temp.read_text(encoding="utf-8"), "partial")


if __name__ == "__main__":
    unittest.main()
