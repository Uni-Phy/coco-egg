"""Sentence embeddings for retrieval, via llama-server in --embedding mode.

Why this exists: token-overlap retrieval only fires when the learner already
knows the pack's vocabulary. Measured on the 2-subject library, natural
phrasing scored 0/7 — "how does rain happen" never reached the water cycle.
Embeddings took the same set to 7/7 at ~9ms a query (docs/roadmap.md).

Same runtime family as the tutor and whisper.cpp, deliberately: a second
llama-server on its own port with bge-small (64MB), rather than a new ONNX +
tokenizer stack. Start it with `make serve-embed`.

Everything here is optional. If the embedding server is unreachable the
callers fall back to lexical retrieval — a degraded egg still teaches, and
this must never be the reason a device goes quiet.
"""
from __future__ import annotations

import math

import requests


def _url(cfg: dict) -> str | None:
    return cfg["tutor"].get("embed_url")


def embed(texts: list[str], cfg: dict) -> list[list[float]] | None:
    """Embed texts, or None if the server is unreachable/misconfigured.

    None means "fall back", never "fail" — see the module docstring.

    Sent in batches because indexing is a whole-corpus operation that grows
    with the course library: 142 chunks in one request already exceeded the
    timeout on a busy Pi, and that failure mode gets worse with every subject
    added. A query is a single short text and never batches.
    """
    url = _url(cfg)
    if not url or not texts:
        return None
    size = cfg["tutor"].get("embed_batch", 16)
    timeout = cfg["tutor"].get("embed_timeout_s", 20)
    out: list[list[float]] = []
    for start in range(0, len(texts), size):
        batch = texts[start:start + size]
        try:
            r = requests.post(f"{url}/v1/embeddings", json={"input": batch},
                              timeout=timeout)
            r.raise_for_status()
            data = r.json()["data"]
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"  embed: {url} unavailable ({e.__class__.__name__}), "
                  f"falling back to lexical retrieval", flush=True)
            return None
        # The server may return results out of order; index is authoritative.
        out += [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]
    return out


def normalise(vec: list[float]) -> list[float]:
    """Unit-length, so similarity is a plain dot product at query time."""
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec] if n else vec


def similarity(a: list[float], b: list[float]) -> float:
    """Cosine of two ALREADY-normalised vectors."""
    return sum(x * y for x, y in zip(a, b))
