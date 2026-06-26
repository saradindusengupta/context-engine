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
