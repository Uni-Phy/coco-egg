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
        # Trailing silence that ends an utterance. 1.1, not 1.2, because 1.1
        # is what the device has always actually used: int(1.2/0.1) is 11,
        # not 12. The rounding is fixed in audio/io.py; the default is set
        # to the measured behaviour so nothing silently got slower.
        "silence_stop_s": 1.1,
        # RMS threshold, tuned on the M0 bench (Pi 5 + eMeet M0 Plus). Measured
        # there: room noise floor sits at 0.00003 rms, while real speech sags to
        # 0.014 mid-sentence. At the old 0.010 a learner who paused to think got
        # cut off mid-question ("What is the" instead of the whole sentence), so
        # this sits well under the speech sag and still 150x over the noise floor.
        "silence_rms": 0.005,
        # Give up if nobody starts talking at all. Distinct from silence_stop_s,
        # which only applies once speech HAS started — with none, the recorder
        # ran to max_utterance_s and a button press with no question bought 30
        # seconds of dead air (measured on the device). 4s is long enough to
        # draw breath and short enough that a miss reads as a miss rather than
        # as a hang. 0 disables it.
        "no_speech_s": 4.0,
        # Where the spoken reply comes out.
        #   "device"  aplay only, the way it has always worked
        #   "browser" the console plays it, so a phone is the speaker and an
        #             egg needs no speaker hardware at all
        #   "both"    for a demo where the room hears it and phones do too
        # Browser playback needs a tap on the page first: no browser will
        # autoplay audio without a gesture, whatever we do here.
        "output": "device",
    },
    "asr": {
        # "whisper" (whisper.cpp via whisper-server) or "moonshine" (in-process
        # moonshine-voice). Whisper stays default until the on-device A/B is in.
        "backend": "whisper",
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
        # This is a CAP, not a fixed depth — the window grows to it and then
        # drops back in one go, because evicting one turn per turn shifted the
        # prefix and re-prefilled the whole conversation every time (measured:
        # 74 tokens appending vs 203 evicting). 0 disables it. See
        # tutor/history.py.
        "history_turns": 4,
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
        # Jokes the device can tell (tutor/jokes.py). NOT a content pack and
        # never loaded into the retrieval corpus — a joke that can be retrieved
        # will eventually be retrieved for a real question. "" disables them.
        "jokes": "fixtures/jokes.json",
        # The egg's introduction, spoken VERBATIM (tutor/intro.py). The one mode
        # where the exact words are the point, so they are authored rather than
        # generated and never go near the model. "" disables it.
        "intro": "fixtures/intro.json",
        # Where the no-repeat decks remember what has already been told
        # (tutor/deck.py). Under state/ because that is the only writable path
        # mounted into the container; without it a restart mid-party deals the
        # same opener again, which is the one repeat anybody notices.
        "jokes_deck": "state/jokes-deck.json",
        "quiz_deck": "state/quiz-deck",
    },
    "tts": {
        "voice": "models/en_US-lessac-medium.onnx",
    },
    "sync": {
        "transcript_dir": "transcripts",   # buffered locally; SYNC state ships these
    },
    "console": {
        # Student view (an LED-ring prototype driven by presentation.CUES) plus
        # a dev trace, on one page. See coco_egg/console/.
        #
        # NO AUTHENTICATION YET, and the events carry what a child said aloud.
        # It serves only LIVE events — never stored transcripts — and is meant
        # for a LAN you control while somebody is watching it. Set enabled:false
        # for anything else until auth lands.
        "enabled": True,
        "host": "0.0.0.0",
        "port": 8090,
        # HTTPS with a self-signed certificate. Not decoration: a browser
        # refuses getUserMedia outside a secure context, so without this a
        # phone cannot be the egg's MICROPHONE at all. The cost is a "not
        # private" warning to tap through once per phone. false serves plain
        # HTTP — the page and the speaker still work, the microphone does not.
        "tls": True,
        "cert_dir": "state",
        # Addresses a phone will type. `hostname -I` sees only the CONTAINER's
        # address, so the LAN address has to be named here or the certificate
        # mismatches and the browser warning gets harsher. Both phone-hotspot
        # ranges are already covered automatically. Delete state/console-cert.pem
        # after changing this to force a regeneration.
        "cert_hosts": [],
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
    # Name the BACKEND, not a URL that may not be in use. This line printed
    # "whisper: http://whisper:8081" while moonshine was running and the whisper
    # server was untouched — it is the one line you read to find out which ASR
    # is live, and it said the wrong thing.
    backend = cfg["asr"].get("backend", "whisper")
    asr = (f"{backend} (in-process)" if backend == "moonshine"
           else f"{backend} {cfg['asr']['whisper_url']}")
    # The same trap as the ASR line above, and it cost a debugging session: this
    # named an ALSA device while audio.output was "browser", so the one line you
    # read to find out where sound comes out said "the eMeet" about a speaker
    # that was deliberately silent. Name the routing, not just the hardware.
    where = cfg["audio"].get("output", "device")
    speaker = cfg["audio"]["output_device"]
    out = {"browser": "browser only — device speaker is SILENT",
           "both": f"{speaker} + browser"}.get(where, speaker)
    return "\n".join([
        f"  audio in:   {cfg['audio']['input_device']}",
        f"  audio out:  {out}",
        f"  asr:        {asr}",
        f"  llama:      {cfg['tutor']['llama_url']}",
        f"  embed:      {cfg['tutor']['embed_url']}",
        f"  tts voice:  {cfg['tts']['voice']}\n",
    ])
