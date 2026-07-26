"""Local TTS via Piper Python API (spec §7). Stays default even after cloud lands."""
from __future__ import annotations

import tempfile
import wave

from piper import PiperVoice

_voices: dict[str, PiperVoice] = {}


def _load(model_path: str) -> PiperVoice:
    voice = _voices.get(model_path)
    if voice is None:
        voice = PiperVoice.load(model_path)
        _voices[model_path] = voice
    return voice


def preload(cfg: dict) -> None:
    """Load the voice before the first turn.

    Measured on the Pi 5 bench: the first synthesize() pays ~2.1s of ONNX
    voice load, every later one ~0.3s. Without this the first learner of the
    day wears that load as latency.
    """
    _load(cfg["tts"]["voice"])


def synthesize(text: str, cfg: dict) -> str:
    voice = _load(cfg["tts"]["voice"])
    out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(out.name, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
    return out.name
