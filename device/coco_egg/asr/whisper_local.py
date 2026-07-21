"""Local ASR via whisper.cpp CLI (spec §7). Swappable behind transcribe()."""
from __future__ import annotations

import subprocess


def transcribe(wav_path: str, cfg: dict) -> str:
    a = cfg["asr"]
    cmd = [a["whisper_bin"], "-m", a["model"], "-l", a["language"],
           "-f", wav_path, "--no-timestamps", "--no-prints"]
    print(f"  whisper: {' '.join(cmd)}", flush=True)
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(
            f"whisper-cli exited {out.returncode}:\n"
            f"{out.stderr.strip() or out.stdout.strip() or '(no output)'}"
        )
    text = out.stdout.strip()
    if not text:
        print(f"  whisper: no speech detected (stderr: {out.stderr.strip() or 'empty'})", flush=True)
    return text
