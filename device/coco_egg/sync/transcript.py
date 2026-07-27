"""Complete turn records, assembled off the event bus.

The old log kept question, reply and a latency number. That is enough to read
back what was said and nothing else — you cannot tell why an answer went
wrong, which lesson it came from, or whether retrieval had even fired. Every
bug found during bring-up needed exactly that missing detail.

This subscribes to the bus instead, so a record carries what the turn actually
did: what was heard, which chunks were retrieved and with what scores, whether
anything degraded, per-stage timings, and the reply. Three consumers want it —
the profile builder next door, the CoCo node's fine-tuning (spec §3), and a
human debugging a bad answer.

★ These are recordings of children speaking. Spec §13 governs retention, and
nothing here leaves the device on its own: the SYNC job at M1 applies retention
rules before anything is shipped.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import threading

from .. import events

_lock = threading.Lock()
_open_turn: dict = {}
_cfg: dict = {}
_on_complete = None


def _path() -> pathlib.Path:
    d = pathlib.Path(_cfg["sync"]["transcript_dir"])
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{dt.date.today().isoformat()}.jsonl"


def _record(event: dict) -> None:
    """Accumulate a turn, and write it out when the turn closes.

    Runs inline on the voice loop's thread, so it does no I/O until turn.end
    and never blocks on anything slower than an append.
    """
    global _open_turn
    kind = event["kind"]
    with _lock:
        if kind == "turn.start":
            _open_turn = {"turn": event["turn"], "stages": {}, "degraded": [],
                          "retrieved": [], "sentences": []}
            return
        if not _open_turn:
            return
        if kind == "heard":
            _open_turn["heard"] = event.get("text", "")
        elif kind == "retrieved":
            _open_turn["path"] = event.get("path")
            _open_turn["retrieved"] = [
                {"id": c["id"], "subject": c.get("subject", ""),
                 "score": c.get("score"), "kept": c.get("kept")}
                for c in event.get("chunks", []) if c.get("kept")]
            _open_turn["considered"] = len(event.get("chunks", []))
        elif kind == "sentence":
            _open_turn["sentences"].append(event.get("text", ""))
        elif kind == "stage":
            _open_turn["stages"][event["stage"]] = event.get("seconds")
        elif kind == "degraded":
            _open_turn["degraded"].append(event.get("component"))
        elif kind == "turn.end":
            done = _open_turn
            _open_turn = {}
            done["ts"] = dt.datetime.now().isoformat(timespec="seconds")
            done["reason"] = event.get("reason")
            done["reply"] = event.get("reply") or " ".join(done.pop("sentences", []))
            done.pop("sentences", None)
            _flush(done)


def _flush(turn: dict) -> None:
    """Append one record. A failed write must not take down the voice loop."""
    try:
        with open(_path(), "a") as f:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"  transcript: could not write ({e}); turn not recorded", flush=True)
        return
    if _on_complete is not None:
        try:
            _on_complete(turn, _cfg)
        except Exception as e:      # a downstream job must never fail a turn
            print(f"  transcript: post-write hook raised {e.__class__.__name__}",
                  flush=True)


def start(cfg: dict, on_complete=None) -> None:
    """Begin recording. `on_complete(turn, cfg)` fires after each write.

    The hook is how the profile builder gets its event-based trigger without
    the recorder knowing anything about profiles.
    """
    global _cfg, _on_complete
    _cfg, _on_complete = cfg, on_complete
    events.subscribe(_record)


def read_recent(cfg: dict, days: int = 14) -> list[dict]:
    """Turn records from the last `days` files, oldest first.

    Bounded by design: the profile builder should get slower as a learner uses
    the device more, and a corrupt line should cost one turn rather than the
    whole history.
    """
    d = pathlib.Path(cfg["sync"]["transcript_dir"])
    if not d.is_dir():
        return []
    turns: list[dict] = []
    for f in sorted(d.glob("*.jsonl"))[-days:]:
        for line in f.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                turns.append(json.loads(line))
            except ValueError:
                continue
    return turns
