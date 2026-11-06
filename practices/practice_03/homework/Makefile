PYTHON ?= python3
PY = .venv/bin/python

.PHONY: setup setup-dev test check demo

setup:
	$(PYTHON) -m venv .venv
	$(PY) -m pip install -r requirements.txt
	$(PY) -m playwright install chromium

setup-dev: setup
	$(PY) -m pip install -r requirements-dev.txt

test:
	$(PY) -m pytest

check: test
	.venv/bin/ruff check .

demo:
	$(PY) verify_live.py
