# A multi-session memory agent

The smallest agent with *real* memory: three tiers (live buffer + rolling summary,
a temporal user model, and semantic episodes), with disciplined movement between them
— compress on the way in, retrieve a scoped slice on the way out — persisted in SQLite
so it survives a process restart. `memory.py` is the only backend-specific file.

See [docs/DEMO_PLAN.md](../../docs/DEMO_PLAN.md) for the full stage script, beats, and checkpoints.

## Run

```bash
cd src/memory
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt           # numpy (required); anthropic/openai optional
# optional — omit either for that capability's deterministic offline fallback:
export ANTHROPIC_API_KEY=...               # real chat
export OPENAI_API_KEY=...                  # real embeddings
python reset.py && python demo.py          # full script: session 1 → restart → session 2
```

Fully offline (no keys) is deterministic and crash-free — the chat stand-in surfaces
the assembled memory, the toy embedder hashes a 256-dim bag-of-words vector.

- `python reset.py` — wipe `mira.db`.
- `python seed.py` — populate session 1 only, to jump straight to the restart beat.

## Inside Claude Code (MCP)

`mcp_server.py` exposes the durable tiers (2 = facts, 3 = episodes) as MCP tools so a
real `claude` session — not the toy loop — can use them: `memory_recall`, `memory_facts`,
`memory_remember`, `memory_upsert_fact`, `forget_user`. It's registered as the
`mira-memory` server in the repo's [.mcp.json](../../.mcp.json); restart Claude Code to
pick it up. Memory persists across restarts in `mira.db` (project root, gitignored).
See [§15 of the plan](../../docs/DEMO_PLAN.md) for the on-stage flow and trade-offs.
