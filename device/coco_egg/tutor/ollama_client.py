"""Local tutor LLM via Ollama (same server pattern as common-os)."""
from __future__ import annotations

import requests

from .prompts import DEFAULT_SCOPE, SYSTEM


def answer(question: str, cfg: dict) -> str:
    t = cfg["tutor"]
    resp = requests.post(
        f"{t['ollama_url']}/api/chat",
        json={
            "model": t["model"],
            "stream": False,
            "messages": [
                {"role": "system", "content": SYSTEM.format(scope=DEFAULT_SCOPE)},
                {"role": "user", "content": question},
            ],
        },
        timeout=t["timeout_s"],
    )
    resp.raise_for_status()
    text = resp.json().get("message", {}).get("content", "").strip()
    return text[: t["max_reply_chars"]]
