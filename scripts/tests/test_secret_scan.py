#!/usr/bin/env python3
"""Tests for scripts/secret-scan."""

import os
import importlib.machinery
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SECRET_SCAN_SCRIPT = REPO_ROOT / "scripts" / "secret-scan"


def load_module():
    loader = importlib.machinery.SourceFileLoader("secret_scan_under_test", str(SECRET_SCAN_SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class SecretScanTests(unittest.TestCase):
    def run_scan(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, str(SECRET_SCAN_SCRIPT), *map(str, args)],
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def run_redact(self, input_value, text=True):
        return subprocess.run(
            [sys.executable, str(SECRET_SCAN_SCRIPT), "--redact"],
            input=input_value,
            text=text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def write_file(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_git(self, repo, *args):
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    def init_git_repo(self, repo):
        self.run_git(repo, "init")

    def create_head(self, repo, files):
        for relpath, text in files.items():
            self.write_file(repo / relpath, text)
        self.run_git(repo, "add", *files.keys())
        tree = self.run_git(repo, "write-tree").stdout.strip()
        commit = subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit-tree", tree, "-m", "init"],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout.strip()
        self.run_git(repo, "update-ref", "HEAD", commit)

    def assert_rule_fires(self, line, rule_id):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_file(Path(tmp) / "fixture.env", line + "\n")
            result = self.run_scan(path)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(f"{rule_id}:", result.stdout)

    def assert_line_clean(self, line, suffix="fixture.txt"):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_file(Path(tmp) / suffix, line + "\n")
            result = self.run_scan(path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_meili_key_fires(self):
        self.assert_rule_fires("MEILI_MASTER_KEY=aBcDeF1234567890aBcDeF1234567890", "meili-key")  # secret-scan: allow

    def test_json_style_quoted_meili_key_fires(self):
        self.assert_rule_fires('"MEILI_MASTER_KEY": "aBcDeF1234567890aBcDeF1234567890"', "meili-key")  # secret-scan: allow

    def test_supermemory_token_fires(self):
        self.assert_rule_fires("SUPERMEMORY_CC_API_KEY=supermemory_live_token_1234567890", "supermemory-token")  # secret-scan: allow
        self.assert_rule_fires("token = sm_abcdefghijklmnopqrstuvwx", "supermemory-token")  # secret-scan: allow

    def test_quoted_supermemory_identifier_fires(self):
        self.assert_rule_fires('"SUPERMEMORY_API_KEY": "supermemory_live_token_1234567890"', "supermemory-token")  # secret-scan: allow

    def test_supermemory_container_tag_stays_clean(self):
        self.assert_line_clean("SUPERMEMORY_CONTAINER_TAG=replus_livetalk", "fixture.env")

    def test_supermemory_api_token_identifier_fires(self):
        self.assert_rule_fires("SUPERMEMORY_API_TOKEN=supermemory_live_token_1234567890", "supermemory-token")  # secret-scan: allow

    def test_supermemory_monkey_identifier_stays_clean(self):
        self.assert_line_clean("SUPERMEMORY_MONKEY=supermemory_live_token_1234567890", "fixture.env")

    def test_credential_identifier_segment_matching(self):
        module = load_module()
        for identifier in ("API_KEY", "apiKey", "SUPERMEMORY_API_TOKEN", "apikey"):
            self.assertTrue(module.is_credential_identifier(identifier), identifier)
        for identifier in ("MONKEY", "AUTHOR", "DONKEY", "passwordless", "SUPERMEMORY_CONTAINER_TAG"):
            self.assertFalse(module.is_credential_identifier(identifier), identifier)
        self.assertTrue(module.is_supermemory_credential_identifier("SUPERMEMORY_API_TOKEN"))
        self.assertFalse(module.is_supermemory_credential_identifier("SUPERMEMORY_MONKEY"))
        self.assertFalse(module.is_supermemory_credential_identifier("SUPERMEMORY_CONTAINER_TAG"))

    def test_ordinary_json_non_credential_key_stays_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_file(Path(tmp) / "fixture.json", '{"name": "value"}\n')
            result = self.run_scan(path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_tailscale_authkey_fires(self):
        self.assert_rule_fires("TAILSCALE_AUTHKEY=tskey-auth-kp1234567890abcdef", "tailscale-authkey")  # secret-scan: allow

    def test_op_uri_fires_only_in_assignment_context(self):
        self.assert_rule_fires("MEILI_MASTER_KEY=op://vault/item/field", "op-uri")  # secret-scan: allow
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_file(
                Path(tmp) / "design.md",
                "- `MEILI_*KEY` / Supermemory token / Tailscale authkey / `op://` / high entropy\n",
            )
            result = self.run_scan(path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_spaced_op_uri_assignment_fires(self):
        self.assert_rule_fires("FOO=op://Private Vault/Some Item/key", "op-uri")  # secret-scan: allow

    def test_bare_op_uri_markdown_with_two_code_spans_stays_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_file(
                Path(tmp) / "design.md",
                "Docs mention `op://Private Vault/Some Item/key` and `FOO=bar`: no secret value.\n",
            )
            result = self.run_scan(path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bearer_token_fires(self):
        self.assert_rule_fires("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456", "bearer-token")  # secret-scan: allow

    def test_high_entropy_fires(self):
        self.assert_rule_fires("session_secret = A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0+/==", "high-entropy")  # secret-scan: allow

    def test_google_docs_url_doc_id_stays_clean(self):
        self.assert_line_clean(
            "Reference: https://docs.google.com/document/d/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789ABCDEFGH/edit",
            "notes.md",
        )

    def test_notion_url_path_id_stays_clean(self):
        self.assert_line_clean(
            "Reference: https://www.notion.so/workspace/Page-0123456789abcdef0123456789abcdef?pvs=4",
            "notes.md",
        )

    def test_prose_high_entropy_token_without_credential_context_stays_clean(self):
        self.assert_line_clean("Meeting URL includes 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcd as an opaque id.", "notes.md")

    def test_credential_assignment_high_entropy_fires_without_spacing(self):
        self.assert_rule_fires("MY_API_KEY=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcd", "high-entropy")  # secret-scan: allow

    def test_json_quoted_api_key_high_entropy_fires(self):
        self.assert_rule_fires('"api_key": "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcd"', "high-entropy")  # secret-scan: allow

    def test_camelcase_api_key_high_entropy_fires(self):
        self.assert_rule_fires("apiKey=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcd", "high-entropy")  # secret-scan: allow

    def test_high_entropy_assignment_rejects_identifier_substrings(self):
        value = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcd"
        for identifier in ("monkey_id", "MONKEY", "AUTHOR", "DONKEY", "passwordless"):
            self.assert_line_clean(f"{identifier}={value}", "fixture.env")

    def test_url_query_credential_high_entropy_fires(self):
        self.assert_rule_fires("https://x.example/cb?token=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcd", "high-entropy")  # secret-scan: allow

    def test_url_path_high_entropy_without_credential_param_stays_clean(self):
        self.assert_line_clean("https://x.example/cb/0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcd", "notes.md")

    def test_github_pat_prefix_fires_in_prose(self):
        self.assert_rule_fires("Pasted ghp_1234567890abcdefABCDEF1234567890abcd in notes.", "high-entropy")  # secret-scan: allow

    def test_jwt_shape_fires_in_prose(self):
        self.assert_rule_fires(
            "Pasted eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkphbmUiLCJpYXQiOjE1MTYyMzkwMjJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c in notes.",  # secret-scan: allow
            "high-entropy",
        )

    def test_compact_jwt_shape_fires(self):
        self.assert_rule_fires(
            "Pasted eyJabcdefghij.klmnopqrstuv.wxyzABCDEFGHI in notes.",  # secret-scan: allow
            "high-entropy",
        )

    def test_two_segment_jwt_like_string_stays_clean(self):
        self.assert_line_clean("Pasted eyJabcdefghij.klmnopqrstuv in notes.", "notes.md")

    def test_identifier_mentions_without_values_do_not_fire(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_file(
                Path(tmp) / "notes.md",
                "Docs mention `MEILI_MASTER_KEY` and FAMILY_MEILI_WRITE_KEY_FAMILY_VAULT with no assigned value.\n",
            )
            result = self.run_scan(path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_allow_pragma_suppresses_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_file(
                Path(tmp) / "fixture.env",
                "TAILSCALE_AUTHKEY=tskey-auth-kp1234567890abcdef  # secret-scan: allow\n",
            )
            result = self.run_scan(path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sha256_context_does_not_fire_high_entropy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_file(
                Path(tmp) / "manifest.yaml",
                "sources_sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n",
            )
            result = self.run_scan(path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_staged_mode_reports_added_secret_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.init_git_repo(repo)
            self.write_file(
                repo / "secrets.env",
                "SAFE=value\nMEILI_MASTER_KEY=aBcDeF1234567890aBcDeF1234567890\n",  # secret-scan: allow
            )
            self.run_git(repo, "add", "secrets.env")

            result = self.run_scan("--staged", cwd=repo)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("secrets.env:2: meili-key:", result.stdout)

    def test_staged_mode_keeps_added_plus_plus_line_in_hunk(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.init_git_repo(repo)
            self.write_file(
                repo / "notes.env",
                "++ note\n"
                "MEILI_MASTER_KEY=aBcDeF1234567890aBcDeF1234567890\n",  # secret-scan: allow
            )
            self.run_git(repo, "add", "notes.env")

            result = self.run_scan("--staged", cwd=repo)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("notes.env:2: meili-key:", result.stdout)

    def test_staged_mode_clean_file_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.init_git_repo(repo)
            self.write_file(repo / "clean.env", "MEILI_MASTER_KEY=<replace-me>\n")
            self.run_git(repo, "add", "clean.env")

            result = self.run_scan("--staged", cwd=repo)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_staged_mode_uses_full_blob_for_sha256_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.init_git_repo(repo)
            self.create_head(repo, {"manifest.yaml": "sources_sha256:\n"})
            self.write_file(
                repo / "manifest.yaml",
                "sources_sha256:\n"
                "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n",  # secret-scan: allow
            )
            self.run_git(repo, "add", "manifest.yaml")

            result = self.run_scan("--staged", cwd=repo)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_staged_mode_without_sha_context_no_longer_flags_bare_hex_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.init_git_repo(repo)
            self.write_file(
                repo / "token.txt",
                "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n",  # secret-scan: allow
            )
            self.run_git(repo, "add", "token.txt")

            result = self.run_scan("--staged", cwd=repo)
            # Bare high-entropy hex IDs caused vault false positives; credential context is now required.
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_staged_mode_flags_credential_assigned_hex_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.init_git_repo(repo)
            self.write_file(
                repo / "token.env",
                "API_TOKEN=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n",  # secret-scan: allow
            )
            self.run_git(repo, "add", "token.env")

            result = self.run_scan("--staged", cwd=repo)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("token.env:1: high-entropy:", result.stdout)

    def test_exit_codes_cover_clean_error_and_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            clean = self.write_file(Path(tmp) / "clean.txt", "no secrets here\n")
            dirty = self.write_file(Path(tmp) / "dirty.env", "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456\n")  # secret-scan: allow

            self.assertEqual(self.run_scan(clean).returncode, 0)
            self.assertEqual(self.run_scan(dirty).returncode, 2)
            self.assertEqual(self.run_scan(Path(tmp) / "missing.txt").returncode, 1)
            self.assertEqual(self.run_scan("--staged", clean).returncode, 1)

    def test_redaction_never_prints_full_secret(self):
        secret = "aBcDeF1234567890aBcDeF1234567890"  # secret-scan: allow
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_file(Path(tmp) / "fixture.env", f"MEILI_MASTER_KEY={secret}\n")
            result = self.run_scan(path)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertNotIn(secret, result.stdout)
            self.assertIn("aBcD...", result.stdout)

    def test_redact_clean_text_passes_through_byte_identical(self):
        text = b"ordinary note\r\nwith no credentials\n"
        result = self.run_redact(text, text=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, text)

    def test_redact_high_risk_token_replaces_value(self):
        secret = "gh" + "p_" + "1234567890abcdefABCDEF1234567890abcd"
        result = self.run_redact(f"pasted token {secret}\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "pasted token <REDACTED:high-entropy>\n")
        self.assertNotIn(secret, result.stdout)

    def test_redact_multiple_distinct_secrets(self):
        tailscale = "ts" + "key-auth-kp1234567890abcdef"
        meili = "aBcDeF1234567890aBcDeF1234567890"  # secret-scan: allow
        result = self.run_redact(f"TAILSCALE_AUTHKEY={tailscale}\nMEILI_MASTER_KEY={meili}\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("TAILSCALE_AUTHKEY=<REDACTED:tailscale-authkey>", result.stdout)
        self.assertIn("MEILI_MASTER_KEY=<REDACTED:meili-key>", result.stdout)
        self.assertNotIn(tailscale, result.stdout)
        self.assertNotIn(meili, result.stdout)

    def test_redact_allow_pragma_suppresses_redaction(self):
        text = "TAILSCALE_AUTHKEY=" + "ts" + "key-auth-kp1234567890abcdef  # secret-scan: allow\n"
        result = self.run_redact(text)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, text)

    def test_redact_binary_stdin_exits_three_and_stdout_untrusted(self):
        result = self.run_redact(b"prefix\0suffix", text=False)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"secret-scan: error:", result.stderr)

    def test_redact_late_nul_byte_exits_three(self):
        result = self.run_redact(b"a" * 5000 + b"\0suffix", text=False)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"secret-scan: error:", result.stderr)

    def test_redact_invalid_utf8_exits_three(self):
        result = self.run_redact(b"prefix\xffsuffix", text=False)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"secret-scan: error:", result.stderr)

    def test_redact_empty_stdin_exits_zero_with_empty_stdout(self):
        result = self.run_redact("")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_redact_same_secret_twice_on_one_line(self):
        secret = "gh" + "p_" + "1234567890abcdefABCDEF1234567890abcd"
        result = self.run_redact(f"pasted {secret} then {secret}\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout,
            "pasted <REDACTED:high-entropy> then <REDACTED:high-entropy>\n",
        )
        self.assertNotIn(secret, result.stdout)

    def test_redact_adjacent_different_secrets_without_corrupting_output(self):
        meili = "aBcDeF1234567890aBcDeF1234567890"  # secret-scan: allow
        tailscale = "ts" + "key-auth-kp1234567890abcdef"
        result = self.run_redact(f"MEILI_MASTER_KEY={meili} TAILSCALE_AUTHKEY={tailscale}\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "MEILI_MASTER_KEY=<REDACTED:meili-key> TAILSCALE_AUTHKEY=<REDACTED:tailscale-authkey>\n")
        self.assertNotIn(meili, result.stdout)
        self.assertNotIn(tailscale, result.stdout)

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_staged_mode_requires_git_repo_for_error_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_scan("--staged", cwd=tmp)
            self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
