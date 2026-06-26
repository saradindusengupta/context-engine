import os

HAVE_ANTHROPIC = bool(os.getenv("ANTHROPIC_API_KEY"))
HAVE_OPENAI    = bool(os.getenv("OPENAI_API_KEY"))
OFFLINE        = not (HAVE_ANTHROPIC or HAVE_OPENAI)   # narrative flag; per-call fallback lives in llm.py
CHAT_MODEL     = os.getenv("CHAT_MODEL", "claude-sonnet-4-6")
EMBED_DIM      = 256          # toy embedding dimension when OpenAI embeddings aren't available
TOKEN_BUDGET   = 150          # small so compression fires within session 1
TOP_K          = 3            # scoped retrieval: only the k most relevant episodes
DB_PATH        = os.getenv("DB_PATH", "mira.db")
