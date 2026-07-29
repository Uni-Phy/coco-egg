"""Quiz mode: the device asks, and marks, without a model in the loop."""
import json
import pathlib

import pytest

from coco_egg import config, tutor
from coco_egg.tutor import llama_client, quiz

PACKS = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "packs"


@pytest.fixture
def cfg():
    c = config.load(path=None)
    c["tutor"]["embed_url"] = None
    c["tutor"]["pack"] = str(PACKS / "jyotisha.json")
    c["tutor"]["quiz_questions"] = 3
    return c


@pytest.fixture(autouse=True)
def _clean():
    llama_client._pack = None      # the pack is cached per process
    quiz.reset()
    yield
    llama_client._pack = None
    quiz.reset()


def play(text, cfg):
    return list(tutor.stream_sentences(text, cfg))


@pytest.mark.parametrize("said", [
    "quiz me",
    "quiz me on jyotisha",
    # What whisper ACTUALLY returns for these, measured with tools/asr_ab.py.
    # The trigger has to survive the ASR, not assume it: spoken "quiz me" comes
    # back as one word, and that is the commonest way to start a quiz.
    "Quizmy",
    "Quizmy on Jaya Tisha",
    "quizme",
    "test me",
    "let's play a quiz",
    "start a quiz",
    "ask me some questions",
    "quiz",
])
def test_these_start_a_game(said):
    assert quiz.is_start(said)


@pytest.mark.parametrize("asked", [
    "what is a nakshatra",
    "tell me about the quizmaster of india",   # 'quiz' as a word, not a request
    "hello",
    "what is a fraction",
])
def test_these_do_not(asked):
    assert not quiz.is_start(asked)


def test_a_quiz_request_beats_the_opener_rule():
    """"let's play a quiz" is textbook is_opener(); the quiz must win."""
    assert llama_client.is_opener("let's play a quiz")
    assert quiz.is_start("let's play a quiz")


def test_starting_asks_the_first_question(cfg):
    said = " ".join(play("quiz me", cfg))
    assert "3 questions" in said
    assert "Question 1." in said
    assert quiz.active()


def test_a_right_answer_scores_and_moves_on(cfg):
    play("quiz me", cfg)
    item = quiz._game.current
    said = " ".join(play(item["accept"][0], cfg))
    assert said.startswith("Correct!")
    assert "Question 2." in said


def test_a_wrong_answer_still_teaches_the_answer(cfg):
    """Being marked wrong must never leave the learner without the answer."""
    play("quiz me", cfg)
    item = quiz._game.current
    said = " ".join(play("a banana", cfg))
    assert "Not quite" in said
    assert item["a"] in said


def test_the_game_ends_and_reports_a_score(cfg):
    play("quiz me", cfg)
    for _ in range(3):
        play("a banana", cfg)
    assert not quiz.active()


def test_a_perfect_round_is_recognised(cfg):
    play("quiz me", cfg)
    last = ""
    for _ in range(3):
        last = " ".join(play(quiz._game.current["accept"][0], cfg))
    assert "all 3 right" in last
    assert not quiz.active()


def test_stopping_early_ends_the_game(cfg):
    play("quiz me", cfg)
    said = " ".join(play("stop", cfg))
    assert "end" in said.lower()
    assert not quiz.active()


def test_i_dont_know_is_not_marked_wrong_rudely(cfg):
    play("quiz me", cfg)
    item = quiz._game.current
    said = " ".join(play("i don't know", cfg))
    assert "No problem" in said
    assert item["a"] in said


def test_repeat_asks_the_same_question_again(cfg):
    play("quiz me", cfg)
    first = " ".join(play("say that again", cfg))
    assert "Question 1." in first
    assert quiz._game.at == 0


def test_answers_are_not_sent_to_retrieval(cfg):
    """While a game runs, "twenty seven" is an answer, not a question."""
    play("quiz me", cfg)
    assert quiz.active()
    said = " ".join(play("twenty seven", cfg))
    assert said.startswith(("Correct!", "Not quite"))


def test_judging_is_forgiving_about_how_it_was_said(cfg):
    item = {"a": "Twenty seven.", "accept": ["twenty seven", "27"]}
    assert quiz.judge("twenty seven", item)
    assert quiz.judge("um, twenty seven I think", item)
    assert quiz.judge("Twenty Seven!", item)
    assert quiz.judge("is it 27", item)
    assert not quiz.judge("twelve", item)
    assert not quiz.judge("", item)


def test_a_pack_with_no_quiz_says_so_instead_of_inventing(cfg):
    cfg["tutor"]["pack"] = str(PACKS / "the-farm.json")
    said = " ".join(play("quiz me", cfg))
    assert "don't have any quiz questions" in said
    assert not quiz.active()


def test_forget_clears_a_half_played_game(cfg):
    play("quiz me", cfg)
    assert quiz.active()
    tutor.forget()
    assert not quiz.active()


def test_every_quiz_item_is_answerable_by_its_own_accept_list():
    """The authored data has to satisfy the judge it will be judged by.

    An accept-list that does not match its own stated answer marks a correct
    learner wrong, and there is no way to notice that by reading the JSON.
    """
    for path in sorted(PACKS.glob("*.json")):
        for item in json.loads(path.read_text()).get("quiz", []):
            assert item.get("accept"), f"{path.name}: {item['q']} has no accept list"
            assert quiz.judge(item["a"], item), (
                f"{path.name}: stated answer {item['a']!r} fails its own "
                f"accept list {item['accept']}")
