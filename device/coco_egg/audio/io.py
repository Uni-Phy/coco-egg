"""Audio capture/playback via the USB audio class device (eMeet M0 Plus).

The M0 Plus does AEC/NR/AGC in hardware, so we deliberately do NOT add
software echo cancellation here. Keep this layer dumb: record 16k mono,
stop on trailing silence, play wav files.
"""
from __future__ import annotations

import subprocess
import tempfile
import time
import wave
from typing import Callable

import numpy as np
import sounddevice as sd

BlockCallback = Callable[[np.ndarray, bool], None]


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


# What the last real recording attempt proved, or None before there has been
# one. PortAudio enumerates devices ONCE per process, so in a daemon that has
# been up for hours query_devices() answers "what was plugged in at startup" —
# it happily listed a USB mic that had since been unplugged, /health repeated
# that, and the page therefore never fell back to the phone. An actual capture
# attempt cannot be stale, so it outranks the enumeration.
_capture_worked: bool | None = None


def note_capture(ok: bool) -> None:
    """Record whether opening the microphone actually worked."""
    global _capture_worked
    _capture_worked = ok


def has_input() -> bool:
    """Whether this device has a microphone that actually opens.

    The console asks so a phone can default to being the microphone when the
    egg has none. Without it the obvious action — tap the egg — fails with a
    hardware error that is true, unactionable from a phone, and reads to a
    visitor as the whole device being broken.

    Answers False rather than raising: this is a question about hardware, and
    every caller wants a fallback, not an exception.
    """
    if _capture_worked is not None:
        return _capture_worked
    try:
        return any(d["max_input_channels"] > 0 for d in sd.query_devices())
    except (OSError, sd.PortAudioError):
        return False


def record_utterance(cfg: dict, on_block: BlockCallback | None = None) -> tuple[np.ndarray, float]:
    """Record until trailing silence or max length.

    Returns (int16 mono @16k, monotonic time of end-of-speech). The second
    value is when the learner stopped talking, NOT when this returns — the
    silence_stop_s hangover sits between the two. The learner waits through
    that hangover, so latency has to be measured from end-of-speech or M0
    under-reports itself by silence_stop_s (spec §16 says measure honestly).

    `on_block(chunk, is_silent)` fires inline once per 100 ms block; the
    streaming transcriber (asr/streaming.py) uses it to overlap ASR with
    speech. Runs on this thread — must not block.
    """
    a = cfg["audio"]
    sr = a["sample_rate"]
    block = int(sr * 0.1)
    # round(), not int(): 1.2 / 0.1 is 11.999999999999998 in floating point, so
    # int() silently truncated a configured 1.2s hangover to 1.1s and a 30s cap
    # to 29.9s. The defaults were lowered to match what the device was actually
    # doing, so this fixes the arithmetic without changing behaviour.
    silence_blocks_needed = round(a["silence_stop_s"] / 0.1)
    max_blocks = round(a["max_utterance_s"] / 0.1)
    # Separate from silence_stop_s, which only applies once speech has STARTED.
    # With no speech at all the recorder ran to max_utterance_s, so pressing the
    # button and saying nothing bought 30 seconds of dead air — measured on the
    # device as a hangover of 30.048s. In front of an audience that is the worst
    # failure mode the loop has, because it looks like a hang rather than a miss.
    # 0 restores the old behaviour.
    give_up_blocks = round(a.get("no_speech_s", 0) / 0.1)

    # Opening the stream is the only honest test of whether a microphone is
    # there: PortAudio's device list is enumerated once per process and goes
    # stale the moment somebody unplugs the USB mic. Both outcomes are recorded
    # so /health — and therefore the phone — learns from the attempt.
    try:
        device = resolve_input(cfg)
        stream = sd.InputStream(samplerate=sr, channels=1, dtype="int16",
                                device=device, blocksize=block)
    except (RuntimeError, OSError, sd.PortAudioError):
        note_capture(False)
        raise
    note_capture(True)

    chunks: list[np.ndarray] = []
    silent = 0
    voiced_yet = False
    speech_end = time.monotonic()
    with stream:
        for elapsed_blocks in range(max_blocks):
            data, _ = stream.read(block)
            mono = data[:, 0]
            chunk = mono.copy()
            chunks.append(chunk)
            rms = float(np.sqrt(np.mean((mono.astype(np.float32) / 32768.0) ** 2)))
            is_silent = rms < a["silence_rms"]
            if not is_silent:
                voiced_yet, silent = True, 0
                speech_end = time.monotonic()
            elif voiced_yet:
                silent += 1
            if on_block is not None:
                on_block(chunk, is_silent)
            if voiced_yet and is_silent and silent >= silence_blocks_needed:
                break
            # Nobody started talking. Give the turn back rather than holding the
            # room. Checked AFTER on_block so the streaming transcriber still
            # sees every block it would have seen.
            if (not voiced_yet and give_up_blocks
                    and elapsed_blocks + 1 >= give_up_blocks):
                return np.zeros(0, dtype=np.int16), speech_end
    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
    return audio, speech_end


def level(audio: np.ndarray) -> tuple[float, float]:
    """(rms, peak) of an utterance, both 0..1. How loud was it, really?

    Without this the recording is the one stage with no measurement, and a
    garbled transcript is unattributable: whisper and moonshine both returned
    nonsense on 2026-07-29 ("Is that hard? created life created life", "Thank
    you for listening.") and there was no way to tell a bad backend from a
    learner who was too far from the mic. Compare against audio.silence_rms:
    an utterance whose rms sits near the silence threshold never had a question
    in it, whatever the transcript claims.
    """
    if audio.size == 0:
        return 0.0, 0.0
    f = audio.astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(f ** 2))), float(np.max(np.abs(f)))


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
