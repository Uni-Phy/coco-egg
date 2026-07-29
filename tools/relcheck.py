"""One real voice turn through the release container — the deploy smoke test.

`make eval` proves retrieval still works and the unit tests prove the logic
does, but neither touches a microphone or a speaker. This does the whole thing
on the actual hardware: beep, listen, transcribe, retrieve, generate, speak, and
report the one number that is the product metric.

    docker exec -it egg python tools/relcheck.py

Needs a real mic and a person to talk. The beep is the "speak now" cue, and it
doubles as a speaker check — if you do not hear it, nothing after this matters.
The eMeet's hardware AEC means you cannot substitute a recording played through
the device's own speaker (README), so this really does need a human.

Because it goes through tutor.stream_sentences(), saying "quiz me" here
exercises quiz mode end to end as well.
"""
from __future__ import annotations

import pathlib
import sys
import time
import wave

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "device"))

from coco_egg import config                            # noqa: E402
from coco_egg.asr import transcribe                    # noqa: E402
from coco_egg.audio import play_wav, record_utterance  # noqa: E402
from coco_egg.audio.io import write_wav                # noqa: E402
from coco_egg.tts import preload, synthesize           # noqa: E402
from coco_egg.tutor import llama_client, quiz, stream_sentences  # noqa: E402

SAMPLE_RATE = 16000
CUE_HZ = 880
CUE_S = 0.22


def cue(cfg: dict) -> None:
    """A short tone, so the speaker is proven before the answer depends on it."""
    t = np.linspace(0, CUE_S, int(CUE_S * SAMPLE_RATE), False)
    tone = (0.3 * np.sin(2 * np.pi * CUE_HZ * t) * 32767).astype(np.int16)
    path = "/tmp/relcheck-cue.wav"
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(tone.tobytes())
    play_wav(path, cfg)


def grounding(question: str, cfg: dict) -> str:
    """What the answer will be built on. Skipped for quiz turns, which retrieve
    nothing — asking anyway would run an embedding call for no reason."""
    if quiz.active() or quiz.is_start(question):
        return "quiz mode (no retrieval)"
    _, hits = llama_client.build_messages(question, cfg)
    return str([c["id"] for c in hits]) if hits else "model knowledge"


def main() -> None:
    cfg = config.load()
    cfg["audio"]["max_utterance_s"] = 15
    preload(cfg)     # keep the ~2.1s voice load out of the measured turn

    cue(cfg)
    print("SPEAK NOW", flush=True)
    # t0 is end-of-speech, not "recorder returned" — the learner sits through
    # the trailing-silence hangover too, so it belongs in the number.
    audio, t0 = record_utterance(cfg)
    level = (float(np.sqrt(np.mean((audio.astype(np.float32) / 32768) ** 2)))
             if audio.size else 0.0)
    if level < cfg["audio"]["silence_rms"]:
        sys.exit(f"nothing heard (rms {level:.4f}, floor {cfg['audio']['silence_rms']})")

    question = transcribe(write_wav(audio, SAMPLE_RATE), cfg).strip()
    print(f"HEARD   : {question!r}", flush=True)
    print(f"GROUNDED: {grounding(question, cfg)}", flush=True)

    first_audio, spoken = None, []
    for sentence in stream_sentences(question, cfg):
        speech = synthesize(sentence, cfg)
        if first_audio is None:
            first_audio = time.monotonic() - t0
        spoken.append(sentence)
        play_wav(speech, cfg)
    print(f"ANSWER  : {' '.join(spoken)}", flush=True)
    if first_audio is not None:
        print(f"LATENCY : {first_audio:.1f}s (end-of-speech -> first audio)", flush=True)


if __name__ == "__main__":
    main()
