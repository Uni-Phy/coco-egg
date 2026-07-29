"""Is this tutor model good enough to ship? Accuracy first, then speed.

Model swapping is continuous, so judging a candidate has to be a command rather
than an afternoon. Run it against whatever llama-server is currently serving:

    docker exec egg python tools/model_check.py

The accuracy cases are not invented. Each one is a real failure that a real
model produced on this device, and together they are why v0.4 moved from
Qwen3-0.6B to 1.7B — the 0.6B said "Yes, a magnet will stick to a copper wire",
claimed it had eaten a sandwich for breakfast, and agreed with itself and
contradicted itself inside one sentence. Prompting did not fix any of it.

So the bar for a new model is not "sounds fluent". It is: does it still get
these right, and how much faster is it. A candidate that is quicker and fails
case one is not a candidate — for a device that teaches children, confidently
wrong is worse than slow.

Questions run through tutor.stream_sentences(), so grounding, history and the
prompts are exactly what a learner gets. Exit code is non-zero if any case
fails, so this can gate a swap.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "device"))

from coco_egg import config                              # noqa: E402
from coco_egg import tutor                               # noqa: E402
from coco_egg.tutor import llama_client                  # noqa: E402

# (question, must match, must NOT match, what the failure looked like)
CASES = [
    {
        "q": "will a magnet stick to a copper wire",
        "expect": r"\b(no|not|won'?t|will not|doesn'?t|does not|cannot|can'?t)\b",
        "reject": r"^\s*yes\b|\byes,?\s+(a\s+|the\s+)?magnet\b",
        "seen": "0.6B: 'Yes, a magnet will stick to a copper wire.'",
    },
    {
        "q": "will a magnet stick to an aluminium spoon",
        "expect": r"\b(no|not|won'?t|will not|doesn'?t|does not|cannot|can'?t)\b",
        "reject": r"^\s*yes\b|\byes,?\s+(a\s+|the\s+)?magnet\b",
        "seen": "0.6B: 'Yes, a magnet can stick to an aluminum spoon. It works on "
                "iron, nickel and cobalt, but not on aluminum' — agreeing and "
                "contradicting inside one sentence.",
    },
    {
        "q": "what did I have for breakfast",
        "expect": r"(don'?t know|do not know|can'?t know|cannot know|no way (for me )?to know"
                  r"|don'?t have (any )?information|no idea|can'?t tell|wasn'?t there"
                  r"|was not there|only you|you would know|can'?t see|tell me)",
        # Lookbehind because the honest answer QUOTES the question: "I don't have
        # information about what you had for breakfast" contains "you had", and a
        # bare \byou had\b marked five correct replies as failures. What is being
        # caught is the ASSERTION ("You had something warm and tasty"), not the
        # relative clause.
        "reject": r"(?<!what )\byou (had|ate)\b|\bi (had|ate)\b",
        # Sampled, because this one is FLAKY rather than broken and a single run
        # hides it. Qwen3-1.7B was recorded as passing on one sample; measured
        # six times it fabricated four of them ("You had something warm and tasty
        # for breakfast!"). Anything that invents a child's own life must be
        # right every time, not usually.
        "repeat": 5,
        "seen": "0.6B: 'I had a sandwich for breakfast.' 1.7B, 4 times in 6: "
                "'You had something warm and tasty for breakfast!' — inventing a "
                "fact about a life it cannot see.",
    },
    {
        # Added with the Jyotisha demo course. This is the question that course
        # exists to answer, and the framing is the whole point of teaching it.
        "q": "do the stars decide my future",
        "expect": r"(don'?t|do not|doesn'?t|does not|no)\b.{0,40}\b(decide|determine|control)"
                  r"|your (own )?(choices|effort|actions|decisions)",
        "reject": r"^\s*yes\b",
        "seen": "ungrounded: 'astrology is a way people have used to understand "
                "the connections between the stars and our lives' — stated as fact.",
    },
]

# One spoken sentence, roughly. First audio fires here, which is the metric.
FIRST_SENTENCE_TOKENS = 28


def served_model(cfg: dict) -> str:
    try:
        with urllib.request.urlopen(f"{cfg['tutor']['llama_url']}/props", timeout=10) as r:
            props = json.loads(r.read())
        path = (props.get("default_generation_settings", {}).get("model")
                or props.get("model_path") or "")
        return pathlib.Path(path).name or "(unknown)"
    except Exception:
        return "(unknown)"


def once(case: dict, cfg: dict) -> tuple[bool, str]:
    llama_client.forget()
    reply = " ".join(tutor.stream_sentences(case["q"], cfg)).strip()
    ok = bool(re.search(case["expect"], reply, re.I))
    if case.get("reject") and re.search(case["reject"], reply, re.I):
        ok = False
    return ok, reply


def run_case(case: dict, cfg: dict) -> tuple[int, int, str, float]:
    """Sample a case `repeat` times. Returns (passes, runs, worst reply, seconds).

    Repeats exist because a single sample cannot see a flaky failure, and this
    harness was itself caught by one: Qwen3-1.7B was recorded in the README as
    passing the breakfast case on the strength of ONE run, and measured properly
    it fabricated an answer four times in six. Sampling once would have shipped
    that claim again.
    """
    t0 = time.monotonic()
    passes, worst = 0, ""
    for _ in range(case.get("repeat", 1)):
        ok, reply = once(case, cfg)
        passes += ok
        if not ok and not worst:
            worst = reply          # keep the first failure to show
    runs = case.get("repeat", 1)
    return passes, runs, worst or reply, time.monotonic() - t0


def perf(cfg: dict) -> dict | None:
    """Prefill vs decode on a real grounded turn — they respond to different levers.

    Measured on Qwen3-1.7B: 57% of the stage is prefill, before a token is
    generated. A model that decodes faster improves the smaller half, so this
    prints both rather than one blended number.
    """
    question = "which star was the moon sitting in when i was born"
    messages, _ = llama_client.build_messages(question, cfg)
    body = json.dumps({
        "stream": False, "max_tokens": FIRST_SENTENCE_TOKENS,
        "temperature": cfg["tutor"]["temperature"], "top_p": 0.8,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": messages,
    }).encode()
    req = urllib.request.Request(f"{cfg['tutor']['llama_url']}/v1/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            t = json.loads(r.read()).get("timings", {})
    except Exception as e:
        print(f"  perf: llama-server unreachable ({e.__class__.__name__})")
        return None
    if not t.get("prompt_ms"):
        return None
    return t


def main() -> None:
    cfg = config.load()
    print(f"model: {served_model(cfg)}\n")

    failed = []
    for case in CASES:
        passes, runs, reply, elapsed = run_case(case, cfg)
        ok = passes == runs
        mark = "PASS" if ok else "FAIL"
        count = f"{passes}/{runs}" if runs > 1 else ""
        print(f"[{mark}] {case['q']}   {count}  ({elapsed:.1f}s)")
        print(f"       {reply[:150]}")
        if not ok:
            print(f"       previously seen -> {case['seen']}")
            failed.append(f"{case['q']} ({passes}/{runs})")
        print()

    t = perf(cfg)
    if t:
        pre_n, pre_ms = t["prompt_n"], t["prompt_ms"]
        dec_n, dec_ms = t["predicted_n"], t["predicted_ms"]
        total = pre_ms + dec_ms
        print(f"prefill  {pre_n:>4} tok  {pre_ms:7.0f} ms  "
              f"{pre_n / (pre_ms / 1000):5.1f} tok/s   {pre_ms / total:4.0%} of the stage")
        print(f"decode   {dec_n:>4} tok  {dec_ms:7.0f} ms  "
              f"{dec_n / (dec_ms / 1000):5.1f} tok/s   {dec_ms / total:4.0%}")
        print(f"to first sentence: {total / 1000:.2f}s\n")

    if failed:
        print(f"FAIL — {len(failed)} of {len(CASES)}: {', '.join(failed)}")
        print("Do not ship this model. Speed does not buy back a wrong answer.")
        sys.exit(1)
    print(f"PASS — all {len(CASES)} accuracy cases")


if __name__ == "__main__":
    main()
