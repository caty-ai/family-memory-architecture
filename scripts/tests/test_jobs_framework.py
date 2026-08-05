#!/usr/bin/env python3
"""Tests for Issue #11 jobs framework scripts."""

import json
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
JOB_HEARTBEAT = REPO_ROOT / "scripts" / "job-heartbeat"
WATCHDOG = REPO_ROOT / "scripts" / "watchdog"
JOBS_MANIFEST = REPO_ROOT / "manifests" / "jobs.yaml"
PERSONAL_HOT_LINT = REPO_ROOT / "scripts" / "personal-hot-lint"
SAVE_CANDIDATE = REPO_ROOT / "scripts" / "save-candidate-suggest"


def write_file(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def utc_stamp(hours_ago=0):
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def heartbeat_payload(job, status="ok", fail_count=0, hours_ago=0):
    return {
        "job": job,
        "last_run": utc_stamp(hours_ago),
        "status": status,
        "fail_count": fail_count,
        "duration_ms": 1,
        "docs": 0,
    }


class JobsFrameworkTests(unittest.TestCase):
    def run_script(self, script, *args, input_text=None, env=None):
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        return subprocess.run(
            [sys.executable, str(script), *map(str, args)],
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=run_env,
            check=False,
        )

    def load_script_module(self, name, script):
        loader = importlib.machinery.SourceFileLoader(name, str(script))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_job_heartbeat_ok_fail_increment_reset_and_invalid_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            hb = Path(tmp) / "hb"
            ok = self.run_script(JOB_HEARTBEAT, "demo-job", "ok", "--docs", "2", "--duration-ms", "7", "--heartbeat-dir", hb)
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            payload = json.loads((hb / "demo-job.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["job"], "demo-job")
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["fail_count"], 0)
            self.assertEqual(payload["docs"], 2)
            self.assertEqual(payload["duration_ms"], 7)

            first_fail = self.run_script(JOB_HEARTBEAT, "demo-job", "fail", "--reason", "bad", "--heartbeat-dir", hb)
            second_fail = self.run_script(JOB_HEARTBEAT, "demo-job", "fail", "--reason", "bad", "--heartbeat-dir", hb)
            self.assertEqual(first_fail.returncode, 0, first_fail.stderr)
            self.assertEqual(second_fail.returncode, 0, second_fail.stderr)
            payload = json.loads((hb / "demo-job.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["fail_count"], 2)
            self.assertEqual(payload["reason"], "bad")

            reset = self.run_script(JOB_HEARTBEAT, "demo-job", "ok", "--heartbeat-dir", hb)
            self.assertEqual(reset.returncode, 0, reset.stderr)
            payload = json.loads((hb / "demo-job.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["fail_count"], 0)
            self.assertNotIn("reason", payload)

            invalid = self.run_script(JOB_HEARTBEAT, "../bad", "fail", "--heartbeat-dir", hb)
            self.assertEqual(invalid.returncode, 1)
            self.assertFalse((hb / "../bad.json").exists())
            sentinel = json.loads((hb / "_invalid-job.json").read_text(encoding="utf-8"))
            self.assertEqual(sentinel["job"], "_invalid-job")
            self.assertEqual(sentinel["status"], "fail")
            self.assertIn("../bad", sentinel["reason"])

    def write_manifest(self, path, body):
        return write_file(path, "jobs:\n" + body)

    def write_heartbeat(self, hb, filename, payload):
        write_file(hb / filename, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def run_watchdog(self, manifest, hb, host="laptop", extra=()):
        return self.run_script(
            WATCHDOG,
            "--jobs-manifest",
            manifest,
            "--heartbeat-dir",
            hb,
            "--host",
            host,
            *extra,
        )

    def test_watchdog_ok_alerts_filters_on_demand_and_self_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: fresh
    desc: "fresh"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: fresh.json
    alert: [stderr]
  - id: old
    desc: "old"
    host: laptop
    owner: agent-a
    period_hours: 1
    heartbeat: old.json
    alert: [stderr]
  - id: failed
    desc: "failed"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: failed.json
    alert: [stderr]
  - id: missing
    desc: "missing"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: missing.json
    alert: [stderr]
  - id: exempted
    desc: "exempted"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: exempted.json
    alert: [stderr]
    exempt: true
  - id: remote
    desc: "remote"
    host: server
    owner: agent-b
    period_hours: 24
    heartbeat: remote.json
    alert: [stderr]
  - id: ondemand
    desc: "ondemand"
    host: laptop
    owner: agent-a
    period_hours: null
    heartbeat: ondemand.json
    alert: [stderr]
""",
            )
            self.write_heartbeat(hb, "fresh.json", heartbeat_payload("fresh"))
            self.write_heartbeat(hb, "old.json", heartbeat_payload("old", hours_ago=3))
            self.write_heartbeat(hb, "failed.json", heartbeat_payload("failed", status="fail", fail_count=3))
            self.write_heartbeat(hb, "ondemand.json", heartbeat_payload("ondemand", hours_ago=1000))

            result = self.run_watchdog(manifest, hb)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("fresh: ok", result.stdout)
            self.assertIn("old: ALERT", result.stdout)
            self.assertIn("failed: ALERT", result.stdout)
            self.assertIn("missing: ALERT", result.stdout)
            self.assertIn("exempted: skipped (exempt)", result.stdout)
            self.assertIn("ondemand: ok", result.stdout)
            self.assertNotIn("remote:", result.stdout)
            self.assertEqual(json.loads((hb / "watchdog-laptop.json").read_text(encoding="utf-8"))["status"], "ok")

    def test_watchdog_all_ok_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: fresh
    desc: "fresh"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: fresh.json
    alert: [stderr]
""",
            )
            self.write_heartbeat(hb, "fresh.json", heartbeat_payload("fresh"))
            result = self.run_watchdog(manifest, hb)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("1 ok, 0 alert", result.stdout)

    def test_watchdog_writes_laptop_self_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: fresh
    desc: "fresh"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: fresh.json
    alert: [stderr]
""",
            )
            self.write_heartbeat(hb, "fresh.json", heartbeat_payload("fresh"))
            result = self.run_watchdog(manifest, hb, host="laptop")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((hb / "watchdog-laptop.json").exists())
            self.assertFalse((hb / "watchdog.json").exists())

    def test_watchdog_writes_desktop_self_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: fresh
    desc: "fresh"
    host: desktop
    owner: agent-a
    period_hours: 24
    heartbeat: fresh.json
    alert: [stderr]
""",
            )
            self.write_heartbeat(hb, "fresh.json", heartbeat_payload("fresh"))
            result = self.run_watchdog(manifest, hb, host="desktop")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((hb / "watchdog-desktop.json").exists())
            self.assertFalse((hb / "watchdog.json").exists())

    def test_watchdog_host_runs_do_not_mask_other_host_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: watchdog-laptop
    desc: "Common job watchdog (laptop)"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: watchdog-laptop.json
    alert: [stderr, notify]
  - id: watchdog-desktop
    desc: "Common job watchdog (desktop)"
    host: desktop
    owner: agent-a
    period_hours: 24
    heartbeat: watchdog-desktop.json
    alert: [stderr, notify]
  - id: fresh
    desc: "fresh"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: fresh.json
    alert: [stderr, notify]
""",
            )
            seeded_failure = heartbeat_payload("watchdog-laptop", status="fail", fail_count=3)
            self.write_heartbeat(hb, "watchdog-laptop.json", seeded_failure)
            self.write_heartbeat(hb, "fresh.json", heartbeat_payload("fresh"))

            self.run_watchdog(manifest, hb, host="desktop")

            laptop_payload = json.loads((hb / "watchdog-laptop.json").read_text(encoding="utf-8"))
            self.assertEqual(laptop_payload, seeded_failure)
            self.assertEqual(laptop_payload["status"], "fail")
            self.assertEqual(laptop_payload["fail_count"], 3)

            laptop_run = self.run_watchdog(manifest, hb, host="laptop")
            self.assertIn("watchdog-laptop: ALERT", laptop_run.stdout)

    def test_watchdog_self_heartbeat_job_matches_host_manifest_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: fresh-agent-a
    desc: "fresh agent-a"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: fresh-agent-a.json
    alert: [stderr]
  - id: fresh-desktop
    desc: "fresh desktop"
    host: desktop
    owner: agent-a
    period_hours: 24
    heartbeat: fresh-desktop.json
    alert: [stderr]
""",
            )
            self.write_heartbeat(hb, "fresh-agent-a.json", heartbeat_payload("fresh-agent-a"))
            self.write_heartbeat(hb, "fresh-desktop.json", heartbeat_payload("fresh-desktop"))

            for host in ("laptop", "desktop"):
                with self.subTest(host=host):
                    result = self.run_watchdog(manifest, hb, host=host)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    payload = json.loads((hb / f"watchdog-{host}.json").read_text(encoding="utf-8"))
                    self.assertEqual(payload["job"], f"watchdog-{host}")

    def test_watchdog_desktop_valid_heartbeat_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: agent-g-backup
    desc: "agent-g backup"
    host: desktop
    owner: agent-a
    period_hours: 24
    heartbeat: agent-g-backup.json
    alert: [stderr]
""",
            )
            self.write_heartbeat(hb, "agent-g-backup.json", heartbeat_payload("agent-g-backup"))
            result = self.run_watchdog(manifest, hb, host="desktop")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("agent-g-backup: ok", result.stdout)

    def test_watchdog_desktop_missing_heartbeat_alerts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: agent-g-backup
    desc: "agent-g backup"
    host: desktop
    owner: agent-a
    period_hours: 24
    heartbeat: agent-g-backup.json
    alert: [stderr]
""",
            )
            result = self.run_watchdog(manifest, hb, host="desktop")
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("agent-g-backup: ALERT (heartbeat missing)", result.stdout)

    def test_watchdog_desktop_job_excluded_by_laptop_host_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: agent-g-backup
    desc: "agent-g backup"
    host: desktop
    owner: agent-a
    period_hours: 24
    heartbeat: agent-g-backup.json
    alert: [stderr]
""",
            )
            result = self.run_watchdog(manifest, hb, host="laptop")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("agent-g-backup:", result.stdout)

    def test_watchdog_mixed_manifest_filters_to_requested_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: watchdog
    desc: "watchdog"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: watchdog.json
    alert: [stderr]
  - id: agent-g-backup
    desc: "agent-g backup"
    host: desktop
    owner: agent-a
    period_hours: 24
    heartbeat: agent-g-backup.json
    alert: [stderr]
""",
            )
            self.write_heartbeat(hb, "agent-g-backup.json", heartbeat_payload("agent-g-backup"))
            desktop = self.run_watchdog(manifest, hb, host="desktop")
            self.assertEqual(desktop.returncode, 0, desktop.stdout + desktop.stderr)
            self.assertIn("agent-g-backup: ok", desktop.stdout)
            self.assertNotIn("watchdog", desktop.stdout)

            (hb / "agent-g-backup.json").unlink()
            self.write_heartbeat(hb, "watchdog.json", heartbeat_payload("watchdog"))
            laptop_run = self.run_watchdog(manifest, hb, host="laptop")
            self.assertEqual(laptop_run.returncode, 0, laptop_run.stdout + laptop_run.stderr)
            self.assertIn("watchdog: ok", laptop_run.stdout)
            self.assertNotIn("agent-g-backup", laptop_run.stdout)

    def test_watchdog_cli_rejects_unknown_host_and_choices_match_allowed_hosts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            result = self.run_script(WATCHDOG, "--jobs-manifest", root / "jobs.yaml", "--heartbeat-dir", hb, "--host", "mars")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid choice", result.stderr)

        module = self.load_script_module("watchdog_host_choices_under_test", WATCHDOG)
        host_choices = []
        original_add_argument = module.argparse.ArgumentParser.add_argument

        def capturing_add_argument(parser, *args, **kwargs):
            if "--host" in args:
                host_choices.append(kwargs["choices"])
            return original_add_argument(parser, *args, **kwargs)

        try:
            module.argparse.ArgumentParser.add_argument = capturing_add_argument
            module.parse_args([])
        finally:
            module.argparse.ArgumentParser.add_argument = original_add_argument

        self.assertEqual(len(host_choices), 1)
        self.assertEqual(set(host_choices[0]), module.ALLOWED_HOSTS)

    def test_watchdog_fractional_period_staleness(self):
        # fable-loop-harness#41: first fractional period (0.25h tick) must flow
        # through the staleness math — fresh (<30min) ok, aged (>30min) alert.
        for hours_ago, expect_rc in ((0.15, 0), (0.6, 2)):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                hb = root / "hb"
                hb.mkdir()
                manifest = self.write_manifest(
                    root / "jobs.yaml",
                    """  - id: tick-job
    desc: "five minute tick"
    host: server
    owner: agent-e
    period_hours: 0.25
    heartbeat: tick-job.json
    alert: [stderr]
""",
                )
                self.write_heartbeat(
                    hb, "tick-job.json", heartbeat_payload("tick-job", hours_ago=hours_ago)
                )
                result = self.run_watchdog(manifest, hb, host="server")
                self.assertEqual(
                    result.returncode, expect_rc,
                    f"hours_ago={hours_ago}: {result.stdout}{result.stderr}",
                )
                if expect_rc == 2:
                    self.assertIn("heartbeat stale", result.stdout)

    def test_watchdog_accepts_agent_e_and_agent_f_owners(self):
        # fable-loop-harness#41: loop-harness cron jobs registered with their real owners
        for owner in ("agent-e", "agent-f", "agent-g"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                hb = root / "hb"
                hb.mkdir()
                manifest = self.write_manifest(
                    root / "jobs.yaml",
                    f"""  - id: {owner}-job
    desc: "{owner} job"
    host: server
    owner: {owner}
    period_hours: 24
    heartbeat: {owner}-job.json
    alert: [stderr]
""",
                )
                self.write_heartbeat(hb, f"{owner}-job.json", heartbeat_payload(f"{owner}-job"))
                result = self.run_watchdog(manifest, hb, host="server")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_watchdog_accepts_agent_c_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: updater-agent-c
    desc: "updater agent-c"
    host: laptop
    owner: agent-c
    period_hours: 24
    heartbeat: updater-agent-c.json
    alert: [stderr]
""",
            )
            self.write_heartbeat(hb, "updater-agent-c.json", heartbeat_payload("updater-agent-c"))
            result = self.run_watchdog(manifest, hb)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("updater-agent-c: ok", result.stdout)

    def test_watchdog_real_manifest_validates_for_all_allowed_hosts(self):
        for host in ("laptop", "server", "desktop"):
            with self.subTest(host=host):
                with tempfile.TemporaryDirectory() as tmp:
                    hb = Path(tmp) / "hb"
                    hb.mkdir()
                    result = self.run_watchdog(JOBS_MANIFEST, hb, host=host)
                    self.assertIn(result.returncode, (0, 2), result.stdout + result.stderr)
                    self.assertNotIn("must be one of", result.stderr)

    def test_watchdog_rejects_unknown_manifest_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: unknown-host
    desc: "unknown host"
    host: mars
    owner: agent-a
    period_hours: 24
    heartbeat: unknown-host.json
    alert: [stderr]
""",
            )
            result = self.run_watchdog(manifest, hb)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("host must be one of", result.stderr)

    def test_watchdog_rejects_unknown_manifest_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: agent-g-backup
    desc: "agent-g backup"
    host: desktop
    owner: mars
    period_hours: 24
    heartbeat: agent-g-backup.json
    alert: [stderr, notify, inbox]
    note: "matches real agent-g-backup manifest shape"
""",
            )
            result = self.run_watchdog(manifest, hb, host="desktop")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("owner must be one of", result.stderr)

    def test_watchdog_validates_manifest_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: broken
    desc: "broken"
    host: laptop
    owner: agent-a
    period_hours: 24
    alert: [stderr]
""",
            )
            result = self.run_watchdog(manifest, hb)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("missing required field(s): heartbeat", result.stderr)

    def test_watchdog_rejects_special_heartbeat_filenames(self):
        for heartbeat in ['"."', '".."', '""']:
            with self.subTest(heartbeat=heartbeat):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    hb = root / "hb"
                    manifest = self.write_manifest(
                        root / "jobs.yaml",
                        f"""  - id: broken
    desc: "broken"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: {heartbeat}
    alert: [stderr]
""",
                    )
                    result = self.run_watchdog(manifest, hb)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("heartbeat must be a filename", result.stderr)

    def test_watchdog_alerts_on_invalid_and_incomplete_heartbeats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: invalid-json
    desc: "invalid json"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: invalid.json
    alert: [stderr]
  - id: missing-keys
    desc: "missing keys"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: missing-keys.json
    alert: [stderr]
""",
            )
            write_file(hb / "invalid.json", "{")
            write_file(hb / "missing-keys.json", json.dumps({"job": "missing-keys"}) + "\n")
            result = self.run_watchdog(manifest, hb)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("invalid-json: PAUSED", result.stdout)
            self.assertIn("corrupt heartbeat", result.stdout)
            self.assertIn("missing-keys: PAUSED", result.stdout)
            self.assertIn("missing required field", result.stdout)
            self.assertNotIn("heartbeat stale", result.stdout)

    def test_watchdog_corrupt_heartbeat_pauses_persistently_until_explicit_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: demo
    desc: "demo"
    host: laptop
    owner: agent-a
    period_hours: 1
    heartbeat: demo.json
    alert: [stderr]
""",
            )
            heartbeat_path = write_file(hb / "demo.json", "{not-json\n")
            corrupt_evidence = heartbeat_path.read_bytes()

            first = self.run_watchdog(manifest, hb, extra=("--json",))
            self.assertEqual(first.returncode, 2, first.stdout + first.stderr)
            first_report = json.loads(first.stdout)
            self.assertEqual(first_report["paused_count"], 1)
            self.assertEqual(first_report["stale_count"], 0)
            self.assertEqual(first_report["jobs"][0]["status"], "paused")
            self.assertEqual(first_report["jobs"][0]["reason_code"], "corrupt")
            self.assertEqual(heartbeat_path.read_bytes(), corrupt_evidence)

            # Even a later valid emitter-shaped file cannot feed the job back
            # into runnable state while the pause marker remains.
            self.write_heartbeat(hb, "demo.json", heartbeat_payload("demo"))
            second = self.run_watchdog(manifest, hb)
            self.assertEqual(second.returncode, 2, second.stdout + second.stderr)
            self.assertIn("demo: PAUSED", second.stdout)

            blocked_emit = self.run_script(
                JOB_HEARTBEAT,
                "demo",
                "ok",
                "--heartbeat-dir",
                hb,
            )
            self.assertEqual(blocked_emit.returncode, 2)
            self.assertIn("paused", blocked_emit.stderr)

            resumed = self.run_watchdog(manifest, hb, extra=("--resume", "demo"))
            self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
            self.assertIn("demo: re-armed", resumed.stdout)
            self.assertIn("demo: ok", resumed.stdout)
            self.assertFalse((hb / ".paused" / "demo.json.pause.json").exists())

    def test_watchdog_resume_still_corrupt_heartbeat_repauses_in_same_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: demo
    desc: "demo"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: demo.json
    alert: [stderr]
""",
            )
            write_file(hb / "demo.json", "{not-json\n")
            marker_path = hb / ".paused" / "demo.json.pause.json"

            first = self.run_watchdog(manifest, hb)
            self.assertEqual(first.returncode, 2, first.stdout + first.stderr)
            self.assertTrue(marker_path.exists())

            resumed = self.run_watchdog(manifest, hb, extra=("--resume", "demo"))
            self.assertEqual(resumed.returncode, 2, resumed.stdout + resumed.stderr)
            self.assertIn("demo: re-armed", resumed.stdout)
            self.assertIn("demo: PAUSED", resumed.stdout)
            self.assertNotIn("demo: ok", resumed.stdout)
            self.assertTrue(marker_path.exists())

    def test_watchdog_resume_rejects_job_owned_by_different_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: remote
    desc: "remote"
    host: server
    owner: agent-a
    period_hours: 24
    heartbeat: remote.json
    alert: [stderr]
""",
            )
            marker_path = hb / ".paused" / "remote.json.pause.json"
            marker_path.parent.mkdir()
            marker_path.write_text("{}\n", encoding="utf-8")

            result = self.run_watchdog(manifest, hb, extra=("--resume", "remote"))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("cannot re-arm 'remote' from host 'laptop'", result.stderr)
            self.assertTrue(marker_path.exists())

    def test_watchdog_multi_resume_validates_every_request_before_unlinking(self):
        for later_job in ("missing", "remote"):
            with self.subTest(later_job=later_job), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                hb = root / "hb"
                hb.mkdir()
                manifest = self.write_manifest(
                    root / "jobs.yaml",
                    """  - id: local
    desc: "local"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: local.json
    alert: [stderr]
  - id: remote
    desc: "remote"
    host: server
    owner: agent-a
    period_hours: 24
    heartbeat: remote.json
    alert: [stderr]
""",
                )
                local_marker = hb / ".paused" / "local.json.pause.json"
                remote_marker = hb / ".paused" / "remote.json.pause.json"
                local_marker.parent.mkdir()
                local_marker.write_text("{}\n", encoding="utf-8")
                remote_marker.write_text("{}\n", encoding="utf-8")

                result = self.run_watchdog(
                    manifest,
                    hb,
                    extra=("--resume", "local", "--resume", later_job),
                )

                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertTrue(local_marker.exists())
                self.assertTrue(remote_marker.exists())

    def test_watchdog_corrupt_values_never_leak_into_pause_state_or_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: mismatched-job
    desc: "mismatched job field"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: mismatched-job.json
    alert: [stderr]
  - id: invalid-status
    desc: "invalid status field"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: invalid-status.json
    alert: [stderr]
  - id: invalid-last-run
    desc: "invalid last_run field"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: invalid-last-run.json
    alert: [stderr]
""",
            )
            prefix = "github_" + "pat_"
            secrets = {
                "mismatched-job": prefix + ("j" * 24),
                "invalid-status": prefix + ("s" * 24),
                "invalid-last-run": prefix + ("t" * 24),
            }
            for job_id in secrets:
                payload = heartbeat_payload(job_id)
                if job_id == "mismatched-job":
                    payload["job"] = secrets[job_id]
                elif job_id == "invalid-status":
                    payload["status"] = secrets[job_id]
                else:
                    payload["last_run"] = secrets[job_id]
                self.write_heartbeat(hb, f"{job_id}.json", payload)

            result = self.run_watchdog(manifest, hb)

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            for job_id, secret in secrets.items():
                self.assertIn(f"{job_id}: PAUSED", result.stdout)
                marker_text = (
                    hb / ".paused" / f"{job_id}.json.pause.json"
                ).read_text(encoding="utf-8")
                self.assertNotIn(secret, marker_text)
                self.assertNotIn(secret, result.stdout)
                self.assertNotIn(secret, result.stderr)

    def test_watchdog_unknown_schema_version_pauses_with_distinct_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: future
    desc: "future"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: future.json
    alert: [stderr]
""",
            )
            payload = heartbeat_payload("future")
            payload["schema_version"] = "job-heartbeat/v999"
            self.write_heartbeat(hb, "future.json", payload)

            result = self.run_watchdog(manifest, hb)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("future: PAUSED", result.stdout)
            self.assertIn("unknown heartbeat schema version", result.stdout)
            marker = json.loads(
                (hb / ".paused" / "future.json.pause.json").read_text(encoding="utf-8")
            )
            self.assertEqual(marker["reason_code"], "unknown-version")

    def test_watchdog_never_overwrites_its_own_corrupt_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: watchdog-laptop
    desc: "watchdog"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: watchdog-laptop.json
    alert: [stderr]
""",
            )
            heartbeat_path = write_file(hb / "watchdog-laptop.json", "{broken")
            evidence = heartbeat_path.read_bytes()

            result = self.run_watchdog(manifest, hb)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("watchdog-laptop: PAUSED", result.stdout)
            self.assertEqual(heartbeat_path.read_bytes(), evidence)

    def test_watchdog_fail_count_and_staleness_boundaries(self):
        module = self.load_script_module("watchdog_under_test", WATCHDOG)
        now = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
        job = {"id": "demo", "period_hours": 1, "heartbeat": "demo.json"}
        with tempfile.TemporaryDirectory() as tmp:
            hb = Path(tmp)
            self.write_heartbeat(
                hb,
                "demo.json",
                {
                    "job": "demo",
                    "last_run": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
                    "status": "fail",
                    "fail_count": 2,
                    "duration_ms": 1,
                    "docs": 0,
                },
            )
            result = module.check_job(job, hb, now)
            self.assertEqual(result["status"], "ok")

    def test_watchdog_writes_fail_heartbeat_on_internal_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            result = self.run_watchdog(root / "missing-jobs.yaml", hb)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            payload = json.loads((hb / "watchdog-laptop.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "fail")

    def test_watchdog_inbox_post_respects_manifest_alert_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            hb.mkdir()
            inbox = root / "inbox"
            manifest = self.write_manifest(
                root / "jobs.yaml",
                """  - id: notify-only
    desc: "notify only"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: notify-only.json
    alert: [stderr, notify]
  - id: inbox-only
    desc: "inbox only"
    host: laptop
    owner: agent-a
    period_hours: 24
    heartbeat: inbox-only.json
    alert: [stderr, inbox]
""",
            )
            result = self.run_script(
                WATCHDOG,
                "--jobs-manifest",
                manifest,
                "--heartbeat-dir",
                hb,
                "--host",
                "laptop",
                "--inbox-post",
                env={"FAMILY_HOT_INBOX": str(inbox)},
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            events = list(inbox.glob("*.json"))
            self.assertEqual(len(events), 1, result.stdout + result.stderr)
            event = json.loads(events[0].read_text(encoding="utf-8"))
            self.assertEqual(event["created_by"], "watchdog")
            self.assertEqual(event["summary"], "1 alert(s): inbox-only")
            self.assertNotIn("notify-only", event["summary"])

    def make_hot(self, path, body):
        return write_file(path, body)

    def run_personal_lint(self, hot_path, wiki_root, hb):
        return self.run_script(PERSONAL_HOT_LINT, "--hot-path", hot_path, "--wiki-root", wiki_root, "--heartbeat-dir", hb)

    def test_personal_hot_lint_size_warn_and_fail(self):
        today = datetime.now(timezone.utc).date().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wiki = root / "wiki"
            wiki.mkdir()
            hb = root / "hb"
            warn_path = self.make_hot(wiki / "warn.md", f"---\nupdated: {today}\n---\n" + ("x" * 7200))
            warn = self.run_personal_lint(warn_path, wiki, hb)
            self.assertEqual(warn.returncode, 0, warn.stdout + warn.stderr)
            self.assertIn("size: warn=1 fail=0", warn.stdout)

            fail_path = self.make_hot(wiki / "fail.md", f"---\nupdated: {today}\n---\n" + ("x" * 8300))
            fail = self.run_personal_lint(fail_path, wiki, hb)
            self.assertEqual(fail.returncode, 2, fail.stdout + fail.stderr)
            self.assertIn("size: warn=0 fail=1", fail.stdout)

    def test_personal_hot_lint_stale_dead_link_and_clean(self):
        today = datetime.now(timezone.utc).date().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wiki = root / "wiki"
            write_file(wiki / "Existing.md", "# Existing\n")
            hb = root / "hb"

            stale_path = self.make_hot(wiki / "stale.md", "---\nupdated: 2000-01-01\n---\n")
            stale = self.run_personal_lint(stale_path, wiki, hb)
            self.assertEqual(stale.returncode, 0, stale.stdout + stale.stderr)
            self.assertIn("staleness: warn=1 fail=0", stale.stdout)

            dead_path = self.make_hot(wiki / "dead.md", f"---\nupdated: {today}\n---\n[[nonexistent-target]]\n")
            dead = self.run_personal_lint(dead_path, wiki, hb)
            self.assertEqual(dead.returncode, 0, dead.stdout + dead.stderr)
            self.assertIn("dead wikilink target: nonexistent-target", dead.stdout)

            clean_path = self.make_hot(wiki / "clean.md", f"---\nupdated: {today}\n---\n[[Existing]]\n")
            clean = self.run_personal_lint(clean_path, wiki, hb)
            self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
            self.assertIn("warnings=0 failures=0", clean.stdout)

    def test_personal_hot_lint_ignores_code_wikilinks_and_resolves_aliases(self):
        today = datetime.now(timezone.utc).date().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wiki = root / "wiki"
            hb = root / "hb"
            write_file(wiki / "target.md", "# target\n")
            hot = self.make_hot(
                wiki / "hot.md",
                f"""---
updated: {today}
---
`[[inline-missing]]`

```
[[fenced-missing]]
```

[[target|alias]]
[[target#anchor]]
""",
            )
            result = self.run_personal_lint(hot, wiki, hb)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("warnings=0 failures=0", result.stdout)
            self.assertNotIn("dead-wikilink", result.stdout)

    def test_personal_hot_lint_secret_scan_outcome_categories(self):
        today = datetime.now(timezone.utc).date().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wiki = root / "wiki"
            hot = self.make_hot(wiki / "hot.md", f"---\nupdated: {today}\n---\n")
            module = self.load_script_module("personal_hot_lint_under_test", PERSONAL_HOT_LINT)
            args = type("Args", (), {"hot_path": str(hot), "wiki_root": str(wiki)})()

            module.run_secret_scan = lambda _path: ("findings", "found\n")
            with contextlib.redirect_stderr(io.StringIO()):
                findings = module.lint(args)
            self.assertIn({"severity": "fail", "category": "secret", "message": "secret-scan found findings"}, findings)
            self.assertNotIn("secret-scan-error", {finding["category"] for finding in findings})

            module.run_secret_scan = lambda _path: ("error", "boom\n")
            with contextlib.redirect_stderr(io.StringIO()):
                findings = module.lint(args)
            self.assertIn({"severity": "fail", "category": "secret-scan-error", "message": "boom"}, findings)
            self.assertNotIn("secret", {finding["category"] for finding in findings})

    def test_save_candidate_suggest_candidates_and_silent_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.jsonl"
            rows = [
                {"message": {"content": [{"text": "この方針は後で見直す"}]}},
                {"message": {"content": [{"text": "最終決定: ここに保存する"}]}},
                {"message": {"content": [{"text": "実測でレイテンシが判明"}]}},
                {"message": {"content": [{"text": "今後は短く書く"}]}},
            ]
            path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            payload = json.dumps({"transcript_path": str(path)})
            result = self.run_script(SAVE_CANDIDATE, input_text=payload)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
            self.assertEqual(len(lines), 3)
            # hints come from write-guard route() (fma #98, spec §4)
            self.assertIn("この方針は後で見直す", lines[0])
            self.assertIn("family-vault 30_decisions/", lines[0])
            self.assertIn("最終決定: ここに保存する", lines[1])
            self.assertIn("family-vault 30_decisions/", lines[1])
            self.assertIn("実測でレイテンシが判明", lines[2])
            self.assertIn("50_references", lines[2])

            none_path = Path(tmp) / "none.jsonl"
            none_path.write_text(json.dumps({"message": {"content": [{"text": "plain text"}]}}) + "\n", encoding="utf-8")
            none = self.run_script(SAVE_CANDIDATE, input_text=json.dumps({"transcript_path": str(none_path)}))
            self.assertEqual(none.returncode, 0)
            self.assertEqual(none.stdout, "")

            malformed = self.run_script(SAVE_CANDIDATE, input_text="{}")
            self.assertEqual(malformed.returncode, 0)
            self.assertEqual(malformed.stdout, "")

    def test_save_candidate_suggest_suppresses_temporary_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.jsonl"
            rows = [
                {"message": {"content": [{"text": "一時的なメモ: 今回だけの決定"}]}},
                {"message": {"content": [{"text": "最終決定: ここに保存する"}]}},
            ]
            path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            result = self.run_script(SAVE_CANDIDATE, input_text=json.dumps({"transcript_path": str(path)}))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("一時的なメモ", result.stdout)
            self.assertIn("ここに保存する", result.stdout)

    FAKE_WRITE_GUARD = '''\
def route(description, attrs=None):
    if "REFUSEME" in description:
        return {"layer": "refused", "path_hint": "x", "format_hint": "y", "caveats": []}
    if "UNKNOWNME" in description:
        return {"layer": "unknown", "path_hint": "", "format_hint": "", "caveats": []}
    if "GARBAGEME" in description:
        return ["not", "a", "dict"]
    return {"layer": "fake-layer", "path_hint": "fake/path\\nsecond-line",
            "format_hint": "reason (ascii ref)", "caveats": []}
'''

    def test_save_candidate_suggest_route_edge_cases_via_fake_write_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-write-guard.py"
            fake.write_text(self.FAKE_WRITE_GUARD, encoding="utf-8")
            path = Path(tmp) / "transcript.jsonl"
            rows = [
                {"message": {"content": [{"text": "決定 REFUSEME はここ"}]}},
                {"message": {"content": [{"text": "決定 UNKNOWNME はここ"}]}},
                {"message": {"content": [{"text": "決定 GARBAGEME はここ"}]}},
                {"message": {"content": [{"text": "決定 NORMAL はここ"}]}},
            ]
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
            result = self.run_script(
                SAVE_CANDIDATE,
                input_text=json.dumps({"transcript_path": str(path)}),
                env={"FMA_WRITE_GUARD_PATH": str(fake)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
            # refused suppressed entirely; unknown + garbage fall back to heuristic
            self.assertNotIn("REFUSEME", result.stdout)
            self.assertEqual(len(lines), 3)
            self.assertIn("UNKNOWNME", lines[0])
            self.assertIn("family-vault 30_decisions", lines[0])
            self.assertIn("GARBAGEME", lines[1])
            self.assertIn("family-vault 30_decisions", lines[1])
            # normal fake route: newline flattened, ascii-paren spec ref stripped
            self.assertIn("NORMAL", lines[2])
            self.assertIn("fake-layer fake/path second-line（reason）", lines[2])

    def test_save_candidate_suggest_never_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            path = Path(tmp) / "transcript.jsonl"
            path.write_text(
                json.dumps({"message": {"content": [{"text": "最終決定: ここに保存する"}]}},
                           ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            result = self.run_script(
                SAVE_CANDIDATE,
                input_text=json.dumps({"transcript_path": str(path)}),
                env={"HOME": str(home)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("30_decisions", result.stdout)
            leftovers = [p for p in home.rglob("*") if p.is_file()]
            self.assertEqual(leftovers, [], f"hook persisted files: {leftovers}")

    def test_save_candidate_suggest_write_guard_unavailable_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.jsonl"
            rows = [
                {"message": {"content": [{"text": "最終決定: ここに保存する"}]}},
                {"message": {"content": [{"text": "実測でレイテンシが判明"}]}},
            ]
            path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            result = self.run_script(
                SAVE_CANDIDATE,
                input_text=json.dumps({"transcript_path": str(path)}),
                env={"FMA_WRITE_GUARD_PATH": str(Path(tmp) / "missing-write-guard")},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("write-guard unavailable", result.stderr)
            # heuristic fallback keeps suggesting
            self.assertIn("family-vault 30_decisions", result.stdout)
            self.assertIn("personal-wiki", result.stdout)

    def test_save_candidate_suggest_filters_secret_candidates(self):
        secret_value = "MEILI_MASTER_KEY=aBcDeF1234567890aBcDeF1234567890"  # secret-scan: allow
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.jsonl"
            rows = [
                {"message": {"content": [{"text": "方針: clean before"}]}},
                {"message": {"content": [{"text": f"決定: do not print {secret_value}"}]}},
                {"message": {"content": [{"text": "実測: clean after"}]}},
                {"message": {"content": [{"text": "今後は clean replacement"}]}},
            ]
            path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            result = self.run_script(SAVE_CANDIDATE, input_text=json.dumps({"transcript_path": str(path)}))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(secret_value, result.stdout)
            self.assertNotIn("do not print", result.stdout)
            self.assertIn("clean before", result.stdout)
            self.assertIn("clean after", result.stdout)

    def test_save_candidate_suggest_secret_scan_load_failure_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.jsonl"
            row = {"message": {"content": [{"text": "方針: clean but scanner missing"}]}}
            path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            result = self.run_script(
                SAVE_CANDIDATE,
                input_text=json.dumps({"transcript_path": str(path)}),
                env={"FMA_SECRET_SCAN_PATH": str(Path(tmp) / "missing-secret-scan")},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")

    def test_save_candidate_suggest_malformed_inputs_are_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.jsonl"
            cases = [
                "",
                "not json",
                "{}",
                json.dumps({"transcript_path": str(missing)}),
            ]
            for input_text in cases:
                with self.subTest(input_text=input_text):
                    result = self.run_script(SAVE_CANDIDATE, input_text=input_text)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, "")
            if hasattr(os, "mkfifo"):
                fifo = Path(tmp) / "transcript.fifo"
                os.mkfifo(fifo)
                result = self.run_script(SAVE_CANDIDATE, input_text=json.dumps({"transcript_path": str(fifo)}))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_save_candidate_suggest_tolerates_one_torn_final_jsonl_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.jsonl"
            valid = {"message": {"content": [{"text": "最終決定: torn tail の前は有効"}]}}
            path.write_text(
                json.dumps(valid, ensure_ascii=False) + "\n" + '{"message":',
                encoding="utf-8",
            )
            result = self.run_script(
                SAVE_CANDIDATE,
                input_text=json.dumps({"transcript_path": str(path)}),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("torn tail の前は有効", result.stdout)


class TelegramAlertTests(unittest.TestCase):
    """maybe_telegram / load_telegram_config (fma #31 telegram alert route)."""

    def setUp(self):
        loader = importlib.machinery.SourceFileLoader("watchdog_telegram_test", str(WATCHDOG))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.module = importlib.util.module_from_spec(spec)
        loader.exec_module(self.module)
        # module.urllib is the process-wide package — restore urlopen after each test
        self.addCleanup(
            setattr, self.module.urllib.request, "urlopen", self.module.urllib.request.urlopen
        )

    def use_env_file(self, tmp, text=None):
        path = Path(tmp) / "telegram.env"
        if text is not None:
            path.write_text(text, encoding="utf-8")
        os.environ["FMA_TELEGRAM_ENV"] = str(path)
        self.addCleanup(os.environ.pop, "FMA_TELEGRAM_ENV", None)
        return path

    def test_load_telegram_config_absent_file_is_silent_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.use_env_file(tmp, text=None)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertIsNone(self.module.load_telegram_config())
            self.assertEqual(stderr.getvalue(), "")

    def test_load_telegram_config_incomplete_warns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.use_env_file(tmp, "TELEGRAM_BOT_TOKEN=tok-123\n")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertIsNone(self.module.load_telegram_config())
            self.assertIn("missing TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID", stderr.getvalue())

    def test_load_telegram_config_parses_comments_and_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.use_env_file(
                tmp,
                "# monitoring bot\nTELEGRAM_BOT_TOKEN='tok-123'\nTELEGRAM_CHAT_ID=\"42\"\n\nnoise\n",
            )
            self.assertEqual(self.module.load_telegram_config(), ("tok-123", "42"))

    def test_load_telegram_config_keeps_mismatched_quotes_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.use_env_file(
                tmp,
                "TELEGRAM_BOT_TOKEN='tok\"123\nTELEGRAM_CHAT_ID=42'\n",
            )
            self.assertEqual(self.module.load_telegram_config(), ("'tok\"123", "42'"))

    def test_maybe_telegram_alerts_without_config_send_nothing(self):
        def must_not_call(*args, **kwargs):
            raise AssertionError("urlopen must not be called when telegram is unconfigured")

        with tempfile.TemporaryDirectory() as tmp:
            self.use_env_file(tmp, text=None)  # env var points at a missing file
            self.module.urllib.request.urlopen = must_not_call
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.module.maybe_telegram([{"id": "job-a", "reason": "heartbeat stale"}], "server")
            self.assertEqual(stderr.getvalue(), "")

    def test_maybe_telegram_non_utf8_env_file_warns_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "telegram.env"
            path.write_bytes(b"TELEGRAM_BOT_TOKEN=\xff\xfe\x00bad\n")
            os.environ["FMA_TELEGRAM_ENV"] = str(path)
            self.addCleanup(os.environ.pop, "FMA_TELEGRAM_ENV", None)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.module.maybe_telegram([{"id": "job-a", "reason": "heartbeat stale"}], "server")
            self.assertIn("telegram env unreadable", stderr.getvalue())

    def test_maybe_telegram_alert_missing_id_never_raises(self):
        sent = {}

        class FakeResponse:
            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout=None):
            sent["body"] = request.data.decode("utf-8")
            return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp:
            self.use_env_file(tmp, "TELEGRAM_BOT_TOKEN=tok-123\nTELEGRAM_CHAT_ID=42\n")
            self.module.urllib.request.urlopen = fake_urlopen
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.module.maybe_telegram([{"reason": "heartbeat stale"}], "server")
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn("unknown", sent["body"])

    def test_maybe_telegram_rejected_description_masks_token(self):
        class FakeResponse:
            def read(self):
                return b'{"ok": false, "error_code": 401, "description": "Unauthorized: tok-123 invalid"}'

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with tempfile.TemporaryDirectory() as tmp:
            self.use_env_file(tmp, "TELEGRAM_BOT_TOKEN=tok-123\nTELEGRAM_CHAT_ID=42\n")
            self.module.urllib.request.urlopen = lambda request, timeout=None: FakeResponse()
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.module.maybe_telegram([{"id": "job-a", "reason": "heartbeat stale"}], "server")
            message = stderr.getvalue()
            self.assertIn("telegram alert rejected: 401", message)
            self.assertIn("<token>", message)
            self.assertNotIn("tok-123", message)

    def test_maybe_telegram_non_json_response_warns_without_raising(self):
        class FakeResponse:
            def read(self):
                return b"<html>gateway error</html>"

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with tempfile.TemporaryDirectory() as tmp:
            self.use_env_file(tmp, "TELEGRAM_BOT_TOKEN=tok-123\nTELEGRAM_CHAT_ID=42\n")
            self.module.urllib.request.urlopen = lambda request, timeout=None: FakeResponse()
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.module.maybe_telegram([{"id": "job-a", "reason": "heartbeat stale"}], "server")
            self.assertIn("telegram alert failed", stderr.getvalue())

    def test_maybe_telegram_posts_alert_payload(self):
        sent = {}

        class FakeResponse:
            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout=None):
            sent["url"] = request.full_url
            sent["body"] = request.data.decode("utf-8")
            return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp:
            self.use_env_file(tmp, "TELEGRAM_BOT_TOKEN=tok-123\nTELEGRAM_CHAT_ID=42\n")
            self.module.urllib.request.urlopen = fake_urlopen
            alerts = [
                {"id": "job-a", "status": "alert", "reason": "heartbeat stale"},
                {"id": "job-b", "status": "alert", "reason": "fail_count 3"},
            ]
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.module.maybe_telegram(alerts, "server")
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn("bottok-123/sendMessage", sent["url"])
            self.assertIn("chat_id=42", sent["body"])
            self.assertIn("job-a", sent["body"])
            self.assertIn("job-b", sent["body"])

    def test_maybe_telegram_failure_never_raises_and_masks_token(self):
        def exploding_urlopen(request, timeout=None):
            raise OSError("boom tok-123 unreachable")

        with tempfile.TemporaryDirectory() as tmp:
            self.use_env_file(tmp, "TELEGRAM_BOT_TOKEN=tok-123\nTELEGRAM_CHAT_ID=42\n")
            self.module.urllib.request.urlopen = exploding_urlopen
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.module.maybe_telegram([{"id": "job-a", "reason": "heartbeat stale"}], "server")
            message = stderr.getvalue()
            self.assertIn("telegram alert failed", message)
            self.assertIn("<token>", message)
            self.assertNotIn("tok-123", message)

    def test_maybe_telegram_rejected_response_warns(self):
        class FakeResponse:
            def read(self):
                return b'{"ok": false, "error_code": 403, "description": "bot was blocked"}'

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with tempfile.TemporaryDirectory() as tmp:
            self.use_env_file(tmp, "TELEGRAM_BOT_TOKEN=tok-123\nTELEGRAM_CHAT_ID=42\n")
            self.module.urllib.request.urlopen = lambda request, timeout=None: FakeResponse()
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.module.maybe_telegram([{"id": "job-a", "reason": "heartbeat stale"}], "server")
            self.assertIn("telegram alert rejected: 403 bot was blocked", stderr.getvalue())

    def test_maybe_telegram_no_alerts_reads_nothing_sends_nothing(self):
        def must_not_call(*args, **kwargs):
            raise AssertionError("urlopen must not be called without alerts")

        self.module.urllib.request.urlopen = must_not_call
        os.environ["FMA_TELEGRAM_ENV"] = "/nonexistent/never-read.env"
        self.addCleanup(os.environ.pop, "FMA_TELEGRAM_ENV", None)
        self.module.maybe_telegram([], "server")


if __name__ == "__main__":
    unittest.main()
