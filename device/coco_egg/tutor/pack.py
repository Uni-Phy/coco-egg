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


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text)]


class Pack:
    def __init__(self, data: dict):
        self.topic = data.get("topic", "")
        self.chunks: list[dict] = data["chunks"]
        n_docs = len(self.chunks)
        df: dict[str, int] = {}
        for c in self.chunks:
            c["_title_tokens"] = set(_tokens(c.get("title", "")))
            c["_tokens"] = c["_title_tokens"] | set(_tokens(c["text"]))
            for t in c["_tokens"]:
                df[t] = df.get(t, 0) + 1
        self._idf = {t: math.log(1 + n_docs / n) for t, n in df.items()}

    @classmethod
    def load(cls, path: str | pathlib.Path) -> "Pack":
        return cls(json.loads(pathlib.Path(path).read_text()))

    def retrieve(self, question: str, k: int = 3) -> list[dict]:
        """Top-k chunks by summed idf of question terms present in the chunk.

        Title matches count triple: chunk titles name the concept, so a
        question term hitting the title is a much stronger signal than the
        same term buried in another chunk's body text.
        """
        q_terms = set(_tokens(question))
        scored = []
        for c in self.chunks:
            score = sum(self._idf[t] * (3.0 if t in c["_title_tokens"] else 1.0)
                        for t in q_terms if t in c["_tokens"])
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda pair: -pair[0])
        return [c for _, c in scored[:k]]
