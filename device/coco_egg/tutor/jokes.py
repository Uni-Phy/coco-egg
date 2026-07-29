"""Telling jokes, without the model and without repeating itself.

Asked for a joke, the 1.7B tells the same joke. Not a similar one - the same
one, again and again, because joke variety is precisely what a small model does
not have. It is the identical failure to the quiz: the interesting thing is not
generation, it is *selection*, and a model is the wrong tool for selection.

So jokes are authored (fixtures/jokes.json) and dealt from a no-repeat deck
(deck.py). Every joke is told once before any is told twice, the deck survives a
restart, and the joke just told cannot lead the reshuffle. With 44 loaded, a
party runs a long time before anything comes round.

Setup and punchline are yielded as SEPARATE sentences on purpose. The device
speaks sentence by sentence, so the split becomes the comic pause - line, beat,
answer. Yielded together they arrive in one breath and stop being jokes.

Free of the LLM, so a joke costs only TTS (~1.4s) rather than ~3.5s of
generation, and cannot come back inappropriate for a room full of children.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Iterator

from .deck import Deck

# "another" and "again" only count once a joke has just been told, so "tell me
# again" after a lesson still means repeat the lesson.
_ASK = re.compile(
    # [\s.!?]* rather than \s* before the anchor: ASR punctuates, so "Another
    # joke." never reached the end-of-string alternative and the second-most
    # natural way to ask for one silently did nothing.
    r"\b(tell|say|know|got|give)\b.{0,18}\bjokes?\b|\bjokes?\b[\s.!?]*$|^\s*jokes?\b"
    r"|\bmake me laugh\b|\bsomething funny\b|\bbe funny\b|\bmore jokes?\b", re.I)
_ANOTHER = re.compile(
    r"^\s*(another|one more|again|more|next|keep going|another one)\b", re.I)

_jokes: list[dict] | None = None
_deck: Deck | None = None
_told_one = False


def _load(cfg: dict) -> list[dict]:
    global _jokes, _deck
    if _jokes is not None:
        return _jokes
    path = cfg["tutor"].get("jokes")
    _jokes = []
    if path and pathlib.Path(path).is_file():
        try:
            data = json.loads(pathlib.Path(path).read_text())
            _jokes = [j for j in data.get("jokes", [])
                      if j.get("setup") and j.get("punchline")]
        except (ValueError, OSError) as e:
            print(f"  jokes: could not load {path} ({e.__class__.__name__})", flush=True)
    if _jokes:
        # Fingerprint the content so editing the file resets the deck rather
        # than dealing saved indices into a list that changed underneath them.
        digest = hashlib.sha256(
            "\n".join(j["setup"] for j in _jokes).encode()).hexdigest()[:16]
        _deck = Deck(len(_jokes), digest, cfg["tutor"].get("jokes_deck"))
        print(f"  jokes: {len(_jokes)} loaded, {_deck.left} before a reshuffle",
              flush=True)
    return _jokes


def is_request(text: str) -> bool:
    """Asked for a joke? "another one" counts only right after one was told."""
    t = (text or "").strip()
    if not t:
        return False
    if _ASK.search(t):
        return True
    return bool(_told_one and _ANOTHER.match(t))


def reset() -> None:
    """A new learner is not mid-run of anything. The DECK is not cleared: it is
    the memory of what has been told, and that is the point of it."""
    global _told_one
    _told_one = False


def tell(cfg: dict) -> Iterator[str]:
    global _told_one
    jokes = _load(cfg)
    if not jokes or _deck is None:
        yield "I don't have any jokes loaded yet."
        return
    index = _deck.draw()
    if index is None:
        yield "I don't have any jokes loaded yet."
        return
    joke = jokes[index]
    _told_one = True
    # Two sentences, so TTS puts a real beat between them.
    yield joke["setup"]
    yield joke["punchline"]


def remaining() -> int:
    """Jokes left before the deck reshuffles. For the console and for a host."""
    return _deck.left if _deck else 0
