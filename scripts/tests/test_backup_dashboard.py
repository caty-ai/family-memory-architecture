#!/usr/bin/env python3
"""Tests for the static family backup dashboard."""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = REPO_ROOT / "scripts" / "backup-dashboard"


def stamp(hours_ago=0):
    value = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def payload(job, status="ok", hours_ago=0, reason="", fail_count=0):
    data = {"job": job, "last_run": stamp(hours_ago), "status": status, "fail_count": fail_count, "duration_ms": 1, "docs": 0}
    if reason:
        data["reason"] = reason
    return data


class BackupDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("test_backup_dashboard", str(DASHBOARD))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.dashboard = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.dashboard)

    def manifest(self, root, jobs):
        lines = ["jobs:"]
        for job in jobs:
            lines.extend([
                f"  - id: {job['id']}", f"    desc: \"{job['id']}\"", f"    host: {job.get('host', 'laptop')}",
                f"    owner: {job.get('owner', 'agent-a')}", f"    period_hours: {job.get('period_hours', 1)}",
                f"    heartbeat: {job.get('heartbeat', job['id'] + '.json')}", "    alert: [stderr]",
            ])
            if job.get("repo"):
                lines.append(f"    repo: {job['repo']}")
        path = root / "jobs.yaml"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def generate(self, manifest, heartbeat_dir, out, dry_run=False, extra_args=None):
        args = ["--jobs", str(manifest), "--heartbeat-dir", str(heartbeat_dir), "--out", str(out), "--no-github"]
        if extra_args:
            args.extend(extra_args)
        if dry_run:
            args.append("--dry-run")
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            code = self.dashboard.main(args)
        self.assertEqual(code, 0)
        return captured.getvalue()

    def write_heartbeat(self, heartbeat_dir, job, **kwargs):
        heartbeat_dir.mkdir(exist_ok=True)
        (heartbeat_dir / f"{job}.json").write_text(json.dumps(payload(job, **kwargs)), encoding="utf-8")

    def test_states_ordering_and_neutral_host(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            jobs = [
                {"id": "ok", "owner": "agent-f"}, {"id": "missing", "owner": "agent-e"},
                {"id": "stale", "owner": "agent-g"}, {"id": "failed", "owner": "agent-a"},
                {"id": "remote", "host": "server", "owner": "agent-b"},
            ]
            manifest = self.manifest(root, jobs)
            hb = root / "heartbeats"
            self.write_heartbeat(hb, "ok")
            self.write_heartbeat(hb, "stale", hours_ago=3)
            self.write_heartbeat(hb, "failed", status="fail", fail_count=1)
            output = self.generate(manifest, hb, root / "index.html", dry_run=True)
            self.assertLess(output.index(">failed<"), output.index(">stale<"))
            self.assertLess(output.index(">stale<"), output.index(">missing<"))
            self.assertLess(output.index(">missing<"), output.index(">ok<"))
            self.assertIn("Not yet aggregated (neutral)", output)
            self.assertGreater(output.index("Not yet aggregated (neutral)"), output.index(">ok<"))
            self.assertIn("◻️ NO DATA", output)

    def test_existing_heartbeat_on_non_aggregated_host_is_evaluated_normally(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.manifest(root, [{"id": "server-ok", "host": "server", "owner": "agent-b"}])
            heartbeat_dir = root / "heartbeats"
            self.write_heartbeat(heartbeat_dir, "server-ok")

            output = self.generate(manifest, heartbeat_dir, root / "index.html", dry_run=True)

            self.assertIn("🟢 OK", output)
            self.assertIn(">server-ok<", output)
            self.assertNotIn("Not yet aggregated (neutral)", output)

    def test_corrupt_heartbeat_on_aggregated_host_is_no_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.manifest(root, [{"id": "corrupt"}])
            heartbeat_dir = root / "heartbeats"
            heartbeat_dir.mkdir()
            (heartbeat_dir / "corrupt.json").write_text("not valid json{", encoding="utf-8")

            output = self.generate(manifest, heartbeat_dir, root / "index.html", dry_run=True)

            self.assertIn('<tr class="state-no_data">', output)
            self.assertIn("◻️ NO DATA", output)

    def test_non_numeric_fail_count_on_aggregated_host_is_no_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.manifest(root, [{"id": "bad-fail-count"}])
            heartbeat_dir = root / "heartbeats"
            self.write_heartbeat(heartbeat_dir, "bad-fail-count", fail_count="not-a-number")

            output = self.generate(manifest, heartbeat_dir, root / "index.html", dry_run=True)

            self.assertIn('<tr class="state-no_data">', output)
            self.assertIn("◻️ NO DATA", output)

    def test_aggregated_hosts_override_moves_server_job_to_no_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.manifest(root, [{"id": "server-missing", "host": "server"}])
            heartbeat_dir = root / "heartbeats"

            output = self.generate(
                manifest, heartbeat_dir, root / "index.html", dry_run=True,
                extra_args=["--aggregated-hosts", "laptop,desktop,server"],
            )

            self.assertIn('<tr class="state-no_data">', output)
            self.assertIn("◻️ NO DATA", output)
            self.assertNotIn("Not yet aggregated (neutral)", output)

    def test_escaping_repo_dry_run_and_atomic_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.manifest(root, [{"id": "repo-job", "repo": "owner/name"}])
            hb = root / "heartbeats"
            self.write_heartbeat(hb, "repo-job", status="fail", reason="<script>alert(1)</script>")
            out = root / "nested" / "index.html"
            output = self.generate(manifest, hb, out, dry_run=True)
            self.assertFalse(out.exists())
            self.assertNotIn("<script>alert(1)</script>", output)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", output)
            self.assertIn('href="https://github.com/owner/name"', output)
            self.generate(manifest, hb, out)
            self.assertTrue(out.exists())
            self.assertTrue(out.read_text(encoding="utf-8").rstrip().endswith("</html>"))


if __name__ == "__main__":
    unittest.main()
