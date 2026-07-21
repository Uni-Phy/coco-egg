"""Audio capture/playback via the USB audio class device (eMeet M0 Plus).

The M0 Plus does AEC/NR/AGC in hardware, so we deliberately do NOT add
software echo cancellation here. Keep this layer dumb: record 16k mono,
stop on trailing silence, play wav files.
"""
from __future__ import annotations

import subprocess
import tempfile
import wave

import numpy as np
import sounddevice as sd


def record_utterance(cfg: dict) -> np.ndarray:
    """Record until trailing silence or max length. Returns int16 mono @16k."""
    a = cfg["audio"]
    sr = a["sample_rate"]
    block = int(sr * 0.1)
    silence_blocks_needed = int(a["silence_stop_s"] / 0.1)
    max_blocks = int(a["max_utterance_s"] / 0.1)

    chunks: list[np.ndarray] = []
    silent = 0
    voiced_yet = False
    with sd.InputStream(samplerate=sr, channels=1, dtype="int16",
                        device=a["input_device"] if a["input_device"] != "default" else None,
                        blocksize=block) as stream:
        for _ in range(max_blocks):
            data, _ = stream.read(block)
            mono = data[:, 0]
            chunks.append(mono.copy())
            rms = float(np.sqrt(np.mean((mono.astype(np.float32) / 32768.0) ** 2)))
            if rms >= a["silence_rms"]:
                voiced_yet, silent = True, 0
            elif voiced_yet:
                silent += 1
                if silent >= silence_blocks_needed:
                    break
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)


def write_wav(audio: np.ndarray, sr: int) -> str:
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(f.name, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(audio.tobytes())
    return f.name


def play_wav(path: str, cfg: dict) -> None:
    # aplay keeps us on the ALSA default (the M0 Plus) without format fuss.
    subprocess.run(["aplay", "-q", path], check=False)
