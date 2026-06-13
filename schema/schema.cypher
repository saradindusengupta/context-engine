// Identity & uniqueness — operational context first
CREATE CONSTRAINT service_name  IF NOT EXISTS FOR (s:Service)  REQUIRE s.name IS UNIQUE;
CREATE CONSTRAINT deploy_id      IF NOT EXISTS FOR (d:Deploy)   REQUIRE d.id   IS UNIQUE;
CREATE CONSTRAINT incident_id    IF NOT EXISTS FOR (i:Incident) REQUIRE i.id   IS UNIQUE;
CREATE CONSTRAINT engineer_name  IF NOT EXISTS FOR (e:Engineer) REQUIRE e.name IS UNIQUE;
CREATE CONSTRAINT policy_id      IF NOT EXISTS FOR (p:Policy)   REQUIRE p.id   IS UNIQUE;
CREATE CONSTRAINT decision_id    IF NOT EXISTS FOR (x:Decision) REQUIRE x.id   IS UNIQUE;
CREATE CONSTRAINT fact_id        IF NOT EXISTS FOR (f:Fact)     REQUIRE f.id   IS UNIQUE;

// Helpful lookups for the event clock
CREATE INDEX fact_valid IF NOT EXISTS FOR (f:Fact) ON (f.invalidAt);
