.PHONY: test

ARTIFACTS := \
	context.md \
	problem.md \
	analysis.md \
	product_management.md \
	project_management.md \
	adr.md \
	tests_unit.md \
	tests_integration.md \
	tests_load.md \
	tests_e2e.md \
	prompts.md

test:
	@test -f README.md
	@test -f TRAINING_PR.diff
	@for file in $(ARTIFACTS); do test -s "$$file" || { echo "Missing or empty: $$file"; exit 1; }; done
	@grep -q "## Context Pack" context.md
	@grep -q "## Метрики" problem.md
	@grep -q "## TO BE" analysis.md
	@grep -q '```gherkin' product_management.md
	@grep -q '```mermaid' project_management.md
	@grep -q "## Архитектурная схема" adr.md
	@grep -q "P1-01" prompts.md
	@grep -q "P1-02" prompts.md
	@echo "Practice 1 artifacts: OK"
