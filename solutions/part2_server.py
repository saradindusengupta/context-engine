"""FastMCP server exposing the context engine over stdio.

Scoped reads return small, structured payloads (never the whole graph); writes
close the loop by recording decisions and facts back into the graph. Backend is
chosen by ``STORE_BACKEND`` — the tools below are identical for Neo4j or SQLite.

    uv run python src/server.py            # stdio
    npx @modelcontextprotocol/inspector uv run python src/server.py
"""

import datetime as dt

from mcp.server.fastmcp import FastMCP

from store import Store

mcp = FastMCP("context-engine")
s = Store()


# ---------- SCOPED READS ----------
@mcp.tool()
def get_service_state(service: str) -> dict:
    """Current state of a service: live facts + open incidents + latest deploy.
    Scoped to one service so we never flood the context window."""
    return s.get_service_state(service)


@mcp.tool()
def get_event_timeline(service: str, limit: int = 10) -> list:
    """Ordered event clock for a service: deploys, incidents, decisions."""
    return s.get_event_timeline(service, limit)


@mcp.tool()
def find_precedent(service: str, action: str = "") -> list:
    """Prior decisions on this service (optionally matching an action) with rationale + outcome."""
    return s.find_precedent(service, action)


# ---------- WRITES (close the loop) ----------
@mcp.tool()
def record_decision(
    incident_id: str,
    action: str,
    rationale: str,
    made_by: str,
    policy_id: str = "",
    exception: bool = False,
    precedent_id: str = "",
) -> dict:
    """Write a decision trace back into the graph: action + why + who + policy + precedent."""
    now = dt.datetime.now(dt.UTC)
    did = f"dec-{incident_id.lower()}-{now:%H%M%S}"
    s.upsert_node(
        did,
        "Decision",
        action=action,
        rationale=rationale,
        made_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        made_by=made_by,
        exception=exception,
    )
    s.upsert_node(made_by, "Engineer", name=made_by)
    s.upsert_edge(did, "RESOLVES", incident_id)
    s.upsert_edge(did, "MADE_BY", made_by)
    if action == "rollback":
        s.set_node_prop(incident_id, "status", "MITIGATED")
    if policy_id and s.node_exists(policy_id):
        s.upsert_edge(did, "APPLIED", policy_id)
    if precedent_id and s.node_exists(precedent_id):
        s.upsert_edge(did, "CITES_PRECEDENT", precedent_id)
    return {"recorded": did, "action": action}


@mcp.tool()
def add_fact(text: str, service: str, valid_at: str, source: str, supersedes: str = "") -> dict:
    """Append a temporal fact; optionally retire the fact it supersedes (set invalidAt)."""
    fid = f"fact-{abs(hash((text, valid_at))) % 10_000_000}"
    if supersedes:
        s.set_node_prop(supersedes, "invalidAt", valid_at)
        s.set_node_prop(supersedes, "status", "superseded")
    s.upsert_node(service, "Service", name=service)
    s.upsert_node(
        fid,
        "Fact",
        text=text,
        validAt=valid_at,
        invalidAt=None,
        status="canonical",
        source=source,
    )
    s.upsert_edge(fid, "ABOUT", service)
    return {"fact": fid}


if __name__ == "__main__":
    mcp.run()  # stdio transport
