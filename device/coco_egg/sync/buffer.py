"""Buffer-and-forward transcript store (spec §4 SYNC state).

v0: append JSONL locally. The SYNC job that ships these to the CoCo node
(and pulls content packs / model updates) comes with M1. Retention rules
per spec §13 apply before anything leaves the device.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib


def log_interaction(question: str, reply: str, latency_s: float, cfg: dict) -> None:
    d = pathlib.Path(cfg["sync"]["transcript_dir"])
    d.mkdir(parents=True, exist_ok=True)
    day = dt.date.today().isoformat()
    with open(d / f"{day}.jsonl", "a") as f:
        f.write(json.dumps({
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "q": question, "a": reply, "latency_s": round(latency_s, 2),
        }) + "\n")
