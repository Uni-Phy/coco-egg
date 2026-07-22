import pathlib

import pytest

from coco_egg import config
from coco_egg.tutor import llama_client
from coco_egg.tutor.pack import Pack

PACK_PATH = pathlib.Path(__file__).parents[2] / "fixtures" / "content-pack.json"


@pytest.fixture
def pack():
    return Pack.load(PACK_PATH)


def test_retrieve_ranks_relevant_chunk_first(pack):
    hits = pack.retrieve("how do plants make their food")
    assert hits and hits[0]["id"] in ("photosynthesis", "plants-soil")


def test_retrieve_off_topic_returns_nothing(pack):
    assert pack.retrieve("zzz qqq xyzzy") == []


def test_retrieve_handles_soil_misconception(pack):
    hits = pack.retrieve("why does the plant not just eat the soil")
    assert hits[0]["id"] == "plants-soil"


def test_fallback_speaks_canned_explanation(pack, monkeypatch):
    """LLM unreachable -> the pack's pre-written explanation, sentence-split."""
    cfg = config.load(path=None)
    cfg["tutor"]["llama_url"] = "http://127.0.0.1:9"  # closed port
    cfg["tutor"]["pack"] = str(PACK_PATH)
    monkeypatch.setattr(llama_client, "_pack", None)
    sentences = list(llama_client.stream_sentences("what is photosynthesis", cfg))
    assert len(sentences) >= 2
    assert "photosynthesis" in " ".join(sentences).lower()


def test_fallback_unknown_when_no_match(pack, monkeypatch):
    cfg = config.load(path=None)
    cfg["tutor"]["llama_url"] = "http://127.0.0.1:9"
    cfg["tutor"]["pack"] = str(PACK_PATH)
    monkeypatch.setattr(llama_client, "_pack", None)
    sentences = list(llama_client.stream_sentences("qqq zzz xyzzy", cfg))
    assert "don't know" in " ".join(sentences)
