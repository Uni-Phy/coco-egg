"""Conversation memory: the last few turns, held in RAM.

Live testing on 2026-07-28 showed why this is not optional for a tutor. Every
turn was sent alone, so a follow-up had nothing to follow: "that was very big"
invented a field of crops, and when the learner complained that the answer did
not follow, the tutor agreed with the complaint and elaborated on the
nonsense. Teaching is conversational — "why?", "I don't understand", "tell me
more" are the core moves, and all of them were broken.

Where this sits in the prompt is the whole reason it is affordable. History is
APPEND-ONLY, so placed above the volatile grounding it lands inside
llama-server's cached prefix and costs prefill only once, on the turn it is
created. Measured: with grounding at the tail, computed tokens stay flat as a
conversation deepens; with grounding above, each retained turn added ~26
tokens of recompute on every later turn, forever (docs/model-notes.md).

Kept deliberately small. RAM is not the constraint — the KV cache costs about
0.11 MB per token, so even a long history is megabytes. The constraint is that
a turn evicted from the window shifts the prefix and invalidates the cache
below it, so a window that turns over every turn would defeat the point.

Which is exactly what a plain sliding deque did, and it shipped that way.
Measured on the device 2026-07-29, prefill tokens as llama-server reports them:

    [h1 h2 h3] append, nothing evicted    74 tokens   1550 ms
    [h2 h3 h4] one turn evicted          203 tokens   4039 ms

Every turn from the fourth onward paid a full re-prefill — about 2.5s, forever.
The eviction is therefore BATCHED: the window grows to `turns` and then drops
back to `KEEP_ON_TRIM` in one go. Growth is pure append, so those turns stay
cached; the prefix breaks once per batch instead of once per turn. With the
defaults below that is one expensive turn in three rather than three in three.
"""
from __future__ import annotations

# A turn is a (question, reply) pair. Four is the high-water mark, not a fixed
# depth — see KEEP_ON_TRIM. Enough that "why?", "tell me more" and a correction
# still see what they refer to.
DEFAULT_TURNS = 4

# What survives a trim. Never zero: dropping to nothing would make the turn
# after a trim behave like a fresh conversation, which is the bug conversation
# memory exists to fix.
KEEP_ON_TRIM = 2

# Replies are capped before storing. The model rambles past its 3-sentence
# instruction, and a 600-char reply kept verbatim would push the window over
# the context budget without adding anything a follow-up needs.
MAX_REPLY_CHARS = 320


class History:
    """The last N (question, reply) pairs for one learner, oldest first."""

    def __init__(self, turns: int = DEFAULT_TURNS):
        self._cap = max(0, turns)
        # Trim target: half the window, at least one turn while the window
        # holds any at all. A deque with maxlen cannot express this — it evicts
        # one per append, which is the behaviour being replaced.
        # cap - 1 guarantees headroom: keeping exactly `cap` would trim on every
        # append, which is the sliding behaviour this replaces.
        self._keep = min(KEEP_ON_TRIM, max(1, self._cap - 1)) if self._cap else 0
        self._turns: list[tuple[str, str]] = []

    def add(self, question: str, reply: str) -> None:
        """Record a completed turn. Empty turns are not worth remembering."""
        question, reply = question.strip(), reply.strip()
        if not question or not reply:
            return
        if not self._cap:
            return
        self._turns.append((question, reply[:MAX_REPLY_CHARS]))
        if len(self._turns) > self._cap:
            # Batched, not sliding: keep the newest few and drop the rest in one
            # go, so the next few turns are pure appends onto a cached prefix.
            self._turns = self._turns[-self._keep:]

    def messages(self) -> list[dict]:
        """Prior turns as chat messages, ready to sit above the volatile tail."""
        out: list[dict] = []
        for question, reply in self._turns:
            out.append({"role": "user", "content": question})
            out.append({"role": "assistant", "content": reply})
        return out

    def last_question(self) -> str:
        """The most recent question, for resolving what a follow-up refers to."""
        return self._turns[-1][0] if self._turns else ""

    def clear(self) -> None:
        """Forget the conversation. A new learner must not inherit the last one."""
        self._turns.clear()

    def __len__(self) -> int:
        return len(self._turns)
