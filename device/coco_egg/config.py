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
        # RMS threshold, tuned on the M0 bench (Pi 5 + eMeet M0 Plus). Measured
        # there: room noise floor sits at 0.00003 rms, while real speech sags to
        # 0.014 mid-sentence. At the old 0.010 a learner who paused to think got
        # cut off mid-question ("What is the" instead of the whole sentence), so
        # this sits well under the speech sag and still 150x over the noise floor.
        "silence_rms": 0.005,
    },
    "asr": {
        # Path to whisper.cpp CLI binary and model. Bench: build whisper.cpp
        # and download ggml-base.en (or small) into models/.
        "whisper_bin": "whisper-cli",
        "model": "models/ggml-base.en.bin",
        "language": "en",
    },
    "tutor": {
        # Qwen3-1.7B via llama-server (llama.cpp) — locked, spec decision #8.
        # Start it with `make serve`; the served model is whatever the server
        # loaded, so there is no model name here.
        "llama_url": "http://127.0.0.1:8080",
        "temperature": 0.7,           # Qwen3 recommended non-thinking sampling
        "timeout_s": 30,
        "max_reply_chars": 600,       # keep spoken answers short
        # Curriculum content pack (spec §7 RAG). Retrieval grounds the LLM;
        # with no LLM reachable the pack's canned explanations are spoken
        # directly. Real packs come from the CoCo node; this is the fixture.
        "pack": "fixtures/content-pack.json",
    },
    "tts": {
        "voice": "models/en_US-lessac-medium.onnx",
    },
    "sync": {
        "transcript_dir": "transcripts",   # buffered locally; SYNC state ships these
    },
    "trigger": {
        "mode": "keyboard",   # bench: Enter key. Device: "gpio" (M1, XVF3800 GPI)
    },
    "bench": {
        # Headless bench inputs. Used by the `w`/`q`/`r` keys in main.run() to
        # exercise the pipeline without a microphone. Replace sample_question.wav
        # with a real recording (e.g. `arecord -f S16_LE -r 16000 -c 1 -d 3 …`)
        # for meaningful STT output; the shipped file is a placeholder.
        "sample_wav": "fixtures/sample_question.wav",
        "sample_question": "fixtures/sample_question.txt",
        "sample_reply": "fixtures/sample_reply.txt",
    },
}


def load(path: str | None = None) -> dict:
    cfg = {k: dict(v) for k, v in DEFAULTS.items()}
    for candidate in ([path] if path else []) + ["egg.yaml", "/etc/coco/egg.yaml"]:
        if candidate and pathlib.Path(candidate).exists():
            if not pathlib.Path(candidate).is_file():
                raise SystemExit(
                    f"coco-egg: {candidate} is a directory, not a file -"
                    f"remove it and use 'make up' to start the stack."
                )
            user = yaml.safe_load(pathlib.Path(candidate).read_text()) or {}
            for section, values in user.items():
                cfg.setdefault(section, {}).update(values or {})
            break
    return cfg
