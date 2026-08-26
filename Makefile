PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
TODAY := 2026-08-25

.PHONY: demo demo-deterministic test install venv

venv:
	python3 -m venv .venv && .venv/bin/pip install -q anthropic

install:
	pip install -e ".[agents]"

# Urgency bands, dispatch matching, and suspicious-completion pre-reopening.
# No API key, no model calls. --today pins the run so the output is
# reproducible from the fixture.
demo-deterministic:
	PYTHONPATH=src $(PY) -m ammar.cli examples/tickets.csv --no-agents \
		--today $(TODAY) -o closures.csv

# Full pass: draft the closure, cost it, review it, gate it. Needs ANTHROPIC_API_KEY.
demo:
	PYTHONPATH=src $(PY) -m ammar.cli examples/tickets.csv \
		--today $(TODAY) -o closures.csv

test:
	PYTHONPATH=src $(PY) tests/test_ammar.py
	PYTHONPATH=src $(PY) tests/test_agents.py
	PYTHONPATH=src $(PY) tests/check_closures.py
