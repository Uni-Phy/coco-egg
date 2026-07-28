"""Local ASR via whisper.cpp whisper-server (spec §7). Swappable behind transcribe()."""
from __future__ import annotations

import io
import re
import wave

import numpy as np
import requests

# Whisper marks non-speech input with bracket tags — [BLANK_AUDIO], [MUSIC],
# (silence), [Applause]. Sent to the LLM they read as a literal question and
# the model politely improvises, so a button press with no speech comes back
# as a generic tutor intro. Strip these; if nothing is left, it was silence.
_TAG = re.compile(r"[\[\(][^\]\)]*[\]\)]")


def transcribe(wav_path: str, cfg: dict) -> str:
    """Batch entry: POST an existing WAV file to whisper-server /inference."""
    url = f"{cfg['asr']['whisper_url']}/inference"
    print(f"  whisper: POST {url}", flush=True)
    with open(wav_path, "rb") as f:
        return _post(url, f, cfg)


def transcribe_np(audio: np.ndarray, sr: int, cfg: dict) -> str:
    """Streaming entry: pack an int16 mono buffer into a WAV in memory and POST."""
    url = f"{cfg['asr']['whisper_url']}/inference"
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(audio.tobytes())
    buf.seek(0)
    return _post(url, buf, cfg)


def _post(url: str, wav_file, cfg: dict) -> str:
    a = cfg["asr"]
    resp = requests.post(
        url,
        files={"file": ("audio.wav", wav_file, "audio/wav")},
        data={"language": a["language"], "response_format": "json"},
        timeout=a["timeout_s"],
    )
    resp.raise_for_status()
    text = (resp.json().get("text") or "").strip()
    if text and not _TAG.sub("", text).strip():
        text = ""
    if not text:
        print("  whisper: no speech detected", flush=True)
    return text
