"""coco-egg zero — the local voice loop (M0).

Pipeline (spec §5): trigger -> record -> local ASR -> local tutor -> local TTS -> play.
Fully offline. Cloud does not exist in this file; it arrives at M2 as an
optional route inside stream_sentences(), never as a dependency.

Bench trigger: press Enter to talk (keyboard mode). w/q/r keys let you skip
upstream stages so the pipeline can be exercised without a mic. GPIO mode
lands at M1.
"""
from __future__ import annotations

import pathlib
import sys
import termios
import threading
import time
import tty
import wave

from . import config, console, events, trigger
from .audio import play_wav, record_utterance
from .states import UiState
from .sync import transcript
from .tutor import profile_builder
from .asr import StreamingTranscriber, transcribe, preload as preload_asr
from .tts import synthesize, preload as preload_tts
from .tutor import remember, stream_sentences, warm


CONSOLE_ONLY_MENU = (
    "No TTY. Press SPACE in the console to speak.\n"
    "[Ctrl-C] exit"
)

MENU = (
    "[Enter] speak: mic -> ASR -> LLM -> TTS  (or SPACE in the console)\n"
    "[w]     wav:   sample WAV -> ASR -> LLM -> TTS\n"
    "[q]     text:  sample question -> LLM -> TTS\n"
    "[r]     reply: sample reply -> TTS\n"
    "[Space] toggle output: audio device / file\n"
    "[Ctrl-C] exit"
)


def set_ui(state: UiState) -> None:
    # M1: drive the LED ring here (XVF3800 GPO / Pi GPIO). Bench: print.
    events.emit("state", state=state.name)
    print(f"[{state.name}]", flush=True)


def _nudge(cfg: dict, reason: str) -> None:
    """Nothing came through — say so, so the learner isn't left in dead air."""
    events.end_turn(reason=reason)
    set_ui(UiState.SPEAKING)
    play_wav(synthesize("Sorry, I didn't catch that. Try again.", cfg), cfg)
    set_ui(UiState.IDLE)


def one_turn(cfg: dict) -> None:
    events.begin_turn()
    set_ui(UiState.LISTENING)
    # Streaming ASR: partials POST during speech, and the final POST fires at
    # first silence — its encoder runs in parallel with the hangover instead
    # of chaining after it (asr/streaming.py).
    txn = StreamingTranscriber(cfg)
    # t0 is end-of-speech, not "recorder returned": the learner sits through
    # the trailing-silence hangover too, so it counts as latency.
    audio, t0 = record_utterance(cfg, on_block=txn.push)
    if audio.size == 0:
        _nudge(cfg, "no-audio")
        return
    set_ui(UiState.THINKING)
    # The hangover is dead air the learner waits through before any work
    # starts — 1.2s of the ~5s (README). It is a stage like the others.
    events.emit("stage", stage="hangover", seconds=round(time.monotonic() - t0, 3))
    txn.flush()   # no-op unless recording ended without a trailing-silence run
    t_asr = time.monotonic()
    question = txn.result(timeout_s=cfg["asr"]["timeout_s"])
    events.emit("stage", stage="asr", seconds=round(time.monotonic() - t_asr, 3))
    events.emit("heard", text=question)
    if not question:
        _nudge(cfg, "no-speech")
        return
    print(f"  heard: {question}")
    # Stream the reply sentence-by-sentence: speak each one as it lands, so
    # first audio never waits for the full generation (spec §7).
    first_audio = 0.0
    spoken: list[str] = []
    for sentence in stream_sentences(question, cfg):
        t_tts = time.monotonic()
        speech = synthesize(sentence, cfg)
        if not spoken:
            first_audio = time.monotonic() - t0
            events.emit("stage", stage="tts", seconds=round(time.monotonic() - t_tts, 3))
            events.emit("stage", stage="first_audio", seconds=round(first_audio, 3))
            print(f"  latency (end-of-speech -> first-audio): {first_audio:.2f}s")
        spoken.append(sentence)
        set_ui(UiState.SPEAKING)
        play_wav(speech, cfg)
        events.emit("spoken", index=len(spoken) - 1, text=sentence)
    reply = " ".join(spoken)
    print(f"  reply: {reply}")
    if reply:
        remember(question, reply, cfg)   # so the next turn can refer back
    events.end_turn(reason="ok", reply=reply, latency_s=round(first_audio, 3))
    set_ui(UiState.IDLE)


def _read_text(path: str) -> str:
    return pathlib.Path(path).read_text().strip()


def _concat_wav(inputs: list[str], out_path: str) -> None:
    # Sentence WAVs come from piper with identical params, so a straight
    # frame concat is enough. No resampling.
    with wave.open(inputs[0], "rb") as first:
        params = first.getparams()
    with wave.open(out_path, "wb") as out:
        out.setparams(params)
        for src in inputs:
            with wave.open(src, "rb") as w:
                out.writeframes(w.readframes(w.getnframes()))


def _speak(sentences, cfg: dict, output_mode: str, t0: float) -> tuple[list[str], float]:
    spoken: list[str] = []
    speech_paths: list[str] = []
    first_audio = 0.0
    for sentence in sentences:
        speech = synthesize(sentence, cfg)
        if not spoken:
            first_audio = time.monotonic() - t0
            print(f"  latency: {first_audio:.2f}s")
        spoken.append(sentence)
        set_ui(UiState.SPEAKING)
        match output_mode:
            case "device":
                play_wav(speech, cfg)
                events.emit("spoken", index=len(spoken) - 1, text=sentence)
            case "file":
                speech_paths.append(speech)
    if output_mode == "file" and speech_paths:
        transcript_dir = pathlib.Path(cfg["sync"]["transcript_dir"])
        transcript_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(transcript_dir / f"reply-{int(time.time())}.wav")
        _concat_wav(speech_paths, out_path)
        print(f"  wrote: {out_path}")
    return spoken, first_audio


def bench_turn(cfg: dict, start_at: str, output_mode: str) -> None:
    """Skip upstream stages and drive the rest of the pipeline from a fixture.

    Sibling to one_turn(): the mic path stays untouched; this one exists so
    the pipeline can be exercised in a container with no /dev/snd and no
    microphone.
    """
    t0 = time.monotonic()
    events.begin_turn()
    match start_at:
        case "wav":
            set_ui(UiState.THINKING)
            question = transcribe(cfg["bench"]["sample_wav"], cfg)
        case "question":
            set_ui(UiState.THINKING)
            question = _read_text(cfg["bench"]["sample_question"])
        case "reply":
            set_ui(UiState.SPEAKING)
            spoken, _ = _speak([_read_text(cfg["bench"]["sample_reply"])], cfg, output_mode, t0)
            print(f"  reply: {' '.join(spoken)}")
            events.end_turn(reason="ok", reply=" ".join(spoken))
            set_ui(UiState.IDLE)
            return
        case _:
            raise ValueError(f"unknown start_at: {start_at}")

    events.emit("heard", text=question)
    if not question:
        events.end_turn(reason="no-speech")
        set_ui(UiState.IDLE)
        return
    print(f"  heard: {question}")
    spoken, first_audio = _speak(stream_sentences(question, cfg), cfg, output_mode, t0)
    reply = " ".join(spoken)
    print(f"  reply: {reply}")
    events.end_turn(reason="ok", reply=reply, latency_s=round(first_audio, 3))
    set_ui(UiState.IDLE)


def _keyboard(fd: int) -> None:
    """Feed the bench keyboard into the same queue the console uses.

    On a thread so the loop can wait on one place for both. Reading stdin
    directly in the loop is what made the console unable to start a turn.
    """
    try:
        tty.setcbreak(fd)
        while True:
            ch = sys.stdin.read(1)
            if not ch:                 # stdin closed
                trigger.close()
                return
            trigger.request("keyboard", key=ch)
    except (OSError, ValueError):
        trigger.close()


def run() -> None:
    cfg = config.load()
    print("coco-egg zero — local voice loop.")
    print(config.summary(cfg))
    if cfg["trigger"]["mode"] != "keyboard":
        raise NotImplementedError("gpio trigger arrives at M1")
    # A TTY is no longer required, only useful: with the console enabled the
    # egg is fully drivable from a browser, which is also what `docker compose
    # up -d` (no -it) gives you.
    keyboard = sys.stdin.isatty()
    if not keyboard and not cfg.get("console", {}).get("enabled", True):
        raise SystemExit("coco-egg: no TTY and no console — nothing can start a turn. "
                         "Run docker with -it, or enable the console.")

    preload_tts(cfg)   # pay the ~2.1s Piper voice load now, not on the first learner
    preload_asr(cfg)   # and moonshine's model download/init (no-op for whisper)
    warm(cfg)          # and the pack load + static-prefix prefill, in the background
    console.serve(cfg) # observer only; a failure here must not stop teaching
    # Complete turn records come off the event bus, and each write nudges the
    # profile builder — event-based, so an idle device does no work at all.
    transcript.start(cfg, on_complete=profile_builder.on_turn)

    output_mode = "device"

    old_attrs, fd = None, None
    if keyboard:
        fd = sys.stdin.fileno()
        old_attrs = termios.tcgetattr(fd)
        threading.Thread(target=_keyboard, args=(fd,), daemon=True).start()
    try:
        while True:
            print(MENU if keyboard else CONSOLE_ONLY_MENU, flush=True)
            print(f"Output: {output_mode}\n")
            # ONE place to wait, for every source. The keyboard thread and the
            # console's POST /trigger both call trigger.request(), so a turn
            # started from a browser and a turn started from the terminal run
            # the same code below. GPIO at M1 is a third caller, not a third
            # branch. Polled rather than blocking so Ctrl-C stays responsive.
            event = None
            while event is None:
                event = trigger.wait(timeout=0.5)
            if event.get("source") == "eof":
                break
            # The console has one action and it means "ask a question", which
            # is what Enter means here. The bench keys stay keyboard-only.
            key = event.get("key", "\r") if event["source"] == "keyboard" else "\r"
            trigger.begin()
            try:
                match key:
                    case "\r" | "\n":
                        one_turn(cfg)
                    case "w":
                        bench_turn(cfg, "wav", output_mode)
                    case "q":
                        bench_turn(cfg, "question", output_mode)
                    case "r":
                        bench_turn(cfg, "reply", output_mode)
                    case " ":
                        output_mode = "file" if output_mode == "device" else "device"
            except Exception as e:  # keep the loop alive on the bench
                print("\n")
                events.emit("error", where="turn", error=e.__class__.__name__, message=str(e))
                set_ui(UiState.ERROR)
                print(f"  error: {e}\n", file=sys.stderr)
            finally:
                trigger.end()
    except KeyboardInterrupt:
        print()
    finally:
        if old_attrs is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)


if __name__ == "__main__":
    run()
