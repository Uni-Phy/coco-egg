"""Openers: the turns that start a session instead of asking something.

Measured on the device, "let's study physics" retrieved the measurement-units
lesson and answered with a lecture about metres. A whole subject is not a
question, so retrieval picks some arbitrary lesson inside it — and the learner
never gets asked what they actually wanted to know.

The risk in fixing that is the opposite failure: classing a real question as an
opener and refusing to teach it. That is what most of this file guards.
"""
import json
import pathlib

import pytest

from coco_egg import config
from coco_egg.tutor import llama_client
from coco_egg.tutor.llama_client import is_opener

SOURCES = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "sources"


@pytest.fixture
def cfg():
    c = config.load(path=None)
    c["tutor"]["embed_url"] = None      # lexical path; no server needed
    c["tutor"]["pack"] = None
    return c


@pytest.fixture(autouse=True)
def _clean():
    llama_client.forget()
    yield
    llama_client.forget()


@pytest.mark.parametrize("said", [
    "hello",
    "hi coco",
    "hey there",
    "namaste",
    "good morning",
    "good evening coco",
    "bye",
    "goodbye",
    "see you tomorrow",
    "thanks",
    "thank you so much",
])
def test_greetings_are_openers(said):
    assert is_opener(said)


@pytest.mark.parametrize("said", [
    "let's study physics",
    "lets start maths",
    "let's do some science",
    "shall we begin",
    "can we study the human body",
    "could we learn about the farm",
    "i want to learn about plants",
    "i'd like to study history",
    "teach me something",
])
def test_proposals_are_openers(said):
    assert is_opener(said)


@pytest.mark.parametrize("asked", [
    "what is a fraction",
    "why is the sky blue",
    "how do animals breathe",
    "who runs my village",
    "which king became a buddhist after a war",
    "tell me about the lion pillar",       # "tell me" is not a proposal
    "tell me a joke",
    "can the government stop me praying",  # "can the", not "can we"
    "do plants eat mud",
    "if I cut a chapati in two what do I have",
])
def test_real_questions_are_not_openers(asked):
    assert not is_opener(asked)


@pytest.mark.parametrize("said", [
    "thanks, what is a fraction",              # gratitude, then a real question
    "hi coco why is the sky blue",
    "let's say I have 3 apples, how many is that",
])
def test_a_question_hiding_behind_an_opener_is_still_a_question(said):
    """The greeting is the wrapper, not the turn. Answer what was asked."""
    assert not is_opener(said)


def test_the_eval_question_set_is_never_classed_as_an_opener():
    """The regression this rule could plausibly cause, stated against real data.

    Every question a course ships is one a learner is expected to get taught.
    If a new opener pattern ever swallows one, retrieval silently stops firing
    for it and the eval will not catch it — the eval calls retrieve_semantic()
    directly and never sees this rule.
    """
    questions = [
        r["q"]
        for f in sorted(SOURCES.glob("*.questions.json"))
        for r in json.loads(f.read_text()).get("should_retrieve", [])
    ]
    assert questions, "no course questions found — check the fixtures path"
    swallowed = [q for q in questions if is_opener(q)]
    assert not swallowed, f"openers swallowed real questions: {swallowed}"


def test_an_opener_is_not_grounded(cfg):
    """The actual fix: no lesson gets picked on the learner's behalf."""
    messages, hits = llama_client.build_messages("let's study physics", cfg)
    assert hits == []
    assert "not asking a question" in messages[-1]["content"]
    assert messages[-1]["content"].endswith("let's study physics")


def test_a_question_still_reaches_retrieval(cfg):
    """Guard the other direction: the opener path must not shadow questions."""
    messages, _ = llama_client.build_messages("what is a fraction", cfg)
    assert "not asking a question" not in messages[-1]["content"]


def test_empty_input_is_not_an_opener():
    assert not is_opener("")
    assert not is_opener("   ")


# --- naming a subject, rather than asking about it -------------------------
#
# Measured on the device 2026-07-29: after two turns about kickboxing, the
# single word "Astrology." came back with the kickboxing answer VERBATIM, even
# though retrieval had correctly found the planets lesson and put it in the
# prompt. A bare noun carries no instruction, so the strongest thing in context
# wins — and that is whatever the tutor last said.

@pytest.mark.parametrize("said", [
    "astrology",
    "Kickboxing.",
    "photosynthesis",
    "the water cycle",
    "fractions",
])
def test_a_named_subject_is_a_nomination(said):
    assert llama_client.is_topic_nomination(said)


@pytest.mark.parametrize("said", [
    "what is a fraction",              # a question, however short
    "why is the sky blue",
    "tell me more",                    # a follow-up: no content words at all
    "do plants eat mud",               # three content words
    "is zero just nothing",            # yes/no question; `nothing` is a stopword
    "are magnets attracted to copper",
    "can magnets pull wood",
    "hello",                           # an opener, checked first
    "let's study physics",
    "i would like to learn",
    "",
])
def test_these_are_not_nominations(said):
    assert not llama_client.is_topic_nomination(said)


def test_a_nomination_drops_the_history(cfg):
    """The actual fix for the kickboxing repeat.

    Instruction alone did not beat context dominance on a 1.7B — the previous
    answer sits right there and repeating it is the path of least resistance.
    """
    llama_client.remember("Kickboxing.", "Kickboxing is a sport where you kick.", cfg)
    messages, _ = llama_client.build_messages("Astrology.", cfg)

    assert [m["role"] for m in messages] == ["system", "user"]
    assert "Kickboxing" not in messages[-1]["content"]
    assert "NEW subject" in messages[-1]["content"]


def test_a_follow_up_still_keeps_its_history(cfg):
    """Guard the other direction: dropping history for real follow-ups would
    reintroduce the bug conversation memory was added to fix."""
    llama_client.remember("what is friction", "It resists sliding.", cfg)
    messages, _ = llama_client.build_messages("why do we need it", cfg)
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]


def test_the_eval_question_set_is_never_a_nomination():
    """Nominations skip the history but still retrieve, so a course question
    caught here would not break retrieval — but it would be told it had
    changed subject mid-lesson, which is wrong and worth catching."""
    questions = [
        r["q"]
        for f in sorted(SOURCES.glob("*.questions.json"))
        for r in json.loads(f.read_text()).get("should_retrieve", [])
    ]
    caught = [q for q in questions if llama_client.is_topic_nomination(q)]
    assert not caught, f"course questions treated as subject changes: {caught}"
