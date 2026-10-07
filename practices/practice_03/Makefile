.PHONY: install test check

install:
	@$(MAKE) -s -C lab install

test:
	@$(MAKE) -s -C lab test

check: test
	python3 lab/verify_evidence.py
