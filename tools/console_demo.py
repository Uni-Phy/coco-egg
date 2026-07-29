"""Drive the console with a scripted session — no mic, no models, no device.

    python tools/console_demo.py            # http://localhost:8090
    python tools/console_demo.py --once     # one turn, then exit

The console renders `presentation.CUES`, and until now nothing could exercise
that table end to end without a Pi, a microphone and a person. This publishes
the same events the voice loop does, at roughly the same intervals, so the
student view and the dev trace can be built, reviewed and demoed anywhere.

The script is deliberately not all happy path. It walks a grounded answer, a
question that retrieves nothing, a named subject that is deliberately not
grounded, a degraded turn with the embedding server down, and a turn where
nothing was heard — because those are the cues that are hard to check and easy
to get wrong. The unheard turn in
particular is the one with a min_dwell floor protecting it: a fully degraded
turn can run start to end in milliseconds, and with no floor the ring strobes
through four states inside a single frame.
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "device"))

from coco_egg import config, console, events            # noqa: E402


def wait(seconds: float) -> None:
    time.sleep(seconds)


def state(name: str) -> None:
    events.emit("state", state=name)


def turn(heard, chunks, sentences, *, stages, reason="ok", degraded=None,
         path="semantic", floor=0.62):
    events.begin_turn()
    state("LISTENING")
    wait(1.4)
    if heard is None:
        # Nothing came through. Both no-audio and no-speech say the same thing
        # to a learner — ask me again — and the difference is dev-mode detail.
        events.emit("heard", text="")
        events.end_turn(reason=reason)
        state("IDLE")
        wait(2.2)
        return

    state("THINKING")
    events.emit("stage", stage="hangover", seconds=1.2)
    events.emit("heard", text=heard)
    if degraded:
        events.emit("degraded", component=degraded[0], fallback=degraded[1])
    if chunks is not None:
        events.emit("retrieved", question=heard, path=path, scale="cosine",
                    floor=floor, relative_floor=round(floor * 1.4, 3),
                    chunks=chunks)
    else:
        events.emit("topic" if heard.strip().count(" ") < 2 else "opener", text=heard)
    for name, secs in stages:
        wait(min(secs, 1.6))
        events.emit("stage", stage=name, seconds=secs)

    state("SPEAKING")
    spoken = []
    for i, s in enumerate(sentences):
        events.emit("sentence", index=i, text=s)
        events.emit("spoken", index=i, text=s)
        spoken.append(s)
        wait(1.1)
    events.end_turn(reason="ok", reply=" ".join(spoken),
                    latency_s=round(sum(s for _, s in stages) + 1.2, 3))
    state("IDLE")
    wait(2.0)


SESSION = [
    # Grounded: the common good case, and what the trace is meant to show.
    dict(heard="which star was the moon sitting in when i was born",
         chunks=[{"id": "nakshatra", "title": "Nakshatra", "subject": "Jyotisha",
                  "score": 0.781, "lexical_bonus": True, "kept": True},
                 {"id": "rashi-and-nakshatras", "title": "Rashi and Nakshatras",
                  "subject": "Jyotisha", "score": 0.702, "lexical_bonus": False,
                  "kept": True},
                 {"id": "kundali-map", "title": "Kundali Map", "subject": "Jyotisha",
                  "score": 0.648, "lexical_bonus": False, "kept": False}],
         sentences=["A nakshatra is a patch of sky the moon travels through.",
                    "There are twenty seven of them, one for about each day.",
                    "The one the moon was in when you were born is your birth star."],
         stages=[("retrieval", 0.4), ("llm_first_sentence", 3.5), ("tts", 1.3)]),

    # Retrieves nothing, which is a normal and frequent outcome, not a failure.
    dict(heard="what is game theory", chunks=[],
         sentences=["Game theory is the study of how people choose when the",
                    "result depends on what someone else chooses too."],
         stages=[("retrieval", 0.3), ("llm_first_sentence", 2.9), ("tts", 1.1)]),

    # A named subject: not grounded, history dropped. The trace has to make the
    # difference between this and "retrieved nothing" visible.
    dict(heard="Astrology.", chunks=None,
         sentences=["Astrology is the tradition of reading meaning into where",
                    "the planets sit. What would you like to know about it?"],
         stages=[("llm_first_sentence", 3.1), ("tts", 1.2)]),

    # Embedding server down: degraded to lexical, still answering.
    dict(heard="how does rain happen",
         chunks=[{"id": "clouds-and-rain", "title": "Clouds and Rain",
                  "subject": "The sky and the seasons", "score": 4.21,
                  "lexical_bonus": False, "kept": True}],
         path="lexical", floor=1.68, degraded=("embed", "lexical"),
         sentences=["Tiny drops inside a cloud bump into each other and join up.",
                    "When a drop gets too heavy to float, it falls as rain."],
         stages=[("retrieval", 0.1), ("llm_first_sentence", 4.8), ("tts", 1.4)]),

    # Nothing heard. The cue that must never look like the device's fault.
    dict(heard=None, chunks=None, sentences=[], stages=[], reason="no-speech"),
]


def main() -> None:
    cfg = config.load()
    cfg.setdefault("console", {})["port"] = int(cfg.get("console", {}).get("port", 8090))
    if console.serve(cfg) is None:
        sys.exit("console did not start")
    print("  demo: open the URL above, press 'd' for the dev trace. Ctrl-C to stop.",
          flush=True)
    once = "--once" in sys.argv
    try:
        while True:
            for step in SESSION:
                turn(**step)
            if once:
                return
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
