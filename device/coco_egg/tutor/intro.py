"""The egg's introduction, spoken exactly as written.

The one mode where the words are the point. A manifesto that comes out slightly
different each time is not a manifesto, and a 1.7B asked to introduce itself
returns "I'm CoCo, your friendly voice tutor!" — pleasant, and not what this is.
So the lines live in fixtures/intro.json and are spoken verbatim, with no model
anywhere near them. A test asserts the spoken text still equals the file.

Delivery is why it reads as lines rather than a paragraph. The device speaks one
line, synthesises the next, then plays it, so **the line break is the pause**.
"They said intelligence would be metered and billed." and "We said: intelligence
belongs to the people." are two entries because the beat between them is the
call and response; as one string they run together and it is gone.

Free of the LLM, so it costs only TTS and cannot be paraphrased, shortened, or
embellished on the night.
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Iterator

# Deliberately generous, because this is the demo opener and it has to fire on
# whatever the ASR returns. "who are you" is included on purpose: it is what
# people actually ask an unfamiliar object, and this IS the answer.
_ASK = re.compile(
    r"\bintroduce\s+(yourself|you)\b|\bintroduction\b|\byour\s+intro\b"
    r"|\b(do|say|give)\s+(your|the)\s+intro\b"
    r"|\bwho\s+(are|r)\s+(you|u)\b|\bwhat\s+are\s+you\b"
    r"|\btell\s+(me|us)\s+about\s+(yourself|you)\b", re.I)

_lines: list[str] | None = None


def _load(cfg: dict) -> list[str]:
    global _lines
    if _lines is not None:
        return _lines
    path = cfg["tutor"].get("intro")
    _lines = []
    if path and pathlib.Path(path).is_file():
        try:
            data = json.loads(pathlib.Path(path).read_text())
            _lines = [ln for ln in data.get("lines", []) if ln.strip()]
        except (ValueError, OSError) as e:
            print(f"  intro: could not load {path} ({e.__class__.__name__})", flush=True)
    return _lines


def is_request(text: str) -> bool:
    return bool(_ASK.search(text or ""))


def speak(cfg: dict) -> Iterator[str]:
    """The introduction, one line at a time, exactly as written."""
    lines = _load(cfg)
    if not lines:
        yield "I don't have my introduction loaded yet."
        return
    yield from lines


def text(cfg: dict) -> str:
    """The whole introduction as one string — for checking it is still exact."""
    return "\n".join(_load(cfg))
