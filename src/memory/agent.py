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
        if facts:
            mem_blocks.append("USER MEMORY: " + "; ".join(f"{k}={v}" for k, v in facts))
        if self.summary:
            mem_blocks.append("SUMMARY SO FAR: " + self.summary)
        if recalled:
            mem_blocks.append("RECALLED EPISODES: " + " || ".join(recalled))
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
    t = text.lower()
    out = []
    if "prefer" in t and ("short" in t or "concise" in t or "direct" in t):
        out.append(("answer_style", "short and direct"))
    m = re.search(r"deadline (?:is|moved to|to) (\w+)", t)
    if m:
        out.append(("deadline", m.group(1).capitalize()))   # store "Monday", not "monday"
    m = re.search(r"preparing for (?:a |an )?([\w ]+?) exam", t)
    if m:
        out.append(("goal", m.group(1).strip() + " exam"))
    return out
