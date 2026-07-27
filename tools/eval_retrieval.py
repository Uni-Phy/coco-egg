"""Retrieval eval: does the right lesson fire when a learner asks their way?

The v0.3 retrieval rule was verified against questions phrased in the pack's
own words, so precision was measured and recall never was — it shipped at 0/7
on natural phrasing (docs/model-notes.md §7). This exists so that cannot
happen again: every question here is deliberately phrased the way a learner
would, NOT the way the pack does.

    python tools/eval_retrieval.py              # score current settings
    python tools/eval_retrieval.py --sweep      # similarity floor vs outcome
    python tools/eval_retrieval.py --lexical    # score the fallback path

Exit code is non-zero when the bar is missed, so `make eval` can gate a pack.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "device"))

from coco_egg import config                    # noqa: E402
from coco_egg.tutor.pack import Pack           # noqa: E402

# (question, expected chunk id). Phrased as a child would, never as the pack
# does — that is the whole point of the file.
SHOULD_RETRIEVE = [
    ("how do animals breathe", "respiration"),
    ("why do we need air", "respiration"),
    ("what do plants need to grow", "photosynthesis"),
    ("why are leaves green", "photosynthesis"),
    ("do plants eat mud", "plants-soil"),
    ("how does rain happen", "water-cycle"),
    ("where do clouds come from", "water-cycle"),
    ("what is one half", "fractions"),
    ("if I cut a chapati in two what do I have", "fractions"),
    ("what rights do I have", "constitution"),
    ("can the government stop me praying", "constitution"),
    ("who runs my village", "parliament-and-local-government"),
    ("who decides about roads in our village", "parliament-and-local-government"),
    ("which king became a buddhist after a war", "ashoka-and-buddhism"),
    ("tell me about the lion pillar", "ashoka-and-buddhism"),
]

# Nothing in the library answers these. Grounding one of them is how the tutor
# ends up explaining a blue sky with evaporation, or claiming it ate a roti.
SHOULD_NOT_RETRIEVE = [
    "what did I have for breakfast",
    "why is the sky blue",
    "what is the range",
    "what is game theory",
    "who is my teacher",
    "what is 7 times 8",
    "tell me a joke",
]

MIN_RECALL = 0.80        # of SHOULD_RETRIEVE, top hit is the expected chunk
MAX_FALSE_POSITIVE = 0.30


def score(pack: Pack, cfg: dict, lexical: bool) -> tuple[float, float, list[str]]:
    notes = []
    hits = 0
    for q, want in SHOULD_RETRIEVE:
        got = pack.retrieve(q) if lexical else pack.retrieve_semantic(q, cfg)
        if got is None:
            sys.exit("eval: embedding server unreachable — start `make serve-embed`")
        top = got[0]["id"] if got else None
        if top == want:
            hits += 1
        else:
            notes.append(f"  MISS  {q!r} -> {top or '(nothing)'}  want {want}")
    fps = 0
    for q in SHOULD_NOT_RETRIEVE:
        got = pack.retrieve(q) if lexical else pack.retrieve_semantic(q, cfg)
        if got:
            fps += 1
            notes.append(f"  FALSE {q!r} -> {got[0]['id']}")
    return hits / len(SHOULD_RETRIEVE), fps / len(SHOULD_NOT_RETRIEVE), notes


def main() -> None:
    cfg = config.load()
    lexical = "--lexical" in sys.argv
    pack = Pack.load_config(cfg["tutor"]["pack"])
    if not pack:
        sys.exit("eval: no packs loaded — check tutor.pack")
    print(f"{len(pack.chunks)} chunks / {len(pack.subjects)} subjects\n")

    if "--sweep" in sys.argv:
        print("similarity floor sweep (recall vs false positives):")
        for floor in [0.45, 0.50, 0.52, 0.55, 0.58, 0.60, 0.62, 0.65]:
            Pack.MIN_SIMILARITY = floor
            recall, fp, _ = score(pack, cfg, lexical=False)
            print(f"  MIN_SIMILARITY={floor:.2f}  recall={recall:5.0%}  false-positives={fp:5.0%}")
        return

    recall, fp, notes = score(pack, cfg, lexical)
    path = "lexical (fallback)" if lexical else f"semantic (floor {Pack.MIN_SIMILARITY})"
    print(f"path: {path}")
    print(f"  recall           {recall:5.0%}  (bar {MIN_RECALL:.0%})")
    print(f"  false positives  {fp:5.0%}  (bar {MAX_FALSE_POSITIVE:.0%})")
    if notes:
        print("\n" + "\n".join(notes))
    ok = recall >= MIN_RECALL and fp <= MAX_FALSE_POSITIVE
    print("\nPASS" if ok else "\nFAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
