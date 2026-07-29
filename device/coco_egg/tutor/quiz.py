"""Quiz master: the device asks, the learner answers, and no model is involved.

Deliberately LLM-FREE, which is the whole design decision here. A quiz turn is
a question, a verdict and the next question — if each of those costs a 3.5s
generation the game stops being a game. Questions are authored in the pack and
judged against an accept-list, so a turn costs only TTS (~1.4s) and cannot be
hallucinated. It is the same reasoning that keeps `explain` out of the LLM's
hands in tools/build_pack.py: a wrong answer read aloud to a child, in the one
mode where the device is claiming to mark them, is the worst failure available.

The cost of that choice is real and worth stating: judging is string matching,
so a correct answer phrased unusually gets marked wrong. Accept-lists are
written generously to compensate, and the verdict always says what the answer
was rather than only that the learner missed it.

Routing lives in tutor/__init__.py and checks this module FIRST, because "let's
play a quiz" is also a textbook opener (llama_client.is_opener) and would
otherwise be answered with a friendly invitation to ask a question instead.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterator

from .deck import Deck
from .llama_client import _get_pack

DEFAULT_QUESTIONS = 5

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
# `\s*m[ey]` rather than `\s+me`, because the trigger has to survive ASR rather
# than assume it. Measured with tools/asr_ab.py: whisper renders spoken "quiz
# me" as the single word "Quizmy", and "quiz me on jyotisha" as "Quizmy on Jaya
# Tisha" — so the most natural way to start a quiz never fired. Elision like
# this is what a general ASR does to an unfamiliar two-word phrase, and the
# demo path has to tolerate it.
_START = re.compile(
    # ^quiz\w* first, and it is the one that matters: chasing spellings loses.
    # The same spoken "quiz me" came back as "Quizmy" on one run and "Quizmi" on
    # the next, so matching the elision letter by letter was always going to be
    # a step behind. An utterance that STARTS with quiz-something is a request
    # to play, whatever the ASR made of the second word.
    r"^\s*quiz\w*\b"
    r"|\b(quiz|test)\s*m[ey]\b|\bquiz\s*time\b|\b(play|start|begin|do)\s+(a\s+)?quiz\b"
    r"|\bask\s+me\s+(some\s+)?questions?\b", re.I)
_STOP = re.compile(
    r"\b(stop|quit|exit|enough|finished|done|no more)\b", re.I)
_REPEAT = re.compile(r"\b(repeat|again|say that again|pardon|what was that)\b", re.I)
_PASS = re.compile(r"\b(i don'?t know|no idea|dunno|skip|pass|next)\b", re.I)


class Game:
    """One run of questions. Module-level singleton; one learner per egg."""

    def __init__(self) -> None:
        self.questions: list[dict] = []
        self.at = 0
        self.correct = 0

    @property
    def running(self) -> bool:
        return self.at < len(self.questions)

    @property
    def current(self) -> dict | None:
        return self.questions[self.at] if self.running else None

    def clear(self) -> None:
        self.questions, self.at, self.correct = [], 0, 0


_game = Game()


def active() -> bool:
    return _game.running


def reset() -> None:
    """Drop the game — a new learner must not inherit a half-played round."""
    _game.clear()


def is_start(text: str) -> bool:
    return bool(_START.search(text or ""))


def _norm(text: str) -> str:
    return " ".join(_PUNCT.sub(" ", (text or "").lower()).split())


def judge(said: str, item: dict) -> bool:
    """Did the learner say the thing? Substring match on a generous accept-list.

    Substring rather than equality because the answer arrives as speech: "um,
    twenty seven I think" has to count. The accept-list carries numerals and
    words both ("27", "twenty seven"), since whisper picks either.
    """
    s = _norm(said)
    if not s:
        return False
    return any(_norm(a) in s for a in item.get("accept", []))


def _subject_filter(text: str, items: list[dict]) -> list[dict]:
    """"quiz me on the sky" -> only questions from a matching subject."""
    said = _norm(text)
    picked = [i for i in items
              if i.get("subject") and
              any(w in said for w in _norm(i["subject"]).split() if len(w) > 3)]
    return picked or items


_decks: dict[str, Deck] = {}


def _dealer(items: list[dict], cfg: dict) -> Deck:
    """A no-repeat deck per question set, so round two is not round one again.

    random.sample() picks fresh each round, which means the same question can
    open three rounds running — at a party that reads as a broken device rather
    than as chance. Keyed by the content, so a filtered subject gets its own
    deck and editing a pack resets it.
    """
    digest = hashlib.sha256("\n".join(i["q"] for i in items).encode()).hexdigest()[:16]
    if digest not in _decks:
        path = cfg["tutor"].get("quiz_deck")
        _decks[digest] = Deck(len(items), digest,
                              f"{path}-{digest}.json" if path else None)
    return _decks[digest]


def _summary() -> str:
    n = len(_game.questions)
    got = _game.correct
    if not n:
        return "That is the end of the quiz."
    if got == n:
        return f"That is the end. You got all {n} right. Brilliant!"
    return f"That is the end. You got {got} out of {n} right. Well played!"


def _ask(item: dict, lead: str = "") -> str:
    number = _game.at + 1
    return f"{lead}Question {number}. {item['q']}"


def turn(text: str, cfg: dict) -> Iterator[str]:
    """One quiz exchange: start it, answer a question, or finish it.

    Yields spoken sentences like stream_sentences() does, so main.one_turn
    cannot tell the difference and streams them to TTS the same way.
    """
    if not _game.running:
        yield from _start(text, cfg)
        return

    if _STOP.search(text):
        yield _summary()
        reset()
        return

    if _REPEAT.search(text):
        yield _ask(_game.current)
        return

    item = _game.current
    # The answer follows as its own sentence rather than being spliced in after
    # "the answer is". Answers are written as full sentences and several are
    # proper nouns, so splicing produced "The answer is The two points where..."
    # — which is what a learner would actually have heard.
    if _PASS.search(text):
        verdict = f"No problem. {item['a']}"
    elif judge(text, item):
        _game.correct += 1
        verdict = f"Correct! {item['a']}"
    else:
        verdict = f"Not quite. {item['a']}"
    yield verdict

    _game.at += 1
    if _game.running:
        yield _ask(_game.current)
    else:
        yield _summary()
        reset()


def _start(text: str, cfg: dict) -> Iterator[str]:
    pack = _get_pack(cfg)
    items = list(getattr(pack, "quiz", []) or []) if pack else []
    if not items:
        # Honest degrade: a pack with no authored questions is not quizzable,
        # and inventing them with the model is exactly what this module avoids.
        yield "I don't have any quiz questions loaded yet."
        yield "Ask me about a subject instead and I'll teach you."
        return

    items = _subject_filter(text, items)
    want = min(int(cfg["tutor"].get("quiz_questions", DEFAULT_QUESTIONS)), len(items))
    _game.clear()
    _game.questions = [items[i] for i in _dealer(items, cfg).draw_many(want)]
    subject = _game.questions[0].get("subject", "")
    lead = f"Alright! {want} questions" + (f" on {subject}. " if subject else ". ")
    yield _ask(_game.questions[0], lead)
