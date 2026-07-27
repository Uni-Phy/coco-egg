"""M0 latency bench: drive the real local loop N times, report the split.

Spec §16 makes M0 responsible for measuring end-of-speech -> first-audio
honestly and then setting the bar. This is the instrument that produced the
numbers in the README, so the bar can be re-checked after a change (smaller
whisper model, fewer retrieved chunks, a different board) instead of being
re-argued.

ASR runs from a recorded WAV rather than the mic, so it is repeatable and
needs no human. The mic path is unchanged and still what one_turn() uses; the
recorder's trailing-silence hangover is added back in at the end because the
learner waits through it.

The tutor question ROTATES every turn, and that is load-bearing. llama-server
caches the prompt prefix, so asking the same question twice reuses the whole
prompt and prefill collapses from ~2.2s to ~0.10s — an earlier version of this
bench repeated one question and reported a median ~2s faster than a learner
will ever see. Rotating means every turn pays the prefill a genuinely new
question costs. Only the shared SYSTEM preamble stays cached, which is exactly
what happens in the field.

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

# Rotated so no turn reuses the previous turn's cached prompt. Mixed on
# purpose: pack-grounded, general knowledge, and arithmetic have different
# prompt lengths and reply lengths, so a median over them is representative
# of a real session rather than of one lucky question.
BENCH_QUESTIONS = [
    "What is photosynthesis?",      # grounded, long pack material
    "Who was Ashoka?",              # general, no grounding
    "Explain the water cycle.",     # grounded
    "How does an aeroplane fly?",   # general
    "What are fractions?",          # grounded
    "What is half of 30?",          # general, short reply
]


def main() -> None:
    args = sys.argv[1:]
    speak = "--speak" in args
    n = next((int(a) for a in args if a.isdigit()), 5)

    cfg = config.load()
    wav = cfg["bench"]["sample_wav"]
    hangover = cfg["audio"]["silence_stop_s"]

    # *.wav is gitignored, so this is not in a fresh clone — say so usefully
    # rather than letting whisper-cli fail on a missing file. It has to be a
    # real recording anyway: the numbers are only meaningful against real
    # speech, so shipping a synthetic stand-in would flatter the ASR stage.
    if not pathlib.Path(wav).exists():
        sys.exit(
            f"bench: {wav} is missing (*.wav is gitignored).\n"
            f"Record a real question into it first, e.g.\n"
            f"  arecord -f S16_LE -r 16000 -c 1 -d 3 {wav}"
        )

    preload(cfg)   # as a long-running device would; keeps voice load out of turn 1

    rows = []
    for i in range(n):
        t0 = time.monotonic()
        heard = transcribe(wav, cfg)
        asr_s = time.monotonic() - t0
        if not heard:
            sys.exit(f"bench: {wav} transcribed to nothing — record a real question into it")
        # ASR cost is measured on the real recording; the tutor stage runs on a
        # rotating question so prefill is never served from the prompt cache.
        question = BENCH_QUESTIONS[i % len(BENCH_QUESTIONS)]

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
              f"-> first_audio={first:.2f}s (perceived {first + hangover:.2f}s)  [{question}]")
        if i == 0:
            print(f"   ASR heard: {heard!r} (from {wav})")
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
