"""Ingest the sample data into the context graph via the semantic store API.

Run from the repo root so ``data/...`` paths resolve and ``from store import
Store`` picks up ``src/`` on ``sys.path[0]``:

    uv run python src/ingest.py

All writes are idempotent (upsert), so re-running reproduces the same state.
"""

import json
import pathlib
import re

from store import Store


def main():
    s = Store()

    # Deploys: each line -> a Deploy node (+ AFFECTS / MADE_BY edges); a config change -> a Fact.
    for line in pathlib.Path("data/deploys.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        s.upsert_node(d["service"], "Service", name=d["service"])
        s.upsert_node(d["by"], "Engineer", name=d["by"])
        s.upsert_node(
            d["id"], "Deploy", sha=d["sha"], at=d["at"], change=d.get("change"), by=d["by"]
        )
        s.upsert_edge(d["id"], "AFFECTS", d["service"])
        s.upsert_edge(d["id"], "MADE_BY", d["by"])
        if d.get("change"):
            fid = "fact-" + d["id"]
            s.upsert_node(
                fid,
                "Fact",
                text=f"{d['service']} config: {d['change']}",
                validAt=d["at"],
                invalidAt=None,
                status="canonical",
                source="deploys.jsonl",
            )
            s.upsert_edge(fid, "ABOUT", d["service"])

    # Incident note: parse the header fields, link to the triggering deploy.
    note = pathlib.Path("data/incident-4827.md").read_text()
    inc = {
        "id": re.search(r"INC-\d+", note).group(),
        "sev": re.search(r"SEV-\d", note).group(),
        "opened": re.search(r"Opened:\s*(\S+)", note).group(1),
        "service": "payments-api",
        "trigger": "dep-1191",
    }
    s.upsert_node(inc["service"], "Service", name=inc["service"])
    s.upsert_node(
        inc["id"], "Incident", severity=inc["sev"], opened_at=inc["opened"], status="OPEN"
    )
    s.upsert_edge(inc["id"], "IMPACTS", inc["service"])
    s.upsert_edge(inc["id"], "TRIGGERED_BY", inc["trigger"])

    # Policy
    s.upsert_node(
        "POL-ROLLBACK-1",
        "Policy",
        name="Rollback threshold",
        rule="Roll back if 5xx > 5% for 10+ min, unless forward-fix approved by owner",
    )

    # Precedent (seeded so find_precedent has something to return)
    s.upsert_node("payments-api", "Service", name="payments-api")
    s.upsert_node("rao", "Engineer", name="rao")
    s.upsert_node(
        "INC-3300",
        "Incident",
        severity="SEV-2",
        status="RESOLVED",
        opened_at="2026-03-04T10:00:00Z",
    )
    s.upsert_edge("INC-3300", "IMPACTS", "payments-api")
    s.upsert_node(
        "dec-3300",
        "Decision",
        action="forward-fix",
        rationale="added circuit breaker; rollback risked data backfill",
        made_at="2026-03-04T11:00:00Z",
        made_by="rao",
        exception=True,
        outcome="resolved in 40m",
    )
    s.upsert_edge("dec-3300", "RESOLVES", "INC-3300")
    s.upsert_edge("dec-3300", "MADE_BY", "rao")

    print("ingested")


if __name__ == "__main__":
    main()
