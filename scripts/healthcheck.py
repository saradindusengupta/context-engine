"""Pre-flight check: store reachable + server registers the 5 tools.

Backend-agnostic (works for neo4j and sqlite). Run under the mcp env:

    uv run python scripts/healthcheck.py

Exits 0 and prints OK on success; exits 1 with a hint on failure.
"""

import pathlib
import sys

# Put src/ on the path so `import store` / `import server` resolve (mirrors how
# `python src/server.py` runs); resolve off __file__, not cwd.
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import anyio  # noqa: E402  (transitive dep of mcp)

EXPECTED = {
    "get_service_state",
    "get_event_timeline",
    "find_precedent",
    "record_decision",
    "add_fact",
}


def check_store():
    from store import Store

    assert Store().ping(), "store ping returned falsy"


async def _list_tools(mcp):
    # Prefer the public async API; fall back to the internal registry across SDK versions.
    try:
        return [t.name for t in await mcp.list_tools()]
    except Exception:
        tm = getattr(mcp, "_tool_manager", None)
        return list(getattr(tm, "_tools", {}).keys())


def check_server():
    import server  # NOTE: also constructs Store() at import time

    names = set(anyio.run(_list_tools, server.mcp))
    missing = EXPECTED - names
    assert not missing, f"missing tools: {sorted(missing)}"
    assert len(names) == 5, f"expected 5 tools, found {len(names)}: {sorted(names)}"
    return sorted(names)


def main():
    try:
        check_store()
    except Exception as e:
        print(f"FAIL: store not reachable -> {type(e).__name__}: {e}")
        print(
            "  hint: is Neo4j up? `docker compose up -d` then wait for healthy, "
            "or set STORE_BACKEND=sqlite"
        )
        return 1
    try:
        tools = check_server()
    except Exception as e:
        print(f"FAIL: server import / tool registration -> {type(e).__name__}: {e}")
        print("  hint: run under the mcp env: `uv run python scripts/healthcheck.py`")
        return 1
    print(f"OK  (store reachable; server lists {len(tools)} tools: {', '.join(tools)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
