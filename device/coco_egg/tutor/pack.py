"""Curriculum content pack: load + retrieve (spec §7 local RAG).

v0 is deliberately dependency-free: a pack is a JSON file of chunks and
retrieval is token-overlap scoring (BM25-lite, unicode-aware so Hindi/Marathi
text works). Chunks carry an optional pre-written spoken "explain" used when
no LLM is reachable. An embedding model can replace retrieve() later without
touching callers. Real packs come from the CoCo node; the fixture pack is the
hardcoded starting point.
"""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
import re

from .. import events
from . import embed as embedding

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


def _emit_retrieved(question: str, path: str, scale: str, floor: float,
                    relative_floor: float, ranked: list[tuple], hits: list[dict]) -> None:
    """Publish what retrieval saw — every candidate, kept or cut, with its score.

    Retrieval is the one stage whose output is invisible in the spoken answer,
    and both failures we are still chasing are near-misses: "why is the sky
    blue" grounds on the water cycle, "can the government stop me praying"
    lands on local government instead of the constitution. Neither is
    diagnosable from the hits alone — you have to see what nearly won and by
    how much (docs/console-design.md).

    Guarded by events.active() because formatting candidates costs something
    and nobody is watching most of the time. Retrieval itself is unchanged:
    `ranked` is scored on the way past, and `hits` is whatever the caller
    already decided to return.
    """
    if not events.active():
        return
    kept = {id(c) for c in hits}
    top = sorted(ranked, key=lambda r: -r[0])[:5]
    events.emit(
        "retrieved", question=question, path=path, scale=scale, floor=round(floor, 4),
        relative_floor=round(relative_floor, 4),
        chunks=[{"id": c.get("id", ""), "title": c.get("title", ""),
                 "subject": c.get("subject", ""), "score": round(score, 4),
                 "lexical_bonus": bonus, "kept": id(c) in kept}
                for score, bonus, c in top],
    )


class Pack:
    # A chunk scoring below this fraction of the best chunk is noise, not a
    # second opinion. Tuned on the fixture pack: a real topic match outscores
    # incidental overlap by ~3x, so 0.4 keeps genuine multi-chunk topics
    # (photosynthesis + respiration) and drops the stragglers.
    MIN_RATIO = 0.4

    # Cosine floor for an embedding hit. Picked off the measured curve
    # (`tools/eval_retrieval.py --sweep`), not by eye — the bands overlap, so
    # no floor is clean and the knee is what matters:
    #
    #   floor  0.55 -> recall 93%, false positives 71%
    #   floor  0.58 -> recall 87%, false positives 29%   <- here
    #   floor  0.65 -> recall 60%, false positives  0%
    #
    # Biased slightly toward recall: a miss means the learner gets the small
    # model's unaided knowledge instead of our curated material, while a loose
    # hit still carries the "answer from your own knowledge where this falls
    # short" instruction (prompts.GROUNDING). Re-sweep when packs are added.
    MIN_SIMILARITY = 0.58

    # Added to a chunk's similarity when the question also shares a title term
    # or several content words. Lexical evidence is precise where embeddings
    # are fuzzy, so it breaks ties rather than gating.
    LEXICAL_BONUS = 0.05

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
        self._vectors: list[list[float]] | None = None

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

    def _passage(self, chunk: dict) -> str:
        return f"{chunk.get('title', '')}. {chunk['text']}"

    def index(self, cfg: dict) -> bool:
        """Embed every chunk once, cached on disk. True if vectors are ready.

        Embedding costs ~53ms a chunk, which is nothing once but real on every
        boot of a device that should be answering within seconds of power-on.
        The cache key is a hash of the passages themselves, so editing or
        adding a pack invalidates it and nothing else does.
        """
        if self._vectors is not None:
            return True
        passages = [self._passage(c) for c in self.chunks]
        digest = hashlib.sha256(chr(10).join(passages).encode()).hexdigest()[:16]
        cache = pathlib.Path(cfg["tutor"].get("embed_cache", ".embed-cache"))
        cached = cache / f"{digest}.json"
        if cached.is_file():
            try:
                self._vectors = json.loads(cached.read_text())
                return True
            except ValueError:
                pass   # corrupt cache is not worth failing over; re-embed
        vecs = embedding.embed(passages, cfg)
        if vecs is None:
            return False
        self._vectors = [embedding.normalise(v) for v in vecs]
        try:
            cache.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(self._vectors))
        except OSError as e:
            print(f"  pack: could not cache embeddings ({e}); continuing", flush=True)
        print(f"  pack: embedded {len(passages)} chunks", flush=True)
        return True

    def retrieve_semantic(self, question: str, cfg: dict, k: int = 3) -> list[dict] | None:
        """Hybrid: embeddings for recall, lexical evidence to break ties.

        Returns None when embeddings are unavailable, so callers fall back to
        the lexical path rather than losing retrieval entirely.
        """
        if not self.index(cfg):
            return None
        qvec = embedding.embed([question], cfg)
        if not qvec:
            return None
        qv = embedding.normalise(qvec[0])
        q_terms = _content_tokens(question)

        scored, ranked = [], []
        for vec, c in zip(self._vectors, self.chunks):
            sim = embedding.similarity(qv, vec)
            shared = [t for t in q_terms if t in c["_tokens"]]
            bonus = _is_topic_match(shared, c)
            if bonus:
                sim += self.LEXICAL_BONUS
            ranked.append((sim, bonus, c))
            if sim >= self.MIN_SIMILARITY:
                scored.append((sim, c))
        hits: list[dict] = []
        relative = 0.0
        if scored:
            scored.sort(key=lambda pair: -pair[0])
            # Relative cut as well as absolute: a clear winner should not drag
            # in near-misses, which bloats the prompt and blurs the answer.
            relative = 0.92 * scored[0][0]
            hits = [c for sim, c in scored[:k] if sim >= relative]
        _emit_retrieved(question, "semantic", "cosine", self.MIN_SIMILARITY, relative,
                        ranked, hits)
        return hits

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
        hits: list[dict] = []
        floor = 0.0
        if scored:
            scored.sort(key=lambda pair: -pair[0])
            # Relative, so the floor the console draws is per-question. Note it
            # is summed idf, not a cosine — the two paths are not comparable.
            floor = self.MIN_RATIO * scored[0][0]
            hits = [c for score, c in scored[:k] if score >= floor]
        _emit_retrieved(question, "lexical", "idf", floor, floor,
                        [(score, False, c) for score, c in scored], hits)
        return hits
