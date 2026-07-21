from coco_egg import config
from coco_egg.states import EggState, UiState
from coco_egg.tutor.llama_client import split_ready_sentences, visible_text


def test_defaults_load():
    cfg = config.load(path=None)
    assert cfg["audio"]["sample_rate"] == 16000
    assert cfg["tutor"]["llama_url"].startswith("http://127.0.0.1")


def test_states_exist():
    assert EggState.LOCAL and EggState.SYNC and EggState.CLOUD_ENHANCED
    assert UiState.LISTENING and UiState.SPEAKING


def test_split_ready_sentences():
    done, rest = split_ready_sentences("One. Two! Is three?  And a trailing bit")
    assert done == ["One.", "Two!", "Is three?"]
    assert rest == "And a trailing bit"
    done, rest = split_ready_sentences("no boundary yet")
    assert done == [] and rest == "no boundary yet"


def test_visible_text_strips_think():
    assert visible_text("<think>hmm</think>Answer.") == "Answer."
    # an unclosed think block is held back entirely until it closes
    assert visible_text("Sure. <think>still reason") == "Sure. "
    assert visible_text("plain text") == "plain text"
