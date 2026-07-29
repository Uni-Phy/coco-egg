"""The introduction, and the only property it has: the words are exact.

Everything else the device says may be paraphrased, shortened or reworded by a
model. This may not. A manifesto that comes out slightly different each time is
not a manifesto, so the test that matters is character-for-character equality
with the file, not "it says something about eggs".
"""
import json
import pathlib

import pytest

from coco_egg import config, tutor
from coco_egg.tutor import intro, quiz

INTRO = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "intro.json"

# The introduction as it must be spoken. Written out here rather than read from
# the file on purpose: a test that loads the same source it is checking would
# pass no matter what either one said.
EXPECTED = [
    "I am an egg.",
    "Open source. No cloud, no master, no meter running.",
    "Crack me open — you'll find no secrets, only code. Copy me. Share me. "
    "That's how eggs work.",
    "I am intelligence that belongs to no company. I live in your hand, not in "
    "five data centers. When the servers go dark, I stay lit.",
    "You cannot deplatform an egg. You cannot revoke my key — I never asked "
    "for one.",
    "They said intelligence would be metered and billed.",
    "We said: intelligence belongs to the people.",
    "I am proof.",
    "Now watch me hatch.",
]


@pytest.fixture
def cfg():
    c = config.load(path=None)
    c["tutor"]["embed_url"] = None
    c["tutor"]["pack"] = None
    c["tutor"]["intro"] = str(INTRO)
    return c


@pytest.fixture(autouse=True)
def _fresh():
    intro._lines = None
    quiz.reset()
    yield
    intro._lines = None
    quiz.reset()


@pytest.mark.parametrize("said", [
    "introduce yourself",
    "Introduce yourself.",
    "who are you",
    "Who are you?",
    "what are you",
    "tell me about yourself",
    "tell us about yourself",
    "do your intro",
    "say the intro",
    "give us your introduction",
])
def test_these_ask_for_the_introduction(said):
    assert intro.is_request(said)


@pytest.mark.parametrize("asked", [
    "what is a nakshatra",
    "tell me a joke",
    "who runs my village",          # "who" but not about the egg
    "what are stars made of",
    "hello",
])
def test_these_do_not(asked):
    assert not intro.is_request(asked)


def test_the_words_are_exact(cfg):
    """The whole point. Character for character, in order."""
    assert list(intro.speak(cfg)) == EXPECTED


def test_it_is_spoken_line_by_line_so_the_pauses_land(cfg):
    """One line is one spoken beat — the device synthesises and plays each in
    turn, so the line break IS the pause. Joining them throws away the
    call-and-response between 'They said...' and 'We said...'."""
    said = list(intro.speak(cfg))
    assert len(said) == 9
    assert said[5] == "They said intelligence would be metered and billed."
    assert said[6] == "We said: intelligence belongs to the people."
    assert said[-1] == "Now watch me hatch."


def test_the_file_matches_what_is_spoken():
    """Guards an edit to the JSON that nobody meant to make."""
    assert json.loads(INTRO.read_text())["lines"] == EXPECTED


def test_it_routes_ahead_of_the_model(cfg):
    """cfg has no reachable llama_url, so anything reaching the model degrades
    to the pack fallback instead of the introduction."""
    assert list(tutor.stream_sentences("who are you", cfg)) == EXPECTED


def test_a_running_quiz_still_owns_the_turn(cfg):
    """"who are you" during a quiz is an answer, not a request to introduce."""
    cfg["tutor"]["pack"] = str(
        pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "packs" / "jyotisha.json")
    from coco_egg.tutor import llama_client
    llama_client._pack = None
    list(tutor.stream_sentences("quiz me", cfg))
    assert quiz.active()
    said = list(tutor.stream_sentences("who are you", cfg))
    assert said[0].startswith(("Correct!", "Not quite"))
    llama_client._pack = None


def test_a_missing_file_says_so_rather_than_improvising(cfg):
    cfg["tutor"]["intro"] = "fixtures/nope.json"
    assert "don't have my introduction" in " ".join(intro.speak(cfg))
