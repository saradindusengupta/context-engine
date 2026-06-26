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
