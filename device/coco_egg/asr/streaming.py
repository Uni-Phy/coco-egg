"""Client-side streaming ASR over whisper-server /inference (batch, HTTP).

Two overlaps buy latency here (README §16, task C2):

1. Partial transcripts POSTed *during* speech. Whisper serialises requests,
   so if a POST is still in flight the next candidate is dropped rather than
   queued — otherwise partials would pile up behind the encoder.
2. The final POST fires after `stream_speculate_after_s` of trailing silence,
   not after the full `silence_stop_s` hangover. The 1.44 s encoder now
   overlaps with the ~1.2 s hangover instead of chaining after it.

Known MVP limitation: if the learner pauses mid-sentence past
`stream_speculate_after_s` and then resumes, the earlier speculative POST
returns a truncated transcript that we cannot cancel. `silence_stop_s` at
1.2 s makes this rare in practice; a resume-aware re-dispatch is future work.
"""
from __future__ import annotations

import threading

import numpy as np

from .. import events
from .whisper_local import transcribe_np


class StreamingTranscriber:
    """One instance per turn. `push()` on every mic block; `result()` at end."""

    def __init__(self, cfg: dict):
        self._cfg = cfg
        self._sr = cfg["audio"]["sample_rate"]
        self._min_voiced_samples = int(cfg["asr"]["stream_min_voiced_s"] * self._sr)
        self._speculate_after_blocks = max(
            1, int(cfg["asr"]["stream_speculate_after_s"] / 0.1)
        )

        self._chunks: list[np.ndarray] = []
        self._voiced_samples = 0
        self._silent_run = 0

        self._slot = threading.Lock()   # partials never queue behind partials
        self._final_dispatched = False
        self._final_ready = threading.Event()
        self._final_result = ""
        self._final_error: Exception | None = None

    def push(self, chunk: np.ndarray, is_silent: bool) -> None:
        if chunk.size:
            self._chunks.append(chunk)
            if is_silent:
                self._silent_run += 1
            else:
                self._silent_run = 0
                self._voiced_samples += chunk.size

        if self._final_dispatched:
            return

        if (self._silent_run >= self._speculate_after_blocks
                and self._voiced_samples >= self._min_voiced_samples):
            self._dispatch_final()
            return

        if is_silent or self._voiced_samples < self._min_voiced_samples:
            return
        if not self._slot.acquire(blocking=False):
            return
        threading.Thread(
            target=self._partial, args=(self._snapshot(),), daemon=True
        ).start()

    def flush(self) -> None:
        """Fallback for the max-utterance case: no long silence ever fired the
        speculative final, so dispatch it now from the caller's thread."""
        if not self._final_dispatched:
            self._dispatch_final()

    def final_dispatched(self) -> bool:
        return self._final_dispatched

    def result(self, timeout_s: float) -> str:
        if not self._final_ready.wait(timeout=timeout_s):
            raise TimeoutError("streaming ASR did not complete in time")
        if self._final_error is not None:
            raise self._final_error
        return self._final_result

    def _snapshot(self) -> np.ndarray:
        return np.concatenate(self._chunks) if self._chunks else np.zeros(0, dtype=np.int16)

    def _dispatch_final(self) -> None:
        self._final_dispatched = True
        threading.Thread(
            target=self._final, args=(self._snapshot(),), daemon=True
        ).start()

    def _partial(self, audio: np.ndarray) -> None:
        try:
            text = transcribe_np(audio, self._sr, self._cfg)
            if text:
                events.emit("partial_heard", text=text)
        except Exception as e:
            print(f"  whisper (partial): {e.__class__.__name__}: {e}", flush=True)
        finally:
            self._slot.release()

    def _final(self, audio: np.ndarray) -> None:
        try:
            # Wait behind any in-flight partial: whisper serialises anyway.
            with self._slot:
                self._final_result = transcribe_np(audio, self._sr, self._cfg)
        except Exception as e:
            self._final_error = e
        finally:
            self._final_ready.set()
