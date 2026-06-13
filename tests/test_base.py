"""Behavioral tests for the context engine, run against the SQLite backend.

Covers ingest, the three scoped reads, the two writes, precedent accumulation,
and persistence across a fresh store instance (the demo's Checkpoint-3 in miniature).
"""

import server


def test_ingest_creates_service_and_deploys(seeded):
    assert seeded.node_exists("payments-api")
    assert seeded.node_exists("dep-1190")
    assert seeded.node_exists("dep-1191")


def test_fact_only_for_changed_deploy(seeded):
    # dep-1191 has a config change -> a Fact; dep-1190 has none.
    assert seeded.node_exists("fact-dep-1191")
    assert not seeded.node_exists("fact-dep-1190")


def test_get_service_state(seeded):
    state = server.get_service_state("payments-api")
    assert state["service"] == "payments-api"
    assert any("timeout 5s -> 30s" in f for f in state["facts"])
    assert "INC-4827" in state["incidents"]
    assert state["latest_deploy"]["id"] == "dep-1191"  # guards the C1 ordering fix
    assert state["latest_deploy"]["by"] == "rao"  # guards the C2 dep.by fix


def test_get_service_state_unknown_service(seeded):
    state = server.get_service_state("does-not-exist")
    assert state["facts"] == []
    assert state["incidents"] == []


def test_get_event_timeline_ordering(seeded):
    tl = server.get_event_timeline("payments-api")
    # newest first: INC-4827 (09:21) > dep-1191 (09:02) > dep-1190 > dec-3300
    assert tl[0]["ref"] == "INC-4827"
    ats = [e["at"] for e in tl]
    assert ats == sorted(ats, reverse=True)
    kinds = {e["kind"] for e in tl}
    assert {"deploy", "incident", "decision"} <= kinds


def test_find_precedent_returns_seeded_decision(seeded):
    precs = server.find_precedent("payments-api")
    dec = next(p for p in precs if p["decision"] == "dec-3300")
    assert dec["action"] == "forward-fix"
    assert dec["exception"] is True
    assert "40" in dec["outcome"]


def test_find_precedent_action_filter(seeded):
    assert server.find_precedent("payments-api", action="rollback") == []
    fwd = server.find_precedent("payments-api", action="forward-fix")
    assert [p["decision"] for p in fwd] == ["dec-3300"]


def test_record_decision_writes_and_links(seeded):
    out = server.record_decision(
        incident_id="INC-4827",
        action="forward-fix",
        rationale="cite dec-3300; rollback risks backfill",
        made_by="rao",
        policy_id="POL-ROLLBACK-1",
        exception=True,
        precedent_id="dec-3300",
    )
    assert out["recorded"].startswith("dec-inc-4827-")
    assert out["action"] == "forward-fix"
    # precedent accumulation: the new decision is now findable
    decisions = {p["decision"] for p in server.find_precedent("payments-api")}
    assert out["recorded"] in decisions
    assert seeded.node_exists("POL-ROLLBACK-1")


def test_record_decision_rollback_mitigates(seeded):
    server.record_decision(
        incident_id="INC-4827",
        action="rollback",
        rationale="over threshold, no approved forward-fix",
        made_by="rao",
    )
    # status flipped from OPEN -> MITIGATED, so it drops out of open incidents
    assert "INC-4827" not in server.get_service_state("payments-api")["incidents"]


def test_add_fact_appends_and_supersedes(seeded):
    first = server.add_fact(
        text="5xx back under 5%",
        service="payments-api",
        valid_at="2026-06-14T10:00:00Z",
        source="test",
    )["fact"]
    assert any("5xx back under 5%" in f for f in server.get_service_state("payments-api")["facts"])

    server.add_fact(
        text="5xx steady",
        service="payments-api",
        valid_at="2026-06-15T10:00:00Z",
        source="test",
        supersedes=first,
    )
    facts = server.get_service_state("payments-api")["facts"]
    assert not any("5xx back under 5%" in f for f in facts)  # retired
    assert any("5xx steady" in f for f in facts)


def test_persistence_across_store_instances(seeded):
    out = server.record_decision(
        incident_id="INC-4827",
        action="forward-fix",
        rationale="durable trace",
        made_by="rao",
        precedent_id="dec-3300",
    )
    import store as store_mod

    fresh = store_mod.Store()  # a brand-new connection, never saw the write
    decisions = {p["decision"] for p in fresh.find_precedent("payments-api")}
    assert out["recorded"] in decisions
