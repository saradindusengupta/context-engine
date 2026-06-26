# Live Demo Plan — A Multi-Session Memory Agent

Companion to the AiT 2026 Workshop Plan. This is the presenter's build script: the scenario, the stack, the exact code, the on-stage beats, the checkpoints, and the fallbacks. It is **presenter-driven** — the audience watches, nobody sets up. Everything is written so the only backend-specific file is `memory.py`; swapping SQLite → Postgres/pgvector + Redis is one adapter.

> **Patch log (vs. the original draft).** Four fixes were applied after a code review:
> 1. **Online mode dropped all memory.** `chat()` now folds the memory blocks (encoded as `role:"system"` messages) into the Anthropic `system` prompt; the API rejects system-role entries inside `messages`, so the old code silently sent the model *zero* retrieved memory and the persistence moment failed whenever an API key was set.
> 2. **Compaction never fired.** `TOKEN_BUDGET` dropped 800 → 150 and the "long stretch" is now several real turns, so compression actually triggers within session 1. The demo also self-reports the turn on which it fired (and warns if it didn't).
> 3. **Provider key asymmetry crashed online runs.** Fallback is now *per-capability*: chat uses Anthropic only when `ANTHROPIC_API_KEY` is set, embeddings use OpenAI only when `OPENAI_API_KEY` is set, each independently. A single run never mixes embedding dimensions.
> 4. **`demo.py` double-compacted and mislabelled the window.** `step()` already compacts; the script now reads `agent.last_compacted` and shows the summary block appearing, instead of calling `compact_if_needed()` a second time (a no-op).
>
> Also: deadlines are stored capitalised (`Monday`), and the previously-referenced `seed.py` now has code (§10).

---

## 1. Demo thesis (what the audience should walk away believing)

> A bigger context window is not memory. We'll build the smallest agent that has **real** memory: three tiers (short-term conversational, user-specific, long-term semantic), with disciplined **movement** between them — compress on the way in, retrieve a **scoped** slice on the way out — persisted so it survives a **process restart**. Kill the process, start a fresh session, and the agent still knows the user.

## 2. The scenario (one story, told in five beats)

**Domain:** a personal study/assistant bot called **Mira** — neutral and relatable, with a nod to the proposal's healthcare framing (same mechanics, lower stakes for a live stage). One user talks to Mira across two sessions separated by a restart.

- **Session 1** establishes durable facts: *"I'm preparing for a databases exam," "I prefer short, direct answers," "my deadline is Friday."* → these become **user memory** (tier 2) and **episodes** (tier 3).
- A long stretch of chat crosses the **token budget** → the agent **compresses** old turns into a rolling summary; the raw user turns are already externalized as episodes (tier 3), so the content is restorable.
- A question triggers **scoped retrieval**: only the top-k relevant memories enter the window — not the whole history.
- The user **contradicts** an earlier fact: *"actually, the deadline moved to Monday."* → the old fact is **superseded** (`invalid_at` set), the new one becomes canonical.
- **Restart the process** (fresh session, empty buffer). Ask *"what's my deadline, and how do I like answers?"* → Mira reloads tier 2 + semantically retrieves the relevant episode and answers correctly. **The memory survived the boundary.**

## 3. Stack & rationale

| Layer | Choice (demo) | Production swap | Why |
|-------|---------------|-----------------|-----|
| State / user model | **SQLite** (`facts`, `episodes`) | **Postgres** | Tier 2 is relational state; zero-install for the stage |
| Semantic store | **SQLite + cosine over stored vectors** (NumPy) | **pgvector / a vector DB** | Tier 3 is semantic recall; NumPy keeps it dependency-light and bulletproof live |
| Hot cache | **in-process LRU** (caches tier-2 fact reads) | **Redis** | Sub-second repeat reads of the user model; shows the caching seam |
| LLM + embeddings | **Anthropic** (chat) + **OpenAI** (embeddings), each with an **offline deterministic fallback** | same | The fallbacks are *independent* and *per-capability*: a missing key degrades only that capability, so the demo never hard-fails on a bad network/key |

**The portability point:** `memory.py` is the only file that knows the backend. `agent.py`, `llm.py`, and the demo script are identical whether you run SQLite+NumPy on a laptop or Postgres+pgvector+Redis in production.

## 4. Repo layout

```
src/memory/
├── README.md            # one-paragraph setup + how to run the script
├── requirements.txt     # numpy ; anthropic (optional) ; openai (optional)
├── config.py            # budget, top_k, model names, capability flags
├── llm.py               # chat() + embed(), with per-capability offline fallback
├── memory.py            # Store: tiers 2/3 + LRU cache (the only backend-specific file)
├── agent.py             # assemble_context(), step(), compaction, write-back
├── demo.py              # scripted, non-interactive stage run (deterministic order)
├── seed.py              # seed "session 1" so you can jump straight to the restart
├── reset.py             # wipe the db between runs
└── mcp_server.py        # FastMCP wrapper: expose tiers 2/3 to Claude Code (§15)

docs/DEMO_PLAN.md        # this document
```

## 5. Setup (done once, before the talk)

```bash
cd src/memory
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt           # numpy (required); anthropic/openai optional
export ANTHROPIC_API_KEY=...              # optional; omit for the deterministic chat stand-in
export OPENAI_API_KEY=...                 # optional; omit for the deterministic toy embedder
python reset.py && python demo.py         # dry-run the full script end to end
```

`requirements.txt`: `numpy` (required); `anthropic` and/or `openai` (optional — each used only when its key is present).

**Capability matrix (no crash in any cell):**

| `ANTHROPIC_API_KEY` | `OPENAI_API_KEY` | chat | embeddings |
|:---:|:---:|---|---|
| set | set | Anthropic model | OpenAI `text-embedding-3-small` |
| set | unset | Anthropic model | deterministic toy (256-dim) |
| unset | set | deterministic stand-in | OpenAI |
| unset | unset | deterministic stand-in | deterministic toy |

The stage default is **bottom row** (fully offline, deterministic). A single run always takes one branch per capability, so stored vectors never mix dimensions — but if you change key config mid-session, run `reset.py` first.

## 6. Configuration — `config.py`

```python
import os

HAVE_ANTHROPIC = bool(os.getenv("ANTHROPIC_API_KEY"))
HAVE_OPENAI    = bool(os.getenv("OPENAI_API_KEY"))
OFFLINE        = not (HAVE_ANTHROPIC or HAVE_OPENAI)   # narrative flag; per-call fallback lives in llm.py
CHAT_MODEL     = os.getenv("CHAT_MODEL", "claude-sonnet-4-6")
EMBED_DIM      = 256          # toy embedding dimension when OpenAI embeddings aren't available
TOKEN_BUDGET   = 150          # small so compression fires within session 1 (see note)
TOP_K          = 3            # scoped retrieval: only the k most relevant episodes
DB_PATH        = os.getenv("DB_PATH", "mira.db")
```

`TOKEN_BUDGET = 150` is intentional. The offline chat stand-in emits short strings, so the original 800 never compacted across the scripted turns. At 150 the buffer crosses the budget a few turns in and the audience sees compression happen; the demo prints exactly which turn tripped it.

## 7. LLM adapter — `llm.py` (per-capability offline fallback)

```python
import os, hashlib, re
import numpy as np
from config import HAVE_ANTHROPIC, HAVE_OPENAI, CHAT_MODEL, EMBED_DIM

def _toy_embed(text: str) -> list[float]:
    """Deterministic hashed bag-of-words embedding — no network, stable across runs."""
    v = np.zeros(EMBED_DIM, dtype=np.float32)
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        v[h % EMBED_DIM] += 1.0
    n = np.linalg.norm(v)
    return (v / n).tolist() if n else v.tolist()

def embed(text: str) -> list[float]:
    # Real embeddings only when an OpenAI key is present; otherwise the toy
    # embedder. The branch is fixed for the whole run, so dims never mix.
    if not HAVE_OPENAI:
        return _toy_embed(text)
    from openai import OpenAI
    e = OpenAI().embeddings.create(model="text-embedding-3-small", input=text)
    return e.data[0].embedding

def chat(system: str, messages: list[dict]) -> str:
    if not HAVE_ANTHROPIC:
        # Deterministic stand-in: surface the memory we were handed so the
        # demo still *demonstrates recall* without a model.
        mem = [m["content"] for m in messages if m["role"] == "system"]
        last_user = next((m["content"] for m in reversed(messages)
                          if m["role"] == "user"), "")
        recalled = " | ".join(mem)[:400]
        return f"[offline] Using memory ⟶ {recalled}\n(answering: {last_user})"
    # The Anthropic API rejects system-role entries inside `messages`, so the
    # memory blocks must be folded into the `system` prompt — otherwise every
    # retrieved fact/episode is silently dropped and the model answers blind.
    from anthropic import Anthropic
    mem = "\n".join(m["content"] for m in messages if m["role"] == "system")
    full_system = system + (("\n\n" + mem) if mem else "")
    msg = Anthropic().messages.create(
        model=CHAT_MODEL, max_tokens=400, system=full_system,
        messages=[m for m in messages if m["role"] != "system"],
    )
    return msg.content[0].text

def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)   # ~4 chars/token, good enough for a budget demo
```

## 8. The store — `memory.py` (the only backend-specific file)

```python
import sqlite3, json, time
from collections import OrderedDict
import numpy as np
from config import DB_PATH

class LRU:
    def __init__(self, cap=128):
        self.cap, self.d = cap, OrderedDict()
    def get(self, k):
        if k in self.d:
            self.d.move_to_end(k); return self.d[k]
        return None
    def put(self, k, v):
        self.d[k] = v; self.d.move_to_end(k)
        if len(self.d) > self.cap: self.d.popitem(last=False)

class Store:
    """Tier 2 (facts / user model) + Tier 3 (episodes / semantic) + hot cache.
    Every row is partitioned by user_id — the seam that shards to millions of users."""
    def __init__(self, path=DB_PATH):
        self.db = sqlite3.connect(path)
        self.cache = LRU()
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS facts(
          id INTEGER PRIMARY KEY, user_id TEXT, key TEXT, value TEXT,
          valid_at REAL, invalid_at REAL, status TEXT);   -- tier 2, temporal
        CREATE TABLE IF NOT EXISTS episodes(
          id INTEGER PRIMARY KEY, user_id TEXT, text TEXT, vec TEXT,
          at REAL, importance REAL);                       -- tier 3, semantic
        CREATE INDEX IF NOT EXISTS ix_facts_user    ON facts(user_id);
        CREATE INDEX IF NOT EXISTS ix_episodes_user ON episodes(user_id);
        """)
        self.db.commit()

    # ---- Tier 2: user memory with temporal validity ----
    def upsert_fact(self, user_id, key, value):
        now = time.time()
        # supersede any current fact with the same key (contradiction handling)
        self.db.execute("""UPDATE facts SET invalid_at=?, status='superseded'
                           WHERE user_id=? AND key=? AND invalid_at IS NULL""",
                        (now, user_id, key))
        self.db.execute("""INSERT INTO facts(user_id,key,value,valid_at,invalid_at,status)
                           VALUES(?,?,?,?,NULL,'canonical')""",
                        (user_id, key, value, now))
        self.db.commit()
        self.cache.put(("facts", user_id), None)   # invalidate

    def current_facts(self, user_id):
        cached = self.cache.get(("facts", user_id))
        if cached is not None:
            return cached
        rows = self.db.execute("""SELECT key,value FROM facts
                                  WHERE user_id=? AND invalid_at IS NULL
                                  ORDER BY valid_at""", (user_id,)).fetchall()
        self.cache.put(("facts", user_id), rows)
        return rows

    # ---- Tier 3: episodic / semantic recall ----
    def add_episode(self, user_id, text, vec, importance=1.0):
        self.db.execute("""INSERT INTO episodes(user_id,text,vec,at,importance)
                           VALUES(?,?,?,?,?)""",
                        (user_id, text, json.dumps(vec), time.time(), importance))
        self.db.commit()

    def search(self, user_id, qvec, k, now=None):
        """Scoped retrieval: top-k by importance × recency-decay × cosine — for THIS user only."""
        now = now or time.time()
        q = np.array(qvec, dtype=np.float32)
        out = []
        for text, vec, at, imp in self.db.execute(
                "SELECT text,vec,at,importance FROM episodes WHERE user_id=?", (user_id,)):
            v = np.array(json.loads(vec), dtype=np.float32)
            cos = float(q @ v)                              # vectors are unit-norm
            decay = 0.5 ** ((now - at) / (7 * 86400))       # half-life ~1 week
            out.append((imp * (0.6 * cos + 0.4 * decay), text))
        out.sort(reverse=True)
        return [t for _, t in out[:k]]

    def forget_user(self, user_id):
        """GDPR right-to-be-forgotten: delete tiers 2+3 for a user, then you'd re-index."""
        self.db.execute("DELETE FROM facts    WHERE user_id=?", (user_id,))
        self.db.execute("DELETE FROM episodes WHERE user_id=?", (user_id,))
        self.db.commit()
        self.cache.put(("facts", user_id), None)   # invalidate stale cached facts
```

## 9. The agent — `agent.py` (assemble → answer → write back → compact)

```python
from memory import Store
from llm import chat, embed, approx_tokens
from config import TOKEN_BUDGET, TOP_K

SYSTEM = ("You are Mira, a study assistant with long-term memory. "
          "Use the USER MEMORY and RECALLED EPISODES to stay consistent across sessions.")

class Agent:
    def __init__(self, user_id):
        self.user_id = user_id
        self.store   = Store()
        self.buffer  = []        # tier 0/1: live turns this session
        self.summary = ""        # tier 1: rolling compressed summary (ephemeral)
        self.last_compacted = False   # whether the most recent step() compacted

    def assemble_context(self, user_msg):
        """Build the window: system + user memory + rolling summary + scoped recall + recent turns."""
        facts = self.store.current_facts(self.user_id)
        recalled = self.store.search(self.user_id, embed(user_msg), TOP_K)
        mem_blocks = []
        if facts:    mem_blocks.append("USER MEMORY: " +
                                       "; ".join(f"{k}={v}" for k, v in facts))
        if self.summary: mem_blocks.append("SUMMARY SO FAR: " + self.summary)
        if recalled: mem_blocks.append("RECALLED EPISODES: " + " || ".join(recalled))
        msgs = [{"role": "system", "content": b} for b in mem_blocks]
        msgs += self.buffer[-6:]                       # only recent raw turns
        msgs += [{"role": "user", "content": user_msg}]
        return msgs

    def step(self, user_msg):
        msgs = self.assemble_context(user_msg)
        reply = chat(SYSTEM, msgs)
        # write-back: episode (tier 3) + extracted facts (tier 2)
        self.store.add_episode(self.user_id, f"user: {user_msg}", embed(user_msg))
        for key, val in extract_facts(user_msg):
            self.store.upsert_fact(self.user_id, key, val)
        self.buffer += [{"role": "user", "content": user_msg},
                        {"role": "assistant", "content": reply}]
        self.last_compacted = self.compact_if_needed()   # record for the demo to read
        return reply, msgs

    def compact_if_needed(self):
        """Compression: when the buffer exceeds budget, summarize the oldest turns
        and drop their raw text from the window. The user turns are already in tier 3
        as episodes, so their content stays restorable."""
        used = sum(approx_tokens(m["content"]) for m in self.buffer)
        if used <= TOKEN_BUDGET:
            return False
        old, self.buffer = self.buffer[:-4], self.buffer[-4:]
        digest = "; ".join(m["content"] for m in old)[:300]
        self.summary = (self.summary + " " + f"[compressed {len(old)} turns] " + digest).strip()
        return True

def extract_facts(text: str):
    """Tiny rule-based extractor for the demo (a real system uses an LLM call here)."""
    import re
    t = text.lower(); out = []
    if "prefer" in t and ("short" in t or "concise" in t or "direct" in t):
        out.append(("answer_style", "short and direct"))
    m = re.search(r"deadline (?:is|moved to|to) (\w+)", t)
    if m: out.append(("deadline", m.group(1).capitalize()))   # store "Monday", not "monday"
    m = re.search(r"preparing for (?:a |an )?([\w ]+?) exam", t)
    if m: out.append(("goal", m.group(1).strip() + " exam"))
    return out
```

## 10. The stage script — `demo.py` (deterministic, non-interactive)

```python
from agent import Agent
from memory import Store
from llm import approx_tokens
import reset

USER = "patient-42"

def show_window(label, msgs):
    tok = sum(approx_tokens(m["content"]) for m in msgs)
    print(f"\n--- WINDOW [{label}]  (~{tok} tokens) ---")
    for m in msgs:
        print(f"  {m['role']:9} | {m['content'][:90]}")

def session_one():
    a = Agent(USER)
    turns = [
        "Hi, I'm preparing for a databases exam.",
        "I prefer short, direct answers.",
        "My deadline is Friday.",
        # the "long stretch": real turns so the buffer crosses TOKEN_BUDGET on stage
        "Explain ACID.", "Explain indexes.", "Explain joins.",
        "Explain normalization.", "Explain transactions.",
    ]
    shown = False
    for line in turns:
        a.step(line)
        if a.last_compacted and not shown:           # show compression the first time it fires
            print(f"\n⟶ buffer crossed TOKEN_BUDGET on: {line!r}")
            show_window("just after compaction", a.assemble_context("(continue)"))
            print("SUMMARY SO FAR:", a.summary[:160])
            shown = True
    if not shown:
        print("\n⚠ compaction never fired — lower TOKEN_BUDGET in config.py")

    # contradiction:
    a.step("Actually, the deadline moved to Monday.")
    print("\nCURRENT FACTS (tier 2):", Store().current_facts(USER))

def session_two_after_restart():
    print("\n==== PROCESS RESTART — fresh Agent, empty buffer ====")
    a = Agent(USER)                       # new buffer, same db on disk
    reply, msgs = a.step("What's my deadline, and how do I like answers?")
    show_window("reconstructed from memory", msgs)
    print("\nMIRA:", reply)

if __name__ == "__main__":
    reset.main()                           # clean slate
    session_one()
    session_two_after_restart()
```

`seed.py` (pre-populate session 1 so you can jump straight to the restart beat):

```python
import reset
from demo import session_one

if __name__ == "__main__":
    reset.main()
    session_one()
    print("\nseeded — now run `python -c 'import demo; demo.session_two_after_restart()'` "
          "to show only the restart beat")
```

`reset.py`:

```python
from config import DB_PATH
import os
def main():
    if os.path.exists(DB_PATH): os.remove(DB_PATH)
    print("db wiped")
if __name__ == "__main__": main()
```

## 11. On-stage beats (what to say while it runs)

1. **Tiers, live.** Run `session_one()`. Point at the writes per turn: *"buffer is RAM; facts are the user model; episodes are long-term semantic memory."* Every turn writes one episode; turns that state a preference/fact also write 0–2 facts.
2. **Compression.** When the script prints `⟶ buffer crossed TOKEN_BUDGET on: …`, show the reconstructed window: it now carries a `SUMMARY SO FAR:` block and the buffer is back down to the last few turns. *"We didn't truncate and lose it — we summarized. The raw user turns are already in tier 3 as episodes, so the content is restorable."*
3. **Scoped retrieval.** Show that the window holds only `TOP_K` recalled episodes: *"This is the whole point — we pull the slice relevant to this question, not the firehose. Same discipline as scoped tools."*
4. **Contradiction.** After "deadline moved to Monday," print the facts table: the Friday fact is `superseded`, Monday is `canonical`. *"Current truth is a query, not the latest write — and we kept the history."*
5. **The money moment — persistence.** Run `session_two_after_restart()`. New `Agent`, empty buffer, no summary in memory. It still answers deadline + style correctly. *"No chat history. It remembered because the memory lives in the hierarchy, not the window."*
6. **Scale (talk over the code).** Point at `user_id` on every table and the `ix_*_user` indexes, the LRU on the tier-2 read path, and `forget_user()`: *"Partition by user → shard to millions. Swap the LRU for Redis and SQLite for Postgres+pgvector — `memory.py` is the only file that changes. Run consolidation as a sleep-time job off the request path."*

## 12. Checkpoints

- **C1 — tiers:** after session 1, `facts` has 3 canonical rows (`goal`, `answer_style`, `deadline`) and `episodes` has one row per turn with a vector.
- **C2 — compression:** the demo prints the turn that crossed `TOKEN_BUDGET`; afterward `summary` is non-empty and the reconstructed window shows a `SUMMARY SO FAR:` block. (If you see the `⚠ compaction never fired` warning, lower `TOKEN_BUDGET`.)
- **C3 — scoped retrieval:** the reconstructed window contains ≤ `TOP_K` recalled episodes, not the full history.
- **C4 — contradiction:** exactly one canonical `deadline` fact (`Monday`); the `Friday` row is `superseded`.
- **C5 — persistence:** the post-restart answer names **Monday** and **short and direct** with an empty buffer — in both the offline stand-in (which surfaces the assembled memory) and, with `ANTHROPIC_API_KEY` set, a real model reply (the memory is now folded into the system prompt, so the model actually sees it).

## 13. Failure modes & fallbacks (ranked by likelihood)

1. **No Anthropic key / network down** → `chat()` uses the deterministic stand-in automatically; it still *demonstrates recall* by surfacing the assembled memory. The demo's point (memory, not generation) survives.
2. **No OpenAI key / embeddings provider errors** → `embed()` falls back to the toy embedder independently; nothing to configure, and chat can still be a real model.
3. **DB left dirty from a rehearsal** → `python reset.py` (or `python seed.py` to jump straight to the restart beat).
4. **Running long** → run `python seed.py` to pre-populate session 1, then show only beats 4–5 (contradiction + persistence).
5. **Total A/V failure** → play the 3–4 min screen recording of the full script (kept in the repo).

## 14. Optional extensions (mention, don't build live)

- Replace `extract_facts` with an LLM "memory writer" call (true self-editing memory blocks).
- Swap NumPy cosine for `sqlite-vec` or pgvector; swap the LRU for Redis (and extend the cache to the `search` path, not just fact reads).
- Add a **sleep-time** consolidation job that merges related episodes and refreshes summaries overnight.
- Add an **eval harness**: a fixed question set scored for cross-session consistency and retrieval hit-rate.

## 15. Running it inside Claude Code (MCP)

The same `memory.py` can back a **real agent instead of the toy chat loop**. Claude Code becomes the model, the agent loop, and tiers 0/1 (its own context window + compaction); the demo's durable tiers (2 = facts, 3 = episodes) are exposed as MCP tools. Nothing in `memory.py` changes — `mcp_server.py` is a thin FastMCP wrapper, structurally identical to this repo's `src/server.py`.

`src/memory/mcp_server.py` registers five tools (verified: all five register; the supersede path makes `deadline=Friday` → `deadline=Monday` canonical with `Friday` retained as `superseded`):

| Tool | Tier | Does |
|------|------|------|
| `memory_recall(user_id, query, k=3)` | 2 + 3 read | canonical facts **+** top-k episodes relevant to `query` — a small scoped payload, not the firehose |
| `memory_facts(user_id)` | 2 read | the current user model (canonical only; superseded history withheld) |
| `memory_remember(user_id, text)` | 3 + 2 write | store the raw turn as an episode, opportunistically extract + upsert facts |
| `memory_upsert_fact(user_id, key, value)` | 2 write | model-driven explicit fact write; supersedes the prior value for `key` |
| `forget_user(user_id)` | 2 + 3 delete | GDPR right-to-be-forgotten |

Wired in via a second `.mcp.json` server (alongside `context-engine`):

```json
"mira-memory": {
  "type": "stdio",
  "command": "uv",
  "args": ["run", "--directory", "${CLAUDE_PROJECT_DIR:-.}", "python", "src/memory/mcp_server.py"],
  "env": { "DB_PATH": "mira.db" }
}
```

`DB_PATH=mira.db` resolves under the project root (gitignored) and persists across `claude` restarts — that's what makes the money moment real.

**On stage:** in a live `claude` session, tell it a couple of durable facts (it calls `memory_remember` / `memory_upsert_fact`), ask a question (it calls `memory_recall`), then **quit Claude Code and reopen it** — a brand-new process with an empty context — and ask again. It still knows you, because the memory lives in the MCP-backed store, not the window.

**Trade-offs vs. the standalone demo (be honest with the room):**
- You **lose on-stage visibility of tiers 0/1.** Compression (beat 2) and window-scoping (beat 3) now happen *inside* Claude Code's black box; you can only instrument the durable tiers. The standalone `demo.py` remains the artifact that *shows* all three tiers and the movement between them.
- It's **non-deterministic.** Keep the scripted `demo.py` as the rehearsed safety net (beat-by-beat, fallback recording); use the MCP path as the "…and here it is wired into a real agent" reveal, not the load-bearing demo.

---

### Why this mirrors the workshop's three pillars
- **Hierarchical memory:** buffer + summary (tier 1), `facts` (tier 2), `episodes` (tier 3) — paged into the window by `assemble_context`.
- **Compression & retrieval:** `compact_if_needed` (restorable compression) and `search` (scoped, multi-factor retrieval).
- **Persistence & scaling:** on-disk SQLite, `user_id` partitioning, LRU→Redis seam, and the one-file backend swap.
