#!/usr/bin/env python3
"""Tests for scripts/capture-shipper."""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CAPTURE_SHIPPER = REPO_ROOT / "scripts" / "capture-shipper"


def load_module():
    loader = importlib.machinery.SourceFileLoader("capture_shipper_under_test", str(CAPTURE_SHIPPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def write_record(path, **overrides):
    record = {
        "ts": "2026-07-07T00:00:00Z",
        "event": "message_received",
        "sessionKey": "session-1",
        "agentId": "agent-g",
        "content": "hello memory",
    }
    record.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(json.dumps(record, separators=(",", ":")).encode("utf-8") + b"\n")
    return record


class CaptureShipperTests(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(CAPTURE_SHIPPER), *map(str, args)],
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def write_env(self, path, base_url, mode=0o600):
        path.write_text(
            "\n".join(
                [
                    "SUPERMEMORY_API_" + "KEY=local-test-key",
                    f"SUPERMEMORY_API_BASE={base_url}",
                    "SUPERMEMORY_CONTAINER=personal-test",
                    "SUPERMEMORY_ADD_PATH=/v3/documents",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        os.chmod(path, mode)
        return path

    def run_module(self, argv, requests, post_func=None):
        module = load_module()

        def fake_post(url, api_key, payload):
            requests.append({"url": url, "api_key": api_key, "body": payload})
            return 200

        original_sleep = module.time.sleep
        module.post_payload = post_func or fake_post
        module.time.sleep = lambda _seconds: None
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = module.main([str(item) for item in argv])
        finally:
            module.time.sleep = original_sleep
        return code, stdout.getvalue(), stderr.getvalue()

    def test_clean_record_posts_expected_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            record = write_record(spool / "2026-07-07.jsonl")
            requests = []

            code, stdout, stderr = self.run_module(["--spool", spool, "--env-file", env_file], requests)

            self.assertEqual(code, 0, stdout + stderr)
            self.assertEqual(len(requests), 1)
            request = requests[0]
            self.assertEqual(request["url"], "https://supermemory.test/v3/documents")
            self.assertEqual(request["api_key"], "local-test-key")
            body = request["body"]
            self.assertEqual(body["content"], record["content"])
            self.assertEqual(body["containerTags"], ["personal-test"])
            self.assertEqual(body["metadata"]["event"], "message_received")
            self.assertEqual(body["metadata"]["sessionKey"], "session-1")
            self.assertRegex(body["metadata"]["idempotencyKey"], r"^[0-9a-f]{64}$")
            self.assertTrue((spool / "sent" / "2026-07-07.jsonl").exists())

    def test_secret_record_is_quarantined_and_redacted_before_send(self):
        secret = "gh" + "p_" + "1234567890abcdefABCDEF1234567890abcd"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            write_record(spool / "2026-07-07.jsonl", content=f"token {secret}")
            requests = []

            code, stdout, stderr = self.run_module(["--spool", spool, "--env-file", env_file], requests)

            self.assertEqual(code, 0, stdout + stderr)
            body = requests[0]["body"]
            self.assertEqual(body["content"], "token <REDACTED:high-entropy>")
            self.assertNotIn(secret, json.dumps(body))
            quarantine_dir = spool / "quarantine"
            quarantine_file = quarantine_dir / "2026-07-07.jsonl"
            self.assertEqual(stat.S_IMODE(quarantine_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(quarantine_file.stat().st_mode), 0o600)
            self.assertIn(secret, quarantine_file.read_text(encoding="utf-8"))

    def test_unsafe_metadata_secret_is_redacted_before_send(self):
        secret = "gh" + "p_" + "1234567890abcdefABCDEF1234567890abcd"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            write_record(spool / "2026-07-07.jsonl", sessionKey=secret)
            requests = []

            code, stdout, stderr = self.run_module(["--spool", spool, "--env-file", env_file], requests)

            self.assertEqual(code, 0, stdout + stderr)
            self.assertEqual(len(requests), 1)
            body = requests[0]["body"]
            self.assertEqual(body["content"], "hello memory")
            self.assertEqual(body["metadata"]["sessionKey"], "<REDACTED:high-entropy>")
            self.assertNotIn(secret, json.dumps(body))

    def test_metadata_scan_exit_three_fails_closed_without_advancing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            spool_file = spool / "2026-07-07.jsonl"
            write_record(spool_file, event="bad!")
            stub_scan = root / "secret-scan-stub"
            stub_scan.write_text(
                "import sys\n"
                "text = sys.stdin.read()\n"
                "if text == 'bad!':\n"
                "    sys.exit(3)\n"
                "sys.stdout.write(text)\n"
                "sys.exit(0)\n",
                encoding="utf-8",
            )

            module = load_module()
            module.SECRET_SCAN = stub_scan
            requests = []

            def fake_post(url, api_key, payload):
                requests.append(payload)
                return 200

            module.post_payload = fake_post
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = module.main(["--spool", str(spool), "--env-file", str(env_file)])

            self.assertEqual(code, 1)
            self.assertEqual(requests, [])
            self.assertIn("secret-scan failed", stderr.getvalue())
            self.assertTrue(spool_file.exists())
            self.assertFalse((spool / "sent" / "2026-07-07.jsonl").exists())
            self.assertFalse((spool / "2026-07-07.jsonl.offset").exists())
            metrics = (spool / "metrics.log").read_text(encoding="utf-8").strip().splitlines()[-1]
            self.assertIn("failed=1", metrics)

    def test_normal_metadata_is_not_scanned_per_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            record = write_record(
                spool / "2026-07-07.jsonl",
                event="message_received",
                ts="2026-07-07T12:34:56Z",
                sessionKey="sess-2026-07-07-abc123",
                agentId="agent.agent-a-1",
            )
            module = load_module()
            requests = []
            calls = []

            def fake_scan(content):
                calls.append(content)
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            def fake_post(url, api_key, payload):
                requests.append(payload)
                return 200

            module.scan_content = fake_scan
            module.post_payload = fake_post
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = module.main(["--spool", str(spool), "--env-file", str(env_file)])

            self.assertEqual(code, 0, stdout.getvalue() + stderr.getvalue())
            self.assertEqual(calls, [record["content"]])
            metadata = requests[0]["metadata"]
            self.assertEqual(metadata["event"], record["event"])
            self.assertEqual(metadata["ts"], record["ts"])
            self.assertEqual(metadata["sessionKey"], record["sessionKey"])
            self.assertEqual(metadata["agentId"], record["agentId"])

    def test_scan_content_uses_utf8_under_c_locale(self):
        module = load_module()
        original_environ = os.environ.copy()
        try:
            os.environ.clear()
            os.environ.update({"LC_ALL": "C", "LANG": "C", "PATH": original_environ.get("PATH", "")})
            scan = module.scan_content("家族のウェビナー記録を安全に保存します")
        finally:
            os.environ.clear()
            os.environ.update(original_environ)

        self.assertEqual(scan.returncode, 0, scan.stderr)
        self.assertEqual(scan.stdout, "家族のウェビナー記録を安全に保存します")

    def test_secret_scan_exit_three_fails_closed_without_advancing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            spool_file = spool / "2026-07-07.jsonl"
            write_record(spool_file, content="first")
            write_record(spool_file, content="second")
            stub_scan = root / "secret-scan-stub"
            stub_scan.write_text("import sys\nsys.stdin.read()\nsys.exit(3)\n", encoding="utf-8")

            module = load_module()
            module.SECRET_SCAN = stub_scan
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = module.main(["--spool", str(spool), "--env-file", str(env_file)])

            self.assertEqual(code, 1)
            self.assertIn("failed closed", stderr.getvalue())
            self.assertTrue(spool_file.exists())
            self.assertFalse((spool / "sent" / "2026-07-07.jsonl").exists())
            self.assertFalse((spool / "2026-07-07.jsonl.offset").exists())

    def test_offset_resume_does_not_skip_or_double_ship(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            spool_file = spool / "2026-07-07.jsonl"
            write_record(spool_file, ts="2026-07-07T00:00:00Z", content="one")
            write_record(spool_file, ts="2026-07-07T00:00:01Z", content="two")
            requests = []

            first_code, first_stdout, first_stderr = self.run_module(
                ["--spool", spool, "--env-file", env_file, "--max-batch", "1"],
                requests,
            )
            second_code, second_stdout, second_stderr = self.run_module(["--spool", spool, "--env-file", env_file], requests)

            self.assertEqual(first_code, 0, first_stdout + first_stderr)
            self.assertEqual(second_code, 0, second_stdout + second_stderr)
            self.assertEqual([item["body"]["content"] for item in requests], ["one", "two"])
            self.assertTrue((spool / "sent" / "2026-07-07.jsonl").exists())
            self.assertFalse((spool / "2026-07-07.jsonl.offset").exists())

    def test_empty_content_record_is_skipped_and_does_not_block_following_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            spool_file = spool / "2026-07-07.jsonl"
            write_record(spool_file, event="register", sessionKey="", agentId="", content="")
            write_record(spool_file, ts="2026-07-07T00:00:01Z", content="first real")
            write_record(spool_file, ts="2026-07-07T00:00:02Z", content="second real")
            requests = []

            code, stdout, stderr = self.run_module(["--spool", spool, "--env-file", env_file], requests)

            self.assertEqual(code, 0, stdout + stderr)
            self.assertEqual([item["body"]["content"] for item in requests], ["first real", "second real"])
            metrics = (spool / "metrics.log").read_text(encoding="utf-8").strip().splitlines()[-1]
            self.assertIn("quarantined=0 skipped=1 failed=0", metrics)
            self.assertTrue((spool / "sent" / "2026-07-07.jsonl").exists())
            self.assertFalse(spool_file.exists())
            self.assertFalse((spool / "2026-07-07.jsonl.offset").exists())

    def test_empty_content_record_dry_run_does_not_post_advance_offset_or_move_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            spool_file = spool / "2026-07-07.jsonl"
            write_record(spool_file, event="register", sessionKey="", agentId="", content="")
            write_record(spool_file, ts="2026-07-07T00:00:01Z", content="first real")
            write_record(spool_file, ts="2026-07-07T00:00:02Z", content="second real")
            requests = []

            def unexpected_post(url, api_key, payload):
                requests.append(payload)
                raise AssertionError("dry-run must not POST")

            code, stdout, stderr = self.run_module(
                ["--spool", spool, "--env-file", env_file, "--dry-run"],
                requests,
                unexpected_post,
            )

            self.assertEqual(code, 0, stdout + stderr)
            self.assertEqual(requests, [])
            self.assertIn("dry-run would send", stderr)
            self.assertTrue(spool_file.exists())
            self.assertFalse((spool / "2026-07-07.jsonl.offset").exists())
            self.assertFalse((spool / "sent" / "2026-07-07.jsonl").exists())

    def test_metrics_line_matches_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            write_record(spool / "2026-07-07.jsonl", content="hello")
            requests = []

            code, stdout, stderr = self.run_module(["--spool", spool, "--env-file", env_file], requests)

            self.assertEqual(code, 0, stdout + stderr)
            metrics = (spool / "metrics.log").read_text(encoding="utf-8").strip().splitlines()[-1]
            self.assertRegex(
                metrics,
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z \| files=1 records=1 sent=1 redacted=0 quarantined=0 skipped=0 failed=0 bytes_sent=5$",
            )

    def test_env_file_must_be_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            write_record(spool / "2026-07-07.jsonl", content="hello")
            env_file = self.write_env(root / "env", "https://supermemory.test", mode=0o644)

            result = self.run_script("--spool", spool, "--env-file", env_file)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expected 0600", result.stderr)

    def test_retry_on_5xx_then_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            write_record(spool / "2026-07-07.jsonl")
            attempts = []

            def flaky_post(url, api_key, payload):
                attempts.append(payload["content"])
                if len(attempts) < 3:
                    raise urllib.error.HTTPError(url, 500, "server error", hdrs=None, fp=None)
                return 200

            code, stdout, stderr = self.run_module(["--spool", spool, "--env-file", env_file], [], flaky_post)

            self.assertEqual(code, 0, stdout + stderr)
            self.assertEqual(attempts, ["hello memory", "hello memory", "hello memory"])
            self.assertTrue((spool / "sent" / "2026-07-07.jsonl").exists())

    def test_retry_on_urlerror_exhaustion_leaves_record_in_spool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            spool_file = spool / "2026-07-07.jsonl"
            write_record(spool_file)
            attempts = []

            def failing_post(url, api_key, payload):
                attempts.append(payload["content"])
                raise urllib.error.URLError("connection refused")

            code, stdout, stderr = self.run_module(["--spool", spool, "--env-file", env_file], [], failing_post)

            self.assertEqual(code, 1, stdout + stderr)
            self.assertEqual(attempts, ["hello memory", "hello memory", "hello memory"])
            self.assertIn("send failed", stderr)
            self.assertTrue(spool_file.exists())
            self.assertFalse((spool / "sent" / "2026-07-07.jsonl").exists())
            self.assertFalse((spool / "2026-07-07.jsonl.offset").exists())

    def test_no_retry_on_4xx(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            write_record(spool / "2026-07-07.jsonl")
            attempts = []

            def rejected_post(url, api_key, payload):
                attempts.append(payload["content"])
                raise urllib.error.HTTPError(url, 400, "bad request", hdrs=None, fp=None)

            code, stdout, stderr = self.run_module(["--spool", spool, "--env-file", env_file], [], rejected_post)

            self.assertEqual(code, 1, stdout + stderr)
            self.assertEqual(attempts, ["hello memory"])
            self.assertIn("send failed", stderr)
            self.assertIn("HTTPError 400", stderr)

    def test_dry_run_does_not_post_advance_offset_or_move_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            spool_file = spool / "2026-07-07.jsonl"
            write_record(spool_file)
            requests = []

            def unexpected_post(url, api_key, payload):
                requests.append(payload)
                raise AssertionError("dry-run must not POST")

            code, stdout, stderr = self.run_module(["--spool", spool, "--env-file", env_file, "--dry-run"], requests, unexpected_post)

            self.assertEqual(code, 0, stdout + stderr)
            self.assertEqual(requests, [])
            self.assertIn("dry-run would send", stderr)
            self.assertTrue(spool_file.exists())
            self.assertFalse((spool / "2026-07-07.jsonl.offset").exists())
            self.assertFalse((spool / "sent" / "2026-07-07.jsonl").exists())

    def test_decode_error_is_quarantined_and_following_record_is_processed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            spool_file = spool / "2026-07-07.jsonl"
            spool_file.parent.mkdir(parents=True, exist_ok=True)
            bad_line = b'{"content": "unterminated"\n'
            with spool_file.open("ab") as handle:
                handle.write(bad_line)
            write_record(spool_file, content="first valid")
            write_record(spool_file, content="second valid")
            requests = []

            code, stdout, stderr = self.run_module(
                ["--spool", spool, "--env-file", env_file, "--max-batch", "1"],
                requests,
            )

            self.assertEqual(code, 1, stdout + stderr)
            self.assertIn("invalid spool record", stderr)
            self.assertEqual([item["body"]["content"] for item in requests], ["first valid"])
            quarantine_files = list((spool / "quarantine").glob("*.jsonl"))
            self.assertEqual(len(quarantine_files), 1)
            self.assertEqual(quarantine_files[0].read_bytes(), bad_line)
            offset = int((spool / "2026-07-07.jsonl.offset").read_text(encoding="utf-8").strip())
            self.assertGreater(offset, len(bad_line))
            metrics = (spool / "metrics.log").read_text(encoding="utf-8").strip().splitlines()[-1]
            self.assertIn("failed=1", metrics)

    def test_offset_beyond_eof_leaves_file_in_spool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "https://supermemory.test")
            spool_file = spool / "2026-07-07.jsonl"
            write_record(spool_file)
            (spool / "2026-07-07.jsonl.offset").write_text("999999\n", encoding="utf-8")
            requests = []

            code, stdout, stderr = self.run_module(["--spool", spool, "--env-file", env_file], requests)

            self.assertEqual(code, 1, stdout + stderr)
            self.assertEqual(requests, [])
            self.assertIn("offset 999999 is beyond current size", stderr)
            self.assertTrue(spool_file.exists())
            self.assertFalse((spool / "sent" / "2026-07-07.jsonl").exists())
            metrics = (spool / "metrics.log").read_text(encoding="utf-8").strip().splitlines()[-1]
            self.assertIn("failed=1", metrics)

    def test_http_non_localhost_url_is_refused_before_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "spool"
            env_file = self.write_env(root / "env", "http://example.test")
            write_record(spool / "2026-07-07.jsonl")
            requests = []

            code, stdout, stderr = self.run_module(["--spool", spool, "--env-file", env_file], requests)

            self.assertEqual(code, 1, stdout + stderr)
            self.assertEqual(requests, [])
            self.assertIn("unsupported scheme/host", stderr)

    def test_localhost_http_urls_are_allowed_for_tests(self):
        for base_url in ("http://127.0.0.1:8080", "http://localhost:8080"):
            with self.subTest(base_url=base_url), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                spool = root / "spool"
                env_file = self.write_env(root / "env", base_url)
                write_record(spool / "2026-07-07.jsonl")
                requests = []

                code, stdout, stderr = self.run_module(["--spool", spool, "--env-file", env_file], requests)

                self.assertEqual(code, 0, stdout + stderr)
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0]["url"], f"{base_url}/v3/documents")


if __name__ == "__main__":
    unittest.main()
