"""Jokes, and the one property that matters at a party: it must not repeat.

Asked for a joke the 1.7B tells the same joke, every time. Authored jokes fix
the variety; a DECK rather than random choice fixes the repeats. With 44 jokes
and random.choice the chance of a repeat inside ten draws is about 68% — which
at a party reads as a broken device, not as chance.
"""
import json
import pathlib

import pytest

from coco_egg import config, tutor
from coco_egg.tutor import jokes
from coco_egg.tutor.deck import Deck

JOKES = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "jokes.json"


@pytest.fixture
def cfg(tmp_path):
    c = config.load(path=None)
    c["tutor"]["embed_url"] = None
    c["tutor"]["pack"] = None
    c["tutor"]["jokes"] = str(JOKES)
    c["tutor"]["jokes_deck"] = str(tmp_path / "deck.json")
    return c


@pytest.fixture(autouse=True)
def _fresh():
    jokes._jokes = None
    jokes._deck = None
    jokes.reset()
    yield
    jokes._jokes = None
    jokes._deck = None
    jokes.reset()


@pytest.mark.parametrize("said", [
    "tell me a joke",
    "do you know any jokes",
    "tell a joke",
    "joke",
    "jokes",
    "make me laugh",
    "say something funny",
    "got a joke for me",
    "tell me another joke",
    # ASR punctuates. These are transcripts, not typed input.
    "Another joke.",
    "Jokes!",
    "tell me a joke?",
])
def test_these_ask_for_a_joke(said):
    assert jokes.is_request(said)


@pytest.mark.parametrize("asked", [
    "what is a nakshatra",
    "why is the sky blue",
    "hello",
    "quiz me",
    "what is so funny about gravity",   # 'funny' but not a request
])
def test_these_do_not(asked):
    assert not jokes.is_request(asked)


def test_another_only_counts_after_a_joke(cfg):
    """"again" after a lesson means repeat the lesson, not tell a joke."""
    assert not jokes.is_request("another one")
    list(jokes.tell(cfg))
    assert jokes.is_request("another one")
    jokes.reset()
    assert not jokes.is_request("another one")


def test_setup_and_punchline_are_separate_sentences(cfg):
    """The split IS the comic pause — the device speaks one sentence at a time."""
    said = list(jokes.tell(cfg))
    assert len(said) == 2
    assert all(s.strip() for s in said)


def test_no_joke_repeats_until_every_joke_has_been_told(cfg):
    """The property this whole module exists for."""
    total = len(json.loads(JOKES.read_text())["jokes"])
    seen = [" ".join(jokes.tell(cfg)) for _ in range(total)]
    assert len(set(seen)) == total, "a joke came round before the deck was empty"


def test_the_deck_reshuffles_instead_of_running_dry(cfg):
    total = len(json.loads(JOKES.read_text())["jokes"])
    told = [" ".join(jokes.tell(cfg)) for _ in range(total * 2)]
    assert all(t.strip() for t in told)
    assert len(set(told)) == total       # two full passes, nothing missing


def test_a_reshuffle_does_not_repeat_back_to_back(cfg):
    """Back to back is the only repeat anyone actually notices."""
    total = len(json.loads(JOKES.read_text())["jokes"])
    told = [" ".join(jokes.tell(cfg)) for _ in range(total + 1)]
    assert told[total] != told[total - 1]


def test_the_deck_survives_a_restart(cfg):
    """`docker restart egg` mid-party must not deal the same opener again."""
    first = " ".join(jokes.tell(cfg))
    jokes._jokes = None                  # simulate a fresh process
    jokes._deck = None
    rest = [" ".join(jokes.tell(cfg)) for _ in range(6)]
    assert first not in rest


def test_editing_the_jokes_resets_the_deck(tmp_path, cfg):
    """Saved indices must not be dealt into a list that changed underneath."""
    d1 = Deck(5, "aaaa", str(tmp_path / "d.json"))
    d1.draw_many(4)
    d2 = Deck(9, "bbbb", str(tmp_path / "d.json"))
    assert d2.left == 9


def test_missing_jokes_file_says_so_rather_than_failing(cfg):
    cfg["tutor"]["jokes"] = "fixtures/nope.json"
    said = " ".join(jokes.tell(cfg))
    assert "don't have any jokes" in said


def test_a_joke_request_never_reaches_the_model(cfg):
    """No llama_url is set on cfg, so anything reaching the model would raise."""
    said = list(tutor.stream_sentences("tell me a joke", cfg))
    assert len(said) == 2


def test_every_joke_is_speakable(cfg):
    """Spoken aloud, so no visual gags and nothing that needs to be seen."""
    for joke in json.loads(JOKES.read_text())["jokes"]:
        for part in (joke["setup"], joke["punchline"]):
            assert part.strip() and part.strip()[-1] in ".?!", part
            assert len(part) < 160, part
