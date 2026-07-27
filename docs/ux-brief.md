# UX/UI brief — v0.3 design stream

Design surface for the `v0.3-ux` branch. Naveen designs, we code here.
Everything below is measured on the real bench, not estimated.

## The one number that should drive the design

**Median 7.3s from "learner stops talking" to "egg starts talking"**
(4.96–8.63s). Spec §16 wanted 2–3s. We will not close that with engineering
alone this cycle — see `docs/model-notes.md`, the CPU is bandwidth-bound and
the thin-model swap costs accuracy.

So the UX job is not decoration. **7.3s of silence reads as "it's broken";
7.3s of legible waiting reads as "it's thinking."** That is a design problem,
and right now it is the highest-leverage one on the device.

Budget breakdown to design against:

| | duration | what the learner should perceive |
|---|---|---|
| trailing silence before we even start | 1.2s | "it knows I finished" |
| ASR | 1.8s | "it heard me" |
| LLM first sentence | 1.3–4.1s | "it's thinking" |
| TTS | 0.4–1.6s | — |
| then it speaks, sentence by sentence | | |

**The cheapest win available:** warm TTS renders a short phrase in **0.25s**.
An acknowledgement ("Hmm, let me think…") spoken ~0.3s after end-of-speech
takes *time-to-first-audio from 7.3s to ~0.5s* without touching the model.
This is a design call, not an engineering one — does it feel warm or
patronising? Does it vary per turn or repeat? Does it differ for a hard
question vs an easy one (we know the latency before we speak)? Does it ever
say something useful ("that's a good one")?

## Surface 1 — device state UI (LED ring + earcons)

`UiState` already exists in `device/coco_egg/states.py`:
`IDLE · LISTENING · THINKING · SPEAKING · OFFLINE · ERROR`. Today `set_ui()`
just prints the state name.

**Hardware reality:** the current bench mic (eMeet M0 Plus) has **no GPIO** —
spec §5 calls it "not embeddable, no GPIO", strictly the M0 bench part. The
XVF3800 that replaces it at M1 has **3 GPI / 5 GPO** for button and LEDs. So
an LED ring cannot be driven on this board.

What that means for the stream: design the behaviour now, simulate it in the
browser, and put it behind a driver interface so the M1 board is a backend
swap, not a rewrite. Design questions worth answering:

- Colour + motion per state, and the *transitions* (LISTENING→THINKING is the
  moment the learner needs most reassurance).
- Does THINKING animate at a fixed rate, or track actual progress? We know
  when the first sentence lands and could show real progress rather than a
  fake spinner.
- OFFLINE is "informational only — the egg still works". How does it show
  that without reading as an error? Offline is the *normal* state (spec §2).
- ERROR vs "I don't know that" — very different, must not look the same.
- Does the ring stay lit while speaking, or pulse with the audio?

## Surface 2 — web console (demo + debug)

Runs on the Pi, viewed from a laptop/phone on the LAN. This is the surface
that unlocks the others: it hosts the LED simulator, makes the eval set
legible, and is the demo screen when showing the egg to someone.

Should show live: current state · what it heard · the reply streaming in
sentence by sentence · per-stage latency for the turn · **which pack chunks
were retrieved and their scores** (that last one is how we caught the "why is
the sky blue → water cycle" false positive).

Note there is no HTTP server in the device app today — `main.py` is a TTY menu.
This is new surface area, and it is also the natural home for the eval runner.

## Surface 3 — companion admin app

The "specialised knowledge we add" surface, and the demo lever from v0.2:
upload a document → `tools/build_pack.py` turns it into a pack → the egg
teaches that subject with our examples. Also transcript review and device
status.

Today: one pack file at a time (`tutor.pack`), no registry, no UI. Multi-pack
is on the v0.3 list you picked.

## Surface 4 — physical / industrial design

Spec §6 has the enclosure as **[OPEN]**, 3D-printed for v0: egg-form, vented,
speaker grille, LED diffuser. Constraints that are already fixed: the speaker
must be driven through the XVF3800 board (§5), 4Ω 3–5W full-range driver
2–3", mains-powered (no battery in v0), Pi 5 needs airflow — it thermally
throttles and we are pinning all 4 cores during every answer.

Open product decision this stream should settle (spec §15 decision #5,
owner: Product): **wake word vs push-to-talk button vs both.** Spec
recommends button for v0, wake word fast-follow. A button also gives us a
precise end-of-speech signal, which would let us cut the 1.2s VAD hangover —
worth ~1.2s of the 7.3s.

## Known-good, do not redesign

- **Barge-in is available.** Measured: a full-volume tone played out the
  speaker records at the mic noise floor — hardware AEC cancels it completely.
  Spec decision #3 says ship M1 half-duplex and "enable barge-in when the UX
  is ready". The hardware is ready; this is now purely a UX call.
- The egg genuinely works with the network off. Offline is the base state.
