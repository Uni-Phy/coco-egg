"""The event bus is peripheral, so these mostly test that it cannot hurt.

The rule this device runs on is that a failure in something nobody's life
depends on — a console, a log, a metric — never takes down the voice loop. A
bus that can raise into one_turn(), or block it, is worse than no bus.
"""
import pathlib

import pytest

from coco_egg import config, events
from coco_egg.tutor import embed as embedding
from coco_egg.tutor import llama_client
from coco_egg.tutor.pack import Pack

PACKS_DIR = pathlib.Path(__file__).parents[2] / "fixtures" / "packs"


@pytest.fixture(autouse=True)
def clean_bus():
    """No subscriber survives a test — the bus is module-global state."""
    yield
    for fn in list(events._subscribers):
        events.unsubscribe(fn)


@pytest.fixture
def recorder() -> list:
    seen: list = []
    events.subscribe(seen.append)
    return seen


def offline_cfg(tmp_path) -> dict:
    """Every backend pointed at a closed port: the fully degraded device."""
    cfg = config.load(path=None)
    cfg["tutor"]["llama_url"] = "http://127.0.0.1:9"
    cfg["tutor"]["embed_url"] = "http://127.0.0.1:9"
    cfg["tutor"]["pack"] = str(PACKS_DIR)
    cfg["tutor"]["embed_cache"] = str(tmp_path / "embed-cache")
    return cfg


def test_no_subscribers_is_the_normal_case():
    """The shipped state: nobody's laptop is open. Emitting must be a no-op."""
    assert not events.active()
    events.begin_turn()
    events.emit("heard", text="how does rain happen")
    events.end_turn(reason="ok")


def test_a_subscriber_that_raises_is_dropped_not_propagated(recorder):
    """One broken subscriber must not end the turn, or the next fifty turns."""
    def explode(event):
        raise RuntimeError("subscriber is broken")

    events.subscribe(explode)
    events.emit("state", state="THINKING")   # explode() raises here
    events.emit("state", state="SPEAKING")   # ...and is gone by here

    assert explode not in events._subscribers
    assert [e["state"] for e in recorder] == ["THINKING", "SPEAKING"]


def test_events_carry_turn_and_ordering(recorder):
    """seq is strictly increasing and turn ids advance — the console keys on both."""
    first = events.begin_turn()
    events.emit("heard", text="one")
    events.end_turn(reason="ok")
    second = events.begin_turn()
    events.emit("heard", text="two")

    assert second == first + 1
    seqs = [e["seq"] for e in recorder]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert [e["kind"] for e in recorder] == [
        "turn.start", "heard", "turn.end", "turn.start", "heard"]
    assert [e["turn"] for e in recorder] == [first, first, first, second, second]


def test_stream_drops_rather_than_blocking_the_loop():
    """A reader that stopped reading must cost the voice loop nothing."""
    with events.Stream(maxsize=2) as stream:
        for i in range(5):
            events.emit("sentence", index=i, text=str(i))
    assert stream.dropped == 3
    # What survives is the newest, which is what a live trace wants.
    assert [stream.get(timeout=0)["index"] for _ in range(2)] == [3, 4]
    assert stream.get(timeout=0) is None


def test_turn_ordering_through_a_degraded_turn(recorder, tmp_path, monkeypatch):
    """A whole turn with both servers down, in the order the console reads it.

    Uses the offline fallback path deliberately: it is the one full turn that
    runs with no llama-server and no embedding server, so the ordering
    contract is testable without the models installed.
    """
    monkeypatch.setattr(llama_client, "_pack", None)
    cfg = offline_cfg(tmp_path)

    events.begin_turn()
    events.emit("heard", text="what is photosynthesis")
    sentences = list(llama_client.stream_sentences("what is photosynthesis", cfg))
    events.end_turn(reason="ok", reply=" ".join(sentences))

    kinds = [e["kind"] for e in recorder]
    assert kinds[:6] == ["turn.start", "heard",
                         "degraded",        # embedding server unreachable
                         "retrieved",       # ...so retrieval ran lexically
                         "stage",           # retrieval timing
                         "degraded"]        # llama-server unreachable
    assert kinds[-1] == "turn.end"
    assert "sentence" in kinds
    # The first sentence is timed before it is published, and both precede the
    # second sentence — the console draws the answer lane off this order.
    stages = [e["stage"] for e in recorder if e["kind"] == "stage"]
    assert stages == ["retrieval", "llm_first_sentence"]
    assert [e["index"] for e in recorder if e["kind"] == "sentence"] == \
        list(range(len(sentences)))


def test_degraded_events_name_the_component_and_the_fallback(recorder, tmp_path,
                                                             monkeypatch):
    """Offline is a normal state, so it has to say what still works."""
    monkeypatch.setattr(llama_client, "_pack", None)
    list(llama_client.stream_sentences("what is photosynthesis", offline_cfg(tmp_path)))

    degraded = {(e["component"], e["fallback"]) for e in recorder
                if e["kind"] == "degraded"}
    assert degraded == {("embed", "lexical"), ("llama", "pack")}


def test_retrieved_carries_scores_subject_and_the_floor(recorder, tmp_path,
                                                        monkeypatch):
    """The payload the whole console is built on — scores are the point.

    Without them a false positive like "why is the sky blue" grounding on the
    water cycle is invisible: you see the wrong answer, never the 0.60 that
    caused it (docs/model-notes.md §5).
    """
    monkeypatch.setattr(llama_client, "_pack", None)
    list(llama_client.stream_sentences("what is photosynthesis", offline_cfg(tmp_path)))

    got = next(e for e in recorder if e["kind"] == "retrieved")
    assert got["path"] == "lexical" and got["scale"] == "idf"
    assert got["chunks"], "retrieval found nothing to report"
    top = got["chunks"][0]
    assert {"id", "title", "subject", "score", "kept", "lexical_bonus"} <= set(top)
    assert top["id"] == "photosynthesis" and top["kept"] is True
    assert top["subject"]
    # Both cuts come from the device so the console never draws a stale floor.
    assert top["score"] >= got["floor"] >= 0
    assert got["relative_floor"] == got["floor"]   # the lexical floor IS relative


def test_a_miss_still_reports_what_was_considered(recorder, tmp_path, monkeypatch):
    """Retrieving nothing is the common outcome, and it is still a fact to show."""
    monkeypatch.setattr(llama_client, "_pack", None)
    list(llama_client.stream_sentences("qqq zzz xyzzy", offline_cfg(tmp_path)))

    got = next(e for e in recorder if e["kind"] == "retrieved")
    assert got["chunks"] == [] and got["floor"] == 0.0 and got["relative_floor"] == 0.0
    assert not any(e["kind"] == "error" for e in recorder)   # a miss is not an error


def test_semantic_path_reports_both_cuts(recorder, monkeypatch):
    """The production path, and the one whose scores the console is built on.

    Embeddings are stubbed — the server is a separate process and this is
    about the event, not the model. Vectors are picked so one chunk clears
    both cuts, and one clears the absolute floor but is dropped by the
    relative 0.92-of-best rule. That second chunk is the case a console has to
    render distinctly: it looked good enough and still never reached the
    prompt, and reading it as "the floor is too high" sweeps the wrong knob.
    """
    lib = Pack.load_config(str(PACKS_DIR))
    sims = [0.0] * len(lib.chunks)
    sims[0], sims[1] = 0.80, 0.60
    # cosine against [1, 0] is just the first component, so score == sims[i]
    monkeypatch.setattr(lib, "_vectors", [[s, (1 - s * s) ** 0.5] for s in sims])
    monkeypatch.setattr(embedding, "embed", lambda texts, cfg: [[1.0, 0.0]])

    hits = lib.retrieve_semantic("xyzzy", config.load(path=None))

    got = next(e for e in recorder if e["kind"] == "retrieved")
    assert got["path"] == "semantic" and got["scale"] == "cosine"
    assert got["floor"] == Pack.MIN_SIMILARITY
    assert got["relative_floor"] == pytest.approx(0.92 * 0.80)
    kept = [(c["score"], c["kept"]) for c in got["chunks"][:3]]
    assert kept == [(0.8, True), (0.6, False), (0.0, False)]
    assert [c["id"] for c in hits] == [got["chunks"][0]["id"]]
    assert not any(c["lexical_bonus"] for c in got["chunks"])


def test_emitting_costs_nothing_when_nobody_is_watching(tmp_path, monkeypatch):
    """active() is what lets pack.py skip formatting candidates in production."""
    monkeypatch.setattr(llama_client, "_pack", None)
    assert not events.active()
    sentences = list(llama_client.stream_sentences("what is photosynthesis",
                                                   offline_cfg(tmp_path)))
    assert "photosynthesis" in " ".join(sentences).lower()
