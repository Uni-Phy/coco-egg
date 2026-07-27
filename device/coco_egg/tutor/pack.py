"""Curriculum content pack: load + retrieve (spec §7 local RAG).

v0 is deliberately dependency-free: a pack is a JSON file of chunks and
retrieval is token-overlap scoring (BM25-lite, unicode-aware so Hindi/Marathi
text works). Chunks carry an optional pre-written spoken "explain" used when
no LLM is reachable. An embedding model can replace retrieve() later without
touching callers. Real packs come from the CoCo node; the fixture pack is the
hardcoded starting point.
"""
from __future__ import annotations

import json
import math
import pathlib
import re

_WORD = re.compile(r"\w+", re.UNICODE)

# Function words that pad every spoken question. They are useless evidence for
# *which* lesson is meant, and idf cannot filter them in a small pack: in a
# 5-chunk pack "why" is as rare as "photosynthesis". Worse, they show up in
# chunk titles ("The water cycle", "Why plants do not eat soil"), where the
# title boost in retrieve() lets them carry a match on their own — that is how
# "why is the sky blue" used to retrieve the soil lesson.
# Launch language is English (spec §1); a second language needs its own set.
_STOPWORDS = frozenset("""
a an the of to in on at by for and or but if then than as is are was were be
been being do does did can could will would should i you he she it they we me
my your our their them us this that these those what why how when where who
whom whose not no yes with from about into over under more most some any each
both few other such own so very just
""".split())


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text)]


def _content_tokens(text: str) -> set[str]:
    """Question tokens worth matching on — stopwords carry no topic signal."""
    return {t for t in _tokens(text) if t not in _STOPWORDS}


def _is_topic_match(shared: list[str], chunk: dict) -> bool:
    """Is this chunk *about* the question, or does it just share a word?

    A real topic match either names the concept in its title, or overlaps the
    question on more than one content word. One incidental body word is not
    evidence, and acting like it is caused both of the wrong answers measured
    on 2026-07-27: "what did I have for breakfast?" matched the fractions
    lesson on "have" alone (that lesson mentions a roti, so the tutor claimed
    it ate a roti), and "why is the sky blue?" matched the water cycle on
    "sky" alone and explained the sky with evaporation.

    This matters more the thinner the model gets. A 1.7B ignored bad grounding;
    a 0.6B builds its whole answer out of it (docs/model-notes.md §3).
    """
    if not shared:
        return False
    return len(shared) > 1 or any(t in chunk["_title_tokens"] for t in shared)


class Pack:
    # A chunk scoring below this fraction of the best chunk is noise, not a
    # second opinion. Tuned on the fixture pack: a real topic match outscores
    # incidental overlap by ~3x, so 0.4 keeps genuine multi-chunk topics
    # (photosynthesis + respiration) and drops the stragglers.
    MIN_RATIO = 0.4

    def __init__(self, *data: dict):
        # Several packs merge into ONE corpus rather than being searched
        # separately. That is deliberate: idf is a corpus statistic, and it was
        # unusable at 5 chunks (where "why" looked as rare as "photosynthesis").
        # Every subject we add sharpens retrieval for the subjects already here.
        self.subjects = [d.get("topic", "") for d in data if d.get("topic")]
        self.topic = self.subjects[0] if len(self.subjects) == 1 else ""
        self.chunks: list[dict] = []
        for d in data:
            for c in d["chunks"]:
                c.setdefault("subject", d.get("topic", ""))
                self.chunks.append(c)
        n_docs = len(self.chunks)
        df: dict[str, int] = {}
        for c in self.chunks:
            c["_title_tokens"] = set(_tokens(c.get("title", "")))
            c["_tokens"] = c["_title_tokens"] | set(_tokens(c["text"]))
            for t in c["_tokens"]:
                df[t] = df.get(t, 0) + 1
        self._idf = {t: math.log(1 + n_docs / n) for t, n in df.items()}

    @classmethod
    def load(cls, *paths: str | pathlib.Path) -> "Pack":
        """Load one pack, or merge several into a single searchable corpus."""
        return cls(*(json.loads(pathlib.Path(p).read_text()) for p in paths))

    @classmethod
    def load_config(cls, spec: str | list | None) -> "Pack | None":
        """Resolve the `tutor.pack` config: a file, a directory, or a list.

        A directory is the useful shape once subjects are a library rather than
        a single fixture — drop a pack in, it is taught. Missing paths are
        skipped rather than fatal: a device should keep teaching the subjects it
        does have if one pack fails to sync down from the node.
        """
        if not spec:
            return None
        entries = spec if isinstance(spec, list) else [spec]
        paths: list[pathlib.Path] = []
        for entry in entries:
            p = pathlib.Path(entry)
            if p.is_dir():
                paths.extend(sorted(p.glob("*.json")))
            elif p.is_file():
                paths.append(p)
            else:
                print(f"  pack: {entry} not found, skipping", flush=True)
        return cls.load(*paths) if paths else None

    def retrieve(self, question: str, k: int = 3) -> list[dict]:
        """Top-k chunks by summed idf of question terms present in the chunk.

        Title matches count triple: chunk titles name the concept, so a
        question term hitting the title is a much stronger signal than the
        same term buried in another chunk's body text.

        Matching ignores stopwords, and a chunk must score within MIN_RATIO of
        the best chunk to come back at all. Both exist because from v0.2 the
        tutor answers general questions from its own knowledge: a weak match is
        no longer harmless padding, it actively drags the answer off the
        question ("what is the range?" used to retrieve three unrelated
        lessons). Returning nothing is the correct, common outcome.

        The ratio cut also keeps the grounded prompt short, and prefill of that
        prompt is the single biggest slice of time-to-first-audio (see README).
        """
        q_terms = _content_tokens(question)
        scored = []
        for c in self.chunks:
            shared = [t for t in q_terms if t in c["_tokens"]]
            if not _is_topic_match(shared, c):
                continue
            score = sum(self._idf[t] * (3.0 if t in c["_title_tokens"] else 1.0)
                        for t in shared)
            if score > 0:
                scored.append((score, c))
        if not scored:
            return []
        scored.sort(key=lambda pair: -pair[0])
        best = scored[0][0]
        return [c for score, c in scored[:k] if score >= self.MIN_RATIO * best]
