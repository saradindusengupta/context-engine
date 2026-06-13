"""Backend-agnostic store for the context engine.

Both ``Neo4jStore`` and ``SqliteStore`` implement the same semantic API; the
queries (Cypher / SQL) live here, so ``server.py`` and ``ingest.py`` are
backend-agnostic. Pick the backend with ``STORE_BACKEND`` (``neo4j`` default,
or ``sqlite``). Swapping is one env var + zero new dependencies — the SQLite
track uses only the standard library.

Timestamps are stored as ISO-8601 Zulu strings in both backends, so ordering is
identical (lexicographic == chronological) and tool results stay JSON-serializable.
"""

import json
import os
import sqlite3

# Each label's natural-key property. Every node also carries a uniform ``id``
# property (== its natural key) so edges can match endpoints without labels.
KEY_PROP = {
    "Service": "name",
    "Engineer": "name",
    "Deploy": "id",
    "Incident": "id",
    "Policy": "id",
    "Decision": "id",
    "Fact": "id",
}


class Neo4jStore:
    def __init__(self):
        from neo4j import GraphDatabase  # lazy: the SQLite track never imports neo4j

        self.driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(
                os.getenv("NEO4J_USER", "neo4j"),
                os.getenv("NEO4J_PASS", "workshop123"),
            ),
        )

    def run(self, cypher, **params):
        with self.driver.session() as s:
            return [r.data() for r in s.run(cypher, **params)]

    # ---------- write primitives ----------
    def upsert_node(self, node_id, label, **props):
        keyprop = KEY_PROP[label]
        props = {**props, keyprop: node_id, "id": node_id}
        # label/keyprop come from a fixed internal map — safe to interpolate.
        self.run(
            f"MERGE (n:{label} {{{keyprop}: $key}}) SET n += $props",
            key=node_id,
            props=props,
        )

    def upsert_edge(self, src, type, dst):
        # WITH-pipe between the two id lookups avoids a (false-positive) cartesian-product notice.
        self.run(
            f"MATCH (a {{id:$src}}) WITH a MATCH (b {{id:$dst}}) MERGE (a)-[:{type}]->(b)",
            src=src,
            dst=dst,
        )

    def set_node_prop(self, node_id, key, value):
        self.run("MATCH (n {id:$id}) SET n += $patch", id=node_id, patch={key: value})

    def node_exists(self, node_id):
        return self.run("MATCH (n {id:$id}) RETURN count(n) AS c", id=node_id)[0]["c"] > 0

    def ping(self):
        return self.run("RETURN 1 AS ok")[0]["ok"] == 1

    def wipe(self):
        self.run("MATCH (n) DETACH DELETE n")

    # ---------- scoped reads ----------
    def get_service_state(self, service):
        rows = self.run(
            """
            MATCH (svc:Service {name:$service})
            OPTIONAL MATCH (f:Fact)-[:ABOUT]->(svc) WHERE f.invalidAt IS NULL
            WITH svc, collect(DISTINCT f.text) AS facts
            OPTIONAL MATCH (i:Incident)-[:IMPACTS]->(svc) WHERE i.status = 'OPEN'
            WITH svc, facts, collect(DISTINCT i.id) AS incidents
            OPTIONAL MATCH (dep:Deploy)-[:AFFECTS]->(svc)
            WITH svc, facts, incidents, dep ORDER BY dep.at DESC
            WITH svc, facts, incidents,
                 collect({id:dep.id, by:dep.by, change:dep.change}) AS deploys
            RETURN svc.name AS service, facts, incidents,
                   CASE WHEN size(deploys)=1 AND head(deploys).id IS NULL THEN null
                        ELSE head(deploys) END AS latest_deploy
            """,
            service=service,
        )
        return (
            rows[0]
            if rows
            else {"service": service, "facts": [], "incidents": [], "latest_deploy": None}
        )

    def get_event_timeline(self, service, limit=10):
        return self.run(
            """
            MATCH (svc:Service {name:$service})
            CALL (svc) {
              MATCH (dep:Deploy)-[:AFFECTS]->(svc)
              RETURN dep.at AS at, 'deploy' AS kind, dep.id AS ref, dep.change AS detail
              UNION
              MATCH (i:Incident)-[:IMPACTS]->(svc)
              RETURN i.opened_at AS at, 'incident' AS kind, i.id AS ref, i.severity AS detail
              UNION
              MATCH (x:Decision)-[:RESOLVES]->(:Incident)-[:IMPACTS]->(svc)
              RETURN x.made_at AS at, 'decision' AS kind, x.id AS ref, x.action AS detail
            }
            RETURN at, kind, ref, detail ORDER BY at DESC LIMIT $limit
            """,
            service=service,
            limit=limit,
        )

    def find_precedent(self, service, action=""):
        return self.run(
            """
            MATCH (x:Decision)-[:RESOLVES]->(:Incident)-[:IMPACTS]->(svc:Service {name:$service})
            WHERE $action = '' OR x.action = $action
            RETURN x.id AS decision, x.action AS action, x.rationale AS rationale,
                   x.exception AS exception, x.outcome AS outcome, x.made_by AS made_by
            ORDER BY x.made_at DESC LIMIT 5
            """,
            service=service,
            action=action,
        )


_SQLITE_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS nodes (
  id         TEXT PRIMARY KEY,
  label      TEXT NOT NULL,
  props_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS edges (
  src  TEXT NOT NULL,
  type TEXT NOT NULL,
  dst  TEXT NOT NULL,
  PRIMARY KEY (src, type, dst)
);
CREATE INDEX IF NOT EXISTS idx_nodes_label ON nodes(label);
CREATE INDEX IF NOT EXISTS idx_edges_type  ON edges(type);
CREATE INDEX IF NOT EXISTS idx_edges_dst   ON edges(dst, type);
"""


class SqliteStore:
    def __init__(self):
        self.db = sqlite3.connect(
            os.getenv("SQLITE_PATH", "data/context.db"), check_same_thread=False
        )
        self.db.executescript(_SQLITE_SCHEMA)
        self.db.commit()

    # ---------- write primitives ----------
    def upsert_node(self, node_id, label, **props):
        blob = json.dumps({**props, "id": node_id})
        self.db.execute(
            "INSERT INTO nodes(id,label,props_json) VALUES(?,?,json(?)) "
            "ON CONFLICT(id) DO UPDATE SET label=excluded.label, "
            "props_json=json_patch(nodes.props_json, excluded.props_json)",
            (node_id, label, blob),
        )
        self.db.commit()

    def upsert_edge(self, src, type, dst):
        self.db.execute("INSERT OR IGNORE INTO edges(src,type,dst) VALUES(?,?,?)", (src, type, dst))
        self.db.commit()

    def set_node_prop(self, node_id, key, value):
        self.db.execute(
            "UPDATE nodes SET props_json=json_set(props_json,'$.'||?, ?) WHERE id=?",
            (key, value, node_id),
        )
        self.db.commit()

    def node_exists(self, node_id):
        return self.db.execute("SELECT 1 FROM nodes WHERE id=?", (node_id,)).fetchone() is not None

    def ping(self):
        return self.db.execute("SELECT 1").fetchone()[0] == 1

    def wipe(self):
        self.db.execute("DELETE FROM edges")
        self.db.execute("DELETE FROM nodes")
        self.db.commit()

    # ---------- scoped reads ----------
    def get_service_state(self, service):
        facts = [
            r[0]
            for r in self.db.execute(
                "SELECT json_extract(f.props_json,'$.text') FROM nodes f "
                "JOIN edges e ON e.src=f.id AND e.type='ABOUT' AND e.dst=? "
                "WHERE f.label='Fact' AND COALESCE(json_extract(f.props_json,'$.invalidAt'),'')=''",
                (service,),
            )
        ]
        incidents = [
            r[0]
            for r in self.db.execute(
                "SELECT i.id FROM nodes i "
                "JOIN edges e ON e.src=i.id AND e.type='IMPACTS' AND e.dst=? "
                "WHERE i.label='Incident' AND json_extract(i.props_json,'$.status')='OPEN'",
                (service,),
            )
        ]
        row = self.db.execute(
            "SELECT d.id, json_extract(d.props_json,'$.by'), json_extract(d.props_json,'$.change') "
            "FROM nodes d JOIN edges e ON e.src=d.id AND e.type='AFFECTS' AND e.dst=? "
            "WHERE d.label='Deploy' ORDER BY json_extract(d.props_json,'$.at') DESC LIMIT 1",
            (service,),
        ).fetchone()
        latest = {"id": row[0], "by": row[1], "change": row[2]} if row else None
        return {"service": service, "facts": facts, "incidents": incidents, "latest_deploy": latest}

    def get_event_timeline(self, service, limit=10):
        cur = self.db.execute(
            """
            SELECT json_extract(d.props_json,'$.at') AS at, 'deploy' AS kind, d.id AS ref,
                   json_extract(d.props_json,'$.change') AS detail
            FROM nodes d JOIN edges e ON e.src=d.id AND e.type='AFFECTS' AND e.dst=:svc
            WHERE d.label='Deploy'
            UNION ALL
            SELECT json_extract(i.props_json,'$.opened_at'), 'incident', i.id,
                   json_extract(i.props_json,'$.severity')
            FROM nodes i JOIN edges e ON e.src=i.id AND e.type='IMPACTS' AND e.dst=:svc
            WHERE i.label='Incident'
            UNION ALL
            SELECT json_extract(x.props_json,'$.made_at'), 'decision', x.id,
                   json_extract(x.props_json,'$.action')
            FROM nodes x
            JOIN edges r  ON r.src=x.id  AND r.type='RESOLVES'
            JOIN edges im ON im.src=r.dst AND im.type='IMPACTS' AND im.dst=:svc
            WHERE x.label='Decision'
            ORDER BY at DESC LIMIT :lim
            """,
            {"svc": service, "lim": limit},
        )
        return [{"at": r[0], "kind": r[1], "ref": r[2], "detail": r[3]} for r in cur]

    def find_precedent(self, service, action=""):
        cur = self.db.execute(
            """
            SELECT x.id,
                   json_extract(x.props_json,'$.action'),
                   json_extract(x.props_json,'$.rationale'),
                   json_extract(x.props_json,'$.exception'),
                   json_extract(x.props_json,'$.outcome'),
                   json_extract(x.props_json,'$.made_by')
            FROM nodes x
            JOIN edges r  ON r.src=x.id  AND r.type='RESOLVES'
            JOIN edges im ON im.src=r.dst AND im.type='IMPACTS' AND im.dst=:svc
            WHERE x.label='Decision' AND (:act='' OR json_extract(x.props_json,'$.action')=:act)
            ORDER BY json_extract(x.props_json,'$.made_at') DESC LIMIT 5
            """,
            {"svc": service, "act": action},
        )
        return [
            {
                "decision": r[0],
                "action": r[1],
                "rationale": r[2],
                "exception": bool(r[3]),
                "outcome": r[4],
                "made_by": r[5],
            }
            for r in cur
        ]


Store = SqliteStore if os.getenv("STORE_BACKEND", "neo4j").lower() == "sqlite" else Neo4jStore
