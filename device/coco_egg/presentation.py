"""The state language, in one place: state -> colour, motion, dwell, earcon.

The device is screenless. Spec §5 calls the LED ring "non-negotiable UX — the
learner needs to know it heard them", and the M0 bench mic (eMeet M0 Plus) has
no GPIO, so that behaviour cannot be driven or watched until the XVF3800 lands
at M1. Rendering the same language as pixels unblocks it now: the console's
student view is the LED prototype, and the M1 driver becomes a second renderer
of this table rather than a redesign (docs/console-design.md §3).

Three renderers consume it and none of them owns it — the student view today,
the LED driver at M1, the earcons in both. Put a colour or a dwell in a
renderer instead and the other two drift, which is exactly how the LED work
would end up starting from scratch at M1.

Keyed by UiState.name, so the table is already JSON and the browser is handed
the same numbers the driver reads. One rule holds the design together:
**every state stays distinguishable with the colour channel switched off** —
no two share a motion. That is what survives colour blindness, a diffuser
washed out by classroom daylight, and a renderer that has nothing but GPO pins.
"""
from __future__ import annotations

# min_dwell_ms floors how long a cue holds before the next may replace it, and
# it is not cosmetic: the captured fully-degraded trace in
# docs/console-design.md §8 runs turn.start to turn.end in 7ms, so with no
# floor the ring strobes through four states inside one frame.
#
# period_ms is the motion's own clock. THINKING's is the measured median
# time-to-first-audio (README: 5.01s): the arc grows toward the ring and never
# closes it, so a normal turn is one near-lap and an overrun visibly slows
# rather than hitting 100% and sitting there.
#
# exit_ms hands the cue back to IDLE unprompted. Only the two "that did not
# work" cues have one — a latched fault light in a classroom is how a working
# device gets unplugged.
#
# Colours are sRGB for a screen, and are the one part of this table that does
# NOT transfer to hardware: hue, gamma and brightness range through a printed
# diffuser are different enough that the palette gets re-picked on the real
# ring at M1 (docs/console-design.md §11). The language transfers; the hex is
# a starting point.
CUES: dict[str, dict] = {
    # Alive, not busy. ~10 breaths a minute reads calm; faster reads anxious.
    "IDLE": {"colour": "#5A4632", "motion": "breathe", "period_ms": 6000,
             "min_dwell_ms": 400, "exit_ms": None, "earcon": None},

    # Follows the learner's voice where the renderer has the level — the LED
    # driver sits beside record_utterance() and its per-block rms, the browser
    # does not and falls back to period_ms as a gentle breath.
    "LISTENING": {"colour": "#3FBF6F", "motion": "pulse", "period_ms": 900,
                  "min_dwell_ms": 400, "exit_ms": None, "earcon": "open"},

    # The 5s wait. "ack" fires on entry, which is end-of-speech — the single
    # highest-value sound on the device, because it is the only feedback in the
    # 1.2s VAD hangover the learner currently sits through in silence.
    "THINKING": {"colour": "#E0A020", "motion": "fill", "period_ms": 5000,
                 "min_dwell_ms": 400, "exit_ms": None, "earcon": "ack"},

    # Steady, stepping once per spoken sentence. No earcon: the voice is the
    # cue, and a chime in front of every answer is noise 40 times an hour.
    # min_dwell doubles as the tail hold so the ring does not snap dark on the
    # last syllable.
    "SPEAKING": {"colour": "#3FA0E0", "motion": "steady", "period_ms": None,
                 "min_dwell_ms": 600, "exit_ms": None, "earcon": None},

    # Dim, warm, one slow sigh, gone in two seconds. Deliberately not alarm
    # red: red teaches a child that they broke it, and this is the device's
    # fault, not theirs. The operator's channel for faults is dev mode and
    # ShellHub — the ring is the learner's channel.
    "ERROR": {"colour": "#B4726A", "motion": "sigh", "period_ms": 1200,
              "min_dwell_ms": 400, "exit_ms": 2000, "earcon": "fault"},

    # Not a UiState. Both ways a turn ends with nothing heard (turn.end reason
    # no-audio / no-speech) say the same thing to a learner: ask me again. The
    # distinction between them is diagnostic and belongs in dev mode.
    # LISTENING's colour on purpose — same topic, different message, pointing
    # back at the thing to do rather than at a failure. Renderers derive this
    # from turn.end today; it should become a seventh UiState when the LED
    # driver needs it from the state machine (docs/console-design.md §8).
    "UNHEARD": {"colour": "#3FBF6F", "motion": "nudge", "period_ms": 300,
                "min_dwell_ms": 400, "exit_ms": 1600, "earcon": "again"},
}

# OFFLINE is IDLE, and is built from it rather than written out again so the
# two cannot drift apart in an edit. Offline is this product's base state
# (README, first line) and states.py already calls it "informational only", so
# the learner-facing renderers are made structurally incapable of showing it as
# a fault. That the device is offline is a dev-mode fact, not a cue.
CUES["OFFLINE"] = dict(CUES["IDLE"])

_FALLBACK = "IDLE"


def cue(state: str) -> dict:
    """The cue for a state name, falling back to IDLE for anything unknown.

    Unknown is a live possibility rather than a theoretical one: renderers read
    state names off the wire from a device that may be on a different build. An
    unrecognised state has to leave the ring calm and alive, never dark — a
    dark ring is indistinguishable from a dead egg, and that is how a working
    device gets unplugged mid-lesson.

    Returns a copy: a renderer that mutates its cue must not edit the language.
    """
    return dict(CUES.get(state, CUES[_FALLBACK]))


def table() -> dict[str, dict]:
    """The whole language, for a renderer to load once and keep.

    The browser gets exactly what the M1 LED driver reads — same colours, same
    periods, same dwells. The moment those diverge, the student view stops
    being a usable LED prototype, which is its main reason to exist.
    """
    return {name: dict(spec) for name, spec in CUES.items()}


def distinguishable_without_colour() -> bool:
    """Is every distinct cue told apart by motion alone?

    The module's one structural rule, checkable rather than asserted. IDLE and
    OFFLINE are meant to be identical so they count once. This is what survives
    colour blindness, a diffuser washed out by classroom daylight, and an M1
    renderer holding nothing but GPO pins.
    """
    motions = [spec["motion"] for name, spec in CUES.items() if name != "OFFLINE"]
    return len(motions) == len(set(motions))
