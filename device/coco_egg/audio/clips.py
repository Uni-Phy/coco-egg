"""Spoken audio, held briefly so a browser can fetch and play it.

The point is a device with no speaker. The egg already renders every sentence to
a WAV for aplay; publishing that same file under an id lets a phone on the same
network be the speaker instead — and lets several people hear it at once, which
a single speaker cannot do.

Bounded on purpose, and it fixes a leak while it is here. tts.synthesize() opens
its WAV with delete=False and nothing ever removed them, so a device left
running accumulated one temp file per sentence spoken, forever. Eviction here
unlinks, so the working set is the last few clips rather than the whole session.

Kept deliberately small and dumb: no streaming, no transcoding, no seeking. A
sentence of Piper output is tens of kilobytes and the browser fetches it whole
in one request on a LAN.
"""
from __future__ import annotations

import collections
import pathlib
import secrets
import threading

# Enough that a browser lagging several sentences behind still finds its clip,
# small enough that the files on disk stay a handful. Piper sentences are
# ~30-80 KB, so this is a couple of megabytes at worst.
MAX_CLIPS = 32

_lock = threading.Lock()
_clips: collections.OrderedDict[str, pathlib.Path] = collections.OrderedDict()


def publish(wav_path: str) -> str:
    """Register a WAV for serving. Returns the id to put on the wire."""
    clip_id = secrets.token_hex(4)
    with _lock:
        _clips[clip_id] = pathlib.Path(wav_path)
        while len(_clips) > MAX_CLIPS:
            _, old = _clips.popitem(last=False)
            try:
                old.unlink(missing_ok=True)
            except OSError:
                pass          # a clip we cannot delete is not worth failing over
    return clip_id


def path(clip_id: str) -> pathlib.Path | None:
    """The file for an id, or None once it has aged out.

    Returns None rather than raising for an unknown id: the console serves this
    to whatever a browser asks for, and a stale request after a reconnect is
    ordinary rather than exceptional.
    """
    with _lock:
        return _clips.get(clip_id)


def clear() -> None:
    """Drop and delete everything held. For tests and shutdown."""
    with _lock:
        while _clips:
            _, old = _clips.popitem()
            try:
                old.unlink(missing_ok=True)
            except OSError:
                pass


def count() -> int:
    with _lock:
        return len(_clips)
