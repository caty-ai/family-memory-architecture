#!/usr/bin/env python3
"""Tests for scripts/meili-ingest."""

import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MEILI_INGEST_SCRIPT = REPO_ROOT / "scripts" / "meili-ingest"
MANIFEST = REPO_ROOT / "manifests" / "meilisearch-indexes.yaml"


def load_module():
    loader = importlib.machinery.SourceFileLoader("meili_ingest_under_test", str(MEILI_INGEST_SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def write_file(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_family_hot_bytes(body_bytes):
    marker = b"<!-- GENERATED-FILE: family-hot.md; DO NOT EDIT BY HAND -->\n"
    placeholder_meta = (
        b"<!-- generator: family-hot-generator v0; sources_sha256: "
        + (b"0" * 64)
        + b"; body_sha256: "
        + (b"0" * 64)
        + b" -->\n"
    )
    placeholder = marker + placeholder_meta + body_bytes
    lines = placeholder.splitlines(keepends=True)
    body_sha256 = hashlib.sha256(b"".join(lines[:1] + lines[2:])).hexdigest()
    meta = (
        b"<!-- generator: family-hot-generator v0; sources_sha256: "
        + (b"0" * 64)
        + b"; body_sha256: "
        + body_sha256.encode("ascii")
        + b" -->\n"
    )
    return marker + meta + body_bytes


class FakeResponse:
    def __init__(self, body=b"{}"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


class MeiliIngestTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def run_main(self, argv, env=None):
        old_env = os.environ.copy()
        os.environ.clear()
        if env:
            os.environ.update(env)
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = self.module.main(argv)
        finally:
            os.environ.clear()
            os.environ.update(old_env)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_manifest_gate_refuses_unknown_reserved_and_active_existing(self):
        cases = [
            ("nonexistent-index", "not present"),
            ("agent-shared-summaries-{agent}", "reserved"),
            ("kg-entities", "active-existing"),
        ]
        with tempfile.TemporaryDirectory() as hb:
            for uid, expected in cases:
                code, _, stderr = self.run_main(
                    [uid, "--dry-run", "--manifest", str(MANIFEST)],
                    env={"FMA_HEARTBEAT_DIR": hb},
                )
                self.assertEqual(code, 2, stderr)
                self.assertIn(expected, stderr)

    def test_invalid_uid_uses_sentinel_heartbeat_without_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hb = root / "hb"
            code, _, stderr = self.run_main(
                ["../../../x/evil", "--dry-run", "--manifest", str(MANIFEST)],
                env={"FMA_HEARTBEAT_DIR": str(hb)},
            )
            self.assertEqual(code, 2, stderr)
            self.assertIn("not present", stderr)
            self.assertFalse((root / "x" / "evil.json").exists())
            sentinel = hb / "meili-ingest-_invalid-uid.json"
            self.assertTrue(sentinel.exists())
            heartbeat = json.loads(sentinel.read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["status"], "fail")
            self.assertIn("../../../x/evil", heartbeat["reason"])

    def test_manifest_active_third_index_hits_internal_whitelist(self):
        manifest_text = """
endpoints:
  local-dev:
    url: http://localhost:7700
indexes:
  - uid: family-third
    status: active
    ingest:
      script: scripts/meili-ingest
"""
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_file(Path(tmp) / "manifest.yaml", manifest_text)
            hb = Path(tmp) / "hb"
            code, _, stderr = self.run_main(
                ["family-third", "--dry-run", "--manifest", str(manifest)],
                env={"FMA_HEARTBEAT_DIR": str(hb)},
            )
            self.assertEqual(code, 2, stderr)
            self.assertIn("only handles family-vault and family-hot", stderr)
            heartbeat = json.loads((hb / "meili-ingest-family-third.json").read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["status"], "fail")

    def test_missing_family_write_key_refuses_without_network(self):
        calls = []

        def fail_if_called(*args, **kwargs):
            calls.append(args)
            raise AssertionError("network was called")

        old_urlopen = self.module.urllib.request.urlopen
        self.module.urllib.request.urlopen = fail_if_called
        try:
            with tempfile.TemporaryDirectory() as hb:
                code, _, stderr = self.run_main(
                    ["family-vault", "--endpoint", "family", "--dry-run", "--manifest", str(MANIFEST)],
                    env={"FMA_HEARTBEAT_DIR": hb},
                )
        finally:
            self.module.urllib.request.urlopen = old_urlopen
        self.assertEqual(code, 2, stderr)
        self.assertEqual(calls, [])
        self.assertIn("FAMILY_MEILI_WRITE_KEY_FAMILY_VAULT", stderr)

    def test_local_dev_endpoint_uses_manifest_url_when_present(self):
        manifest = {"endpoints": {"local-dev": {"url": "http://127.0.0.1:17700/custom/"}}}
        url, _ = self.module.resolve_endpoint(manifest, "family-vault", "local-dev")
        self.assertEqual(url, "http://127.0.0.1:17700/custom")

    def test_family_hot_checksum_failure_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            hot = vault / "00_index" / "family-hot.md"
            hot.parent.mkdir(parents=True)
            hot.write_bytes(make_family_hot_bytes(b"# Family Hot\n\n- [class:5 id:item-1] Valid\n").replace(b"Valid", b"Talid", 1))
            code, _, stderr = self.run_main(
                ["family-hot", "--dry-run", "--manifest", str(MANIFEST), "--vault-root", str(vault)],
                env={"FMA_HEARTBEAT_DIR": str(Path(tmp) / "hb")},
            )
            self.assertEqual(code, 2, stderr)
            self.assertIn("body-sha256-mismatch", stderr)

    def test_family_hot_item_parsing_preserves_text_and_skips_heartbeat(self):
        body = (
            b"# Family Hot\n\n"
            b"- [class:5 id:item-1] Text with | and; punctuation | ptr: family-vault/a.md; o: agent-a; p: P1; at: 2026-07-06T00:00:00Z\n"
            b"- [class:1 id:generator-heartbeat] at: 2026-07-06T00:00:01Z; gen: family-hot-generator v0; pinned: #4\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            hot = vault / "00_index" / "family-hot.md"
            hot.parent.mkdir(parents=True)
            hot.write_bytes(make_family_hot_bytes(body))
            docs = self.module.build_hot_docs(vault, "2026-07-06T00:00:02Z")
        self.assertEqual(len(docs), 1)
        doc = docs[0]
        self.assertEqual(doc["id"], "item-1")
        self.assertEqual(doc["class"], 5)
        self.assertEqual(
            doc["text"],
            "Text with | and; punctuation | ptr: family-vault/a.md; o: agent-a; p: P1; at: 2026-07-06T00:00:00Z",
        )
        self.assertEqual(doc["ptr"], "family-vault/a.md")
        self.assertEqual(doc["owner"], "agent-a")
        self.assertEqual(doc["priority"], "P1")
        self.assertEqual(doc["at"], "2026-07-06T00:00:00Z")

    def test_attribution_stamps_all_built_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            write_file(vault / "notes.md", "# Title\n\nBody #tag\n")
            hot = vault / "00_index" / "family-hot.md"
            hot.parent.mkdir(parents=True, exist_ok=True)
            hot.write_bytes(make_family_hot_bytes(b"# Family Hot\n\n- [class:5 id:item-1] Text\n"))
            vault_docs = self.module.build_vault_docs(vault, "2026-07-06T00:00:00Z")
            hot_docs = self.module.build_hot_docs(vault, "2026-07-06T00:00:01Z")
        for doc in vault_docs + hot_docs:
            self.assertEqual(doc["_ingest_by"], "agent-a/meili-ingest")
            self.assertRegex(doc["_ingest_at"], r"^2026-07-06T00:00:0[01]Z$")

    def test_path_to_id_preserves_existing_ascii_output(self):
        self.assertEqual(
            self.module.path_to_id("30_decisions/2026-07-05-x.md"),
            "30_decisions_2026-07-05-x_md",
        )

    def test_path_to_id_japanese_path_is_meili_safe_with_hash_suffix(self):
        rel_path = "45_ai-systems/purchased-tommy/LP制作AI....md"
        doc_id = self.module.path_to_id(rel_path)
        expected_suffix = "-" + hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:10]
        self.assertRegex(doc_id, r"^[A-Za-z0-9_-]+$")
        self.assertTrue(doc_id.endswith(expected_suffix), doc_id)

    def test_path_to_id_japanese_paths_do_not_collide_after_sanitizing(self):
        first = self.module.path_to_id("45_ai-systems/purchased-tommy/LP制作AI.md")
        second = self.module.path_to_id("45_ai-systems/purchased-tommy/LP生成AI.md")
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^[A-Za-z0-9_-]+$")
        self.assertRegex(second, r"^[A-Za-z0-9_-]+$")

    def test_path_to_id_long_path_stays_within_meili_limit(self):
        rel_path = ("a" * 520) + ".md"
        doc_id = self.module.path_to_id(rel_path)
        expected_suffix = "-" + hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:10]
        self.assertRegex(doc_id, r"^[A-Za-z0-9_-]+$")
        self.assertLessEqual(len(doc_id.encode("utf-8")), 511)
        self.assertTrue(doc_id.endswith(expected_suffix), doc_id)

    def test_iter_batches_splits_on_byte_cap(self):
        big = "x" * 600_000  # 3 docs of ~600KB must not share one 2MB-capped batch with a 4th
        docs = [{"id": f"d{i}", "content": big} for i in range(4)]
        batches = list(self.module.iter_batches(docs))
        self.assertEqual([len(b) for b in batches], [3, 1])
        small = [{"id": f"s{i}"} for i in range(450)]
        self.assertEqual([len(b) for b in small_batches] if (small_batches := list(self.module.iter_batches(small))) else [], [200, 200, 50])
        one_giant = [{"id": "g", "content": "y" * 3_000_000}]
        self.assertEqual([len(b) for b in self.module.iter_batches(one_giant)], [1])

    def test_batching_chunks_vault_docs_at_two_hundred(self):
        captured = []

        def fake_request(base_url, method, path, key, payload=None):
            if method == "POST" and path.endswith("/documents"):
                captured.append(len(payload))
                return {"taskUid": len(captured)}
            return {}

        old_request = self.module.request_json
        self.module.request_json = fake_request
        try:
            docs = [{"id": str(index)} for index in range(401)]
            task_uids = self.module.post_batches("http://localhost:7700", "family-vault", None, docs)
        finally:
            self.module.request_json = old_request
        self.assertEqual(captured, [200, 200, 1])
        self.assertEqual(task_uids, ["1", "2", "3"])

    def test_ingest_polls_task_until_succeeded(self):
        calls = []
        task_statuses = [{"status": "processing"}, {"status": "succeeded"}]

        def fake_request(base_url, method, path, key, payload=None):
            calls.append((method, path, payload))
            if method == "GET" and path == "/indexes/family-vault":
                return {}
            if method == "POST" and path == "/indexes/family-vault/documents":
                return {"taskUid": 101}
            if method == "GET" and path == "/tasks/101":
                return task_statuses.pop(0)
            raise AssertionError(f"unexpected request {method} {path}")

        old_request = self.module.request_json
        old_sleep = self.module.time.sleep
        self.module.request_json = fake_request
        self.module.time.sleep = lambda seconds: None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                vault = Path(tmp) / "vault"
                write_file(vault / "notes.md", "# Title\n")
                code, stdout, stderr = self.run_main(
                    ["family-vault", "--manifest", str(MANIFEST), "--vault-root", str(vault)],
                    env={"FMA_HEARTBEAT_DIR": str(Path(tmp) / "hb")},
                )
        finally:
            self.module.request_json = old_request
            self.module.time.sleep = old_sleep
        self.assertEqual(code, 0, stderr)
        self.assertIn(
            "ingested index=family-vault docs=1 endpoint=local-dev tasks=1 all-succeeded",
            stdout,
        )
        self.assertEqual([call[:2] for call in calls].count(("GET", "/tasks/101")), 2)

    def test_ingest_failed_task_exits_one_and_records_heartbeat_reason(self):
        error_text = "Document identifier 制作 is invalid"

        def fake_request(base_url, method, path, key, payload=None):
            if method == "GET" and path == "/indexes/family-vault":
                return {}
            if method == "POST" and path == "/indexes/family-vault/documents":
                return {"taskUid": 202}
            if method == "GET" and path == "/tasks/202":
                return {"status": "failed", "error": {"message": error_text}}
            raise AssertionError(f"unexpected request {method} {path}")

        old_request = self.module.request_json
        self.module.request_json = fake_request
        try:
            with tempfile.TemporaryDirectory() as tmp:
                vault = Path(tmp) / "vault"
                hb = Path(tmp) / "hb"
                write_file(vault / "notes.md", "# Title\n")
                code, _, stderr = self.run_main(
                    ["family-vault", "--manifest", str(MANIFEST), "--vault-root", str(vault)],
                    env={"FMA_HEARTBEAT_DIR": str(hb)},
                )
                heartbeat = json.loads((hb / "meili-ingest-family-vault.json").read_text(encoding="utf-8"))
        finally:
            self.module.request_json = old_request
        self.assertEqual(code, 1, stderr)
        self.assertIn("uid=202", stderr)
        self.assertIn(error_text, stderr)
        self.assertEqual(heartbeat["status"], "fail")
        self.assertIn(error_text, heartbeat["reason"])

    def test_ingest_task_polling_timeout_exits_one(self):
        clock = {"now": 0.0}

        def fake_request(base_url, method, path, key, payload=None):
            if method == "GET" and path == "/indexes/family-vault":
                return {}
            if method == "POST" and path == "/indexes/family-vault/documents":
                return {"taskUid": 303}
            if method == "GET" and path == "/tasks/303":
                return {"status": "processing"}
            raise AssertionError(f"unexpected request {method} {path}")

        def fake_sleep(seconds):
            clock["now"] += seconds

        old_request = self.module.request_json
        old_monotonic = self.module.time.monotonic
        old_sleep = self.module.time.sleep
        old_timeout = self.module.TASK_POLL_TIMEOUT_SECONDS
        old_initial = self.module.TASK_POLL_INITIAL_INTERVAL_SECONDS
        old_max = self.module.TASK_POLL_MAX_INTERVAL_SECONDS
        self.module.request_json = fake_request
        self.module.time.monotonic = lambda: clock["now"]
        self.module.time.sleep = fake_sleep
        self.module.TASK_POLL_TIMEOUT_SECONDS = 0.3
        self.module.TASK_POLL_INITIAL_INTERVAL_SECONDS = 0.1
        self.module.TASK_POLL_MAX_INTERVAL_SECONDS = 0.1
        try:
            with tempfile.TemporaryDirectory() as tmp:
                vault = Path(tmp) / "vault"
                hb = Path(tmp) / "hb"
                write_file(vault / "notes.md", "# Title\n")
                code, _, stderr = self.run_main(
                    ["family-vault", "--manifest", str(MANIFEST), "--vault-root", str(vault)],
                    env={"FMA_HEARTBEAT_DIR": str(hb)},
                )
                heartbeat = json.loads((hb / "meili-ingest-family-vault.json").read_text(encoding="utf-8"))
        finally:
            self.module.request_json = old_request
            self.module.time.monotonic = old_monotonic
            self.module.time.sleep = old_sleep
            self.module.TASK_POLL_TIMEOUT_SECONDS = old_timeout
            self.module.TASK_POLL_INITIAL_INTERVAL_SECONDS = old_initial
            self.module.TASK_POLL_MAX_INTERVAL_SECONDS = old_max
        self.assertEqual(code, 1, stderr)
        self.assertIn("tasks not terminal within 180s", stderr)
        self.assertEqual(heartbeat["status"], "fail")
        self.assertIn("tasks not terminal within 180s", heartbeat["reason"])

    def test_dry_run_makes_zero_network_calls(self):
        calls = []

        def fail_if_called(*args, **kwargs):
            calls.append(args)
            raise AssertionError("network was called")

        old_urlopen = self.module.urllib.request.urlopen
        self.module.urllib.request.urlopen = fail_if_called
        try:
            with tempfile.TemporaryDirectory() as tmp:
                vault = Path(tmp) / "vault"
                write_file(vault / "notes.md", "# Title\n")
                code, stdout, stderr = self.run_main(
                    ["family-vault", "--dry-run", "--manifest", str(MANIFEST), "--vault-root", str(vault)],
                    env={"FMA_HEARTBEAT_DIR": str(Path(tmp) / "hb")},
                )
        finally:
            self.module.urllib.request.urlopen = old_urlopen
        self.assertEqual(code, 0, stderr)
        self.assertEqual(calls, [])
        self.assertIn("docs=1", stdout)

    def test_vault_doc_id_collision_fails_ingest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            write_file(vault / "a" / "b.md", "# Nested\n")
            write_file(vault / "a_b.md", "# Flat\n")
            hb = root / "hb"
            code, _, stderr = self.run_main(
                ["family-vault", "--dry-run", "--manifest", str(MANIFEST), "--vault-root", str(vault)],
                env={"FMA_HEARTBEAT_DIR": str(hb)},
            )
            self.assertEqual(code, 1, stderr)
            self.assertIn("doc id collision:", stderr)
            self.assertIn("a_b.md vs a/b.md -> a_b_md", stderr)
            heartbeat = json.loads((hb / "meili-ingest-family-vault.json").read_text(encoding="utf-8"))
            self.assertEqual(heartbeat["status"], "fail")
            self.assertIn("doc id collision:", heartbeat["reason"])

    def test_heartbeat_ok_fail_refusal_counts_increment_and_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            hb = Path(tmp) / "hb"
            vault = Path(tmp) / "vault"
            write_file(vault / "notes.md", "# Title\n")
            env = {"FMA_HEARTBEAT_DIR": str(hb)}

            code, _, _ = self.run_main(
                ["nonexistent-index", "--dry-run", "--manifest", str(MANIFEST)],
                env=env,
            )
            self.assertEqual(code, 2)
            first = json.loads((hb / "meili-ingest-nonexistent-index.json").read_text())
            self.assertEqual(first["status"], "fail")
            self.assertEqual(first["fail_count"], 1)

            code, _, _ = self.run_main(
                ["nonexistent-index", "--dry-run", "--manifest", str(MANIFEST)],
                env=env,
            )
            self.assertEqual(code, 2)
            second = json.loads((hb / "meili-ingest-nonexistent-index.json").read_text())
            self.assertEqual(second["fail_count"], 2)

            code, _, _ = self.run_main(
                ["family-vault", "--dry-run", "--manifest", str(MANIFEST), "--vault-root", str(vault)],
                env=env,
            )
            self.assertEqual(code, 0)
            ok = json.loads((hb / "meili-ingest-family-vault.json").read_text())
            self.assertEqual(ok["status"], "ok")
            self.assertEqual(ok["fail_count"], 0)

            old_request = self.module.request_json
            self.module.request_json = lambda *args, **kwargs: (_ for _ in ()).throw(
                self.module.IngestRuntimeError("network error: test failure")
            )
            try:
                code, _, stderr = self.run_main(
                    ["family-vault", "--manifest", str(MANIFEST), "--vault-root", str(vault)],
                    env=env,
                )
            finally:
                self.module.request_json = old_request
            self.assertEqual(code, 1, stderr)
            failed = json.loads((hb / "meili-ingest-family-vault.json").read_text())
            self.assertEqual(failed["status"], "fail")
            self.assertEqual(failed["fail_count"], 1)
            self.assertEqual(failed["docs"], 1)
            self.assertIn("network error", failed["reason"])

    def test_authorization_header_only_when_key_configured(self):
        seen = []

        def fake_urlopen(req, timeout=60):
            seen.append(req.get_header("Authorization"))
            return FakeResponse()

        old_urlopen = self.module.urllib.request.urlopen
        self.module.urllib.request.urlopen = fake_urlopen
        try:
            self.module.request_json("http://localhost:7700", "GET", "/indexes/family-vault", None)
            self.module.request_json("http://localhost:7700", "GET", "/indexes/family-vault", "test-fake-key-not-real")
        finally:
            self.module.urllib.request.urlopen = old_urlopen
        self.assertEqual(seen[0], None)
        self.assertEqual(seen[1], "Bearer test-fake-key-not-real")

    def test_local_dev_auto_create_only_when_missing(self):
        calls = []

        def make_http_error(code):
            return urllib.error.HTTPError(
                "http://localhost:7700/indexes/family-vault",
                code,
                "missing",
                {},
                io.BytesIO(b'{"message":"missing"}'),
            )

        def fake_missing(base_url, method, path, key, payload=None):
            calls.append((method, path, payload))
            if method == "GET":
                raise self.module.HTTPStatusError(404, "missing")
            return {}

        old_request = self.module.request_json
        self.module.request_json = fake_missing
        try:
            self.module.ensure_local_index(
                "http://localhost:7700",
                "family-vault",
                None,
                {"primaryKey": "id", "searchable": ["title"], "filterable": ["directory"]},
            )
        finally:
            self.module.request_json = old_request
        self.assertEqual([call[0] for call in calls], ["GET", "POST", "PATCH"])

        calls = []

        def fake_exists(base_url, method, path, key, payload=None):
            calls.append((method, path, payload))
            return {}

        self.module.request_json = fake_exists
        try:
            self.module.ensure_local_index("http://localhost:7700", "family-vault", None, {"primaryKey": "id"})
        finally:
            self.module.request_json = old_request
        self.assertEqual([call[0] for call in calls], ["GET"])


if __name__ == "__main__":
    unittest.main()
