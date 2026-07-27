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

import json                                    # noqa: E402

from coco_egg import config                    # noqa: E402
from coco_egg.tutor.pack import Pack           # noqa: E402

SOURCES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "sources"


def load_course_questions() -> tuple[list[tuple[str, str]], list[str]]:
    """Per-course question sets shipped beside their source document.

    A course adds its own questions when it is written, so the eval grows with
    the library instead of being back-filled from memory later. Expected topics
    are matched loosely against the chunk id and title, because ids are derived
    from the prose and shift when a document is re-polished — pinning exact ids
    would make the eval fail on rewording rather than on regression.
    """
    positive, negative = [], []
    for f in sorted(SOURCES.glob("*.questions.json")):
        data = json.loads(f.read_text())
        positive += [(r["q"], r["topic"]) for r in data.get("should_retrieve", [])]
        negative += data.get("should_not_retrieve", [])
    return positive, negative


def topic_matches(chunk: dict, expected: str) -> bool:
    """Loose match: any meaningful word of the expected topic in id or title."""
    haystack = f"{chunk.get('id', '')} {chunk.get('title', '')}".lower()
    words = [w for w in expected.lower().replace("-", " ").split() if len(w) > 3]
    if not words:
        words = expected.lower().replace("-", " ").split()
    return any(w in haystack or w.rstrip("s") in haystack for w in words)

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
    # Was a should_not_retrieve case for as long as no course covered the sky.
    # It is the question children ask most, and grounding it wrongly on the
    # water cycle is what exposed the whole precision problem — so the sky
    # course now teaches it and this is a hit, not a false positive.
    ("why is the sky blue", "sky-blue"),
]

# Nothing in the library answers these. Grounding one of them is how the tutor
# ends up explaining a blue sky with evaporation, or claiming it ate a roti.
SHOULD_NOT_RETRIEVE = [
    "what did I have for breakfast",
    "what is the range",
    "what is game theory",
    "who is my teacher",
    "what is 7 times 8",
    "tell me a joke",
]

MIN_RECALL = 0.80        # of SHOULD_RETRIEVE, top hit is the expected chunk
MAX_FALSE_POSITIVE = 0.30


def score(pack: Pack, cfg: dict, lexical: bool) -> tuple[float, float, list[str]]:
    course_pos, course_neg = load_course_questions()
    positives = SHOULD_RETRIEVE + course_pos
    negatives = SHOULD_NOT_RETRIEVE + course_neg

    notes = []
    hits = 0
    for q, want in positives:
        got = pack.retrieve(q) if lexical else pack.retrieve_semantic(q, cfg)
        if got is None:
            sys.exit("eval: embedding server unreachable — start `make serve-embed`")
        top = got[0] if got else None
        if top is not None and (top["id"] == want or topic_matches(top, want)):
            hits += 1
        else:
            notes.append(f"  MISS  {q!r} -> {top['id'] if top else '(nothing)'}  want {want}")
    fps = 0
    for q in negatives:
        got = pack.retrieve(q) if lexical else pack.retrieve_semantic(q, cfg)
        if got:
            fps += 1
            notes.append(f"  FALSE {q!r} -> {got[0]['id']}")
    return hits / len(positives), fps / len(negatives), notes


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
