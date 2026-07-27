"""Transcript recording off the event bus, and the profile derived from it."""
import json

import pytest
import yaml

from coco_egg import events
from coco_egg.sync import transcript
from coco_egg.tutor import profile, profile_builder


@pytest.fixture
def cfg(tmp_path):
    return {"sync": {"transcript_dir": str(tmp_path / "transcripts")},
            "tutor": {"profile": str(tmp_path / "learner.yaml"),
                      "profile_derived": str(tmp_path / "derived.yaml")}}


def _turn(heard, reply, chunks=()):
    """Drive one turn's worth of events through the bus."""
    events.begin_turn()
    events.emit("heard", text=heard)
    events.emit("retrieved", path="semantic", chunks=list(chunks))
    events.emit("stage", stage="asr", seconds=1.8)
    events.end_turn(reason="ok", reply=reply)


@pytest.fixture
def recording(cfg):
    transcript.start(cfg)
    yield cfg
    events.unsubscribe(transcript._record)


def test_record_captures_what_the_turn_actually_did(recording, cfg):
    """A record must carry retrieval and timings, not just question and reply.

    The thin log it replaced could not answer "why was this answer wrong",
    which is the question every bug during bring-up turned out to need.
    """
    _turn("why do we need air", "To get oxygen.",
          [{"id": "breathing", "subject": "The human body", "score": 0.71, "kept": True},
           {"id": "plants", "subject": "The farm", "score": 0.60, "kept": False}])
    rows = transcript.read_recent(cfg)
    assert len(rows) == 1
    row = rows[0]
    assert row["heard"] == "why do we need air"
    assert row["reply"] == "To get oxygen."
    assert row["stages"]["asr"] == 1.8
    assert [c["id"] for c in row["retrieved"]] == ["breathing"]   # kept only
    assert row["considered"] == 2                                  # but both seen
    assert row["path"] == "semantic"


def test_a_failed_write_does_not_raise(recording, cfg, monkeypatch):
    """A full disk must not take down the voice loop mid-answer."""
    def boom(*a, **k):
        raise OSError("no space left on device")
    monkeypatch.setattr("builtins.open", boom)
    _turn("anything", "a reply")     # must not propagate


def test_derived_profile_counts_rather_than_infers(cfg):
    turns = [{"heard": "what is friction", "retrieved": [{"subject": "Physics"}]},
             {"heard": "why do we need friction", "retrieved": [{"subject": "Physics"}]},
             {"heard": "how do brakes work", "retrieved": [{"subject": "Physics"}]},
             {"heard": "what is a fraction", "retrieved": [{"subject": "Maths"}]},
             {"heard": "who is my teacher", "retrieved": []}]
    facts = profile_builder.summarise(turns)
    assert facts["_turns_seen"] == 5
    assert facts["asks_most_about"] == ["Physics"]        # 3 hits clears the bar
    assert "Maths" not in facts.get("asks_most_about", [])  # 1 hit does not
    assert "who is my teacher" in facts["_asked_but_not_covered"]


def test_repeated_questions_are_surfaced_without_claiming_why(cfg):
    """Counting can see repetition; it cannot see whether they understood."""
    turns = [{"heard": "what is gravity", "retrieved": [{"subject": "Physics"}]},
             {"heard": "what is gravity", "retrieved": [{"subject": "Physics"}]}]
    facts = profile_builder.summarise(turns)
    assert facts["asked_more_than_once"] == ["what is gravity"]


def test_handwritten_profile_wins_over_derived(cfg, tmp_path):
    """A person's statement about a learner must not be overruled by a counter."""
    (tmp_path / "learner.yaml").write_text(yaml.safe_dump(
        {"name": "Asha", "asks_most_about": ["poetry"]}))
    (tmp_path / "derived.yaml").write_text(yaml.safe_dump(
        {"asks_most_about": ["Physics"], "_turns_seen": 40}))
    merged = profile.load(cfg)
    assert merged["asks_most_about"] == ["poetry"]   # human wins
    assert merged["_turns_seen"] == 40               # derived fills the gap
    assert merged["name"] == "Asha"


def test_rebuild_writes_yaml(cfg, tmp_path):
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "transcripts" / "2026-07-28.jsonl").write_text(
        json.dumps({"heard": "what is gravity",
                    "retrieved": [{"subject": "Physics"}]}) + "\n")
    facts = profile_builder.rebuild(cfg)
    assert facts["_turns_seen"] == 1
    assert yaml.safe_load((tmp_path / "derived.yaml").read_text())["_turns_seen"] == 1


def test_corrupt_transcript_line_costs_one_turn_not_the_history(cfg, tmp_path):
    d = tmp_path / "transcripts"
    d.mkdir()
    (d / "2026-07-28.jsonl").write_text(
        json.dumps({"heard": "good line", "retrieved": []}) + "\n"
        + "{not json at all\n"
        + json.dumps({"heard": "another good line", "retrieved": []}) + "\n")
    assert len(transcript.read_recent(cfg)) == 2


def test_operational_facts_never_reach_the_prompt():
    """Underscore keys are for a person or the node, not for the model.

    Prompt tokens are the scarce resource, and telling the tutor about
    questions it failed to answer is not something it can act on.
    """
    described = profile.describe({
        "asks_most_about": ["Physics"],
        "_turns_seen": 40,
        "_asked_but_not_covered": ["who is my class teacher"],
    })
    assert "Physics" in described
    assert "turns seen" not in described
    assert "class teacher" not in described
