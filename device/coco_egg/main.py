"""coco-egg zero — the local voice loop (M0).

Pipeline (spec §5): trigger -> record -> local ASR -> local tutor -> local TTS -> play.
Fully offline. Cloud does not exist in this file; it arrives at M2 as an
optional route inside answer(), never as a dependency.

Bench trigger: press Enter to talk (keyboard mode). GPIO mode lands at M1.
"""
from __future__ import annotations

import sys
import time

from . import config
from .asr import transcribe
from .audio import play_wav, record_utterance
from .audio.io import write_wav
from .states import UiState
from .sync import log_interaction
from .tts import synthesize
from .tutor import answer


def set_ui(state: UiState) -> None:
    # M1: drive the LED ring here (XVF3800 GPO / Pi GPIO). Bench: print.
    print(f"[{state.name}]", flush=True)


def one_turn(cfg: dict) -> None:
    set_ui(UiState.LISTENING)
    audio = record_utterance(cfg)
    if audio.size == 0:
        set_ui(UiState.IDLE)
        return
    t0 = time.monotonic()
    set_ui(UiState.THINKING)
    wav = write_wav(audio, cfg["audio"]["sample_rate"])
    question = transcribe(wav, cfg)
    if not question:
        set_ui(UiState.IDLE)
        return
    print(f"  heard: {question}")
    reply = answer(question, cfg)
    print(f"  reply: {reply}")
    speech = synthesize(reply, cfg)
    latency = time.monotonic() - t0
    print(f"  latency (end-of-speech -> first-audio): {latency:.2f}s")
    set_ui(UiState.SPEAKING)
    play_wav(speech, cfg)
    log_interaction(question, reply, latency, cfg)
    set_ui(UiState.IDLE)


def run() -> None:
    cfg = config.load()
    print("coco-egg zero — local voice loop. Ctrl-C to exit.")
    if cfg["trigger"]["mode"] == "keyboard":
        while True:
            input("Press Enter, then speak...")
            try:
                one_turn(cfg)
            except Exception as e:  # keep the loop alive on the bench
                set_ui(UiState.ERROR)
                print(f"  error: {e}", file=sys.stderr)
    else:
        raise NotImplementedError("gpio trigger arrives at M1")


if __name__ == "__main__":
    run()
