# Family-standard entry point (make test / make lint) so that
# family-dev-handbook templates/ci test-lint workflow can run unmodified.

.PHONY: test lint

test:
	python3 scripts/tests/run_tests.py

lint:
	# No lint tooling exists in this repo yet. This is a deliberate no-op
	# placeholder until a real linter is wired by campaign issue B6/#32
	# successors. It intentionally does nothing and exits 0.
	@true
