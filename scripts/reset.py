"""Reset between sessions: wipe the graph, re-apply schema (neo4j), re-ingest.

    uv run python scripts/reset.py

Idempotent ingest means this deterministically restores the clean Part-1 state.
No binary dump needed.
"""

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from store import Store  # noqa: E402
import ingest  # noqa: E402

store = Store()
store.wipe()
print("graph wiped")

os.chdir(ROOT)  # so data/*.jsonl relative paths and schema path resolve

# schema.cypher is Neo4j-only DDL; constraints survive a wipe and IF NOT EXISTS is a no-op.
if os.getenv("STORE_BACKEND", "neo4j").lower() != "sqlite":
    for stmt in (ROOT / "schema" / "schema.cypher").read_text().split(";"):
        if stmt.strip() and not stmt.strip().startswith("//"):
            store.run(stmt)

ingest.main()
print("reseeded — rejoin at Part 2")
