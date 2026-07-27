"""Local ASR via whisper.cpp whisper-server (spec §7). Swappable behind transcribe()."""
from __future__ import annotations

import requests


def transcribe(wav_path: str, cfg: dict) -> str:
    a = cfg["asr"]
    url = f"{a['whisper_url']}/inference"
    print(f"  whisper: POST {url}", flush=True)
    with open(wav_path, "rb") as f:
        resp = requests.post(
            url,
            files={"file": (wav_path, f, "audio/wav")},
            data={"language": a["language"], "response_format": "json"},
            timeout=a["timeout_s"],
        )
    resp.raise_for_status()
    text = (resp.json().get("text") or "").strip()
    if not text:
        print("  whisper: no speech detected", flush=True)
    return text
