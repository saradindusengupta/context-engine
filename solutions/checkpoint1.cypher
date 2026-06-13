// Checkpoint 1 — current state AND the event timeline from one place.
MATCH (svc:Service {name:'payments-api'})
OPTIONAL MATCH (f:Fact)-[:ABOUT]->(svc) WHERE f.invalidAt IS NULL
OPTIONAL MATCH (i:Incident)-[:IMPACTS]->(svc) WHERE i.status='OPEN'
OPTIONAL MATCH (i)-[:TRIGGERED_BY]->(dep:Deploy)
RETURN svc.name, collect(DISTINCT f.text) AS current_facts,
       collect(DISTINCT {incident:i.id, by:dep.by, change:dep.change}) AS open;
