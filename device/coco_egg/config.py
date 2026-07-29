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
        # whisper.cpp whisper-server. whisper docker service by default;
        # override to 127.0.0.1:8081 for a locally-run whisper-server.
        "whisper_url": "http://whisper:8081",
        "language": "en",
        "timeout_s": 30,
        # Streaming ASR (see asr/streaming.py).
        "stream_min_voiced_s": 0.8,
        "stream_speculate_after_s": 0.6,
    },
    "tutor": {
        # Qwen3-0.6B via llama-server (llama.cpp).
        # Using the llama-cpp service from docker container by default.
        # For testing with locally installed llama-cpp, override in egg.yaml:
        # `tutor: {llama_url: http://127.0.0.1:8080}`.
        # The served model is whatever the server loaded, so no name here.
        "llama_url": "http://llama-tutor:8080",
        "temperature": 0.7,           # Qwen3 recommended non-thinking sampling
        "timeout_s": 30,
        "max_reply_chars": 600,       # keep spoken answers short
        # Curriculum content pack(s) (spec §7 RAG). A file, a DIRECTORY of
        # packs, or a list of either — a directory is the shape to use once
        # subjects are a library: drop a pack in, it gets taught, and the set
        # of loaded packs *is* the list of supported subjects. Merging also
        # sharpens retrieval, since idf is a whole-corpus statistic.
        # Real packs come from the CoCo node; this is the fixture.
        "pack": "fixtures/packs",
        # Optional YAML file describing the learner. Falls back to an inline
        # `learner:` block in egg.yaml. Schema-free on purpose — see
        # tutor/profile.py.
        "profile": "learner.yaml",
        # Written by tutor/profile_builder.py from transcripts, and merged
        # UNDER the hand-written profile above — observation fills gaps, it
        # does not overrule a person. "" disables the builder.
        # Lives under state/ because that is the only writable path mounted
        # into the container: anything else lands in the container layer and is
        # lost on `make build`, which would silently reset a learner's profile
        # every deploy.
        "profile_derived": "state/learner-derived.yaml",
        # Prior turns kept so a follow-up has something to follow ("why?",
        # "tell me more"). They sit ABOVE the retrieved material in the prompt,
        # which is what makes them nearly free: history is append-only, so it
        # lands in llama-server's cached prefix instead of being re-prefilled.
        # 0 disables it. See tutor/history.py.
        "history_turns": 3,
        # How many retrieved chunks are quoted in full. The rest are named
        # only. Three full chunks cost ~422 prompt tokens (~2.8s of a ~3.5s
        # answer) and were mostly near-ties of the same topic. See _material().
        "grounding_full_chunks": 1,
        # Sentence-embedding server for retrieval. llama-embed docker service
        # by default; override to 127.0.0.1:8082 for `make serve-embed`.
        # Unreachable => lexical fallback (see tutor/embed.py).
        "embed_url": "http://llama-embed:8082",
        "embed_timeout_s": 20,
        "embed_cache": "state/.embed-cache",
        # Questions in one round of quiz mode (tutor/quiz.py). Short on
        # purpose: the game has to end while a child still wants more of it.
        "quiz_questions": 5,
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

def summary(cfg: dict) -> str:
    return "\n".join([
        f"  audio in:   {cfg['audio']['input_device']}",
        f"  audio out:  {cfg['audio']['output_device']}",
        f"  whisper:    {cfg['asr']['whisper_url']}",
        f"  llama:      {cfg['tutor']['llama_url']}",
        f"  embed:      {cfg['tutor']['embed_url']}",
        f"  tts voice:  {cfg['tts']['voice']}\n",
    ])
