#!/usr/bin/env python3
"""Tests for scripts/write-guard (仕様 v1.0 §5 受け入れ条件)."""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD_SCRIPT = REPO_ROOT / "scripts" / "write-guard"


def load_module():
    loader = importlib.machinery.SourceFileLoader("write_guard_under_test", str(GUARD_SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


ROUTE_KEYS = {"layer", "path_hint", "format_hint", "caveats"}


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def assert_route_schema(self, result):
        self.assertEqual(set(result), ROUTE_KEYS)
        self.assertIsInstance(result["caveats"], list)

    def test_secret_material_is_refused(self):
        result = self.module.route("save this: GITHUB_TOKEN=ghp_" + "a1B2" * 6, {})
        self.assert_route_schema(result)
        self.assertEqual(result["layer"], "refused")
        self.assertIn("1Password", result["path_hint"])

    def test_secret_mention_without_value_is_not_refused(self):
        result = self.module.route(
            "Meili キーの保管場所と取り扱いルールを記録したい（値は書かない）",
            {"type": "reference"},
        )
        self.assertNotEqual(result["layer"], "refused")

    def test_temporary_routes_to_none_layer(self):
        result = self.module.route("今セッションのデバッグ用ポート番号", {})
        self.assert_route_schema(result)
        self.assertEqual(result["layer"], "none")

    def test_each_type_hint_routes_to_expected_layer(self):
        expected = {
            "decision": ("family-vault", "30_decisions"),
            "profile": ("memory-md", "MEMORY.md"),
            "procedure": ("skill", "Skill"),
            "structured": ("kg", "KG"),
            "project": ("project-repo", "repo"),
            "reference": ("family-vault", "50_references"),
            "episodic": ("supermemory", "personal_"),
        }
        for kind, (layer, hint_fragment) in expected.items():
            with self.subTest(kind=kind):
                result = self.module.route("恒久情報の説明", {"type": kind})
                self.assert_route_schema(result)
                self.assertEqual(result["layer"], layer)
                self.assertIn(hint_fragment, result["path_hint"])

    def test_keyword_classification_without_hint(self):
        result = self.module.route("レビュー既定を2系統に統一と決定した", {})
        self.assertEqual(result["layer"], "family-vault")
        self.assertIn("30_decisions", result["path_hint"])

    def test_unclassifiable_returns_unknown(self):
        result = self.module.route("なんかいい感じのやつ", {})
        self.assertEqual(result["layer"], "unknown")

    def test_review_pending_requires_review_by(self):
        refused = self.module.route(
            "外部記事の比較メモ", {"type": "reference", "review_pending": True}
        )
        self.assertEqual(refused["layer"], "refused")
        # Whitespace or non-date values must not satisfy the requirement.
        for bad in ("   ", "soon", "2026/07/20"):
            with self.subTest(bad=bad):
                result = self.module.route(
                    "外部記事の比較メモ",
                    {"type": "reference", "review_pending": True, "review_by": bad},
                )
                self.assertEqual(result["layer"], "refused")
        allowed = self.module.route(
            "外部記事の比較メモ",
            {"type": "reference", "review_pending": True, "review_by": "2026-07-20"},
        )
        self.assertEqual(allowed["layer"], "family-vault")
        self.assertIn("25_review-pending", allowed["path_hint"])

    def test_shared_family_reroutes_personal_layers_to_shared_plane(self):
        result = self.module.route("嗜好メモ", {"type": "profile", "shared": True})
        self.assertEqual(result["layer"], "family-vault")
        self.assertIn("共有面", result["path_hint"])
        self.assertTrue(any("ポインタ" in c for c in result["caveats"]))

    def test_shared_personal_reroutes_shared_layers_to_personal_plane(self):
        result = self.module.route("決定メモ", {"type": "decision", "shared": False})
        self.assertEqual(result["layer"], "memory-md")
        self.assertIn("個人面", result["path_hint"])

    def test_caller_declared_secret_is_refused_without_scanner_hit(self):
        result = self.module.route("顧客の機微情報を保存したい", {"secret": True})
        self.assertEqual(result["layer"], "refused")
        self.assertTrue(any("declared-by-caller" in c for c in result["caveats"]))

    def test_op_uri_location_pointer_is_not_refused(self):
        result = self.module.route(
            "key の場所: op://family/meili-master/credential", {"type": "reference"}
        )
        self.assertNotEqual(result["layer"], "refused")

    def test_op_uri_does_not_mask_real_secret_on_same_line(self):
        # secret-scan returns early after an op-uri hit; the guard must strip
        # the location pointer first so the real token still gets scanned.
        result = self.module.route(
            "op://family/x/credential GITHUB_TOKEN=ghp_" + "a1B2" * 6, {}
        )
        self.assertEqual(result["layer"], "refused")

    def test_keyword_boundaries_avoid_substring_traps(self):
        # Substrings must not classify: 500kg, report(≠repo),
        # runbookshelf(≠runbook), pull requester(≠pull request).
        for text in (
            "500kgのデータを整理したい",
            "weekly report をまとめたい",
            "my runbookshelf arrived",
            "the pull requester was happy",
        ):
            with self.subTest(text=text):
                result = self.module.route(text, {})
                self.assertEqual(result["layer"], "unknown")

    def test_invalid_agent_name_raises(self):
        with self.assertRaises(ValueError):
            self.module.route("会話要約", {"type": "episodic", "agent": "../../etc"})

    def test_episodic_agent_omitted_has_no_brace_placeholder(self):
        result = self.module.route("会話の要約", {"type": "episodic"})
        self.assertNotIn("{agent}", result["path_hint"])
        self.assertEqual(result["path_hint"], "personal_self")

    def test_personal_reference_keeps_references_destination(self):
        # A personal reference must not lose its 50_references/ hint.
        result = self.module.route("外部記事の比較メモ", {"type": "reference", "shared": False})
        self.assertEqual(result["layer"], "family-vault")
        self.assertIn("50_references", result["path_hint"])

    def test_personal_decision_still_reroutes_to_personal_plane(self):
        result = self.module.route("個人的な決定メモ", {"type": "decision", "shared": False})
        self.assertEqual(result["layer"], "memory-md")

    def test_episodic_long_body_warns(self):
        body = "\n".join(f"line {i}" for i in range(12))
        result = self.module.route("会話の要約", {"type": "episodic", "body": body})
        self.assertTrue(any("10行" in c for c in result["caveats"]))

    def test_structured_names_agent_c_write_authority(self):
        result = self.module.route("会社の関係を登録", {"type": "structured"})
        self.assertTrue(any("Agent C" in c for c in result["caveats"]))


class CliTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["WRITE_GUARD_LOG_DIR"] = self.tmp.name
        self.addCleanup(os.environ.pop, "WRITE_GUARD_LOG_DIR", None)

    def run_cli(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = self.module.main(argv)
        return code, stdout.getvalue()

    def log_entries(self):
        path = Path(self.tmp.name) / "decisions.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_json_output_is_stable_schema(self):
        code, out = self.run_cli(["決定を記録", "--type", "decision", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(set(payload), ROUTE_KEYS)

    def test_secret_refusal_exit_code_and_log_has_no_content(self):
        secret = "AWS_SECRET=AKIA" + "A" * 16
        code, out = self.run_cli([f"push creds {secret}", "--json"])
        self.assertEqual(code, 3)
        # No content on stdout either — only the Route.
        self.assertNotIn("AKIA", out)
        self.assertNotIn("push creds", out)
        entries = self.log_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["refused"], "secret")
        raw = json.dumps(entries[0])
        self.assertNotIn("AKIA", raw)
        self.assertNotIn("push creds", raw)
        # Rule identity is preserved (not the unparsed fallback).
        self.assertTrue(any("high-entropy" in r for r in entries[0]["rules"]))

    def test_policy_refusal_exit_code_4_and_no_description_in_log(self):
        code, _ = self.run_cli(
            ["外部記事の比較メモ", "--type", "reference", "--review-pending"]
        )
        self.assertEqual(code, 4)
        entries = self.log_entries()
        self.assertEqual(entries[0]["refused"], "policy")
        self.assertNotIn("description", entries[0])

    def test_cli_rejects_invalid_agent(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_cli(["会話要約", "--type", "episodic", "--agent", "../evil"])
        self.assertEqual(ctx.exception.code, 2)

    def test_normal_decision_is_logged_with_layer_and_caveats(self):
        code, _ = self.run_cli(["レビュー体制の決定", "--type", "decision"])
        self.assertEqual(code, 0)
        entries = self.log_entries()
        self.assertEqual(entries[0]["layer"], "family-vault")
        self.assertIn("caveats", entries[0])

    def test_agent_flag_flows_into_episodic_path_hint(self):
        code, out = self.run_cli(["会話要約", "--type", "episodic", "--agent", "agent-b", "--json"])
        self.assertEqual(code, 0)
        self.assertIn("personal_agent-b", json.loads(out)["path_hint"])


if __name__ == "__main__":
    unittest.main()
