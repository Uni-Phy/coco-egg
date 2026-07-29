"""Recording stops for two different reasons, and they are not the same reason.

silence_stop_s ends an utterance that HAS started. no_speech_s gives up on one
that never did. Conflating them is why pressing the button and saying nothing
held the room for 30 seconds: measured on the device as a hangover of 30.048s,
which in front of an audience looks like a hang rather than a miss.
"""
import numpy as np
import pytest

from coco_egg import config
from coco_egg.audio import io


class FakeStream:
    """A microphone that plays back a scripted sequence of blocks."""

    def __init__(self, blocks):
        self._blocks = list(blocks)
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n):
        self.reads += 1
        if self._blocks:
            data = self._blocks.pop(0)
        else:
            data = np.zeros(n, dtype=np.int16)     # silence forever after
        return data.reshape(-1, 1), False


def silence(n):
    return np.zeros(n, dtype=np.int16)


def voice(n):
    return (np.ones(n, dtype=np.int16) * 3000)


@pytest.fixture
def cfg():
    c = config.load(path=None)
    c["audio"]["max_utterance_s"] = 30
    c["audio"]["silence_stop_s"] = 1.1
    c["audio"]["no_speech_s"] = 4.0
    return c


@pytest.fixture
def mic(monkeypatch):
    """Install a scripted microphone. Returns a setter for its blocks."""
    holder = {}

    def install(blocks):
        stream = FakeStream(blocks)
        holder["stream"] = stream
        monkeypatch.setattr(io.sd, "InputStream",
                            lambda **kw: stream)
        monkeypatch.setattr(io, "resolve_input", lambda cfg: None)
        return stream

    return install


def test_silence_only_gives_up_after_no_speech_s(cfg, mic):
    """4s at 100ms blocks is 40 reads, not the 300 that max_utterance_s allows."""
    stream = mic([])                        # nothing but silence
    audio, _ = io.record_utterance(cfg)
    assert audio.size == 0
    assert stream.reads == 40


def test_it_does_not_give_up_once_someone_is_talking(cfg, mic):
    """The whole point of the distinction: speech resets the question."""
    block = int(cfg["audio"]["sample_rate"] * 0.1)
    # 6s of silence would trip a naive timer, but speech starts at 3s.
    blocks = [silence(block)] * 30 + [voice(block)] * 20 + [silence(block)] * 20
    stream = mic(blocks)
    audio, _ = io.record_utterance(cfg)
    assert audio.size > 0
    # Ran past the 40-block give-up point because speech arrived first.
    assert stream.reads > 40


def test_speech_then_silence_still_stops_on_silence_stop_s(cfg, mic):
    """The original behaviour has to survive the new one."""
    block = int(cfg["audio"]["sample_rate"] * 0.1)
    blocks = [voice(block)] * 10 + [silence(block)] * 40
    stream = mic(blocks)
    audio, _ = io.record_utterance(cfg)
    assert audio.size > 0
    # 10 voiced + 11 silent (1.1s) = 21 reads, nowhere near max_utterance_s.
    assert stream.reads == 21


def test_zero_disables_the_give_up(cfg, mic):
    """Restores the pre-v0.6 behaviour for anyone who wants it."""
    cfg["audio"]["no_speech_s"] = 0
    cfg["audio"]["max_utterance_s"] = 5      # keep the test quick
    stream = mic([])
    audio, _ = io.record_utterance(cfg)
    assert stream.reads == 50                # ran the full max_utterance_s
    # The OLD path returns the recorded silence rather than nothing, which is
    # then handed to ASR and comes back empty. That round trip cost ~1.8s for a
    # guaranteed empty result; giving up early skips it entirely.
    assert audio.size == 50 * int(cfg["audio"]["sample_rate"] * 0.1)


def test_the_streaming_transcriber_still_sees_every_block(cfg, mic):
    """Giving up must not swallow blocks the ASR path was promised."""
    mic([])
    seen = []
    io.record_utterance(cfg, on_block=lambda chunk, is_silent: seen.append(is_silent))
    assert len(seen) == 40
    assert all(seen)                         # all silent, which is why it gave up
