# Work available — pickable in parallel

Status as of `v0.3` @ 3775963 (2026-07-28). Streams below are grouped so two
people can work at once without colliding; each lists the files it owns. Sizes:
**S** under half a day, **M** one to two days, **L** about a week.

## Where things stand

Running on the bench Pi (10.10.10.186, `~/coco-egg`, branch `v0.3`):

| | |
|---|---|
| tutor | Qwen3-0.6B Q4_K_M, llama-server `:8080`, `-c 1024` |
| retrieval | bge-small-en-v1.5 (64MB), llama-server `:8082` `--embedding` |
| ASR | whisper-server `ggml-base.en` `:8081`, streaming (Jenya) |
| TTS | Piper `en_US-lessac-medium` |
| memory | ~1.4 GB with all three servers, of 8 GB |
| latency | ~5.0–5.6s median perceived (spec §16 wanted 2–3s) |
| retrieval | 75% recall / 11% false positives at 143 chunks |
| tests | 76 passing, ruff clean apart from a known `build_pack.py:62` |
| subjects | **8 loaded, 143 chunks** |

Two things that bite:

- **All three servers are manually started orphans (PPID 1). Nothing survives a
  reboot** — see D1. And llama-server **leaks ~11 MB per request** (984 MB
  fresh → 5.8 GB after 11 h), so **restart the tutor before any timing run or
  demo** or you are measuring the leak (`docs/model-notes.md` §8).
- The committed config names **docker service** hostnames (`llama-tutor`,
  `whisper`, `llama-embed`). The bare-metal bench needs `egg.yaml` overrides
  pointing at `127.0.0.1` — the Pi already has them, gitignored.

Quick start on the device:

```bash
make serve        # tutor, :8080
make serve-embed  # retrieval embeddings, :8082
python tools/eval_retrieval.py && python tools/bench_loop.py 6
```

## Landed 2026-07-28

Six course subjects (12,978 words, 134 chunks) with per-course eval questions ·
semantic retrieval (recall 33%→87% at 8 chunks) · conversation memory, free in
prefill · complete transcripts off the event bus · an LLM-free profile builder ·
console design + event bus · Jenya's whisper-server migration and streaming ASR.

Bugs found and fixed, all from real use rather than review: possessives
tokenising to a bare `s`, the reply stream decoded as latin-1 (which silently
broke the Devanagari path), the 0.6B corrupting pack `explain` text when asked
to polish it, and retrieval ignoring conversation context.

## Open, in priority order

1. **Model A/B — 0.6B vs 1.7B.** Not concluded. The 1.7B is on the device and
   is measurably better at our failure modes (it resists bad grounding; the
   0.6B builds whole wrong answers from it), but prefill is 56 t/s against 149,
   so expect **+2–3s**. Run `tools/eval_retrieval.py` (unchanged — retrieval is
   model-independent), `tools/bench_loop.py`, and the known failure cases.
2. **The yes-bias.** The 0.6B answers "Yes" to yes/no questions regardless of
   the material in front of it — *"Yes, a magnet can stick to an aluminum
   spoon. It works on iron, nickel and cobalt, but not on aluminum."* Prompting
   was tried and failed. This is the strongest case for the behaviour
   fine-tune, not for a bigger prompt.
3. **D1 systemd units** — now containment for the leak, not just hygiene.
4. **Reconcile eval labels.** Reported recall (75%) understates reality: most
   "misses" are the expected topic label disagreeing with the polished chunk id
   (`breathing-and-oxygen` scored against a label of `respiration`). Real recall
   is 75–90%. Do *not* fix by fitting labels to whatever currently retrieves —
   that makes the eval tautological.

---

## Stream A — courses (the demo blocker)

*Owns: `fixtures/packs/`, `tools/build_pack.py`, source docs. No overlap with
device code.*

- **A1 · Three more course packs** `M` — have science/maths + civics/history.
  Need: **the farm** (soil, water, crops, weather), **sky & seasons** (sun,
  moon, monsoon, day/night), and a thicker **maths you can see**. Source text
  is the real work; `build_pack.py --llm` does the rest.
- **A2 · Better chunking** `M` — `build_pack.py` splits at a fixed 700 chars,
  and in heuristic mode takes titles from the first five words. Titles carry a
  3x retrieval weight, so weak titles cost accuracy directly.
- **A3 · Per-chunk "asks"** `S` — extend the `--llm` polish to emit 5–10
  questions each chunk answers. Feeds question-space retrieval and seeds the
  eval set. Treat as promising, not proven: an early test of this looked
  perfect only because the probe questions were verbatim in the seed list.
- **A4 · Pack registry** `S` — versions, enable/disable, subject listing.

**Acceptance for the stream:** 5 subjects load, and `tools/eval_retrieval.py`
still passes with questions added for each new course.

## Stream B — the console

*Owns: new `device/coco_egg/web/`, static assets; small hook in `main.py`.*

- **B1 · Turn event bus** `M` — emit structured events (`heard`,
  `retrieved`+scores, `sentence`, timings) from the pipeline. Everything else
  in this stream depends on it, and it tidies `one_turn`/`bench_turn`.
- **B2 · HTTP server on device** `M` — none exists today; `main.py` is a TTY
  menu. Static page plus SSE. Must not block or crash the voice loop.
- **B3 · Reasoning-trace view** `M` — heard → retrieved chunks *with scores* →
  answer streaming → spoken, with per-stage timings. Build this one first: it
  is simultaneously the demo screen, the debug tool, the retrieval-tuning
  surface and the eval viewer.

Runs **on the device**, not the node — a console you cannot open in a classroom
with no internet is the wrong artifact.

## Stream C — latency

*Owns: `device/coco_egg/asr/`, `audio/io.py`, related config.*

ASR is now the largest single stage; more LLM work will not help.

- **C1 · `tiny.en` A/B** `S` — 1.44s of the 1.78s ASR is whisper's fixed
  30s-window encoder, paid whether the question is 1.6s or 25s. Measure WER
  against `base.en` on real recordings *before* switching. ~1.3s on the table.
- **C2 · Streaming ASR** `L` — transcribe during speech. The pipeline is fully
  serial; this is the one structural win. Pairs with speculative retrieval on
  a partial transcript.
- **C3 · Acknowledgement audio** `S` — a short phrase renders in 0.25s, taking
  *perceived* first-audio to ~0.5s. Blocked on the UX call (`v0.3-ux`), not on
  code.

## Stream D — product hardening

*Owns: `os/`, `sync/buffer.py`, `deploy/`.*

- **D1 · systemd units** `M` — for both llama-servers and the app, with restart
  policies. Highest-value item outside the demo blocker: today a power cut ends
  the demo.
- **D2 · Reply length cap** `S` — cap at N sentences in the stream loop.
  `max_reply_chars` currently cuts mid-word.
- **D3 · Transcript retention** `S` — rotation and limits, spec §13.

## Stream E — retrieval refinement

*Owns: `pack.py`, `tools/eval_retrieval.py`. Coordinate with Stream A, which
adds eval cases.*

- **E1 · Named misses** `M` — two failures are visible in the eval output:
  "why is the sky blue" still grounds on the water cycle, and "can the
  government stop me praying" lands on local government instead of the
  constitution. Re-sweep `MIN_SIMILARITY` once 5 courses are loaded; the knee
  will move.
- **E2 · Answer eval** `M` — `tools/eval_answers.py`: run questions through the
  full tutor and score retrieval hit plus key facts present, per course. This
  is the "which course is demo-ready" scorecard.

## Stream F — UX design

*Owns: `v0.3-ux` branch, docs only.* See `docs/ux-brief.md`. Note that branch
is behind `v0.3` and wants a rebase before new work.

Decisions that unblock code: acknowledgement wording/behaviour (C3), LED state
language, and whether barge-in ships — the hardware AEC is already confirmed
capable, so that is purely a UX gate now.

---

## Carried risks

- **Out-of-pack answers are unrefused by choice.** With a 0.6B that means
  confident wrong answers outside curated subjects. Recall (Stream A + E)
  shrinks the surface; `tools/eval_answers.py` should measure it so the call
  can be revisited with data rather than argument.
- **`MIN_SIMILARITY` is tuned on 2 subjects.** It will need re-sweeping at 5.
- Retrieval eval questions are English and hand-written; they encode our guess
  at how a child phrases things. Real transcripts should replace them.
