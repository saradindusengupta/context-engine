.PHONY: install lint test

install:          ## Install deps (uv primary; pip uv bootstrap for CI).
	python -m pip install --upgrade pip uv
	uv pip install --system -r requirements-test.txt

lint:             ## black --check + flake8.
	black --check src/ scripts/ tests/
	flake8 src/ scripts/ tests/

test:             ## Run pytest against the sqlite backend (no Neo4j needed).
	STORE_BACKEND=sqlite pytest -v --tb=short tests/
