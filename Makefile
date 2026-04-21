.PHONY: generate install dev test clean

SPEC_URL ?= https://api3.judgmentlabs.ai/openapi/json

# Re-generate CLI commands from the OpenAPI spec
generate:
	python3 scripts/generate_cli.py $(SPEC_URL)

# Install the CLI in the current Python environment
install:
	pip install .

# Install in editable (development) mode
dev:
	pip install -e ".[dev]"

# Smoke test: run help and version
test:
	judgment --version
	judgment --help

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
