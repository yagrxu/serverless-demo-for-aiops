.PHONY: install lint typecheck test test-property test-integration-local test-integration-cloud

install:
	uv sync --all-extras

lint:
	uv run ruff check trafgen/ tests/

typecheck:
	uv run mypy trafgen/

test:
	uv run pytest tests/ -m "not integration_local and not integration_cloud" -v

test-property:
	uv run pytest tests/ -m "not integration_local and not integration_cloud" -v --hypothesis-seed=0

test-integration-local:
	uv run pytest tests/ -m integration_local -v --timeout=30

test-integration-cloud:
	uv run pytest tests/ -m integration_cloud -v --timeout=120
