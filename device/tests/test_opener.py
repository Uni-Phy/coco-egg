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
