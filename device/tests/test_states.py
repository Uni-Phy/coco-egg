from coco_egg import config
from coco_egg.states import EggState, UiState


def test_defaults_load():
    cfg = config.load(path=None)
    assert cfg["audio"]["sample_rate"] == 16000
    assert cfg["tutor"]["ollama_url"].startswith("http://127.0.0.1")


def test_states_exist():
    assert EggState.LOCAL and EggState.SYNC and EggState.CLOUD_ENHANCED
    assert UiState.LISTENING and UiState.SPEAKING
