"""Streaming ASR unit tests.

whisper-server is stubbed here: the point is the client-side chunking,
backpressure and finalisation logic in asr/streaming.py, not the model. Only
the code path that would POST is replaced.
"""
import time

import numpy as np
import pytest

from coco_egg import config, events
from coco_egg.asr import streaming


@pytest.fixture(autouse=True)
def clean_bus():
    yield
    for fn in list(events._subscribers):
        events.unsubscribe(fn)


@pytest.fixture
def recorder() -> list:
    seen: list = []
    events.subscribe(seen.append)
    return seen


def _cfg(sr: int = 16000, min_voiced_s: float = 0.1,
         speculate_after_s: float = 0.2) -> dict:
    cfg = config.load(path=None)
    cfg["audio"]["sample_rate"] = sr
    cfg["asr"]["stream_min_voiced_s"] = min_voiced_s
    cfg["asr"]["stream_speculate_after_s"] = speculate_after_s
    cfg["asr"]["timeout_s"] = 5
    return cfg


def _install_fake_whisper(monkeypatch, delay: float = 0.0) -> list[int]:
    """Patch transcribe_np as imported by streaming.py; record call sizes."""
    calls: list[int] = []

    def fake(audio: np.ndarray, sr: int, cfg: dict) -> str:
        calls.append(int(audio.size))
        if delay:
            time.sleep(delay)
        return f"call-{len(calls)}"

    monkeypatch.setattr(streaming, "transcribe_np", fake)
    return calls


def _voice(sr: int) -> np.ndarray:
    """100 ms int16 chunk, RMS well above silence_rms=0.005."""
    return (np.ones(int(sr * 0.1), dtype=np.int16) * 3000)


def _silence(sr: int) -> np.ndarray:
    return np.zeros(int(sr * 0.1), dtype=np.int16)


def test_speculative_final_fires_after_trailing_silence_run(monkeypatch, recorder):
    cfg = _cfg()
    _install_fake_whisper(monkeypatch)
    txn = streaming.StreamingTranscriber(cfg)
    sr = cfg["audio"]["sample_rate"]

    for _ in range(15):
        txn.push(_voice(sr), is_silent=False)
    assert not txn.final_dispatched()

    # speculate_after_s = 0.2s => 2 silent blocks trip it
    for _ in range(3):
        txn.push(_silence(sr), is_silent=True)

    assert txn.final_dispatched()
    assert txn.result(timeout_s=2.0).startswith("call-")


def test_partials_emit_during_speech(monkeypatch, recorder):
    cfg = _cfg()
    _install_fake_whisper(monkeypatch, delay=0.02)
    txn = streaming.StreamingTranscriber(cfg)
    sr = cfg["audio"]["sample_rate"]

    for _ in range(20):
        txn.push(_voice(sr), is_silent=False)
        time.sleep(0.03)
    for _ in range(3):
        txn.push(_silence(sr), is_silent=True)
    txn.result(timeout_s=2.0)

    partials = [e for e in recorder if e["kind"] == "partial_heard"]
    assert partials, "expected ≥1 partial_heard emitted during speech"


def test_flush_dispatches_final_when_recording_never_went_silent(monkeypatch):
    """Max-utterance case: recording capped out before any long silence."""
    cfg = _cfg()
    _install_fake_whisper(monkeypatch)
    txn = streaming.StreamingTranscriber(cfg)
    sr = cfg["audio"]["sample_rate"]

    for _ in range(10):
        txn.push(_voice(sr), is_silent=False)
    assert not txn.final_dispatched()

    txn.flush()
    assert txn.final_dispatched()
    assert txn.result(timeout_s=2.0)


def test_backpressure_drops_partials_rather_than_queueing(monkeypatch):
    """A slow whisper must not cause partials to pile up behind each other —
    whisper serialises, so queueing would just add latency for nothing."""
    cfg = _cfg(min_voiced_s=0.05)
    calls = _install_fake_whisper(monkeypatch, delay=1.0)
    txn = streaming.StreamingTranscriber(cfg)
    sr = cfg["audio"]["sample_rate"]

    for _ in range(5):
        txn.push(_voice(sr), is_silent=False)
        time.sleep(0.01)
    for _ in range(3):
        txn.push(_silence(sr), is_silent=True)
    txn.result(timeout_s=5.0)

    # Exactly one partial (first push) + one final. Everything else dropped.
    assert len(calls) == 2


def test_no_partials_before_min_voiced_threshold(monkeypatch, recorder):
    cfg = _cfg(min_voiced_s=1.0)   # would need 10 voiced blocks; we push 5
    _install_fake_whisper(monkeypatch, delay=0.02)
    txn = streaming.StreamingTranscriber(cfg)
    sr = cfg["audio"]["sample_rate"]

    for _ in range(5):
        txn.push(_voice(sr), is_silent=False)
    for _ in range(3):
        txn.push(_silence(sr), is_silent=True)
    # min_voiced not met, so no speculate_final either — flush() is the fallback
    assert not txn.final_dispatched()
    txn.flush()
    txn.result(timeout_s=2.0)

    assert not [e for e in recorder if e["kind"] == "partial_heard"]


def test_result_raises_on_transcribe_error(monkeypatch):
    cfg = _cfg()

    def boom(*_args, **_kwargs):
        raise RuntimeError("whisper is down")

    monkeypatch.setattr(streaming, "transcribe_np", boom)
    txn = streaming.StreamingTranscriber(cfg)
    sr = cfg["audio"]["sample_rate"]
    for _ in range(10):
        txn.push(_voice(sr), is_silent=False)
    txn.flush()

    with pytest.raises(RuntimeError, match="whisper is down"):
        txn.result(timeout_s=2.0)
