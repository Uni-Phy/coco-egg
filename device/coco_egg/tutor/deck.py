"""Deal without repeats: shuffle once, deal through, reshuffle only when empty.

Asking a small model for a joke gets you the same joke. Not similar — the same
one, two or three times in a row, because joke diversity is exactly the kind of
thing a 1.7B has almost none of. Sampling authored jokes at random has the same
problem for a different reason: with 40 jokes and random choice, the chance of a
repeat inside ten draws is about 68%. At a party that reads as broken.

So this is a deck, not a die. Every item is dealt once before any is dealt
twice, and when the deck runs out it reshuffles with a guard so the joke you
just heard cannot lead the next round.

Persisted, because a demo lasts longer than a process. `docker restart egg`
mid-party would otherwise deal the same opener again, which is the one repeat
anybody would actually notice. The file is keyed by a fingerprint of the
content, so editing the jokes resets the deck instead of dealing stale indices
into a list that changed underneath it.
"""
from __future__ import annotations

import json
import pathlib
import random


class Deck:
    """Indices 0..size-1, dealt in a shuffled order that does not repeat."""

    def __init__(self, size: int, fingerprint: str, path: str | None = None):
        self.size = size
        self.fingerprint = fingerprint
        self.path = pathlib.Path(path) if path else None
        self._remaining: list[int] = []
        self._last: int | None = None
        self._load()

    # -- persistence --------------------------------------------------------
    def _load(self) -> None:
        if self.path and self.path.is_file():
            try:
                saved = json.loads(self.path.read_text())
                if (saved.get("fingerprint") == self.fingerprint
                        and isinstance(saved.get("remaining"), list)):
                    self._remaining = [i for i in saved["remaining"]
                                       if isinstance(i, int) and 0 <= i < self.size]
                    self._last = saved.get("last")
                    return
            except (ValueError, OSError):
                pass          # a corrupt deck is not worth failing a turn over
        self._shuffle()

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({
                "fingerprint": self.fingerprint,
                "remaining": self._remaining,
                "last": self._last,
            }))
        except OSError:
            pass              # state/ unwritable: deal in memory, still no repeats

    # -- dealing ------------------------------------------------------------
    def _shuffle(self) -> None:
        order = list(range(self.size))
        random.shuffle(order)
        # Do not let the item just dealt lead the new deck: back to back is the
        # only repeat anyone notices, and it is the one this exists to prevent.
        if self.size > 1 and order and order[-1] == self._last:
            order[-1], order[0] = order[0], order[-1]
        self._remaining = order

    def draw(self) -> int | None:
        """Next index, or None when there is nothing to deal."""
        if not self.size:
            return None
        if not self._remaining:
            self._shuffle()
        # Popping from the END is O(1) and the order is already random.
        pick = self._remaining.pop()
        self._last = pick
        self._save()
        return pick

    def draw_many(self, n: int) -> list[int]:
        """n distinct indices, in deal order. Fewer only if the deck is smaller."""
        return [i for i in (self.draw() for _ in range(min(n, self.size))) if i is not None]

    @property
    def left(self) -> int:
        """How many before a reshuffle — the useful number for a host to see."""
        return len(self._remaining)
