"""Local TTS via Piper CLI (spec §7). Stays default even after cloud lands."""
from __future__ import annotations

import subprocess
import tempfile


def synthesize(text: str, cfg: dict) -> str:
    t = cfg["tts"]
    out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    subprocess.run(
        [t["piper_bin"], "--model", t["voice"], "--output_file", out.name],
        input=text, text=True, check=True, timeout=60,
    )
    return out.name
