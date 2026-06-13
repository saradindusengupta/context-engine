# Context Engine over MCP

A workshop demo of a **context graph** — not just *what's true now*, but *what happened, in
what order, and why* — exposed to an agent over [MCP](https://modelcontextprotocol.io) with
scoped **read** tools and **write** tools. An agent reads the context, decides, and **records
its decision back into the graph**, so the next agent (or the next session) inherits it.

**Scenario:** on-call / incident response. `payments-api` is degraded right now because deploy
`dep-1191` tripled a timeout and opened incident `INC-4827`. A similar past incident was
*forward-fixed* (precedent `dec-3300`). The agent reads this, applies policy `POL-ROLLBACK-1`,
records a decision — and after a restart a fresh agent can answer *"what did we decide, and why?"*
purely from the graph.

## Quickstart

```bash
uv sync --extra dev                  # install deps into .venv
docker compose up -d                 # start Neo4j 5 (or skip — see SQLite below)
uv run python scripts/healthcheck.py # expect: OK (... lists 5 tools)
docker exec -i neo4j cypher-shell -u neo4j -p workshop123 < schema/schema.cypher
uv run python src/ingest.py          # expect: ingested
npx @modelcontextprotocol/inspector uv run python src/server.py   # explore the 5 tools
```

**No Docker?** The same demo runs on a stdlib-only SQLite backend:

```bash
export STORE_BACKEND=sqlite
uv run python src/ingest.py          # creates data/context.db
uv run python src/server.py          # same 5 MCP tools, no Neo4j
```

## The graph

Nouns: `Service`, `Deploy`, `Incident`, `Engineer`, `Policy`. First-class context:
`Decision` and `Fact` (temporally valid: `validAt` / `invalidAt` / `status`). Relationships:
`AFFECTS`, `IMPACTS`, `TRIGGERED_BY`, `RESOLVES`, `MADE_BY`, `APPLIED`, `CITES_PRECEDENT`,
`ABOUT`. "Current truth" = facts where `invalidAt` is null; the **event clock** is the ordered
stream of deploys, incidents, and decisions.

## MCP tools

| Tool                                                             | Kind  | Purpose                                                |
| ---------------------------------------------------------------- | ----- | ------------------------------------------------------ |
| `get_service_state(service)`                                   | read  | live facts + open incidents + latest deploy (scoped)   |
| `get_event_timeline(service, limit)`                           | read  | ordered deploys / incidents / decisions                |
| `find_precedent(service, action)`                              | read  | prior decisions with rationale + outcome               |
| `record_decision(incident_id, action, rationale, made_by, …)` | write | append a decision trace (+ policy / precedent edges)   |
| `add_fact(text, service, valid_at, source, supersedes)`        | write | append a temporal fact, optionally retiring an old one |

## Backends

One env var, zero new dependencies. Both backends implement the same semantic store API in
[src/store.py](src/store.py); only the query bodies differ.

| `STORE_BACKEND`   | Store           | Notes                                                                                             |
| ------------------- | --------------- | ------------------------------------------------------------------------------------------------- |
| `neo4j` (default) | `Neo4jStore`  | Cypher; creds default to `neo4j/workshop123` @ `bolt://localhost:7687`                        |
| `sqlite`          | `SqliteStore` | stdlib `sqlite3` over `nodes`/`edges` tables; `SQLITE_PATH` (default `data/context.db`) |

Timestamps are stored as ISO-8601 Zulu strings in both, so ordering and tool output are identical.

## Project layout

```text
├── src/
│   ├── store.py          # Neo4jStore + SqliteStore behind one semantic API (STORE_BACKEND selects)
│   ├── ingest.py         # load data/ into the graph (idempotent upserts)
│   └── server.py         # FastMCP server: the 5 tools over stdio
├── schema/schema.cypher  # Neo4j constraints + index (SQLite builds its tables in code)
├── data/                 # sample inputs: deploys.jsonl, incident-4827.md, rollback-policy.md
├── scripts/
│   ├── healthcheck.py    # store reachable + server registers 5 tools
│   └── reset.py          # wipe + re-apply schema + re-ingest (clean Part-1 state)
├── solutions/            # known-good copies for live paste-over fallbacks
├── tests/                # pytest suite (runs on SQLite, no Docker) + fixtures in tests/data/
├── docker-compose.yml    # lean Neo4j 5 with a cypher-shell healthcheck
├── claude_desktop_config.json  # MCP client config (neo4j + sqlite variants)
├── SETUP.md              # step-by-step build & demo runbook
└── docs/demo_plan.md     # design rationale + presenter script
```

## Development

```bash
make install   # deps (uv)
make lint      # black --check + flake8
make test      # STORE_BACKEND=sqlite pytest — 11 cases over all 5 tools, no Docker needed
```

Always run from the repo root so `data/...` paths and `from store import Store` resolve.
Python ≥3.10 required (`mcp[cli]`); CI targets 3.12.

## Reset & teardown

```bash
uv run python scripts/reset.py   # back to clean Part-1 state
docker compose down              # stop Neo4j (add -v to drop the data volume)
```
