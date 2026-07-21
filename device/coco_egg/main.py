"""coco-egg zero — the local voice loop (M0).

Pipeline (spec §5): trigger -> record -> local ASR -> local tutor -> local TTS -> play.
Fully offline. Cloud does not exist in this file; it arrives at M2 as an
optional route inside stream_sentences(), never as a dependency.

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
from .tutor import stream_sentences


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
    # Stream the reply sentence-by-sentence: speak each one as it lands, so
    # first audio never waits for the full generation (spec §7).
    first_audio = 0.0
    spoken: list[str] = []
    for sentence in stream_sentences(question, cfg):
        speech = synthesize(sentence, cfg)
        if not spoken:
            first_audio = time.monotonic() - t0
            print(f"  latency (end-of-speech -> first-audio): {first_audio:.2f}s")
        spoken.append(sentence)
        set_ui(UiState.SPEAKING)
        play_wav(speech, cfg)
    reply = " ".join(spoken)
    print(f"  reply: {reply}")
    if reply:
        log_interaction(question, reply, first_audio, cfg)
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
