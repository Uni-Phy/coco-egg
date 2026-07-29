"""Local ASR via moonshine-voice — in-process, per-chunk streaming.

Same public shape as whisper_local + streaming: `transcribe(wav_path, cfg)`
and `StreamingTranscriber(cfg)` with push/flush/result/final_dispatched. The
difference is where the work happens.

Whisper backend POSTs a full WAV to whisper-server after silence is detected,
so the encoder runs AFTER end-of-speech. Moonshine feeds every mic block into
`Transcriber.add_audio()` as it arrives; by the time the learner stops
talking, the encoder has already caught up and only the decoder tail remains.

Model download on first `Transcriber()` construction is auto (cached under
the moonshine-voice default cache dir). Pre-fetching for reproducible builds
is a later concern; the bench evaluation just needs first-run to work.
"""
from __future__ import annotations

import threading
import wave

import numpy as np

from moonshine_voice import TranscriptEventListener

from .. import events

# Module-level singleton — the model is expensive to load and hot after the
# first turn. Same pattern as tts/piper_local.py and tutor/llama_client._pack.
_transcriber = None
_transcriber_lock = threading.Lock()


def _get_transcriber(cfg: dict):
    global _transcriber
    with _transcriber_lock:
        if _transcriber is None:
            # Lazy import: onnxruntime is heavy, and if backend != moonshine
            # nothing here should pay for it.
            from moonshine_voice import Transcriber, get_model_for_language
            model_path, model_arch = get_model_for_language(cfg["asr"]["language"])
            _transcriber = Transcriber(model_path=model_path, model_arch=model_arch)
    return _transcriber


def _to_float32(audio_int16: np.ndarray) -> np.ndarray:
    return audio_int16.astype(np.float32) / 32768.0


class _Collector(TranscriptEventListener):
    """Listener that captures completed lines and emits partials.

    Inherits TranscriptEventListener so moonshine can call() the object; a
    plain class with only on_line_* methods raises "object is not callable".
    """

    def __init__(self, on_partial=None):
        super().__init__()
        self._lines: list[str] = []
        self._on_partial = on_partial

    def on_line_completed(self, event) -> None:
        text = event.line.text.strip()
        if text:
            self._lines.append(text)

    def on_line_text_changed(self, event) -> None:
        if self._on_partial is None:
            return
        text = event.line.text.strip()
        if text:
            self._on_partial(text)

    def full_text(self) -> str:
        return " ".join(self._lines).strip()


def preload(cfg: dict) -> None:
    """Force model download + init at startup, not during the first turn.

    Sibling of tts.preload(): moonshine's Transcriber pays a 5-10s download
    the very first run and ~2s of model init on every start. Without this the
    first learner would hear silence while the model streams off the network.
    """
    _get_transcriber(cfg)


def transcribe(wav_path: str, cfg: dict) -> str:
    """Batch entry: read a WAV and run it through the streaming pipeline."""
    with wave.open(wav_path, "rb") as w:
        sr = w.getframerate()
        audio_int16 = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return _run(_to_float32(audio_int16), sr, cfg)


def _begin_session(t, collector) -> None:
    """Attach the collector and start a fresh session.

    Defensively stops any prior session first — main.one_turn() early-returns
    on empty audio without calling flush(), which leaves the singleton in a
    "started" state that a naive start() would double-open.
    """
    try:
        t.stop()
    except Exception:
        pass  # not previously started; the following start() is authoritative
    t.remove_all_listeners()
    t.add_listener(collector)
    t.start()


def _run(audio_f32: np.ndarray, sr: int, cfg: dict) -> str:
    t = _get_transcriber(cfg)
    collector = _Collector()
    _begin_session(t, collector)
    # 100 ms chunks mirror the streaming example in moonshine's README and
    # match the block size the mic path uses in production.
    chunk = int(0.1 * sr)
    for i in range(0, len(audio_f32), chunk):
        t.add_audio(audio_f32[i:i + chunk], sr)
    t.stop()
    return collector.full_text()


class StreamingTranscriber:
    """Whisper-shaped facade over the moonshine Transcriber.

    push/flush/result/final_dispatched match asr/streaming.StreamingTranscriber
    so main.one_turn() and its tests don't care which backend runs. Internally
    there is no HTTP, no threading, no speculative dispatch — audio is fed to
    the model as it arrives and stop() finalises the transcript.
    """

    def __init__(self, cfg: dict):
        self._sr = cfg["audio"]["sample_rate"]
        self._transcriber = _get_transcriber(cfg)
        self._collector = _Collector(on_partial=self._emit_partial)
        _begin_session(self._transcriber, self._collector)
        self._stopped = False

    def push(self, chunk: np.ndarray, is_silent: bool) -> None:
        if chunk.size:
            self._transcriber.add_audio(_to_float32(chunk), self._sr)

    def flush(self) -> None:
        self._finalize()

    def final_dispatched(self) -> bool:
        return self._stopped

    def result(self, timeout_s: float) -> str:
        # Kept in the signature for API parity with the whisper backend, where
        # stop() dispatches an HTTP POST that has to be awaited. Moonshine
        # finalises synchronously.
        self._finalize()
        return self._collector.full_text()

    def _finalize(self) -> None:
        if not self._stopped:
            self._transcriber.stop()
            self._stopped = True

    @staticmethod
    def _emit_partial(text: str) -> None:
        events.emit("partial_heard", text=text)
