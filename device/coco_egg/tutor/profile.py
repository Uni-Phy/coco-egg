"""Per-learner layer: who this egg is teaching, and how they like to learn.

Deliberately SCHEMA-FREE. There is no field list here and there should not be
one yet — we do not know which preferences actually change an answer for the
better, and guessing a schema now means migrating it later. Any key/value in
the profile becomes a line the tutor is told about the learner, so the layer
gets richer by editing YAML, not by editing code.

This plays to the hardware. Measured on the M0 bench: a small model's grounded
*generation* is as good as a bigger one's, while its unaided *reasoning* is
not (docs/model-notes.md §3). Personalisation is generation work — rendering
provided material in a given style — so it is exactly the kind of intelligence
a thin model can carry.

Profile lives in egg.yaml under `learner:`, or a path in `tutor.profile`.
"""
from __future__ import annotations

import pathlib

import yaml


def _read(path) -> dict:
    try:
        return yaml.safe_load(pathlib.Path(path).read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def load(cfg: dict) -> dict:
    """The learner, from what a person wrote plus what we observed.

    Two sources, merged: `tutor.profile` (hand-written, or the inline
    `learner:` block) and `tutor.profile_derived`, which the profile builder
    recomputes from transcripts. **The hand-written side wins on conflict.**

    That direction is deliberate. This is a children's device: a teacher must
    be able to state a fact about a learner and have it hold, rather than be
    overruled by a background job counting questions. The derived side fills
    gaps, it does not correct people.
    """
    tutor = cfg.get("tutor", {})
    path = tutor.get("profile")
    written = _read(path) if path and pathlib.Path(path).is_file() else (cfg.get("learner") or {})

    derived_path = tutor.get("profile_derived")
    derived = _read(derived_path) if derived_path and pathlib.Path(derived_path).is_file() else {}
    return {**derived, **written}


def _humanise(key: str) -> str:
    return str(key).replace("_", " ")


def _render(value) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        # Nested keys get humanised too — the model reads this, and a stray
        # new_topics: reads as a variable name rather than a preference.
        return "; ".join(f"{_humanise(k)}: {_render(v)}" for k, v in value.items())
    return str(value)


def describe(profile: dict) -> str:
    """Profile as prompt text, or "" when there is nothing to say.

    Keys are humanised but otherwise passed straight through, so a preference
    we have never heard of still reaches the model. Empty values are dropped —
    a half-filled profile should read as a short profile, not a list of blanks.
    """
    # A leading underscore marks an operational fact — written for a person or
    # the CoCo node, not for the model. `_turns_seen` would spend prompt tokens
    # on something it cannot use, and `_asked_but_not_covered` would tell it
    # about questions it failed, which it can act on even less.
    lines = [f"- {_humanise(k)}: {_render(v)}"
             for k, v in profile.items()
             if not str(k).startswith("_") and v not in (None, "", [], {})]
    return "\n".join(lines)
