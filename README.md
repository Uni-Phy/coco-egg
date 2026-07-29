# coco-egg zero

**Offline-first edge voice tutor** — the first hardware endpoint of the
[CommonCompute (CoCo)](https://commoncompute.org) ecosystem.

A learner presses a button on the egg, asks a question aloud, and hears a
useful spoken answer — **with zero network dependency**. Cloud inference is
a later quality upgrade (Phase 2), never a requirement. Full design
rationale in [`docs/spec.md`](docs/spec.md).

## Architecture in one breath

button → mic (eMeet M0 Plus / ReSpeaker XVF3800) → whisper.cpp →
**Qwen3-1.7B via llama-server (llama.cpp), streamed** → Piper TTS spoken
sentence-by-sentence → speaker. First audio never waits for the full reply.
Transcripts buffer locally and sync opportunistically to the CoCo node,
which fine-tunes the on-device model and ships it back via OTA. Fleet
access via ShellHub.

## Repo layout

```
device/     Python device app (state machine, audio, ASR, tutor, TTS, sync)
os/         image provisioning: first-boot, WiFi manager, ShellHub agent
deploy/     Dockerfile + compose (app updates = image pulls)
docs/       spec.md — the engineering scope & design doc
```

## Getting started

On a Pi 5 with the eMeet M0 Plus plugged in.

> **DietPi**
>
> Install `docker` and `docker-compose`:
> ```shell
> sudo dietpi-software
> ```
>
> Add user to the `audio` group:
> ```shell
> sudo usermod -aG audio $USER
> ```
>
> Then configure audio:
> ```shell
> sudo dietpi-config
> ```
>
> Audio Options -> Sound card
>
> At the botton under `● Auto Detection` choose the device.
> In case of EMEET M0 Plus it was `hw:0,0   : Plus USB Audio`.
>
> Then in the previous menu (Audio Options) select `Auto-conversion [On]`.
>
> Reboot, test with `aplay -L` and `arecord -L`.

Clone the repo and create `egg.yaml` in the root directory to set up audio devices.

Example `egg.yaml` for EMEET M0 Plus:

```yaml
audio:
  input_device: EMEET
  output_device: plughw:CARD=Plus,DEV=0
```

1. input_device: run `arecord -L`, just part of the name is enough
2. output_device: run `aplay -L` and use the `plughw:*` line

Set up and run:

```shell
make models # download models (~1.4 GB)
make up     # start docker containers in the background
make attach # jump to the egg app. Press Enter and start speaking
```

If you need to restart the app, for example after editing `egg.yaml`
or pulling fresh code changes from the repo, do `make attach` then
Ctrl+C - the app will get restarted immediately and the changes
will be applied for the next `make attach`.

Other commands:

```shell
make down   # stop containers
make build  # start containers with `--build` - rebuilds egg and whisper images.
            # Only needed after a Dockerfile edit.
```

## Measured on real hardware (M0 bench)

Pi 5 8GB / Cortex-A76 / DietPi (Debian 13), eMeet M0 Plus USB speakerphone.
whisper.cpp `ggml-base.en` + **Qwen3-1.7B Q4_K_M** via llama-server (`-c 2048`)
+ Piper `en_US-lessac-medium`. Median of rotating questions, voice preloaded,
measured inside the release container:

| stage | median | note |
|---|---|---|
| ASR (whisper-server) | 2.07s | streaming; the encoder is a **fixed 30s-window cost** whatever the utterance length |
| LLM → first sentence | 3.53s (1.52–5.51) | Qwen3-1.7B: prefill ~56 tok/s, decode ~9.8 tok/s |
| TTS (Piper) | 1.36s (0.88–1.65) | scales with sentence length, RTF ≈ 0.09. `preload()` keeps the ~2.1s voice load off the learner's turn |
| **end-of-speech → first audio** | **8.32s (5.57–10.02)** | includes the `silence_stop_s` = 1.2s hangover the learner waits through |

**Model choice is a deliberate accuracy-over-speed trade.** Qwen3-0.6B runs the
same loop at ~5.0s, but it answers "Yes" to yes/no questions regardless of the
lesson in front of it — *"Yes, a magnet will stick to a copper wire"* — and
invents facts, *"I had a sandwich for breakfast"*. The 1.7B gets all three of
those right. Prompting could not fix the 0.6B's yes-bias; a bigger model did.
For a tutor teaching children, confidently wrong is a worse failure than slow.

**The latency bar is still not met.** Spec §16 floated ~2–3s. Where the time
goes now:

1. **LLM first sentence** — 3.53s, back to being the largest stage on the 1.7B.
   Behaviour fine-tuning a smaller model is the way back down; see
   `docs/model-notes.md`.
2. **ASR** — 2.07s, a fixed 30s-window encoder cost. `ggml-tiny.en` is the lever.
3. **Silence hangover** — 1.2s of dead air before work starts. A push-to-talk
   button (spec decision #5) removes it outright.

The **first** turn used to be worse than all of them, because it also paid the
pack load and the prefill of the static system prefix. `tutor.warm()` now does
both at startup on a background thread, the way `preload()` already did for the
Piper voice. Measured against the live server: **172 prompt tokens / 3339 ms
cold vs 16 tokens / 365 ms warmed — ~3.0s off the first turn.** Later turns were
never affected; they already shared that prefix.

Note the mic is an eMeet M0 Plus with **hardware AEC**: it cancels its own
speaker output almost completely (a full-volume tone played into it records at
the noise floor). That is what stops the egg hearing itself, but it also means
you cannot bench ASR by playing a question through the device's own speaker —
that needs a human talking.

## The tutor: open by default, specialist where we curate (v0.2)

v0.1 hard-scoped the tutor to the content pack and refused everything else —
ask it about game theory and it brushed you off. v0.2 inverts that: **the model
answers from its own knowledge and reasoning**, and content packs are
*specialist* knowledge that outranks the model on subjects we curate.

So there are two paths, chosen per question by retrieval:

- **No pack match** (the common case) — the model answers on its own.
  *"Who was Ashoka?" → "Ashoka was a king from ancient India…"*
- **Pack match** — the material is injected and outranks the model's memory,
  so curated subjects get taught our way, with our examples.
  *"What are fractions?" → answers with the roti example from the pack.*

Retrieval therefore has to be both *quiet* and *reachable* — a weak match drags
the answer off the question, but a missed match means the learner gets the
small model's unaided knowledge instead of our curated material.

**Retrieval is semantic** (v0.4), via a 64MB `bge-small` on a second
llama-server (`make serve-embed`). Token matching alone only fired when the
learner already used the pack's vocabulary — "how does rain happen" never
reached the water cycle. Measured on `tools/eval_retrieval.py`:

| path | recall | false positives |
|---|---|---|
| lexical only (fallback) | 55% | 3% |
| semantic + lexical tie-break | **82%** | 6% |

Measured inside the release container at 143 chunks / 8 subjects. Recall
plateaus near 82% however loose the floor gets (`--sweep`), so the remaining
misses are a **ranking** problem, not a threshold one — "why does it get dark at
night" loses to the moon lesson rather than failing to clear the bar.

If the embedding server is unreachable it falls back to lexical — degraded, not
broken. Returning nothing stays a normal, frequent outcome.

**Openers are never grounded (v0.4).** *"Let's study physics"* used to retrieve
the measurement-units lesson and answer with a lecture about metres. A whole
subject is not a question, so retrieval picks some arbitrary lesson inside it
and the learner never gets to say what they wanted. Greetings and proposals
(`let's`, `shall we`, `can we`, `i want to`, `teach me`, with no interrogative)
now skip retrieval and get a short reply that invites a specific question — and
the question that follows grounds normally, because history carries the subject
across. A real question hiding behind a greeting (*"thanks, what is a
fraction"*) is still answered as a question.

Still hardcoded, and worth revisiting: one pack file at a time
(`tutor.pack`), an English-only stopword list, and a `max_reply_chars` cut.

## Content packs (curriculum RAG)

A pack is chunks + spoken explanations + a lesson plan (spec §7). Build one
from any document:

```
python tools/build_pack.py topic.pdf --llm http://127.0.0.1:8080 -o pack.json
```

Heuristic mode (no `--llm`) needs nothing and always works; `--llm` polishes
titles/explanations through any OpenAI-compatible server (bench: llama-server;
production: the CoCo node's big model). Point `tutor.pack` in egg.yaml at the
result. With no llama-server reachable the device speaks the pack's canned
explanations directly — curated subjects still teach with zero LLM, which is
the one case where v0.2 is still as narrow as v0.1.

## Reuse from common-os

`os/wifi-manager` and the first-boot pattern are adapted from
[Uni-Phy/common-os](https://github.com/Uni-Phy/common-os). The Cloudflare
tunnel and web UI were deliberately not carried over.

## License

MIT (placeholder — confirm before public release).
