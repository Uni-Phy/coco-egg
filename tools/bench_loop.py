"""M0 latency bench: drive the real local loop N times, report the split.

Spec §16 makes M0 responsible for measuring end-of-speech -> first-audio
honestly and then setting the bar. This is the instrument that produced the
numbers in the README, so the bar can be re-checked after a change (smaller
whisper model, fewer retrieved chunks, a different board) instead of being
re-argued.

Runs from a recorded WAV rather than the mic, so it is repeatable and needs
no human. The mic path is unchanged and still what one_turn() uses; the
recorder's trailing-silence hangover is added back in at the end because the
learner waits through it.

    python tools/bench_loop.py            # 5 turns, no audio out
    python tools/bench_loop.py 10 --speak # 10 turns, play each reply
"""
from __future__ import annotations

import pathlib
import statistics as st
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "device"))

from coco_egg import config                      # noqa: E402
from coco_egg.asr import transcribe              # noqa: E402
from coco_egg.audio import play_wav              # noqa: E402
from coco_egg.tts import preload, synthesize     # noqa: E402
from coco_egg.tutor import stream_sentences      # noqa: E402


def main() -> None:
    args = sys.argv[1:]
    speak = "--speak" in args
    n = next((int(a) for a in args if a.isdigit()), 5)

    cfg = config.load()
    wav = cfg["bench"]["sample_wav"]
    hangover = cfg["audio"]["silence_stop_s"]
    preload(cfg)   # as a long-running device would; keeps voice load out of turn 1

    rows = []
    for i in range(n):
        t0 = time.monotonic()
        question = transcribe(wav, cfg)
        asr_s = time.monotonic() - t0
        if not question:
            sys.exit(f"bench: {wav} transcribed to nothing — record a real question into it")

        llm_s = tts_s = first = None
        t_llm = time.monotonic()
        spoken: list[str] = []
        for sentence in stream_sentences(question, cfg):
            if first is None:
                llm_s = time.monotonic() - t_llm
            t_tts = time.monotonic()
            speech = synthesize(sentence, cfg)
            if first is None:
                tts_s = time.monotonic() - t_tts
                first = time.monotonic() - t0
            spoken.append(sentence)
            if speak:
                play_wav(speech, cfg)

        rows.append((asr_s, llm_s, tts_s, first))
        print(f"turn {i + 1}: asr={asr_s:.2f} llm_1st={llm_s:.2f} tts={tts_s:.2f} "
              f"-> first_audio={first:.2f}s (perceived {first + hangover:.2f}s)")
        if i == 0:
            print(f"   heard: {question}")
            print(f"   reply: {' '.join(spoken)}")

    print(f"\nn={n}, perceived adds silence_stop_s={hangover}s of hangover")
    for name, idx in [("ASR", 0), ("LLM first sentence", 1), ("TTS", 2), ("-> first audio", 3)]:
        v = [r[idx] for r in rows]
        print(f"  {name:20} min={min(v):.2f}  median={st.median(v):.2f}  max={max(v):.2f}")
    fa = [r[3] for r in rows]
    print(f"  {'PERCEIVED e2e':20} min={min(fa) + hangover:.2f}  "
          f"median={st.median(fa) + hangover:.2f}  max={max(fa) + hangover:.2f}")


if __name__ == "__main__":
    main()
