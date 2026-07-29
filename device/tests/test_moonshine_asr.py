"""Moonshine backend contract tests.

moonshine-voice itself is stubbed — the point is the push/flush/result shape
matching the whisper backend, and the collector's text extraction, not the
model. If a caller can't tell whisper and moonshine apart, that is the goal.
"""
import numpy as np
import pytest

from coco_egg import config, events
from coco_egg.asr import moonshine_local


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


class FakeTranscriber:
    """Records calls in the order moonshine-voice would receive them."""

    def __init__(self, lines_per_stop: list[str] | None = None):
        self.calls: list = []
        self.listener = None
        self._lines_per_stop = lines_per_stop or ["hello world"]

    def remove_all_listeners(self) -> None:
        self.calls.append(("remove_all_listeners",))
        self.listener = None

    def add_listener(self, listener) -> None:
        self.calls.append(("add_listener",))
        self.listener = listener

    def start(self) -> None:
        self.calls.append(("start",))

    def add_audio(self, audio, sr) -> None:
        self.calls.append(("add_audio", audio.size, sr))

    def stop(self) -> None:
        self.calls.append(("stop",))
        for text in self._lines_per_stop:
            self.listener.on_line_completed(_Event(text))


class _Line:
    def __init__(self, text: str):
        self.text = text


class _Event:
    """Moonshine passes an event whose .line.text carries the transcript."""

    def __init__(self, text: str):
        self.line = _Line(text)


def _cfg() -> dict:
    cfg = config.load(path=None)
    cfg["audio"]["sample_rate"] = 16000
    cfg["asr"]["backend"] = "moonshine"
    return cfg


def _install_fake(monkeypatch, lines_per_stop: list[str] | None = None) -> FakeTranscriber:
    fake = FakeTranscriber(lines_per_stop)
    monkeypatch.setattr(moonshine_local, "_get_transcriber", lambda: fake)
    return fake


def _voice(sr: int) -> np.ndarray:
    return (np.ones(int(sr * 0.1), dtype=np.int16) * 3000)


def test_stream_lifecycle_matches_whisper_contract(monkeypatch):
    """__init__ opens a session; push feeds audio; result finalises once."""
    fake = _install_fake(monkeypatch, lines_per_stop=["what is a fraction"])
    txn = moonshine_local.StreamingTranscriber(_cfg())
    sr = 16000

    for _ in range(3):
        txn.push(_voice(sr), is_silent=False)
    assert not txn.final_dispatched()

    assert txn.result(timeout_s=2.0) == "what is a fraction"
    assert txn.final_dispatched()

    kinds = [c[0] for c in fake.calls]
    assert kinds == ["remove_all_listeners", "add_listener", "start",
                     "add_audio", "add_audio", "add_audio", "stop"]


def test_flush_finalises_without_result(monkeypatch):
    """Mirrors the max-utterance path in the whisper streaming tests."""
    fake = _install_fake(monkeypatch)
    txn = moonshine_local.StreamingTranscriber(_cfg())
    txn.push(_voice(16000), is_silent=False)
    txn.flush()

    assert txn.final_dispatched()
    assert ("stop",) in fake.calls
    # calling result() after flush must not call stop() a second time.
    txn.result(timeout_s=2.0)
    assert [c for c in fake.calls if c == ("stop",)] == [("stop",)]


def test_partials_emit_on_line_text_changed(monkeypatch, recorder):
    fake = _install_fake(monkeypatch)
    txn = moonshine_local.StreamingTranscriber(_cfg())
    # Simulate the model emitting a mid-line update during push.
    fake.listener.on_line_text_changed(_Event("what is"))
    fake.listener.on_line_text_changed(_Event("what is a fraction"))
    txn.result(timeout_s=2.0)

    partials = [e["text"] for e in recorder if e["kind"] == "partial_heard"]
    assert partials == ["what is", "what is a fraction"]


def test_transcribe_batch_runs_full_pipeline(monkeypatch, tmp_path):
    """The batch entry uses the same streaming path — verifies WAV -> text."""
    fake = _install_fake(monkeypatch, lines_per_stop=["hello"])

    import wave
    wav = tmp_path / "sample.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(_voice(16000).tobytes())

    assert moonshine_local.transcribe(str(wav), _cfg()) == "hello"
    assert ("start",) in fake.calls and ("stop",) in fake.calls
