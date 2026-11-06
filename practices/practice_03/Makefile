.PHONY: install test setup-check lint check install-hooks

install:
	@$(MAKE) -s -C lab install

test:
	@$(MAKE) -s -C lab test

setup-check:
	python3 -m venv .venv-check
	.venv-check/bin/python -m pip install -r requirements-dev.txt

lint:
	.venv-check/bin/python -m ruff check --config ruff.toml lab/demo

check:
	@bash scripts/check.sh

install-hooks:
	@bash scripts/install-hook.sh
