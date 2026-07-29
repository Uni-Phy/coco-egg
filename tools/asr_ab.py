"""whisper vs moonshine, on the same audio, scored against known text.

    docker exec egg python tools/asr_ab.py

Swapping the ASR backend is a real decision — moonshine's stage measured 0.00s
against whisper's ~1.4s mean on the device — and it was about to be made from a
handful of live turns where BOTH backends produced nonsense. Three turns is not
evidence, and human speech varies more between takes than the backends do
between each other.

So the audio is fixed and the answer is known. Piper synthesises each sentence
once, both backends transcribe the same WAV, and the score is word error rate
against the text that was spoken. Deterministic, repeatable, no microphone.

WHAT THIS DOES NOT MEASURE, and it matters before acting on it: synthetic speech
is clean, evenly paced and close-miked. A child two metres away in a room with a
fan is harder in ways this cannot see, and noise robustness is exactly where
moonshine is expected to give ground. Read this as the CEILING for each backend
and as a fair relative ranking — not as a promise about a classroom.
"""
from __future__ import annotations

import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "device"))

from coco_egg import config          # noqa: E402
from coco_egg.asr import transcribe  # noqa: E402
from coco_egg.tts import synthesize  # noqa: E402

# Real tutor questions: the shapes the device actually gets, including the
# proper nouns a general ASR has never been trained on, which is where a
# curriculum device gets hurt.
SENTENCES = [
    "What is a nakshatra?",
    "Do the stars decide my future?",
    "Why is the sky blue?",
    "How do animals breathe?",
    "Tell me a joke.",
    "Quiz me on jyotisha.",
    "What is one half?",
    "Why does it get dark at night?",
    "Who runs my village?",
    "Let us study physics.",
]

_WORD = re.compile(r"[a-z0-9]+")


def words(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def wer(said: str, heard: str) -> float:
    """Word error rate: edits to turn what was heard into what was said.

    Levenshtein over words, not characters — a transcript is judged by whether
    the words are right, and character distance would score "nakshatra" against
    "nakshatras" as nearly perfect while "a" against "the" looks catastrophic.
    """
    a, b = words(said), words(heard)
    if not a:
        return 0.0 if not b else 1.0
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1] / len(a)


def run(backend: str, wavs: list[tuple[str, str]], cfg: dict) -> dict:
    cfg = {**cfg, "asr": {**cfg["asr"], "backend": backend}}
    rows, total_wer, exact, elapsed = [], 0.0, 0, 0.0
    for said, wav in wavs:
        t0 = time.monotonic()
        try:
            heard = transcribe(wav, cfg)
        except Exception as e:                      # a backend that cannot run
            print(f"  {backend}: {e.__class__.__name__}: {e}")
            return {}
        dt = time.monotonic() - t0
        e = wer(said, heard)
        total_wer += e
        exact += words(said) == words(heard)
        elapsed += dt
        rows.append((said, heard, e, dt))
    return {"backend": backend, "rows": rows, "wer": total_wer / len(wavs),
            "exact": exact, "n": len(wavs), "seconds": elapsed / len(wavs)}


def report(result: dict) -> None:
    if not result:
        return
    print(f"\n=== {result['backend']} ===")
    for said, heard, e, dt in result["rows"]:
        mark = "ok  " if e == 0 else "MISS"
        print(f"  [{mark}] {dt:5.2f}s  wer {e:4.0%}  {heard!r}")
        if e:
            print(f"           spoken: {said!r}")
    print(f"  mean WER {result['wer']:.0%} | exact {result['exact']}/{result['n']}"
          f" | mean {result['seconds']:.2f}s per utterance")


def main() -> None:
    cfg = config.load()
    print(f"synthesising {len(SENTENCES)} utterances with Piper...", flush=True)
    wavs = [(s, synthesize(s, cfg)) for s in SENTENCES]

    results = [r for r in (run(b, wavs, cfg) for b in ("whisper", "moonshine")) if r]
    for r in results:
        report(r)

    if len(results) == 2:
        w, m = results
        print("\n=== verdict ===")
        print(f"  accuracy : whisper {w['wer']:.0%} WER vs moonshine {m['wer']:.0%} WER")
        print(f"  exact    : whisper {w['exact']}/{w['n']} vs moonshine {m['exact']}/{m['n']}")
        print(f"  speed    : whisper {w['seconds']:.2f}s vs moonshine {m['seconds']:.2f}s"
              f"  ({w['seconds'] - m['seconds']:+.2f}s per utterance)")
        print("\n  Clean synthetic speech only. A child across a noisy room is")
        print("  harder in ways this cannot see, and that is where moonshine is")
        print("  expected to give ground. Ceiling and ranking, not a promise.")


if __name__ == "__main__":
    main()
