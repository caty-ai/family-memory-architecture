#!/usr/bin/env python3
"""Regression tests for the fail-closed model catalog gate."""

import datetime as dt
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "model-catalog-check"


class ModelCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.catalog = self.root / "model-catalog.yaml"
        self.schema = self.root / "model-catalog.schema.json"
        self.policy = self.root / "model-catalog.md"
        self.member_dir = self.root / "member-state"
        self.member_schema = self.member_dir / "schema.json"
        self.member_a = self.member_dir / "member-a.json"
        self.baseline = self.root / "baseline-model-catalog.yaml"
        self.member_dir.mkdir()
        shutil.copyfile(REPO_ROOT / "manifests" / "model-catalog.yaml", self.catalog)
        shutil.copyfile(REPO_ROOT / "manifests" / "model-catalog.schema.json", self.schema)
        shutil.copyfile(REPO_ROOT / "policies" / "model-catalog.md", self.policy)
        shutil.copyfile(REPO_ROOT / "manifests" / "member-state" / "schema.json", self.member_schema)
        shutil.copyfile(REPO_ROOT / "manifests" / "member-state" / "member-a.json", self.member_a)
        shutil.copyfile(self.catalog, self.baseline)

    def tearDown(self):
        self.tempdir.cleanup()

    def command(self, *extra, no_site=False):
        command = [sys.executable]
        if no_site:
            command.append("-S")
        command.extend(
            [
                str(CHECKER),
                "--catalog",
                str(self.catalog),
                "--schema",
                str(self.schema),
                "--policy",
                str(self.policy),
                "--member-state-dir",
                str(self.member_dir),
                "--member-schema",
                str(self.member_schema),
                *map(str, extra),
            ]
        )
        return command

    def run_check(self, *extra, no_site=False):
        return subprocess.run(
            self.command(*extra, no_site=no_site),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def catalog_text(self):
        return self.catalog.read_text(encoding="utf-8")

    def write_catalog(self, text):
        self.catalog.write_text(text, encoding="utf-8")

    def adopt_current_catalog(self):
        state = json.loads(self.member_a.read_text(encoding="utf-8"))
        state["catalog_digest_adopted"] = hashlib.sha256(self.catalog.read_bytes()).hexdigest()
        self.member_a.write_text(json.dumps(state), encoding="utf-8")

    def member_state(self):
        return json.loads(self.member_a.read_text(encoding="utf-8"))

    def write_member_state(self, state):
        self.member_a.write_text(json.dumps(state), encoding="utf-8")

    def set_catalog_window(self, catalog_date, effective_date):
        text = re.sub(
            r"^date: [0-9]{4}-[0-9]{2}-[0-9]{2}$",
            f"date: {catalog_date}",
            self.catalog_text(),
            count=1,
            flags=re.M,
        )
        text = re.sub(
            r"^revision_effective_after: [0-9]{4}-[0-9]{2}-[0-9]{2}(?:[ \t]+#.*)?$",
            f"revision_effective_after: {effective_date}",
            text,
            count=1,
            flags=re.M,
        )
        self.write_catalog(text)

    def assert_fails_with(self, needle, result=None):
        result = result or self.run_check()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ERROR:", result.stderr)
        self.assertIn(needle, result.stderr)

    def load_checker_module(self, name):
        loader = importlib.machinery.SourceFileLoader(name, str(CHECKER))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_happy_path(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("member-state records are valid", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_digest_is_stable_and_is_the_only_output(self):
        first = self.run_check("--digest")
        second = self.run_check("--digest")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertRegex(first.stdout, r"^[0-9a-f]{64}\n$")
        self.assertEqual(first.stderr + second.stderr, "")

    def test_stock_python_fallback_without_site_packages(self):
        result = self.run_check("--digest", no_site=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"^[0-9a-f]{64}\n$")

    def test_missing_catalog_fails_closed(self):
        self.catalog.unlink()
        self.assert_fails_with("cannot read catalog")

    def test_malformed_yaml_fails_closed_with_and_without_site_packages(self):
        self.write_catalog("revision:\t1\n")
        self.assert_fails_with("tabs are not allowed")
        self.assert_fails_with("tabs are not allowed", self.run_check(no_site=True))

    def test_raw_tab_in_block_scalar_fails_closed(self):
        self.write_catalog(self.catalog_text().replace("changelog: >\n", "changelog: >\n  tab\there\n", 1))
        self.assert_fails_with("tabs are not allowed")

    def test_single_quoted_scalar_rejects_doubled_quotes_and_backslashes(self):
        for quoted in ("'vendor''a-model-1'", r"'vendor\ta-model-1'", r"'vendor\a-model-1'"):
            with self.subTest(quoted=quoted):
                original = (REPO_ROOT / "manifests" / "model-catalog.yaml").read_text(encoding="utf-8")
                self.write_catalog(original.replace("id: vendor-a-model-1", f"id: {quoted}", 1))
                self.assert_fails_with("unsupported quoting in single-quoted scalar")

    def test_decoded_control_is_rejected_for_single_and_double_quotes(self):
        quoted_values = ("'vendor\u0091a-model-1'", '"vendor\u0091a-model-1"', r'"vendor\ta-model-1"')
        for quoted in quoted_values:
            with self.subTest(quoted=quoted):
                original = (REPO_ROOT / "manifests" / "model-catalog.yaml").read_text(encoding="utf-8")
                self.write_catalog(original.replace("id: vendor-a-model-1", f"id: {quoted}", 1))
                self.assert_fails_with("decoded control character")

    def test_duplicate_yaml_key_fails_closed(self):
        self.write_catalog(self.catalog_text().replace("revision: 1", "revision: 1\nrevision: 2", 1))
        self.assert_fails_with("duplicate key 'revision'")

    def test_missing_required_top_level_field_is_rejected(self):
        self.write_catalog(self.catalog_text().replace("revision: 1\n", "", 1))
        self.assert_fails_with("missing required property 'revision'")

    def test_schema_enum_failure_is_rejected(self):
        self.write_catalog(self.catalog_text().replace("tier: priority", "tier: emergency", 1))
        self.assert_fails_with("must be priority or substitute")

    def test_availability_is_rejected_by_schema_and_g2(self):
        self.write_catalog(self.catalog_text().replace("    rank: 1", "    availability: true\n    rank: 1", 1))
        result = self.run_check()
        self.assert_fails_with("additional property 'availability' is not allowed", result)
        self.assertIn("G2", result.stderr)
        self.assertIn("forbidden availability-shaped key 'availability'", result.stderr)

    def test_each_g2_key_is_rejected_recursively(self):
        for forbidden in ("quota", "liveness", "verified_at", "availability", "writer_conflict"):
            with self.subTest(forbidden=forbidden):
                original = (REPO_ROOT / "manifests" / "model-catalog.yaml").read_text(encoding="utf-8")
                mutated = original.replace(
                    "lineage: {family: family-a, vendor: vendor-a}",
                    f"lineage: {{family: family-a, vendor: vendor-a, {forbidden}: true}}",
                    1,
                )
                self.write_catalog(mutated)
                result = self.run_check(no_site=True)
                self.assert_fails_with(f"forbidden availability-shaped key '{forbidden}'", result)

    def test_g2_sweep_starts_at_catalog_root(self):
        self.write_catalog("quota: true\n" + self.catalog_text())
        result = self.run_check(no_site=True)
        self.assert_fails_with("G2 $.quota: forbidden availability-shaped key 'quota'", result)

    def test_empty_lineage_family_and_missing_vendor_fail(self):
        self.write_catalog(
            self.catalog_text().replace(
                "lineage: {family: family-a, vendor: vendor-a}",
                "lineage: {family: '', extra: nope}",
                1,
            )
        )
        result = self.run_check()
        self.assert_fails_with("lineage.family", result)
        self.assertIn("missing required property 'vendor'", result.stderr)

    def test_duplicate_model_id_fails(self):
        self.write_catalog(self.catalog_text().replace("id: vendor-b-model-1", "id: vendor-a-model-1", 1))
        self.assert_fails_with("duplicate id 'vendor-a-model-1'")

    def test_trial_without_recheck_after_fails(self):
        text = self.catalog_text()
        trial_start = text.index("  - id: vendor-g-model-1")
        trial_end = text.index("  - id: vendor-h-model-1")
        block = text[trial_start:trial_end]
        block = block.replace("    recheck_after: 2026-09-15\n", "", 1)
        self.write_catalog(text[:trial_start] + block + text[trial_end:])
        self.assert_fails_with("recheck_after is required")

    def test_trial_with_quorum_true_fails(self):
        text = self.catalog_text()
        trial_start = text.index("  - id: vendor-g-model-1")
        trial_end = text.index("  - id: vendor-h-model-1")
        block = text[trial_start:trial_end].replace("quorum_eligible: false", "quorum_eligible: true", 1)
        self.write_catalog(text[:trial_start] + block + text[trial_end:])
        self.assert_fails_with("quorum_eligible must be false")

    def test_retired_with_quorum_true_fails(self):
        text = self.catalog_text()
        trial_start = text.index("  - id: vendor-g-model-1")
        trial_end = text.index("  - id: vendor-h-model-1")
        block = text[trial_start:trial_end]
        block = block.replace("status: trial", "status: retired", 1)
        block = block.replace("quorum_eligible: false", "quorum_eligible: true", 1)
        self.write_catalog(text[:trial_start] + block + text[trial_end:])
        result = self.run_check()
        self.assert_fails_with("retired rule", result)
        self.assertIn("quorum_eligible must be false", result.stderr)

    def test_rank_must_be_integer_at_least_one(self):
        for invalid in ("0", "-1", "true"):
            with self.subTest(invalid=invalid):
                original = (REPO_ROOT / "manifests" / "model-catalog.yaml").read_text(encoding="utf-8")
                self.write_catalog(re.sub(r"(^    rank: )[^\n]+", rf"\g<1>{invalid}", original, count=1, flags=re.M))
                self.assert_fails_with("must be an integer >= 1")

    def test_tier_rank_pair_must_be_unique(self):
        text = self.catalog_text()
        rows = re.findall(r"(?ms)^  - id: .*?(?=^  - id: |\Z)", text)
        parsed = []
        for row in rows:
            tier = re.search(r"^    tier: ([^\n]+)$", row, re.M)
            rank = re.search(r"^    rank: ([0-9]+)$", row, re.M)
            if tier and rank:
                parsed.append((row, tier.group(1), rank.group(1)))
        self.assertGreaterEqual(len(parsed), 2)
        source_row, tier, rank = parsed[0]
        target_row = next(row for row, other_tier, _ in parsed[1:] if other_tier == tier)
        mutated_target = re.sub(r"(^    rank: )[0-9]+$", rf"\g<1>{rank}", target_row, count=1, flags=re.M)
        self.write_catalog(text.replace(target_row, mutated_target, 1))
        self.assert_fails_with("duplicate tier-rank")

    def test_at_least_one_drawable_priority_row_is_required(self):
        rows = re.findall(r"(?ms)^  - id: .*?(?=^  - id: |\Z)", self.catalog_text())
        mutated_rows = []
        for row in rows:
            row = row.replace("status: current", "status: trial", 1)
            row = row.replace("quorum_eligible: true", "quorum_eligible: false", 1)
            if "recheck_after:" not in row:
                row = row.replace(
                    "    quorum_eligible: false\n",
                    "    quorum_eligible: false\n    recheck_after: 2099-01-01\n",
                    1,
                )
            mutated_rows.append(row)
        prefix = self.catalog_text()[: self.catalog_text().index("  - id: ")]
        self.write_catalog(prefix + "".join(mutated_rows))
        self.assertNotIn("status: current", self.catalog_text())
        self.assert_fails_with("at least one current priority quorum-eligible row is required")

    def test_revision_must_be_non_boolean_integer_at_least_one(self):
        for invalid in ("true", "0", "-1", "one"):
            with self.subTest(invalid=invalid):
                original = (REPO_ROOT / "manifests" / "model-catalog.yaml").read_text(encoding="utf-8")
                self.write_catalog(original.replace("revision: 1", f"revision: {invalid}", 1))
                self.assert_fails_with("must be an integer >= 1")

    def test_catalog_dates_must_parse_and_effective_must_not_precede_date(self):
        original = self.catalog_text()
        self.write_catalog(original.replace("date: 2026-08-15", "date: 2026-02-30", 1))
        self.assert_fails_with("must be a valid ISO date")
        self.write_catalog(original.replace("revision_effective_after: 2026-08-22", "revision_effective_after: 2026-08-14", 1))
        self.assert_fails_with("revision_effective_after must be on or after date")

    def test_missing_public_snapshot_section_fails(self):
        self.policy.write_text("# policy without required heading\n", encoding="utf-8")
        self.assert_fails_with("required section '## public-snapshot 除外' is absent")

    def test_policy_requires_exact_full_headings_sentence_and_gates(self):
        policy = self.policy.read_text(encoding="utf-8")
        required = (
            "## 非規範宣言（handbook L1-10 と同文・逐語）",
            "## 枠と選出",
            "## 使用時 stamp（fail-closed）",
            "## merge 権限（オーナー専決 + CI ゲート + front door + fast path）",
            "## public-snapshot 除外",
            "## LC-1（退場トリガー）",
            "**G1**",
            "**G2**",
            "カタログは法が禁じる席を合法化できず、メンバーが生存確認できないモデルを使用可能にできない。eligibility はメンバー設定が勝ち、席数と制約はハンドブックが勝つ。",
        )
        for required_text in required:
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, policy)
                self.policy.write_text(policy.replace(required_text, "removed", 1), encoding="utf-8")
                self.assert_fails_with("policy:")
                self.policy.write_text(policy, encoding="utf-8")

    def test_missing_or_malformed_catalog_schema_fails(self):
        self.schema.unlink()
        self.assert_fails_with("cannot read catalog schema")
        self.schema.write_text("{not-json", encoding="utf-8")
        self.assert_fails_with("cannot parse catalog schema")

    def test_nested_catalog_schema_drift_fails_closed(self):
        schema = json.loads(self.schema.read_text(encoding="utf-8"))
        schema["definitions"]["model"]["properties"]["tier"]["enum"].append("emergency")
        self.schema.write_text(json.dumps(schema), encoding="utf-8")
        self.assert_fails_with("catalog schema contract drift")

        shutil.copyfile(REPO_ROOT / "manifests" / "model-catalog.schema.json", self.schema)
        schema = json.loads(self.schema.read_text(encoding="utf-8"))
        schema["definitions"]["model"]["properties"]["lineage"]["additionalProperties"] = True
        self.schema.write_text(json.dumps(schema), encoding="utf-8")
        self.assert_fails_with("catalog schema contract drift")

    def test_published_schema_exactly_matches_checker_contract_and_key_sets(self):
        loader = importlib.machinery.SourceFileLoader("model_catalog_check_contract", str(CHECKER))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        expected = module.expected_catalog_schema()
        actual = json.loads(self.schema.read_text(encoding="utf-8"))
        self.assertEqual(actual, expected)
        self.assertEqual(module.TOP_LEVEL_KEYS, set(expected["properties"]))
        self.assertEqual(module.TOP_LEVEL_REQUIRED, set(expected["required"]))
        model_schema = expected["definitions"]["model"]
        self.assertEqual(module.ROW_KEYS, set(model_schema["properties"]))
        self.assertEqual(module.ROW_REQUIRED, set(model_schema["required"]))
        self.assertEqual(module.LINEAGE_KEYS, set(model_schema["properties"]["lineage"]["properties"]))

        expected_member = module.expected_member_schema()
        actual_member = json.loads(self.member_schema.read_text(encoding="utf-8"))
        self.assertEqual(actual_member, expected_member)
        self.assertEqual(module.MEMBER_KEYS, set(expected_member["properties"]))
        self.assertEqual(module.MEMBER_KEYS, set(expected_member["required"]))
        self.assertEqual(
            expected_member["properties"]["referenced_ids"]["items"],
            expected["definitions"]["nonEmptyString"],
        )

    def test_catalog_id_statuses_rejects_non_dict_row(self):
        module = self.load_checker_module("model_catalog_check_non_dict_row")
        self.assertIsNone(module.catalog_id_statuses({"models": ["not-a-row"]}))

    def test_catalog_id_statuses_rejects_unknown_status(self):
        module = self.load_checker_module("model_catalog_check_unknown_status")
        self.assertIsNone(
            module.catalog_id_statuses({"models": [{"id": "model-a", "status": "paused"}]})
        )

    def test_catalog_id_statuses_rejects_duplicate_id(self):
        module = self.load_checker_module("model_catalog_check_duplicate_id")
        self.assertIsNone(
            module.catalog_id_statuses(
                {
                    "models": [
                        {"id": "model-a", "status": "current"},
                        {"id": "model-a", "status": "retired"},
                    ]
                }
            )
        )

    def test_catalog_id_statuses_returns_id_status_map(self):
        module = self.load_checker_module("model_catalog_check_valid_statuses")
        self.assertEqual(
            module.catalog_id_statuses(
                {
                    "models": [
                        {"id": "model-a", "status": "current"},
                        {"id": "model-b", "status": "trial"},
                        {"id": "model-c", "status": "retired"},
                    ]
                }
            ),
            {"model-a": "current", "model-b": "trial", "model-c": "retired"},
        )

    def test_baseline_is_fail_closed_when_missing_or_invalid(self):
        missing = self.root / "missing.yaml"
        self.assert_fails_with("cannot read baseline catalog", self.run_check("--baseline", missing))
        self.baseline.write_text("revision:\t1\n", encoding="utf-8")
        self.assert_fails_with("tabs are not allowed", self.run_check("--baseline", self.baseline))
        invalid = re.sub(
            r"(^    rank: )[^\n]+",
            r"\g<1>0",
            (REPO_ROOT / "manifests" / "model-catalog.yaml").read_text(encoding="utf-8"),
            count=1,
            flags=re.M,
        )
        self.baseline.write_text(invalid, encoding="utf-8")
        self.assert_fails_with("baseline catalog is invalid", self.run_check("--baseline", self.baseline))

    def test_changed_bytes_require_revision_increase_and_changed_changelog(self):
        self.write_catalog(self.catalog_text() + "\n")
        self.adopt_current_catalog()
        result = self.run_check("--baseline", self.baseline)
        self.assert_fails_with("changed catalog bytes require a revision increase", result)
        self.assertIn("changed catalog bytes require a changed changelog", result.stderr)

    def test_baseline_accepts_identical_bytes_or_complete_revision_metadata(self):
        identical = self.run_check("--baseline", self.baseline)
        self.assertEqual(identical.returncode, 0, identical.stdout + identical.stderr)

        text = self.catalog_text().replace("revision: 1", "revision: 2", 1)
        text = text.replace("changelog: >\n", "changelog: >\n  Baseline regression marker.\n", 1)
        self.write_catalog(text)
        self.adopt_current_catalog()
        changed = self.run_check("--baseline", self.baseline)
        self.assertEqual(changed.returncode, 0, changed.stdout + changed.stderr)

    def test_member_state_missing_extra_and_bad_digest_fields_fail(self):
        state = json.loads(self.member_a.read_text(encoding="utf-8"))
        del state["member"]
        state["availability"] = True
        state["config_digest"] = "not-a-digest"
        self.member_a.write_text(json.dumps(state), encoding="utf-8")
        result = self.run_check()
        self.assert_fails_with("missing required property 'member'", result)
        self.assertIn("additional property 'availability' is not allowed", result.stderr)
        self.assertIn("must be a lowercase SHA-256 digest", result.stderr)

    def test_member_state_missing_referenced_ids_fails(self):
        state = self.member_state()
        del state["referenced_ids"]
        self.write_member_state(state)
        self.assert_fails_with("missing required property 'referenced_ids'")

    def test_member_state_missing_referenced_ids_emits_only_missing_property_error(self):
        state = self.member_state()
        del state["referenced_ids"]
        self.write_member_state(state)
        result = self.run_check()
        self.assert_fails_with("missing required property 'referenced_ids'", result)
        self.assertNotIn("must be an array", result.stderr)

    def test_member_state_referenced_ids_must_be_sorted(self):
        state = self.member_state()
        state["referenced_ids"] = ["vendor-e-model-1", "vendor-a-model-1"]
        self.write_member_state(state)
        result = self.run_check()
        self.assert_fails_with("must be sorted in bytewise/codepoint ascending order", result)
        self.assertIn("LC_ALL=C; case-sensitive", result.stderr)
        self.assertIn("regenerate it from the member's local seat-configuration file", result.stderr)

    def test_documented_generator_produces_accepted_codepoint_order(self):
        upper_id = "Vendor-e-model-1"
        self.write_catalog(self.catalog_text().replace("id: vendor-e-model-1", f"id: {upper_id}", 1))
        policy = self.policy.read_text(encoding="utf-8")
        match = re.search(r"```sh\n  (LC_ALL=C python3 -c .+)\n  ```", policy)
        self.assertIsNotNone(match, "documented referenced_ids generator is missing")
        seat_config = self.root / "member-a-seat-config.json"
        seat_config.write_text(
            json.dumps(
                {
                    "seats": [
                        {"model_id": "vendor-c-model-2"},
                        {"model_id": "vendor-a-model-1"},
                        {"model_id": upper_id},
                        {"model_id": "vendor-a-model-1"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        env = dict(os.environ, SEAT_CONFIG=str(seat_config))
        generated = subprocess.run(
            match.group(1),
            shell=True,
            executable="/bin/sh",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=env,
        )
        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
        self.assertEqual(
            json.loads(generated.stdout),
            [upper_id, "vendor-a-model-1", "vendor-c-model-2"],
        )
        state = self.member_state()
        state["referenced_ids"] = json.loads(generated.stdout)
        self.write_member_state(state)
        self.adopt_current_catalog()
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_documented_generator_matches_published_sample(self):
        generator = (
            'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); '
            'print(json.dumps(sorted({seat["model_id"] for seat in d["seats"]}), '
            'ensure_ascii=False, separators=(",", ":")))'
        )
        env = dict(os.environ, LC_ALL="C")
        result = subprocess.run(
            [
                "python3",
                "-c",
                generator,
                str(REPO_ROOT / "manifests" / "member-state" / "samples" / "seat-config.example.json"),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '["vendor-a-model-1","vendor-e-model-1"]\n')

    def test_member_state_referenced_ids_reject_duplicates(self):
        state = self.member_state()
        state["referenced_ids"] = ["vendor-a-model-1", "vendor-a-model-1"]
        self.write_member_state(state)
        self.assert_fails_with("duplicate model id 'vendor-a-model-1' is not allowed")

    def test_member_state_referenced_ids_reject_empty_list(self):
        state = self.member_state()
        state["referenced_ids"] = []
        self.write_member_state(state)
        self.assert_fails_with("must contain at least one model id")

    def test_member_state_referenced_ids_must_be_a_list(self):
        state = self.member_state()
        state["referenced_ids"] = "vendor-a-model-1"
        self.write_member_state(state)
        self.assert_fails_with(
            "member-state member-a.json: referenced_ids for member 'member-a': must be an array"
        )

    def test_member_state_referenced_ids_reject_non_string_element(self):
        state = self.member_state()
        state["referenced_ids"] = [7, "vendor-a-model-1"]
        self.write_member_state(state)
        self.assert_fails_with(
            "member-state member-a.json: referenced_ids[0] for member 'member-a': "
            "must be a non-empty string"
        )

    def test_member_state_referenced_ids_reject_malformed_id(self):
        state = self.member_state()
        state["referenced_ids"] = ["   "]
        self.write_member_state(state)
        self.assert_fails_with(
            "member-state member-a.json: referenced_ids[0] for member 'member-a': "
            "must be a non-empty string"
        )

    def test_member_state_referenced_id_absent_from_catalog_fails_union(self):
        absent_id = "vendor-z-model-404"
        state = self.member_state()
        state["referenced_ids"] = [absent_id]
        self.write_member_state(state)
        result = self.run_check()
        self.assert_fails_with("absent from the catalog", result)
        self.assertIn("member-a", result.stderr)
        self.assertIn(absent_id, result.stderr)

    def test_member_union_checks_absent_id_after_index_zero(self):
        absent_id = "vendor-z-model-404"
        state = self.member_state()
        state["referenced_ids"] = ["vendor-a-model-1", absent_id]
        self.write_member_state(state)
        result = self.run_check()
        self.assert_fails_with("absent from the catalog", result)
        self.assertIn(absent_id, result.stderr)

    def test_member_union_uses_ids_from_live_catalog_models(self):
        old_id = "vendor-a-model-1"
        new_id = "vendor-a-model-renamed"
        self.write_catalog(
            self.catalog_text().replace(f"  - id: {old_id}", f"  - id: {new_id}", 1)
        )
        self.adopt_current_catalog()
        result = self.run_check()
        self.assert_fails_with("absent from the catalog", result)
        self.assertIn("member-a", result.stderr)
        self.assertIn(old_id, result.stderr)

    def test_empty_catalog_cannot_vacuously_pass_member_union(self):
        text = self.catalog_text()
        self.write_catalog(text[: text.index("  - id: ")])
        result = self.run_check()
        self.assert_fails_with("must contain at least one row", result)
        self.assertIn("cannot validate member referenced_ids", result.stderr)
        self.assertIn("empty or invalid catalog model id set", result.stderr)

    def test_member_reference_to_retired_catalog_row_is_notice(self):
        text = self.catalog_text()
        row_start = text.index("  - id: vendor-a-model-1")
        row_end = text.index("  - id: vendor-b-model-1")
        row = text[row_start:row_end]
        row = row.replace("status: current", "status: retired", 1)
        row = row.replace("quorum_eligible: true", "quorum_eligible: false", 1)
        self.write_catalog(text[:row_start] + row + text[row_end:])
        self.adopt_current_catalog()
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "NOTICE: member 'member-a' references retired model id 'vendor-a-model-1'",
            result.stderr,
        )

    def test_member_reference_to_trial_catalog_row_is_notice(self):
        state = self.member_state()
        state["referenced_ids"] = ["vendor-g-model-1"]
        self.write_member_state(state)
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "NOTICE: member 'member-a' references trial model id 'vendor-g-model-1' "
            "(trial rows are outside the draw and outside quorum)",
            result.stderr,
        )

    def test_member_state_malformed_json_fails_closed(self):
        self.member_a.write_text('{"member":', encoding="utf-8")
        self.assert_fails_with("cannot parse member-state record")

    def test_stale_member_digest_is_notice_within_adoption_window(self):
        today = dt.date.today()
        effective = today + dt.timedelta(days=1)
        self.set_catalog_window(today.isoformat(), effective.isoformat())
        state = json.loads(self.member_a.read_text(encoding="utf-8"))
        state["catalog_digest_adopted"] = "0" * 64
        self.member_a.write_text(json.dumps(state), encoding="utf-8")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            f"NOTICE: member-a lags current digest (within adoption window until {effective.isoformat()})",
            result.stderr,
        )

    def test_absent_reference_is_notice_for_lagging_digest_within_window(self):
        today = dt.date.today()
        self.set_catalog_window(today.isoformat(), today.isoformat())
        absent_id = "vendor-z-model-404"
        state = self.member_state()
        state["catalog_digest_adopted"] = "0" * 64
        state["referenced_ids"] = [absent_id]
        self.write_member_state(state)
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            f"NOTICE: member-state member-a.json: member 'member-a' references model id "
            f"'{absent_id}' that is absent from the catalog "
            f"(within adoption window until {today.isoformat()})",
            result.stderr,
        )
        self.assertIn("NOTICE: member-a lags current digest", result.stderr)
        self.assertNotIn("ERROR:", result.stderr)

    def test_stale_member_digest_is_error_after_adoption_window(self):
        today = dt.date.today()
        self.set_catalog_window(
            (today - dt.timedelta(days=2)).isoformat(),
            (today - dt.timedelta(days=1)).isoformat(),
        )
        absent_id = "vendor-z-model-404"
        state = self.member_state()
        state["referenced_ids"] = [absent_id]
        self.write_member_state(state)
        result = self.run_check()
        self.assert_fails_with("does not match existing catalog digest", result)
        self.assertIn(f"model id '{absent_id}' that is absent from the catalog", result.stderr)
        self.assertNotIn("NOTICE:", result.stderr)

    def test_malformed_member_digest_is_error_even_within_window(self):
        state = json.loads(self.member_a.read_text(encoding="utf-8"))
        state["catalog_digest_adopted"] = "not-a-digest"
        self.member_a.write_text(json.dumps(state), encoding="utf-8")
        result = self.run_check()
        self.assert_fails_with("must be a lowercase SHA-256 digest", result)
        self.assertNotIn("NOTICE:", result.stderr)

    def test_member_schema_is_required_and_fail_closed(self):
        self.member_schema.unlink()
        self.assert_fails_with("cannot read member-state schema")

    def test_member_schema_property_drift_fails_closed(self):
        schema = json.loads(self.member_schema.read_text(encoding="utf-8"))
        del schema["properties"]["catalog_digest_adopted"]["pattern"]
        self.member_schema.write_text(json.dumps(schema), encoding="utf-8")
        self.assert_fails_with("member-state schema contract drift")


if __name__ == "__main__":
    unittest.main(verbosity=2)
