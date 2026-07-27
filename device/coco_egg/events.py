"""Turn events: a one-way tap on the voice loop, for anything that watches it.

The console (docs/console-design.md) is the first consumer, and this module
knows nothing about it. That is deliberate — the loop publishes, and whether
anyone is listening is not the loop's problem.

Three rules, in priority order:

1. **Zero subscribers is the normal case.** A device in a classroom with
   nobody's laptop open takes a lock, sees an empty list and returns; the
   event is never even built. Callers whose payload costs something to
   assemble check active() first (pack.py ranks and formats candidates).
2. **A subscriber never fails the turn.** Anything raised is caught and that
   subscriber is dropped — a peripheral that misbehaves gets disconnected, it
   does not get to end a learner's question.
3. **A subscriber never slows the turn.** Delivery is synchronous, so a
   callback must not do I/O. Stream is the shape for anything that might
   block (SSE to a browser on a slow LAN): a bounded queue that drops its
   oldest event rather than making the egg wait.

Events are plain JSON-serialisable dicts sharing an envelope — seq, turn,
t (seconds since the turn began), ts (wall clock), kind — plus per-kind
fields. The kinds are turn.start, state, heard, retrieved, sentence, spoken,
stage, degraded, error, turn.end. The field-level contract is written out in
docs/console-design.md rather than duplicated here: it is shared with the
console half, so it lives in one place.
"""
from __future__ import annotations

import threading
import time
from queue import Empty, Full, Queue
from typing import Callable

Event = dict
Subscriber = Callable[[Event], None]

_lock = threading.Lock()
_subscribers: list[Subscriber] = []
_seq = 0
_turn = 0
_turn_t0 = time.monotonic()


def subscribe(fn: Subscriber) -> Subscriber:
    """Register a callback. Returns it, so it can be unsubscribed later."""
    with _lock:
        if fn not in _subscribers:
            _subscribers.append(fn)
    return fn


def unsubscribe(fn: Subscriber) -> None:
    """Deregister a callback. Unsubscribing twice is not an error."""
    with _lock:
        if fn in _subscribers:
            _subscribers.remove(fn)


def active() -> bool:
    """Is anyone listening?

    For callers that pay to build their payload. A stale answer is harmless:
    the worst case is one event assembled for nobody, or one skipped.
    """
    return bool(_subscribers)


def begin_turn() -> int:
    """Open a turn: later events are stamped with its id and elapsed clock."""
    global _turn, _turn_t0
    _turn += 1
    _turn_t0 = time.monotonic()
    emit("turn.start")
    return _turn


def end_turn(**fields) -> None:
    """Close a turn. The id stays current so late events still land on it."""
    emit("turn.end", **fields)


def emit(kind: str, **fields) -> None:
    """Publish one event. Safe to call with nobody listening, which is normal.

    Fields must be JSON-serialisable — the bus does not serialise, but every
    subscriber we have in mind does.
    """
    global _seq
    with _lock:
        if not _subscribers:
            return
        _seq += 1
        event: Event = {"seq": _seq, "turn": _turn,
                        "t": round(time.monotonic() - _turn_t0, 3),
                        "ts": round(time.time(), 3), "kind": kind, **fields}
        targets = list(_subscribers)
    for fn in targets:
        try:
            fn(event)
        except Exception as e:
            # Rule 2. Log once and drop it rather than raising here (the caller
            # is mid-turn) or failing again on every event for the rest of the
            # session.
            unsubscribe(fn)
            print(f"  events: subscriber {getattr(fn, '__qualname__', fn)!s} raised "
                  f"{e.__class__.__name__}; dropped", flush=True)


class Stream:
    """A subscriber that cannot slow the publisher: a bounded queue that drops.

    The shape the HTTP/SSE layer uses. A browser on a slow LAN, or a tab that
    stopped reading, must cost the voice loop nothing — so a full queue sheds
    its oldest event and counts the gap instead of waiting for room. Losing
    the middle of a trace is a cosmetic problem; blocking the egg is not.

        with events.Stream() as stream:
            while True:
                event = stream.get(timeout=15)
                ...
    """

    def __init__(self, maxsize: int = 256):
        self._q: Queue = Queue(maxsize)
        self.dropped = 0

    def __enter__(self) -> "Stream":
        subscribe(self.put)
        return self

    def __exit__(self, *exc) -> None:
        unsubscribe(self.put)

    def put(self, event: Event) -> None:
        try:
            self._q.put_nowait(event)
        except Full:
            try:
                self._q.get_nowait()
                self.dropped += 1
            except Empty:
                pass          # a reader drained it in between; nothing to shed
            try:
                self._q.put_nowait(event)
            except Full:
                self.dropped += 1

    def get(self, timeout: float = 1.0) -> Event | None:
        """Next event, or None if nothing arrived inside the timeout."""
        try:
            return self._q.get(timeout=timeout)
        except Empty:
            return None
