# Setup & Demo Runbook — A Context Engine over MCP

This file is the *how to run it*.

All commands run from the repo root: `/Users/saradindusengupta/dev/context-engine`.

> One harmless note: every `uv run` prints `warning: VIRTUAL_ENV=/opt/anaconda3 … will be ignored`. That's just conda being active — uv correctly uses `.venv`. To silence it, run
> `conda deactivate` (or `unset VIRTUAL_ENV`) once in your terminal.

---

## 0. One-time setup

```bash
cd /Users/saradindusengupta/dev/context-engine
uv sync --extra dev          # build .venv with mcp[cli], neo4j, pytest, black, flake8
docker compose up -d         # start Neo4j 5
```

Wait until healthy (≈15–25s on a cold start):

```bash
until [ "$(docker inspect -f '{{.State.Health.Status}}' neo4j)" = "healthy" ]; do sleep 2; done; echo healthy
```

Requirements: Docker, `uv`, Node (for `npx` MCP Inspector). Python ≥3.10 (the demo targets 3.12).

---

## 1. Pre-flight

```bash
uv run python scripts/healthcheck.py
# expect: OK  (store reachable; server lists 5 tools: add_fact, find_precedent,
#              get_event_timeline, get_service_state, record_decision)
```

If this prints `OK`, the whole stack works. If it fails, jump to **§6 Fallbacks**.

---

## 2. Part 1 — build the context graph

Apply the schema (constraints + index), then ingest the sample data:

```bash
docker exec -i neo4j cypher-shell -u neo4j -p workshop123 < schema/schema.cypher
uv run python src/ingest.py          # expect: ingested
```

**Checkpoint 1** — current state *and* the open-incident story from one query:

```bash
docker exec -i neo4j cypher-shell -u neo4j -p workshop123 < solutions/checkpoint1.cypher
```

Expect `payments-api`, the live fact `"timeout 5s -> 30s"`, and
`{incident: INC-4827, by: rao, change: timeout 5s -> 30s}`.

*Talking point:* "Service, Deploy, Incident are obvious nouns. The interesting part is the
temporal **Fact** and, later, the **Decision** — that's what makes this a *context* graph."

---

## 3. Part 2 — expose it over MCP (MCP Inspector)

Launch the server under the Inspector (no API key needed):

```bash
npx @modelcontextprotocol/inspector uv run python src/server.py
```

It opens a browser tab. Then:

1. Click **Connect** (the server command is pre-filled).
2. Open the **Tools** tab → **List Tools**. Confirm exactly **5**: `get_service_state`,
   `get_event_timeline`, `find_precedent`, `record_decision`, `add_fact`.
3. Call each read (fill the args, hit **Run**):

| Tool                   | Args                      | Expect                                                   |
| ---------------------- | ------------------------- | -------------------------------------------------------- |
| `get_service_state`  | `service: payments-api` | `latest_deploy.id = dep-1191`, fact, `INC-4827` open |
| `get_event_timeline` | `service: payments-api` | 5 events, newest first (INC-4827 → dep-1191 → …)      |
| `find_precedent`     | `service: payments-api` | `dec-3300`, forward-fix, "resolved in 40m"             |

*Talking point (at `get_service_state`):* "Scoped tools are why our reads stay small — we
never dump the whole graph into the context window."

Leave the Inspector open, or `Ctrl-C` it before Part 3.

---

## 4. Part 3 — agent integration + the persistence proof

**Connect Claude Desktop** (the high-impact path). The config
[claude_desktop_config.json](claude_desktop_config.json) is already filled with absolute
paths. Copy it into Claude Desktop's config and restart the app:

```bash
cp claude_desktop_config.json ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

Quit and reopen Claude Desktop so it loads the MCP server, then confirm the `context-engine`
tools appear (hammer/tools icon).

**Or connect Claude Code (CLI).** The repo ships a project-scoped [`.mcp.json`](../.mcp.json) that
points Claude Code at the same server — nothing to edit. Start Claude Code from the repo root and
approve the server the first time (project-scoped servers need a one-time OK):

```bash
cd /Users/saradindusengupta/dev/context-engine
claude            # approve "context-engine" when prompted
```

Verify:

```bash
claude mcp list                 # context-engine … ✓ Connected
claude mcp get context-engine   # shows the stdio command + env
```

Inside the session, `/mcp` lists `context-engine` with its 5 tools; then run the same script below.
(Slow first start? `MCP_TIMEOUT=60000 claude`. Re-prompt for approval: `claude mcp
reset-project-choices`. Remove it: `claude mcp remove context-engine`. To use the **SQLite** backend
instead, edit [`.mcp.json`](../.mcp.json) — set `STORE_BACKEND=sqlite` + `SQLITE_PATH` in `env` and
drop the `NEO4J_*` keys.)

**The script (the money moment):**

1. *Read state:* ask **"Why is `payments-api` degraded right now?"** → it calls
   `get_service_state` + `get_event_timeline` and narrates dep-1191 → INC-4827 → 5xx spike.
2. *Read precedent:* ask **"Have we hit something like this before? What did we do?"** →
   `find_precedent` → returns dec-3300 (forward-fix, owner-approved, 40 min).
3. *Decide + write:* ask **"Given POL-ROLLBACK-1 and that precedent, propose an action and
   record it."** → it calls `record_decision(incident_id="INC-4827", action="forward-fix", rationale="…", made_by="rao", policy_id="POL-ROLLBACK-1", exception=true, precedent_id="dec-3300")`.
4. **Persistence proof — Checkpoint 3:** start a **fresh session** (quit & reopen Claude Desktop,
   or exit `claude` and relaunch it) — empty chat history — then ask **"What did we decide about
   INC-4827, and why?"** → a brand-new agent
   calls `find_precedent`/`get_event_timeline`, reads the decision **it never saw written**,
   and explains it, citing the policy and precedent.

*Talking point:* "No chat history, no fine-tuning. The model 'remembered' because the memory
lives in the graph, not the window."

If you'd rather not use Claude Desktop, run the same three prompts' tool calls in the **MCP
Inspector** and narrate them — the persistence proof is then: `Ctrl-C` the Inspector,
relaunch it, call `find_precedent`, and show the recorded decision is still there.

---

## 5. Reset between run-throughs

```bash
uv run python scripts/reset.py
# graph wiped → ingested → reseeded — rejoin at Part 2
```

Wipes the recorded decision and restores the clean Part-1 state (only the seeded `dec-3300`
precedent remains).

---

## 6. Fallbacks (ranked)

- **Docker / Neo4j down on a machine** → switch to the **SQLite track**, zero install, no
  container:

  ```bash
  export STORE_BACKEND=sqlite          # set once in the shell
  uv run python scripts/healthcheck.py # OK
  uv run python src/ingest.py          # ingested  (creates data/context.db)
  uv run python scripts/reset.py       # reseed
  ```

  Everything in Parts 2–3 is identical — for Claude Desktop, use the `context-engine-sqlite`
  block in the config instead. (No schema step: SQLite builds its tables automatically.)
- **Cypher typo on the projector** → paste from [solutions/](solutions/) (`schema.cypher`,
  `ingest.py`, `part2_server.py`, `checkpoint1.cypher`); don't debug live.
- **Claude Desktop won't connect** → run the whole Part 3 script in the Inspector.
- **Ingestion error mid-session** → `uv run python scripts/reset.py`, rejoin at Part 2.

---

## 7. Teardown

```bash
docker compose down        # stop Neo4j (keeps the data volume)
docker compose down -v     # also drop the volume (fully clean)
```

---

## 8. Mira memory demo (the second MCP server)

A companion demo: **Mira**, a multi-session memory agent with three tiers —
live buffer + rolling summary (tier 1), user facts (tier 2), semantic episodes
(tier 3) — persisted in SQLite so memory survives a process restart. Code is
under [`src/memory/`](../src/memory/); `memory.py` is the only backend-specific
file. Full beat-by-beat script and talking points live in the companion
`DEMO_PLAN.md` (repo parent directory).

### Environment

The `uv sync` from §0 already installs the one hard dependency (`numpy`). With
no API keys the demo runs **fully offline and deterministic** — the stage
default. Real chat/embeddings are optional and independent per capability:

```bash
uv add anthropic openai          # only if you want live LLM calls
export ANTHROPIC_API_KEY=...     # real chat; omit for the deterministic stand-in
export OPENAI_API_KEY=...        # real OpenAI embeddings; omit for the toy 256-dim embedder
```

A single run takes one branch per capability, so stored vectors never mix
dimensions. If you change keys mid-session, wipe the store first (below).

### Run A — standalone scripted demo

The scripts use flat imports, so run them **from `src/memory/`**:

```bash
cd src/memory
uv run python reset.py && uv run python demo.py
```

This plays session 1 (tier writes → compaction → contradiction), restarts the
agent with an empty buffer, and answers from memory alone. To jump straight to
the restart beat: `uv run python seed.py`, then
`uv run python -c 'import demo; demo.session_two_after_restart()'`.

Checkpoints: 3 canonical facts after session 1; a `SUMMARY SO FAR:` block once
the buffer crosses `TOKEN_BUDGET` (the script prints the turn that tripped it);
`deadline=Monday` canonical with `Friday` superseded; the post-restart answer
names **Monday** + **short and direct** with an empty buffer.

### Run B — inside Claude Code (MCP)

The repo's [`.mcp.json`](../.mcp.json) ships a second server, `mira-memory`,
alongside `context-engine` — nothing to edit. Start Claude Code from the repo
root and approve it on first use. Five tools: `memory_remember`,
`memory_recall`, `memory_facts`, `memory_upsert_fact`, `forget_user`.

The beats (talk; let Claude call the tools):

1. *Teach durable facts* — "I'm preparing for a databases exam. I prefer short,
   direct answers. My deadline is Friday." → `memory_remember` ×3.
2. *Show the user model* — "what do you remember about me?" → `memory_facts`.
3. *Contradict* — "actually, the deadline moved to Monday." → `memory_remember`
   supersedes Friday; Monday becomes canonical (current truth is a query, not the
   latest write).
4. **Persistence proof — the money moment:** quit Claude Code, reopen it (fresh
   process, empty window), ask "what's my deadline and how do I like answers?" →
   `memory_recall` answers Monday + short-and-direct with no chat history.

*Talking point:* "No chat history. It remembered because the memory lives in the
MCP-backed store, not the window."

### Reset / wipe

The store persists by design — that's the whole point — so start a fresh
rehearsal deliberately. **The two run paths use separate databases:**

| Path | Store file | Wipe with |
| ---- | ---------- | --------- |
| Standalone `demo.py` | `src/memory/mira.db` | `cd src/memory && uv run python reset.py` |
| Claude Code (MCP) | repo-root `mira.db` | `rm mira.db`, or tell Claude "forget `<user_id>`" |

Both are gitignored. In a live session you can also just use a fresh `user_id`
per rehearsal instead of wiping.

---

## Reference

- **Backends:** `STORE_BACKEND` = `neo4j` (default) or `sqlite`. Neo4j creds default to
  `neo4j/workshop123` at `bolt://localhost:7687`; SQLite path defaults to `data/context.db`
  (override with `SQLITE_PATH`).
- **Always run from the repo root** so `data/...` paths and `from store import Store` resolve.
- **Tests (no Docker):** `STORE_BACKEND=sqlite uv run pytest` — 11 cases over all 5 tools.
- **Lint:** `make lint` (black + flake8). **CI:** `make install && make lint && make test`.
