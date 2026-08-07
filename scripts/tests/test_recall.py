#!/usr/bin/env python3
"""Tests for the recall facade CLI."""

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
RECALL_SCRIPT = REPO_ROOT / "scripts" / "recall"


def load_recall_module():
    loader = importlib.machinery.SourceFileLoader("recall_script", str(RECALL_SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class RecallTests(unittest.TestCase):
    def setUp(self):
        self.recall = load_recall_module()

    def write_private_supermemory_env(self, path, contents):
        path.write_text(contents, encoding="utf-8")
        os.chmod(path, 0o600)
        return path

    def run_recall(self, query="needle", layers=("sm", "meili", "grep"), local_only=False, limit=8, adapters=None, timeout=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        kwargs = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        result = self.recall.recall(
            query,
            layers=list(layers),
            local_only=local_only,
            limit=limit,
            scratch_dir=root / "scratch",
            stats_path=root / "stats" / "stats.jsonl",
            adapters=adapters
            or {
                "sm": lambda _query, _limit: [],
                "meili": lambda _query, _limit: [],
                "grep": lambda _query, _limit: [],
            },
            **kwargs,
        )
        return result, root

    def test_supermemory_env_strips_surrounding_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "env"
            self.write_private_supermemory_env(path, 'SUPERMEMORY_CC_API_KEY="sk-test-value"\n')
            self.assertEqual(self.recall.parse_supermemory_env(path), "sk-test-value")

    def test_supermemory_env_strips_surrounding_single_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "env"
            self.write_private_supermemory_env(path, "SUPERMEMORY_CC_API_KEY='sk-test-value'\n")
            self.assertEqual(self.recall.parse_supermemory_env(path), "sk-test-value")

    def test_supermemory_env_accepts_private_0600_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "env"
            self.write_private_supermemory_env(path, 'SUPERMEMORY_CC_API_KEY="sk-test-value"\n')

            self.assertEqual(self.recall.parse_supermemory_env(path), "sk-test-value")

    def test_supermemory_env_rejects_non_0600_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "env"
            path.write_text("SUPERMEMORY_CC_API_KEY=sk-test-value\n", encoding="utf-8")
            os.chmod(path, 0o644)

            with self.assertRaisesRegex(
                self.recall.RecallError,
                r"invalid Supermemory env file: env file mode is 0644, expected 0600; use a real user-owned env file and chmod 600 it",
            ):
                self.recall.parse_supermemory_env(path)

    def test_supermemory_env_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target-env"
            self.write_private_supermemory_env(target, 'SUPERMEMORY_CC_API_KEY="sk-test-value"\n')
            path = root / "env"
            path.symlink_to(target)

            with self.assertRaisesRegex(
                self.recall.RecallError,
                r"invalid Supermemory env file: env file is a symlink; use a real user-owned env file and chmod 600 it",
            ):
                self.recall.parse_supermemory_env(path)

    def test_search_adapters_guard_leading_dash_query(self):
        completed = mock.Mock()
        completed.returncode = 0
        completed.stdout = ""
        completed.stderr = ""

        with mock.patch.dict(self.recall.os.environ, {}, clear=True), mock.patch.object(
            self.recall.subprocess, "run", return_value=completed
        ) as run:
            self.recall.rg_search("--evil", [Path("/tmp/root")], 3)
            self.recall.grep_search("--evil", [Path("/tmp/root")], 3)
            self.recall.mem_search("--evil", 3)

        self.assertEqual(run.call_args_list[0].args[0], ["rg", "--json", "-i", "-m", "3", "-e", "--evil", "--", "/tmp/root"])
        self.assertEqual(run.call_args_list[1].args[0], ["grep", "-Rni", "-m", "3", "-e", "--evil", "--", "/tmp/root"])
        self.assertEqual(
            run.call_args_list[2].args[0],
            [str(self.recall.expand_path(self.recall.DEFAULT_MEM_SEARCH)), "--json", "-l", "3", "--", "--evil"],
        )

    def test_parse_layers_rejects_unknown_and_dedups(self):
        with self.assertRaises(self.recall.RecallError):
            self.recall.parse_layers("bogus")
        self.assertEqual(self.recall.parse_layers("sm,sm,meili"), ["sm", "meili"])

    def test_hit_missing_pointer_is_rejected_at_emit_chokepoint(self):
        hits, rejected = self.recall.emit_hits(
            "meili",
            [
                {"title": "missing pointer", "text": "body"},
                {"path": "/tmp/source.md", "line": 4, "text": "kept"},
            ],
        )
        self.assertEqual(rejected, 1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["layer"], "meili")
        self.assertEqual(hits[0]["pointer"], "/tmp/source.md:4")

    def test_meili_relative_path_resolves_against_existing_candidate_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "15_companies" / "replus.md"
            doc.parent.mkdir(parents=True)
            doc.write_text("needle", encoding="utf-8")

            with mock.patch.dict(self.recall.os.environ, {"RECALL_MEILI_ROOTS": str(root)}):
                result, _run_root = self.run_recall(
                    layers=("meili",),
                    adapters={"meili": lambda _query, _limit: [{"path": "15_companies/replus.md", "line": 12, "text": "hit"}]},
                )

        self.assertEqual(result["rejected_hits"], 0)
        self.assertEqual(result["hits"][0]["pointer"], f"{doc.resolve()}:12")

    def test_meili_relative_path_is_rejected_when_missing_from_candidate_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(self.recall.os.environ, {"RECALL_MEILI_ROOTS": tmp}):
                result, _run_root = self.run_recall(
                    layers=("meili",),
                    adapters={"meili": lambda _query, _limit: [{"path": "15_companies/missing.md", "line": 3, "text": "hit"}]},
                )

        self.assertEqual(result["hits"], [])
        self.assertEqual(result["rejected_hits"], 1)
        self.assertEqual(result["per_layer"]["meili"]["hits"], 0)

    def test_meili_absolute_path_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "absolute.md"
            doc.write_text("needle", encoding="utf-8")

            with mock.patch.dict(self.recall.os.environ, {"RECALL_MEILI_ROOTS": str(Path(tmp) / "empty")}):
                result, _run_root = self.run_recall(
                    layers=("meili",),
                    adapters={"meili": lambda _query, _limit: [{"path": str(doc), "line": 5, "text": "hit"}]},
                )

        self.assertEqual(result["rejected_hits"], 0)
        self.assertEqual(result["hits"][0]["pointer"], f"{doc}:5")

    def test_meili_transcripts_index_item_resolves_existing_session_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcripts_dir = Path(tmp)
            project = "family-memory"
            session_id = "session-123"
            transcript = transcripts_dir / project / f"{session_id}.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text('{"content":"needle"}\n', encoding="utf-8")

            with mock.patch.dict(self.recall.os.environ, {"RECALL_TRANSCRIPTS_DIR": str(transcripts_dir)}):
                result, _run_root = self.run_recall(
                    layers=("meili",),
                    adapters={
                        "meili": lambda _query, _limit: [
                            {
                                "_index": "transcripts",
                                "project": project,
                                "session_id": session_id,
                                "content": "hit",
                            }
                        ]
                    },
                )

        self.assertEqual(result["rejected_hits"], 0)
        self.assertEqual(len(result["hits"]), 1)
        self.assertIn(str(transcript), result["hits"][0]["pointer"])
        self.assertIn(session_id, result["hits"][0]["pointer"])

    def test_meili_transcripts_index_item_rejects_missing_session_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(self.recall.os.environ, {"RECALL_TRANSCRIPTS_DIR": tmp}):
                result, _run_root = self.run_recall(
                    layers=("meili",),
                    adapters={
                        "meili": lambda _query, _limit: [
                            {
                                "_index": "transcripts",
                                "project": "family-memory",
                                "session_id": "missing-session",
                                "content": "hit",
                            }
                        ]
                    },
                )

        self.assertEqual(result["hits"], [])
        self.assertEqual(result["rejected_hits"], 1)
        self.assertEqual(result["per_layer"]["meili"]["hits"], 0)

    def test_meili_transcripts_index_item_rejects_missing_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "family-memory"
            project_dir.mkdir()

            with mock.patch.dict(self.recall.os.environ, {"RECALL_TRANSCRIPTS_DIR": tmp}):
                result, _run_root = self.run_recall(
                    layers=("meili",),
                    adapters={
                        "meili": lambda _query, _limit: [
                            {
                                "_index": "transcripts",
                                "project": "family-memory",
                                "content": "hit",
                            }
                        ]
                    },
                )

        self.assertEqual(result["hits"], [])
        self.assertEqual(result["rejected_hits"], 1)
        self.assertEqual(result["per_layer"]["meili"]["hits"], 0)

    def test_supermemory_pointer_preserves_remote_strings_without_expansion(self):
        with mock.patch.object(self.recall, "expand_path", side_effect=AssertionError("sm data must not expand paths")):
            hits, rejected = self.recall.emit_hits(
                "sm",
                [{"id": "~/memory-$HOME", "containerTag": "$HOME/container~", "content": "kept"}],
            )
        self.assertEqual(rejected, 0)
        self.assertEqual(hits[0]["pointer"], "supermemory:~/memory-$HOME containerTag=$HOME/container~")

    def test_one_layer_exception_fails_open(self):
        def broken(_query, _limit):
            raise RuntimeError("boom")

        result, _root = self.run_recall(
            adapters={
                "sm": lambda _query, _limit: [],
                "meili": broken,
                "grep": lambda _query, _limit: [{"path": "/tmp/kept.md", "line": 7, "text": "kept"}],
            }
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["per_layer"]["meili"]["status"], "error")
        self.assertIn("boom", result["per_layer"]["meili"]["error"])
        self.assertEqual(result["hits"][0]["layer"], "grep")

    def test_timed_out_layer_does_not_block_recall_return(self):
        def slow(_query, _limit):
            time.sleep(2)
            return [{"path": "/tmp/late.md", "line": 1, "text": "late"}]

        start = time.monotonic()
        result, _root = self.run_recall(
            layers=("meili", "grep"),
            timeout=0.2,
            adapters={
                "meili": slow,
                "grep": lambda _query, _limit: [{"path": "/tmp/kept.md", "line": 7, "text": "kept"}],
            },
        )
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 1.0)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["per_layer"]["meili"]["status"], "error")
        self.assertIn("timeout after 0.2s", result["per_layer"]["meili"]["error"])
        self.assertEqual(result["hits"][0]["layer"], "grep")
        self.assertEqual(result["hits"][0]["pointer"], "/tmp/kept.md:7")

    def test_stats_jsonl_shape_omits_raw_query(self):
        raw_query = "very secret family query"
        result, root = self.run_recall(
            query=raw_query,
            layers=("grep",),
            adapters={"grep": lambda _query, _limit: [{"path": "/tmp/a.md", "line": 1, "text": "hit"}]},
        )
        stats_line = (root / "stats" / "stats.jsonl").read_text(encoding="utf-8").strip()
        stats = json.loads(stats_line)
        self.assertEqual(stats["ts"], result["ts"])
        self.assertEqual(stats["query_sha256"], hashlib.sha256(raw_query.encode("utf-8")).hexdigest()[:12])
        self.assertEqual(stats["layers_queried"], ["grep"])
        self.assertIn("sm", stats["per_layer"])
        self.assertIn("meili", stats["per_layer"])
        self.assertIn("grep", stats["per_layer"])
        self.assertFalse(stats["sm_queried"])
        self.assertEqual(stats["rejected_hits"], 0)
        self.assertNotIn(raw_query, stats_line)

    def test_local_only_never_calls_sm_adapter(self):
        sm_adapter = mock.Mock(side_effect=AssertionError("sm should not be called"))
        result, _root = self.run_recall(
            local_only=True,
            adapters={
                "sm": sm_adapter,
                "meili": lambda _query, _limit: [{"path": "/tmp/m.md", "line": 2, "text": "m"}],
                "grep": lambda _query, _limit: [{"path": "/tmp/g.md", "line": 3, "text": "g"}],
            },
        )
        sm_adapter.assert_not_called()
        self.assertEqual(result["layers_queried"], ["meili", "grep"])
        self.assertEqual(result["per_layer"]["sm"]["status"], "skipped")

    def test_limit_propagates_to_each_adapter(self):
        sm_adapter = mock.Mock(return_value=[{"id": "s1", "containerTag": "personal-agent-a", "content": "s1"}])
        meili_adapter = mock.Mock(return_value=[{"path": "/tmp/m.md", "line": 2, "text": "m"}])
        grep_adapter = mock.Mock(return_value=[{"path": "/tmp/g.md", "line": 3, "text": "g"}])
        self.run_recall(
            limit=3,
            adapters={
                "sm": sm_adapter,
                "meili": meili_adapter,
                "grep": grep_adapter,
            },
        )
        sm_adapter.assert_called_once_with("needle", 3)
        meili_adapter.assert_called_once_with("needle", 3)
        grep_adapter.assert_called_once_with("needle", 3)

    def test_round_robin_interleave_handles_uneven_layers(self):
        result, _root = self.run_recall(
            adapters={
                "sm": lambda _query, _limit: [
                    {"id": "s1", "containerTag": "personal-agent-a", "content": "s1"},
                    {"id": "s2", "containerTag": "personal-agent-a", "content": "s2"},
                ],
                "meili": lambda _query, _limit: [{"path": "/tmp/m1.md", "line": 1, "text": "m1"}],
                "grep": lambda _query, _limit: [
                    {"path": "/tmp/g1.md", "line": 1, "text": "g1"},
                    {"path": "/tmp/g2.md", "line": 2, "text": "g2"},
                    {"path": "/tmp/g3.md", "line": 3, "text": "g3"},
                ],
            }
        )
        self.assertEqual([hit["layer"] for hit in result["hits"]], ["sm", "meili", "grep", "sm", "grep", "grep"])

    def test_all_layers_error_returns_nonzero(self):
        def broken(_query, _limit):
            raise RuntimeError("down")

        result, _root = self.run_recall(adapters={"sm": broken, "meili": broken, "grep": broken})
        self.assertEqual(result["exit_code"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
