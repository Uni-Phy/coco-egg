"""Where a turn comes from: the bench keyboard, the console, and later a button.

Until now the loop read stdin directly, so a demo meant pressing Enter in a
terminal while watching a browser — two places at once, and the terminal is the
one nobody should have to look at. The console can start a turn now, which makes
the browser the whole demo surface.

The point of routing both through one queue is that neither is special. GPIO at
M1 becomes a third caller of request() rather than a second branch inside the
loop, which is where a "press the button" path would otherwise diverge from the
"press Enter" path and quietly rot.

Depth of one, on purpose. A demo double-tap, or an impatient child pressing
space four times while the egg is still thinking, must not queue four turns —
the extra presses are rejected and the caller is told, so the UI can say so
rather than silently banking them.
"""
from __future__ import annotations

import threading
from queue import Empty, Full, Queue

EOF = {"source": "eof"}

_q: Queue = Queue(maxsize=1)
_busy = threading.Event()


def request(source: str, key: str = "") -> bool:
    """Ask for a turn. False when one is already running or already queued."""
    if _busy.is_set():
        return False
    try:
        _q.put_nowait({"source": source, "key": key})
        return True
    except Full:
        return False


def wait(timeout: float | None = None) -> dict | None:
    """Next trigger. None on timeout; EOF when the keyboard closed."""
    try:
        return _q.get(timeout=timeout) if timeout is not None else _q.get()
    except Empty:
        return None


def close() -> None:
    """Stdin closed — unblock the loop so it can exit."""
    try:
        _q.put_nowait(EOF)
    except Full:
        pass


def begin() -> None:
    """A turn is running: reject presses until it ends."""
    _busy.set()


def end() -> None:
    _busy.clear()
    # Anything banked while busy is stale by now — the learner pressed during an
    # answer they were still hearing, not to ask a second question.
    try:
        _q.get_nowait()
    except Empty:
        pass


def accepting() -> bool:
    return not _busy.is_set()
