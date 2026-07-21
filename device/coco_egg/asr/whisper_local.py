"""Local ASR via whisper.cpp CLI (spec §7). Swappable behind transcribe()."""
from __future__ import annotations

import subprocess


def transcribe(wav_path: str, cfg: dict) -> str:
    a = cfg["asr"]
    out = subprocess.run(
        [a["whisper_bin"], "-m", a["model"], "-l", a["language"],
         "-f", wav_path, "--no-timestamps", "--no-prints"],
        capture_output=True, text=True, timeout=120,
    )
    return out.stdout.strip()
