"""Local tutor LLM via llama-server (llama.cpp), OpenAI-compatible API.

Locked stack (spec §7 / decision #8): Qwen3-1.7B Q4_K_M, thinking disabled.
The reply is streamed and yielded sentence-by-sentence so TTS can start
speaking while the model is still generating — time-to-first-audio is the
product metric (spec §16 M0), so nothing waits for the full reply.

Thinking is disabled twice over: the server runs with --reasoning-budget 0
(see Makefile `serve`) and we request enable_thinking=false; any <think>
block that slips through is stripped defensively before sentences are cut.
"""
from __future__ import annotations

import json
import re
from typing import Iterator

import requests

from .pack import Pack
from .prompts import GROUNDING, SYSTEM, UNKNOWN

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_THINK_PAIR = re.compile(r"<think>.*?</think>", re.DOTALL)

_pack: Pack | None = None


def _get_pack(cfg: dict) -> Pack | None:
    global _pack
    if _pack is None and cfg["tutor"].get("pack"):
        _pack = Pack.load(cfg["tutor"]["pack"])
    return _pack


def _system_prompt(question: str, cfg: dict) -> tuple[str, list[dict]]:
    """SYSTEM prompt, grounded in retrieved pack chunks when there are any.

    No hit is the normal case in v0.2, not a failure — the model then answers
    the question on its own. Grounding only fires on curated subjects.
    """
    system = SYSTEM
    pack = _get_pack(cfg)
    hits = pack.retrieve(question) if pack else []
    if hits:
        material = "\n\n".join(f"{c['title']}: {c['text']}" for c in hits)
        system += GROUNDING.format(material=material)
    return system, hits


def _fallback_sentences(hits: list[dict]) -> Iterator[str]:
    """No LLM reachable: speak the pack's pre-written explanation (or UNKNOWN).

    This is the hardcoded-first path — the device still teaches with no
    llama-server at all, which is also the production offline-degraded floor.
    """
    text = hits[0].get("explain") or hits[0]["text"] if hits else UNKNOWN
    sentences, rest = split_ready_sentences(text + " ")
    yield from sentences
    if rest.strip():
        yield rest.strip()


def visible_text(raw: str) -> str:
    """Drop completed <think>...</think> blocks and hold back an unclosed one."""
    raw = _THINK_PAIR.sub("", raw)
    open_tag = raw.find("<think>")
    return raw if open_tag == -1 else raw[:open_tag]


def split_ready_sentences(buf: str) -> tuple[list[str], str]:
    """Return (complete sentences, trailing remainder) for a growing buffer."""
    parts = _SENTENCE_END.split(buf)
    return [p.strip() for p in parts[:-1] if p.strip()], parts[-1]


def stream_sentences(question: str, cfg: dict) -> Iterator[str]:
    t = cfg["tutor"]
    system, hits = _system_prompt(question, cfg)
    try:
        resp = requests.post(
            f"{t['llama_url']}/v1/chat/completions",
            json={
                "stream": True,
                "temperature": t["temperature"],
                "top_p": 0.8,  # Qwen3 recommended non-thinking sampling
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": question},
                ],
            },
            timeout=t["timeout_s"],
            stream=True,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  tutor: llama-server unreachable ({e.__class__.__name__}), "
              f"using pack fallback", flush=True)
        yield from _fallback_sentences(hits)
        return
    raw, yielded = "", 0
    try:
        # chunk_size=1: iter_lines buffers 512B by default, which would hold
        # completed sentences back until generation ends — the exact latency
        # this streaming path exists to remove.
        for line in resp.iter_lines(decode_unicode=True, chunk_size=1):
            if not line or not line.startswith("data: "):
                continue
            data = line[len("data: "):]
            if data == "[DONE]":
                break
            delta = json.loads(data)["choices"][0]["delta"].get("content") or ""
            raw += delta
            vis = visible_text(raw)
            if len(vis) >= t["max_reply_chars"]:
                break
            sentences, _ = split_ready_sentences(vis)
            for s in sentences[yielded:]:
                yield s
                yielded += 1
    finally:
        resp.close()
    sentences, rest = split_ready_sentences(visible_text(raw))
    for s in sentences[yielded:]:
        yield s
    if rest.strip():
        yield rest.strip()
