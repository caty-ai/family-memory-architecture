#!/usr/bin/env python3
"""Tests for the standard job-heartbeat emitter."""

import json
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
JOB_HEARTBEAT = REPO_ROOT / "scripts" / "job-heartbeat"


def load_job_heartbeat_module():
    loader = importlib.machinery.SourceFileLoader("job_heartbeat_under_test", str(JOB_HEARTBEAT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class JobHeartbeatTests(unittest.TestCase):
    def run_heartbeat(self, *args):
        return subprocess.run(
            [sys.executable, str(JOB_HEARTBEAT), *map(str, args)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
            check=False,
        )

    def test_envelope_fields_round_trip(self):
        flags = (
            "--run-id", "run-123",
            "--origin", "scheduled",
            "--started-at", "2026-07-21T00:00:00Z",
            "--last-progress-at", "2026-07-21T00:05:00Z",
            "--terminal-reason", "completed",
            "--error-class", "transient",
        )
        expected = {
            "job": "demo",
            "last_run": None,
            "status": "ok",
            "fail_count": 0,
            "duration_ms": 0,
            "docs": 0,
            "run_id": "run-123",
            "origin": "scheduled",
            "started_at": "2026-07-21T00:00:00Z",
            "last_progress_at": "2026-07-21T00:05:00Z",
            "terminal_reason": "completed",
            "error_class": "transient",
        }
        with tempfile.TemporaryDirectory() as tmp:
            heartbeat_dir = Path(tmp) / "heartbeats"
            result = self.run_heartbeat("demo", "ok", "--heartbeat-dir", heartbeat_dir, *flags)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads((heartbeat_dir / "demo.json").read_text(encoding="utf-8"))
            expected["last_run"] = payload["last_run"]
            self.assertEqual(payload, expected)

    def test_all_envelope_enum_values_round_trip(self):
        enum_values = {
            "--origin": ("user", "scheduled", "continuation", "recovery", "subagent"),
            "--terminal-reason": ("completed", "no-progress", "budget", "infra", "blocked", "user-paused"),
            "--error-class": ("deterministic", "transient", "degenerate", "context-overflow"),
        }
        payload_keys = {
            "--origin": "origin",
            "--terminal-reason": "terminal_reason",
            "--error-class": "error_class",
        }
        with tempfile.TemporaryDirectory() as tmp:
            heartbeat_dir = Path(tmp) / "heartbeats"
            for flag, values in enum_values.items():
                for value in values:
                    with self.subTest(flag=flag, value=value):
                        result = self.run_heartbeat(
                            "demo", "ok", "--heartbeat-dir", heartbeat_dir, flag, value,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        payload = json.loads((heartbeat_dir / "demo.json").read_text(encoding="utf-8"))
                        self.assertEqual(payload[payload_keys[flag]], value)

    def test_invalid_envelope_enums_are_rejected_without_writing(self):
        for flag in ("--origin", "--terminal-reason", "--error-class"):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as tmp:
                heartbeat_dir = Path(tmp) / "heartbeats"
                result = self.run_heartbeat("demo", "ok", "--heartbeat-dir", heartbeat_dir, flag, "invalid")
                self.assertEqual(result.returncode, 2)
                self.assertIn("usage:", result.stderr)
                self.assertFalse((heartbeat_dir / "demo.json").exists())

    def test_invalid_free_form_envelope_values_are_rejected_without_writing(self):
        invalid_flags = (
            ("--run-id", ""),
            ("--started-at", "yesterday"),
            ("--last-progress-at", ""),
        )
        for flag, value in invalid_flags:
            with self.subTest(flag=flag, value=value), tempfile.TemporaryDirectory() as tmp:
                heartbeat_dir = Path(tmp) / "heartbeats"
                result = self.run_heartbeat("demo", "ok", "--heartbeat-dir", heartbeat_dir, flag, value)
                self.assertEqual(result.returncode, 2)
                self.assertIn("usage:", result.stderr)
                self.assertFalse((heartbeat_dir / "demo.json").exists())

    def test_iso_utc_timestamps_preserve_original_input(self):
        for timestamp in ("2026-07-21T12:00:00Z", "2026-07-21T12:00:00+00:00"):
            with self.subTest(timestamp=timestamp), tempfile.TemporaryDirectory() as tmp:
                heartbeat_dir = Path(tmp) / "heartbeats"
                result = self.run_heartbeat(
                    "demo", "ok", "--heartbeat-dir", heartbeat_dir, "--started-at", timestamp,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads((heartbeat_dir / "demo.json").read_text(encoding="utf-8"))
                self.assertEqual(payload["started_at"], timestamp)

    def test_no_envelope_flags_preserve_exact_legacy_payload_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            heartbeat_dir = Path(tmp) / "heartbeats"
            result = self.run_heartbeat("demo", "ok", "--docs", "2", "--duration-ms", "7", "--heartbeat-dir", heartbeat_dir)
            self.assertEqual(result.returncode, 0, result.stderr)
            raw_payload = (heartbeat_dir / "demo.json").read_text(encoding="utf-8")
            payload = json.loads(raw_payload)
            expected = {
                "job": "demo",
                "last_run": payload["last_run"],
                "status": "ok",
                "fail_count": 0,
                "duration_ms": 7,
                "docs": 2,
            }
            self.assertEqual(raw_payload, json.dumps(expected, indent=2, sort_keys=True) + "\n")

    def test_fail_count_increments_and_ok_resets(self):
        with tempfile.TemporaryDirectory() as tmp:
            heartbeat_dir = Path(tmp) / "heartbeats"
            for _ in range(2):
                result = self.run_heartbeat("demo", "fail", "--heartbeat-dir", heartbeat_dir)
                self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads((heartbeat_dir / "demo.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["fail_count"], 2)

            result = self.run_heartbeat("demo", "ok", "--heartbeat-dir", heartbeat_dir)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads((heartbeat_dir / "demo.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["fail_count"], 0)

    def test_fail_reason_truncation_and_envelope_fields_round_trip_together(self):
        reason = "x" * 301
        with tempfile.TemporaryDirectory() as tmp:
            heartbeat_dir = Path(tmp) / "heartbeats"
            result = self.run_heartbeat(
                "demo", "fail", "--reason", reason, "--heartbeat-dir", heartbeat_dir,
                "--run-id", "run-456", "--origin", "recovery",
                "--started-at", "2026-07-21T12:00:00Z",
                "--last-progress-at", "2026-07-21T12:01:00+00:00",
                "--terminal-reason", "infra", "--error-class", "transient",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads((heartbeat_dir / "demo.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["reason"], reason[:300])
            self.assertEqual(
                {key: payload[key] for key in ("run_id", "origin", "started_at", "last_progress_at", "terminal_reason", "error_class")},
                {
                    "run_id": "run-456",
                    "origin": "recovery",
                    "started_at": "2026-07-21T12:00:00Z",
                    "last_progress_at": "2026-07-21T12:01:00+00:00",
                    "terminal_reason": "infra",
                    "error_class": "transient",
                },
            )

    def test_invalid_job_rejection_preserves_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            heartbeat_dir = Path(tmp) / "heartbeats"
            result = self.run_heartbeat(
                "../bad", "fail", "--heartbeat-dir", heartbeat_dir,
                "--run-id", "run-789", "--origin", "subagent",
                "--started-at", "2026-07-21T12:00:00Z", "--terminal-reason", "blocked",
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads((heartbeat_dir / "_invalid-job.json").read_text(encoding="utf-8"))
            self.assertEqual(
                {key: payload[key] for key in ("run_id", "origin", "started_at", "terminal_reason")},
                {
                    "run_id": "run-789",
                    "origin": "subagent",
                    "started_at": "2026-07-21T12:00:00Z",
                    "terminal_reason": "blocked",
                },
            )

    def test_write_heartbeat_reserved_envelope_keys_cannot_override_core_payload(self):
        module = load_job_heartbeat_module()
        with tempfile.TemporaryDirectory() as tmp:
            heartbeat_path = Path(tmp) / "heartbeats" / "demo.json"
            module.write_heartbeat(
                heartbeat_path,
                "demo",
                "fail",
                "actual failure",
                2,
                7,
                {
                    "job": "evil",
                    "last_run": "evil",
                    "status": "ok",
                    "fail_count": 99,
                    "duration_ms": 99,
                    "docs": 99,
                    "reason": "evil",
                    "run_id": "allowed",
                },
            )
            payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["job"], "demo")
            self.assertNotEqual(payload["last_run"], "evil")
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(payload["fail_count"], 1)
            self.assertEqual(payload["duration_ms"], 7)
            self.assertEqual(payload["docs"], 2)
            self.assertEqual(payload["reason"], "actual failure")
            self.assertEqual(payload["run_id"], "allowed")
