"""Derive what we have observed about a learner from their transcripts.

Runs on a background thread, triggered by turns accumulating rather than by a
clock, and writes to a SEPARATE file from the hand-written profile. Anything a
person wrote wins on conflict (profile.load merges that way), because this is a
children's device and a human must be able to state a fact about a learner and
have it stick.

Deliberately does NOT use the LLM. Everything here is counted, not inferred.
That is a direct consequence of what the 0.6B did to the content packs: asked
to rewrite vetted curriculum it inverted "a muscle can only pull, never push"
and claimed a magnet attracts any metal (docs/model-notes.md §5). A model that
unreliable rewriting a paragraph in front of it should not be authoring
unsupervised claims about a child. Counting is boring, cheap, and true.

What it cannot see is worth stating: it knows which subjects were asked about,
not whether the learner understood the answer. Comprehension needs either the
node's bigger model over the same transcripts, or a human.
"""
from __future__ import annotations

import collections
import pathlib
import threading

import yaml

from ..sync import transcript

# Turns between rebuilds. Event-based rather than timed: a device sitting idle
# in a cupboard should do nothing at all, and one in a busy classroom should
# keep up. Cheap enough (no model, just counting) that this can be small.
REBUILD_EVERY = 10

# A subject needs this many questions before it is called an interest. One
# question is curiosity; several is a pattern.
MIN_FOR_INTEREST = 3

_turns_since_rebuild = 0
_lock = threading.Lock()


def derived_path(cfg: dict) -> pathlib.Path:
    return pathlib.Path(cfg["tutor"].get("profile_derived", "learner-derived.yaml"))


def summarise(turns: list[dict]) -> dict:
    """Observable facts only. Every value here is a count or a direct quote."""
    subjects: collections.Counter = collections.Counter()
    unanswered: list[str] = []
    asked: collections.Counter = collections.Counter()
    heard_lengths: list[int] = []

    for t in turns:
        heard = (t.get("heard") or "").strip()
        if not heard:
            continue
        asked[heard.lower()] += 1
        heard_lengths.append(len(heard.split()))
        hits = t.get("retrieved") or []
        if hits:
            for c in hits:
                if c.get("subject"):
                    subjects[c["subject"]] += 1
        else:
            unanswered.append(heard)

    # Keys are split by AUDIENCE, not by how they were computed. A leading
    # underscore means "operational" — written to the file for a person or the
    # node to read, and skipped by profile.describe() so it never reaches the
    # tutor's prompt. Two reasons that matters: prompt tokens are the scarce
    # resource (grounding already costs ~422 of them), and telling the model
    # about questions it failed to answer is not something it can act on.
    out: dict = {"_turns_seen": len([t for t in turns if t.get("heard")])}
    if not out["_turns_seen"]:
        return out

    # --- learner-facing: shapes how the tutor speaks to them
    interests = [s for s, n in subjects.most_common() if n >= MIN_FOR_INTEREST]
    if interests:
        out["asks_most_about"] = interests
    # Asked more than once — either it did not land the first time, or it
    # matters to them. Worth the tutor knowing; which one it is, counting
    # cannot tell, so the key does not claim to.
    repeated = [q for q, n in asked.most_common() if n > 1][:5]
    if repeated:
        out["asked_more_than_once"] = repeated
    if heard_lengths:
        out["typical_question_words"] = round(sum(heard_lengths) / len(heard_lengths))

    # --- operational: for us, not for the model
    # Not a learner trait but a content gap, and the most useful thing the
    # transcripts know — it says which course to write next.
    if unanswered:
        out["_asked_but_not_covered"] = unanswered[-8:]
    return out


def rebuild(cfg: dict) -> dict:
    """Recompute the derived profile from recent transcripts and write it."""
    facts = summarise(transcript.read_recent(cfg))
    path = derived_path(cfg)
    try:
        path.write_text(yaml.safe_dump(facts, sort_keys=False, allow_unicode=True))
    except OSError as e:
        print(f"  profile: could not write {path} ({e})", flush=True)
    return facts


def on_turn(turn: dict, cfg: dict) -> None:
    """Post-write hook: rebuild once enough turns have accumulated.

    Rebuilding happens on a daemon thread so a slow disk cannot delay the next
    question. It is counting, not inference, so it does not contend with
    llama-server for the CPU the way an LLM pass would.
    """
    global _turns_since_rebuild
    if not cfg["tutor"].get("profile_derived", "learner-derived.yaml"):
        return
    with _lock:
        _turns_since_rebuild += 1
        if _turns_since_rebuild < REBUILD_EVERY:
            return
        _turns_since_rebuild = 0
    threading.Thread(target=rebuild, args=(cfg,), daemon=True).start()
