"""Configuration for the coco-egg device app.

All paths/models are overridable via /etc/coco/egg.yaml (device) or
./egg.yaml (bench). Defaults target M0 bench: Pi 5 + eMeet M0 Plus.
"""
from __future__ import annotations

import pathlib
import yaml

DEFAULTS = {
    "audio": {
        # USB audio class device (eMeet M0 Plus). "default" lets ALSA pick;
        # override with the exact device name from `python -m sounddevice`.
        "input_device": "default",
        "output_device": "default",
        "sample_rate": 16000,
        "max_utterance_s": 30,
        "silence_stop_s": 1.2,   # stop recording after this much trailing silence
        "silence_rms": 0.010,    # RMS threshold; tune on the bench
    },
    "asr": {
        # Path to whisper.cpp CLI binary and model. Bench: build whisper.cpp
        # and download ggml-base.en (or small) into models/.
        "whisper_bin": "whisper-cli",
        "model": "models/ggml-base.en.bin",
        "language": "en",
    },
    "tutor": {
        # Local LLM served by Ollama (same pattern as common-os).
        "ollama_url": "http://127.0.0.1:11434",
        "model": "llama3.2:3b",      # placeholder; swap for chosen small model
        "timeout_s": 30,
        "max_reply_chars": 600,       # keep spoken answers short
    },
    "tts": {
        "piper_bin": "piper",
        "voice": "models/en_US-lessac-medium.onnx",
    },
    "sync": {
        "transcript_dir": "transcripts",   # buffered locally; SYNC state ships these
    },
    "trigger": {
        "mode": "keyboard",   # bench: spacebar. Device: "gpio" (M1, XVF3800 GPI)
    },
}


def load(path: str | None = None) -> dict:
    cfg = {k: dict(v) for k, v in DEFAULTS.items()}
    for candidate in ([path] if path else []) + ["egg.yaml", "/etc/coco/egg.yaml"]:
        if candidate and pathlib.Path(candidate).exists():
            user = yaml.safe_load(pathlib.Path(candidate).read_text()) or {}
            for section, values in user.items():
                cfg.setdefault(section, {}).update(values or {})
            break
    return cfg
