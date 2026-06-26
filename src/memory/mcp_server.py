"""FastMCP server exposing Mira's hierarchical memory (tiers 2/3) to Claude Code.

In the standalone demo, `llm.py`/`agent.py` are the model and the agent loop. Here
**Claude Code is the model, the agent loop, and tiers 0/1** (its own context window +
compaction); this server only owns the durable tiers — temporal user facts (tier 2) and
semantic episodes (tier 3) — so memory survives across `claude` restarts.

`memory.py` is still the only backend-specific file: swap it for Postgres+pgvector and
these tools are unchanged. Launch:

    uv run --directory . python src/memory/mcp_server.py            # stdio
    npx @modelcontextprotocol/inspector uv run python src/memory/mcp_server.py
"""

from mcp.server.fastmcp import FastMCP

from memory import Store
from llm import embed
from agent import extract_facts

mcp = FastMCP("mira-memory")
store = Store()


# ---------- SCOPED READS ----------
@mcp.tool()
def memory_recall(user_id: str, query: str, k: int = 3) -> dict:
    """Scoped recall for one user: current canonical facts (tier 2) + the top-k
    semantically-relevant episodes (tier 3) for THIS query. Small payload by
    design — never the whole history. Call this before answering a user."""
    return {
        "facts": dict(store.current_facts(user_id)),
        "episodes": store.search(user_id, embed(query), k),
    }


@mcp.tool()
def memory_facts(user_id: str) -> dict:
    """The user's current model (tier 2): canonical facts only. Superseded history
    is retained in the store but not returned."""
    return {"facts": dict(store.current_facts(user_id))}


# ---------- WRITES (close the loop) ----------
@mcp.tool()
def memory_remember(user_id: str, text: str) -> dict:
    """Write-back: store a raw turn as an episode (tier 3) and opportunistically
    extract + upsert any temporal facts (tier 2). Use after each user turn."""
    store.add_episode(user_id, text, embed(text))
    written = {}
    for key, val in extract_facts(text):
        store.upsert_fact(user_id, key, val)   # supersedes any prior value for this key
        written[key] = val
    return {"episode_stored": True, "facts_written": written}


@mcp.tool()
def memory_upsert_fact(user_id: str, key: str, value: str) -> dict:
    """Explicitly write one durable fact (tier 2) — the model-driven path when you
    decide something is worth remembering. Supersedes the prior value for `key`
    (sets `invalid_at`/`status=superseded`); current truth stays a single query."""
    store.upsert_fact(user_id, key, value)
    return {"upserted": {key: value}}


@mcp.tool()
def forget_user(user_id: str) -> dict:
    """GDPR right-to-be-forgotten: delete tiers 2+3 for this user."""
    store.forget_user(user_id)
    return {"forgotten": user_id}


if __name__ == "__main__":
    mcp.run()  # stdio transport
