"""Local tutor LLM via llama-server (llama.cpp), OpenAI-compatible API.

Tutor stack: Qwen3-0.6B Q4_K_M, thinking disabled.
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
import time
from typing import Iterator

import requests

from .. import events
from . import profile
from .history import DEFAULT_TURNS, History
from .pack import Pack
from .prompts import GROUNDING, LEARNER, SYSTEM, UNKNOWN

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_THINK_PAIR = re.compile(r"<think>.*?</think>", re.DOTALL)

# Emoji and pictographs. The reply is SPOKEN, and a smiley either gets read out
# as a word salad or lands in the WAV as mojibake — the 0.6B ends cheerful
# answers with one far more often than the 1.7B did. Deliberately targets the
# pictograph blocks only, not all non-ASCII: Hindi/Marathi packs must survive.
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002190-\U000021FF\U00002300-\U000027BF"
    "\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F\U0001F1E6-\U0001F1FF]+"
)

_pack: Pack | None = None
_history = History(DEFAULT_TURNS)


def _get_pack(cfg: dict) -> Pack | None:
    global _pack
    if _pack is None:
        _pack = Pack.load_config(cfg["tutor"].get("pack"))
        if _pack:
            print(f"  pack: {len(_pack.chunks)} chunks across "
                  f"{len(_pack.subjects) or 1} subject(s): "
                  f"{', '.join(_pack.subjects) or _pack.topic}", flush=True)
    return _pack


def _static_system(cfg: dict) -> str:
    """The part of the prompt that does not change from turn to turn.

    Stays first because llama-server reuses the longest common PREFIX: every
    token before the first change is free on later turns, and everything from
    the change onward is recomputed.
    """
    system = SYSTEM
    learner = profile.describe(profile.load(cfg))
    if learner:
        system += LEARNER.format(learner=learner)
    return system


def _retrieve(question: str, cfg: dict) -> list[dict]:
    """Pack chunks for this question — semantic, falling back to lexical.

    Lexical only fires when a learner happens to use the pack's own words,
    which measured 0/7 on natural phrasing, so it is a degraded mode rather
    than an equal path.
    """
    pack = _get_pack(cfg)
    if not pack:
        return []
    hits = pack.retrieve_semantic(question, cfg)
    if hits is None:
        events.emit("degraded", component="embed", fallback="lexical")
        hits = pack.retrieve(question)
    return hits


def build_messages(question: str, cfg: dict) -> tuple[list[dict], list[dict]]:
    """Messages ordered by VOLATILITY: static first, most-changing last.

    Grounding used to live inside the system message — the most-cached
    position holding the most-volatile content. Measured on the bench, that
    cost ~26 tokens of extra recompute for every turn of conversation kept,
    growing without bound, because a new question changed the prompt at
    position ~141 and invalidated everything after it. With the material moved
    down beside the question, the computed count stays flat at ~423 tokens no
    matter how deep the conversation goes.

    So the ordering is the design, not a detail: anything appended here after
    the volatile tail is free, and anything inserted above it is paid for on
    every subsequent turn.
    """
    hits = _retrieve(question, cfg)
    turn = question
    if hits:
        material = "\n\n".join(f"{c['title']}: {c['text']}" for c in hits)
        turn = GROUNDING.format(material=material).strip() + "\n\n" + question
    prior = _history.messages() if cfg["tutor"].get("history_turns", 0) else []
    return ([{"role": "system", "content": _static_system(cfg)}]
            + prior
            + [{"role": "user", "content": turn}]), hits


def remember(question: str, reply: str, cfg: dict) -> None:
    """Record a finished turn so the next one can refer back to it.

    Called after the reply is complete rather than as it streams: a turn that
    was interrupted is not something the learner heard, and should not be
    something the tutor thinks it said.
    """
    if cfg["tutor"].get("history_turns", 0):
        _history.add(question, reply)


def forget() -> None:
    """Drop the conversation — a new learner must not inherit the last one."""
    _history.clear()


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
    """Speakable text: no <think> blocks, no emoji, no unclosed tag leaking."""
    raw = _EMOJI.sub("", _THINK_PAIR.sub("", raw))
    open_tag = raw.find("<think>")
    return raw if open_tag == -1 else raw[:open_tag]


def split_ready_sentences(buf: str) -> tuple[list[str], str]:
    """Return (complete sentences, trailing remainder) for a growing buffer."""
    parts = _SENTENCE_END.split(buf)
    return [p.strip() for p in parts[:-1] if p.strip()], parts[-1]


def stream_sentences(question: str, cfg: dict) -> Iterator[str]:
    """Reply sentences, published to the event bus as the model produces them.

    Split from _stream() only for the console: a sentence is emitted the
    moment it is generated (not when it is spoken), and retrieval is timed
    apart from generation so the trace shows where the ~5s actually goes.
    Both are lazy — nothing runs until the caller pulls the first sentence.
    """
    t0 = time.monotonic()
    messages, hits = build_messages(question, cfg)
    events.emit("stage", stage="retrieval", seconds=round(time.monotonic() - t0, 3))
    t0 = time.monotonic()
    for i, sentence in enumerate(_stream(messages, hits, cfg)):
        if i == 0:
            events.emit("stage", stage="llm_first_sentence",
                        seconds=round(time.monotonic() - t0, 3))
        events.emit("sentence", index=i, text=sentence)
        yield sentence


def _stream(messages: list[dict], hits: list[dict], cfg: dict) -> Iterator[str]:
    t = cfg["tutor"]
    try:
        resp = requests.post(
            f"{t['llama_url']}/v1/chat/completions",
            json={
                "stream": True,
                "temperature": t["temperature"],
                "top_p": 0.8,  # Qwen3 recommended non-thinking sampling
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": messages,
            },
            timeout=t["timeout_s"],
            stream=True,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  tutor: llama-server unreachable ({e.__class__.__name__}), "
              f"using pack fallback", flush=True)
        events.emit("degraded", component="llama", fallback="pack",
                    error=e.__class__.__name__)
        yield from _fallback_sentences(hits)
        return
    # requests falls back to ISO-8859-1 for text/* with no charset in the
    # header, and iter_lines(decode_unicode=True) honours that — so every
    # multi-byte character arrived mangled: an emoji became four latin-1
    # chars (slipping past the pictograph strip, which matches real
    # codepoints), apostrophes and dashes became "a€™"-style debris, and
    # "पानी" became "à¤ªà¤¾à¤¨à¥". Piper was being handed that to read aloud.
    # llama-server emits UTF-8; say so.
    resp.encoding = "utf-8"
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
