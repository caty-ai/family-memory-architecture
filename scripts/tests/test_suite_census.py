"""Census gate: every scripts/tests/test_*.py must be loaded by run_tests.py.

Guards against the forget-to-register class: a test module that exists on disk
but is never imported into the suite stays invisible to CI — the exact-count
gate in full-suite.yml cannot see tests it never loads, so the suite stays green
while whole modules silently don't run.

Registration is verified against the suite-construction source of run_tests.py
(loadTestsFromModule entries), not sys.modules, so this test gives the same
answer no matter which runner imported it. This file must itself be registered
in run_tests.py — the census includes it.
"""
import pathlib
import re
import unittest

TESTS_DIR = pathlib.Path(__file__).resolve().parent
RUNNER = TESTS_DIR / "run_tests.py"
_REGISTERED_RE = re.compile(r"loadTestsFromModule\((test_[A-Za-z0-9_]+)\)")


def _registered_modules():
    return set(_REGISTERED_RE.findall(RUNNER.read_text(encoding="utf-8")))


def _modules_on_disk():
    return {path.stem for path in TESTS_DIR.glob("test_*.py")}


class SuiteCensusTests(unittest.TestCase):
    def test_every_test_module_on_disk_is_registered(self):
        missing = sorted(_modules_on_disk() - _registered_modules())
        self.assertEqual(
            missing,
            [],
            "test modules exist on disk but are not registered in the "
            "run_tests.py suite (the forget-to-register class): %r" % (missing,),
        )

    def test_every_registered_module_exists_on_disk(self):
        stale = sorted(_registered_modules() - _modules_on_disk())
        self.assertEqual(
            stale,
            [],
            "run_tests.py registers test modules that do not exist on disk: %r"
            % (stale,),
        )


if __name__ == "__main__":
    unittest.main()
