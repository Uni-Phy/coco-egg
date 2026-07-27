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


def load(cfg: dict) -> dict:
    """Profile dict from `tutor.profile` (a YAML file) or inline `learner:`."""
    path = cfg.get("tutor", {}).get("profile")
    if path and pathlib.Path(path).is_file():
        return yaml.safe_load(pathlib.Path(path).read_text()) or {}
    return cfg.get("learner") or {}


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
    lines = [f"- {_humanise(k)}: {_render(v)}"
             for k, v in profile.items() if v not in (None, "", [], {})]
    return "\n".join(lines)
