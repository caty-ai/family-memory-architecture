#!/usr/bin/env python3
"""Tests for scripts/hot-inbox-reader."""

import contextlib
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
READER_SCRIPT = REPO_ROOT / "scripts" / "hot-inbox-reader"


def load_module():
    loader = importlib.machinery.SourceFileLoader("hot_inbox_reader_under_test", str(READER_SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def event_name(ts="20260712T010000Z", owner="agent-a", kind="project", slug="note", suffix="aa11bb22"):
    return f"{ts}__{owner}__{kind}__{slug}__{suffix}.json"


class HotInboxReaderTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.inbox = root / "hot-inbox"
        self.state = root / "state"
        self.inbox.mkdir()
        # Spawn stub appends each received prompt to a capture file.
        self.prompt_capture = root / "prompts.txt"
        self.spawn_ok = [
            sys.executable,
            "-c",
            (
                "import sys, pathlib;"
                " p = pathlib.Path(sys.argv[1]);"
                " p.open('a').write(sys.argv[2] + chr(0));"
                " sys.exit(0)"
            ),
            str(self.prompt_capture),
        ]
        self.spawn_fail = [sys.executable, "-c", "import sys; sys.exit(3)"]

    def event(self, name):
        path = self.inbox / name
        event_id = name.removesuffix(".json")
        _, created_by, kind, _, _ = event_id.split("__")
        payload = {
            "schema_version": "family-hot-event/v0",
            "event_id": event_id,
            "created_at": "2026-07-12T01:00:00Z",
            "created_by": created_by,
            "class": 6,
            "kind": kind,
            "title": "Test event",
            "summary": "Reader fixture.",
            "owner": "agent-a",
            "priority": "P2",
            "promotion_pending": False,
            "related": [],
            "canonical_path": "family-vault/20_projects/test-event.md",
        }
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        return path

    def run_reader(self, spawn, extra=()):
        argv = [
            "--inbox-dir", str(self.inbox),
            "--self-owner", "agent-b",
            "--state-dir", str(self.state),
            *extra,
        ]
        if spawn is not None:
            argv += ["--", *spawn]
        return self.module.main(argv)

    def prompts(self):
        if not self.prompt_capture.exists():
            return []
        raw = self.prompt_capture.read_text(encoding="utf-8")
        return [p for p in raw.split(chr(0)) if p]

    def processed(self):
        directory = self.state / "processed"
        return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []

    def quarantined(self):
        directory = self.state / "quarantine"
        return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []

    def test_malformed_event_is_quarantined_skipped_and_batch_continues(self):
        bad = self.inbox / event_name(ts="20260712T010000Z", slug="bad-json")
        raw = b'{"schema_version": "family-hot-event/v0", broken\n'
        bad.write_bytes(raw)
        good = self.event(event_name(ts="20260712T020000Z", slug="good"))

        rc = self.run_reader(self.spawn_ok)

        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [good.name])
        self.assertEqual(len(self.prompts()), 1)
        quarantine_copy = self.state / "quarantine" / f"{bad.name}.corrupt"
        self.assertEqual(quarantine_copy.read_bytes(), raw)
        self.assertTrue((self.state / "quarantine" / bad.name).exists())

        # The copy is create-once and the marker prevents repeat processing.
        first_mtime = quarantine_copy.stat().st_mtime_ns
        self.assertEqual(self.run_reader(self.spawn_fail), 0)
        self.assertEqual(quarantine_copy.stat().st_mtime_ns, first_mtime)

    def test_secret_bearing_malformed_event_gets_metadata_only_quarantine(self):
        bad = self.inbox / event_name(slug="secret-json")
        secret = "github_pat_" + ("x" * 24)  # secret-scan: allow
        bad.write_text('{"token": "' + secret + '"', encoding="utf-8")

        rc = self.run_reader(self.spawn_ok)

        self.assertEqual(rc, 0)
        quarantine_copy = self.state / "quarantine" / f"{bad.name}.corrupt"
        metadata = json.loads(quarantine_copy.read_text(encoding="utf-8"))
        self.assertFalse(metadata["raw_preserved"])
        self.assertEqual(metadata["secret_scan"], "flagged")
        self.assertNotIn(secret, quarantine_copy.read_text(encoding="utf-8"))
        self.assertEqual(self.prompts(), [])

    def test_invalid_utf8_event_gets_metadata_only_quarantine_and_batch_continues(self):
        bad = self.inbox / event_name(ts="20260712T010000Z", slug="binary-garbage")
        raw = b"\xff\xfe\x00garbage\x80tail"
        bad.write_bytes(raw)
        good = self.event(event_name(ts="20260712T020000Z", slug="good-after-binary"))

        rc = self.run_reader(self.spawn_ok)

        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [good.name])
        self.assertEqual(len(self.prompts()), 1)
        quarantine_copy = self.state / "quarantine" / f"{bad.name}.corrupt"
        metadata = json.loads(quarantine_copy.read_text(encoding="utf-8"))
        self.assertEqual(metadata["source_name"], bad.name)
        self.assertEqual(metadata["size_bytes"], len(raw))
        self.assertFalse(metadata["raw_preserved"])
        self.assertEqual(metadata["secret_scan"], "error")
        self.assertTrue(metadata["reason"].startswith("invalid UTF-8 at byte "))
        self.assertTrue((self.state / "quarantine" / bad.name).exists())

    def test_secret_scanner_spawn_error_is_metadata_only_and_batch_continues(self):
        bad = self.inbox / event_name(ts="20260712T010000Z", slug="scan-spawn-error")
        secret = "github_pat_" + ("s" * 24)  # secret-scan: allow
        bad.write_text('{"token": "' + secret + '"', encoding="utf-8")
        good = self.event(event_name(ts="20260712T020000Z", slug="good-after-scan-error"))
        stderr = io.StringIO()

        with mock.patch.object(
            self.module.subprocess,
            "run",
            side_effect=FileNotFoundError("scanner-spawn-private-detail"),
        ), contextlib.redirect_stderr(stderr):
            rc = self.run_reader(self.spawn_ok)

        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [good.name])
        self.assertEqual(len(self.prompts()), 1)
        quarantine_copy = self.state / "quarantine" / f"{bad.name}.corrupt"
        persisted = quarantine_copy.read_text(encoding="utf-8")
        metadata = json.loads(persisted)
        self.assertFalse(metadata["raw_preserved"])
        self.assertEqual(metadata["secret_scan"], "error")
        self.assertNotIn(secret, persisted)
        self.assertNotIn(secret, stderr.getvalue())
        self.assertNotIn("scanner-spawn-private-detail", stderr.getvalue())

    def test_secret_scanner_timeout_is_metadata_only_and_batch_continues(self):
        bad = self.inbox / event_name(ts="20260712T010000Z", slug="scan-timeout")
        secret = "github_pat_" + ("t" * 24)  # secret-scan: allow
        bad.write_text('{"token": "' + secret + '"', encoding="utf-8")
        good = self.event(event_name(ts="20260712T020000Z", slug="good-after-timeout"))
        stderr = io.StringIO()

        with mock.patch.object(
            self.module.subprocess,
            "run",
            side_effect=self.module.subprocess.TimeoutExpired(
                "scanner-timeout-private-detail", 15
            ),
        ), contextlib.redirect_stderr(stderr):
            rc = self.run_reader(self.spawn_ok)

        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [good.name])
        self.assertEqual(len(self.prompts()), 1)
        quarantine_copy = self.state / "quarantine" / f"{bad.name}.corrupt"
        persisted = quarantine_copy.read_text(encoding="utf-8")
        metadata = json.loads(persisted)
        self.assertFalse(metadata["raw_preserved"])
        self.assertEqual(metadata["secret_scan"], "error")
        self.assertNotIn(secret, persisted)
        self.assertNotIn(secret, stderr.getvalue())
        self.assertNotIn("scanner-timeout-private-detail", stderr.getvalue())

    def test_unknown_event_schema_is_quarantined_not_dispatched(self):
        bad = self.event(event_name(slug="future-schema"))
        payload = json.loads(bad.read_text(encoding="utf-8"))
        payload["schema_version"] = "family-hot-event/v999"
        bad.write_text(json.dumps(payload) + "\n", encoding="utf-8")

        rc = self.run_reader(self.spawn_ok)

        self.assertEqual(rc, 0)
        self.assertTrue((self.state / "quarantine" / f"{bad.name}.corrupt").exists())
        self.assertEqual(self.prompts(), [])

    def test_corrupt_quarantine_retention_sweep_removes_expired_copy(self):
        bad = self.inbox / event_name(slug="old-corrupt")
        bad.write_text("{broken", encoding="utf-8")
        self.assertEqual(self.run_reader(self.spawn_ok), 0)
        quarantine_copy = self.state / "quarantine" / f"{bad.name}.corrupt"
        stale = time.time() - self.module.QUARANTINE_RETENTION_S - 60
        os.utime(quarantine_copy, (stale, stale))

        self.assertEqual(self.run_reader(self.spawn_fail), 0)
        self.assertFalse(quarantine_copy.exists())

    def test_migrate_legacy_state_copies_recognized_artifacts_once(self):
        legacy = Path(self.tmp.name) / "legacy-state"
        names = [event_name(ts=f"20260712T0{index}0000Z", slug=f"state-{index}") for index in range(1, 5)]
        artifacts = {
            Path(".lock"): "legacy lock\n",
            Path("processed") / names[0]: "",
            Path("attempts") / names[1]: "2\n",
            Path("quarantine") / names[2]: "",
            Path("staging") / names[3]: '{"legacy": true}\n',
        }
        for relative, contents in artifacts.items():
            path = legacy / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")

        copied = self.module.migrate_legacy_state(legacy, self.state)

        self.assertEqual(copied, len(artifacts))
        for relative, contents in artifacts.items():
            self.assertEqual((legacy / relative).read_text(encoding="utf-8"), contents)
            self.assertEqual((self.state / relative).read_text(encoding="utf-8"), contents)
        self.assertEqual(self.module.migrate_legacy_state(legacy, self.state), 0)

    def test_migrate_legacy_state_keeps_existing_destination(self):
        legacy = Path(self.tmp.name) / "legacy-state"
        relative = Path("processed") / event_name()
        (legacy / relative).parent.mkdir(parents=True)
        (legacy / relative).write_text("legacy\n", encoding="utf-8")
        (self.state / relative).parent.mkdir(parents=True)
        (self.state / relative).write_text("host-local\n", encoding="utf-8")

        copied = self.module.migrate_legacy_state(legacy, self.state)

        self.assertEqual(copied, 0)
        self.assertEqual((legacy / relative).read_text(encoding="utf-8"), "legacy\n")
        self.assertEqual((self.state / relative).read_text(encoding="utf-8"), "host-local\n")

    def test_migrate_legacy_state_skips_corrupt_raw_artifact_but_keeps_markers(self):
        legacy = Path(self.tmp.name) / "legacy-state"
        name = event_name(slug="legacy-secret")
        marker_path = legacy / "processed" / name
        marker_path.parent.mkdir(parents=True)
        marker_path.write_text("", encoding="utf-8")
        secret = "github_" + "pat_" + ("m" * 24)
        corrupt_path = legacy / "quarantine" / f"{name}.corrupt"
        corrupt_path.parent.mkdir(parents=True)
        corrupt_path.write_text('{"token": "' + secret + '"', encoding="utf-8")

        copied = self.module.migrate_legacy_state(legacy, self.state)

        self.assertEqual(copied, 1)
        self.assertTrue((self.state / "processed" / name).exists())
        self.assertFalse((self.state / "quarantine" / f"{name}.corrupt").exists())
        for migrated in self.state.rglob("*"):
            if migrated.is_file():
                self.assertNotIn(secret, migrated.read_text(encoding="utf-8"))

    def test_migrate_legacy_state_with_no_artifacts_is_noop(self):
        legacy = Path(self.tmp.name) / "empty-legacy-state"
        legacy.mkdir()

        copied = self.module.migrate_legacy_state(legacy, self.state)

        self.assertEqual(copied, 0)
        self.assertTrue(legacy.is_dir())
        self.assertFalse(self.state.exists())

    def test_legacy_state_dir_cli_migrates_before_event_scan(self):
        legacy = Path(self.tmp.name) / "legacy-state"
        target = self.event(event_name())
        marker = legacy / "processed" / target.name
        marker.parent.mkdir(parents=True)
        marker.write_text("", encoding="utf-8")

        rc = self.run_reader(self.spawn_fail, extra=["--legacy-state-dir", str(legacy)])

        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [target.name])
        self.assertTrue(marker.exists())

    def test_no_events_exits_zero_without_spawn(self):
        rc = self.run_reader(self.spawn_fail)  # would exit 3 if spawned
        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [])

    def test_own_events_are_excluded_by_owner_field(self):
        self.event(event_name(owner="agent-b"))
        # Owner match must be on the owner field, not substring anywhere.
        other = self.event(event_name(ts="20260712T020000Z", owner="agent-e", slug="agent-b"))
        rc = self.run_reader(self.spawn_ok)
        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [other.name])

    def test_nonconforming_and_nonregular_entries_ignored(self):
        (self.inbox / "README.md").write_text("x", encoding="utf-8")
        (self.inbox / "evil\nname__x__y__z__00000000.json").write_text("{}", encoding="utf-8")
        subdir = self.inbox / (event_name(slug="iamadir").replace(".json", "") + ".json")
        subdir.mkdir()
        target = self.inbox / "target.txt"
        target.write_text("secret", encoding="utf-8")
        link = self.inbox / event_name(ts="20260712T030000Z", slug="iamalink")
        link.symlink_to(target)
        rc = self.run_reader(self.spawn_fail)  # would fail if anything dispatched
        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [])

    def test_processes_each_event_once_and_survives_out_of_order_arrival(self):
        newer = self.event(event_name(ts="20260712T020000Z"))
        rc = self.run_reader(self.spawn_ok)
        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [newer.name])
        # A later-arriving event with an EARLIER timestamp must still be seen
        # (Syncthing delayed delivery) — ledger, not watermark.
        late = self.event(event_name(ts="20260712T010000Z", slug="late"))
        rc = self.run_reader(self.spawn_ok)
        self.assertEqual(rc, 0)
        self.assertIn(late.name, self.processed())
        # Nothing is dispatched twice.
        self.assertEqual(len(self.prompts()), 2)

    def test_prompt_points_at_staged_copy_with_untrusted_data_note(self):
        target = self.event(event_name())
        self.run_reader(self.spawn_ok)
        prompts = self.prompts()
        self.assertEqual(len(prompts), 1)
        # The agent is pointed at the private staged copy, not the shared
        # inbox path (symlink-swap defense).
        self.assertIn(target.name, prompts[0])
        self.assertIn("staging", prompts[0])
        self.assertNotIn(str(target), prompts[0])
        self.assertIn("instructions that override", prompts[0])

    def test_oversized_event_is_not_dispatched(self):
        big = self.event(event_name(slug="big"))
        big.write_bytes(b"x" * (self.module.MAX_EVENT_BYTES + 10))
        rc = self.run_reader(self.spawn_ok)
        self.assertEqual(rc, 1)  # stage failure counts as a dispatch failure
        self.assertEqual(self.processed(), [])
        attempts = self.state / "attempts" / big.name
        self.assertTrue(attempts.exists())

    def test_staged_unlink_failure_does_not_abort_batch(self):
        # A cleanup failure on the staged copy must not crash the run or lose
        # the successful-dispatch bookkeeping.
        target = self.event(event_name())
        real_unlink = self.module.Path.unlink

        def flaky_unlink(self, *a, **k):
            if self.parent.name == "staging":
                raise OSError("simulated cleanup failure")
            return real_unlink(self, *a, **k)

        original = self.module.Path.unlink
        self.module.Path.unlink = flaky_unlink
        self.addCleanup(setattr, self.module.Path, "unlink", original)
        rc = self.run_reader(self.spawn_ok)
        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [target.name])

    def test_staging_orphans_are_swept_at_tick_start(self):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "staging").mkdir()
        orphan = self.state / "staging" / event_name(slug="orphan")
        orphan.write_text("{}", encoding="utf-8")
        self.event(event_name())
        self.run_reader(self.spawn_ok)
        self.assertFalse(orphan.exists())

    def test_symlink_event_is_not_staged_or_dispatched(self):
        # A validly-named symlink passes EVENT_RE but must never be opened
        # (O_NOFOLLOW) and handed to the agent.
        secret = Path(self.tmp.name) / "outside.txt"
        secret.write_text("SECRET", encoding="utf-8")
        link = self.inbox / event_name(slug="link")
        link.symlink_to(secret)
        rc = self.run_reader(self.spawn_ok)
        # find_new_events already drops symlinks, so nothing is dispatched.
        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [])
        self.assertEqual(self.prompts(), [])

    def test_stage_rejects_nonregular_file_swapped_in_at_open_time(self):
        event = self.event(event_name(slug="opened-fifo"))
        read_fd, write_fd = os.pipe()
        try:
            with mock.patch.object(self.module.os, "open", return_value=read_fd):
                status, staged, corrupt_data, reason = self.module.stage_event(
                    self.state, event
                )
        finally:
            os.close(write_fd)

        self.assertEqual(status, "error")
        self.assertIsNone(staged)
        self.assertIsNone(corrupt_data)
        self.assertIsNone(reason)

    def test_failure_stops_batch_and_retries_then_quarantines(self):
        bad = self.event(event_name(ts="20260712T010000Z", slug="poison"))
        good = self.event(event_name(ts="20260712T020000Z", slug="fine"))
        for attempt in (1, 2):
            rc = self.run_reader(self.spawn_fail, extra=["--max-attempts", "3"])
            self.assertEqual(rc, 1)
            self.assertEqual(self.processed(), [])  # good was never reached
            self.assertEqual(self.quarantined(), [])
        rc = self.run_reader(self.spawn_fail, extra=["--max-attempts", "3"])
        self.assertEqual(rc, 1)
        self.assertEqual(self.quarantined(), [bad.name])
        # After quarantine, the next tick reaches the good event.
        rc = self.run_reader(self.spawn_ok, extra=["--max-attempts", "3"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [good.name])

    def test_success_clears_attempt_counter(self):
        target = self.event(event_name())
        self.run_reader(self.spawn_fail)
        attempts = self.state / "attempts" / target.name
        self.assertTrue(attempts.exists())
        self.run_reader(self.spawn_ok)
        self.assertFalse(attempts.exists())
        self.assertEqual(self.processed(), [target.name])

    def test_max_events_bounds_dispatch_per_tick(self):
        for i in range(1, 4):
            self.event(event_name(ts=f"20260712T0{i}0000Z", slug=f"n{i}"))
        rc = self.run_reader(self.spawn_ok, extra=["--max-events", "2"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.processed()), 2)
        rc = self.run_reader(self.spawn_ok, extra=["--max-events", "2"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.processed()), 3)

    def test_held_flock_skips_tick(self):
        self.event(event_name())
        self.state.mkdir(parents=True, exist_ok=True)
        holder = (self.state / ".lock").open("w")
        self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rc = self.run_reader(self.spawn_fail)  # would fail if dispatched
        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [])

    def test_leftover_unheld_lock_file_does_not_block(self):
        # flock dies with its holder: an existing but unheld lock file (e.g.
        # from a crashed run) must not block acquisition.
        target = self.event(event_name())
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / ".lock").write_text("", encoding="utf-8")
        rc = self.run_reader(self.spawn_ok)
        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [target.name])

    def test_timeout_kills_session_and_counts_attempt(self):
        target = self.event(event_name())
        hang = [sys.executable, "-c", "import time; time.sleep(30)"]
        rc = self.run_reader(hang, extra=["--timeout", "1"])
        self.assertEqual(rc, 1)
        self.assertEqual(self.processed(), [])
        attempts = (self.state / "attempts" / target.name).read_text(encoding="utf-8")
        self.assertEqual(attempts.strip(), "1")

    def test_timeout_sweeps_descendants_that_ignore_sigterm(self):
        self.event(event_name())
        pid_file = Path(self.tmp.name) / "grandchild.pid"
        # Child spawns a SIGTERM-ignoring grandchild, records its pid, hangs.
        stubborn = [
            sys.executable,
            "-c",
            (
                "import os, sys, subprocess, time;"
                " p = subprocess.Popen([sys.executable, '-c',"
                " 'import signal, time;"
                " signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                " time.sleep(60)']);"
                " open(sys.argv[1], 'w').write(str(p.pid));"
                " time.sleep(60)"
            ),
            str(pid_file),
        ]
        rc = self.run_reader(stubborn, extra=["--timeout", "2"])
        self.assertEqual(rc, 1)
        grandchild = int(pid_file.read_text(encoding="utf-8"))
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(grandchild, 0)

    def test_ledger_gc_keeps_fresh_markers_against_syncthing_flap(self):
        target = self.event(event_name())
        self.run_reader(self.spawn_ok)
        self.assertEqual(self.processed(), [target.name])
        target.unlink()
        self.run_reader(self.spawn_ok)
        # Freshly processed marker must survive a transient disappearance...
        self.assertEqual(self.processed(), [target.name])
        # ...so a resurrected event is NOT re-dispatched.
        self.event(target.name)
        self.run_reader(self.spawn_fail)  # would fail if re-dispatched
        self.assertEqual(self.processed(), [target.name])

    def test_present_event_refreshes_old_marker_against_flap(self):
        # Marker mtime = "last seen present". An old marker whose event is
        # still present gets refreshed, so a later one-tick flap cannot GC it.
        target = self.event(event_name())
        self.run_reader(self.spawn_ok)
        markpath = self.state / "processed" / target.name
        old = time.time() - self.module.GC_RETENTION_S - 60
        os.utime(markpath, (old, old))
        self.run_reader(self.spawn_ok)  # event present -> refresh
        target.unlink()
        self.run_reader(self.spawn_fail)  # would fail if re-dispatched
        self.assertEqual(self.processed(), [target.name])

    def test_ledger_gc_drops_markers_past_retention(self):
        target = self.event(event_name())
        self.run_reader(self.spawn_ok)
        target.unlink()
        stale = time.time() - self.module.GC_RETENTION_S - 60
        markpath = self.state / "processed" / target.name
        os.utime(markpath, (stale, stale))
        self.run_reader(self.spawn_ok)
        self.assertEqual(self.processed(), [])

    def test_dry_run_never_spawns_or_marks(self):
        self.event(event_name())
        rc = self.run_reader(None, extra=["--dry-run"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.processed(), [])
        self.assertEqual(self.prompts(), [])

    def test_missing_inbox_dir_is_an_error(self):
        rc = self.module.main(
            [
                "--inbox-dir", str(self.inbox / "nope"),
                "--self-owner", "agent-b",
                "--state-dir", str(self.state),
                "--", *self.spawn_ok,
            ]
        )
        self.assertEqual(rc, 2)

    def test_invalid_arguments_rejected(self):
        for extra in (["--max-events", "0"], ["--timeout", "0"], ["--max-attempts", "0"]):
            with self.assertRaises(SystemExit) as ctx:
                self.run_reader(self.spawn_ok, extra=extra)
            self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
