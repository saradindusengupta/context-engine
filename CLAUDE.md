# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repo was just restructured (commit `706b9ad`). The previous Makefile, `pyproject.toml`, `requirements*.txt`, `docker-compose*.yml`, `Dockerfile`, `MANIFEST.in`, and the entire `src/knowledge_graph/` package were deleted. The repo is currently a near-empty scaffold:

- `src/` — empty (no package yet)
- `data/` — empty (gitignored)
- `config/config.json` — empty file
- `tests/test_base.py` — contains only `import pytest`
- `notebooks/init.ipynb` — placeholder
- No build system, no dependency manifest, no lockfile

Expect that most "how do I run X" answers are "X doesn't exist yet — needs to be created." Do not invent commands that don't work. If the user asks you to set something up, confirm the choice of tooling (uv vs pip, pyproject vs setup.py, etc.) before scaffolding.

## Project intent (from git history, not current code)

The project is a knowledge-graph "context engine" built around **Neo4j + graphiti-core**. Removed-but-recent files included:
- `src/knowledge_graph/quickstart_neo4j.py` (~366 lines) — main implementation
- `docker-compose.yml` + `.dev.yml` + `.prod.yml` for Neo4j
- `DEPLOYMENT.md`, `DOCKER-ENVS.md` for Neo4j ops
- `requirements.txt` including `graphiti-core`

The `.gitignore` still lists `neo4j_data/`, `neo4j_logs/`, `neo4j_import/`, `neo4j_metrics/`, `neo4j_plugins/`, and `.bevel/` — so Neo4j-in-Docker and a Bevel (Hyperledger Bevel?) integration are part of the intended stack.

When asked to "reimplement X" or "bring back Y," check `git show <sha>:<path>` against commits `706b9ad`, `76c1546`, `651fb71` rather than starting from scratch.

## CI workflows (still present, but currently broken)

`.github/workflows/`:
- `main.yml` — CI: runs `make install`, `make lint`, `make test` on Python 3.9. **Currently fails** (no Makefile). Triggers are commented out; only `workflow_dispatch`.
- `lintinig.yml` (sic) — runs `black` and `flake8` via `wearerequired/lint-action@v2` on PRs to `main`.
- `bootstrap_project.yml` — one-shot workflow to rename `src/project_name` → `src/<new_name>` and update README. **Already run** (the package was renamed to `knowledge_graph`, then deleted in the restructure).
- `create-tag.yml`, `release.yml` — semver tag → GitHub release → PyPI publish (needs `PIPY_API_TOKEN` secret).
- `copilot_code_review.yml` — Copilot review on PRs.

Lint baseline implied by workflows: **black + flake8**, Python **3.9**.

## Conventions

- Conventional commits (see `CONTRIBUTING.md`). Example from history: `fix(package): update setup.py arguments`.
- Semantic versioning; releases triggered by pushing a `X.Y.Z` tag.
- Tests live in `tests/` (pytest). When reintroducing tests, add `conftest.py` and fixtures under `tests/data/` per the README's intended layout.
