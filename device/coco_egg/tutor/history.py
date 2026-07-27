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
"""
from __future__ import annotations

import collections

# A turn is a (question, reply) pair. Three is enough for "why?", "tell me
# more" and a correction to still see what they refer to, and short enough
# that the window is stable across a normal exchange.
DEFAULT_TURNS = 3

# Replies are capped before storing. The model rambles past its 3-sentence
# instruction, and a 600-char reply kept verbatim would push the window over
# the context budget without adding anything a follow-up needs.
MAX_REPLY_CHARS = 320


class History:
    """The last N (question, reply) pairs for one learner, oldest first."""

    def __init__(self, turns: int = DEFAULT_TURNS):
        self._turns: collections.deque = collections.deque(maxlen=max(0, turns))

    def add(self, question: str, reply: str) -> None:
        """Record a completed turn. Empty turns are not worth remembering."""
        question, reply = question.strip(), reply.strip()
        if not question or not reply:
            return
        self._turns.append((question, reply[:MAX_REPLY_CHARS]))

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
