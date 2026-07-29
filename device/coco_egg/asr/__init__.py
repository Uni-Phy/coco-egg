"""ASR backend selection.

`cfg["asr"]["backend"]` picks whisper or moonshine
(in-process, per-chunk streaming). Both back the same public shape
so main.py and tests don't care which one is live. Moonshine's imports are
lazy — ONNX Runtime never loads when whisper is selected.
"""
from __future__ import annotations

from .streaming import StreamingTranscriber as _WhisperStreaming
from .whisper_local import transcribe as _whisper_transcribe


def preload(cfg: dict) -> None:
    """Pay backend startup costs before the first turn.
    moonshine downloads + loads the ONNX model."""
    if cfg["asr"].get("backend") == "moonshine":
        from .moonshine_local import preload as _pre
        _pre(cfg)


def transcribe(wav_path: str, cfg: dict) -> str:
    if cfg["asr"].get("backend") == "moonshine":
        from .moonshine_local import transcribe as _tx
        return _tx(wav_path, cfg)
    return _whisper_transcribe(wav_path, cfg)


def StreamingTranscriber(cfg: dict):
    if cfg["asr"].get("backend") == "moonshine":
        from .moonshine_local import StreamingTranscriber as _ST
        return _ST(cfg)
    return _WhisperStreaming(cfg)
