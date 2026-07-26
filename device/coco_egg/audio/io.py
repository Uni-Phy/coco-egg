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


def resolve_input(cfg: dict) -> int | None:
    """Pick the capture device from cfg, print it, or raise if missing."""
    name = cfg["audio"]["input_device"]
    inputs = [(i, d) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
    if not inputs:
        raise RuntimeError(
            "no capture devices found. Is the USB mic plugged in?"
        )
    if name == "default":
        picked = sd.query_devices(kind="input")
        index = None
    else:
        match = next(((i, d) for i, d in inputs if name.lower() in d["name"].lower()), None)
        if not match:
            listing = "\n  ".join(f"[{i}] {d['name']}" for i, d in inputs)
            raise RuntimeError(f"input device {name!r} not found. Available:\n  {listing}")
        index, picked = match
    print(
        f"audio: input = {picked['name']!r} "
        f"(native {int(picked['default_samplerate'])} Hz, requested {cfg['audio']['sample_rate']} Hz)",
        flush=True,
    )
    return index


def record_utterance(cfg: dict) -> np.ndarray:
    """Record until trailing silence or max length. Returns int16 mono @16k."""
    a = cfg["audio"]
    sr = a["sample_rate"]
    block = int(sr * 0.1)
    silence_blocks_needed = int(a["silence_stop_s"] / 0.1)
    max_blocks = int(a["max_utterance_s"] / 0.1)

    device = resolve_input(cfg)
    chunks: list[np.ndarray] = []
    silent = 0
    voiced_yet = False
    with sd.InputStream(samplerate=sr, channels=1, dtype="int16",
                        device=device,
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
    # aplay keeps us out of format-conversion trouble. Honor output_device
    # when set so egg.yaml pinning actually lands, not just the ALSA default.
    dev = cfg["audio"]["output_device"]
    args = ["aplay", "-q"]
    if dev != "default":
        args += ["-D", dev]
    args.append(path)
    subprocess.run(args, check=False)
