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

## Bench quickstart (M0: Pi 5 + eMeet M0 Plus)

1. Build [whisper.cpp](https://github.com/ggml-org/whisper.cpp) and put
   `ggml-base.en.bin` in `models/`.
2. Build [llama.cpp](https://github.com/ggml-org/llama.cpp) so `llama-server`
   is on your PATH, then `make model` to download Qwen3-1.7B Q4_K_M
   (needs `pip install huggingface_hub` for the `hf` CLI).
3. Install [Piper](https://github.com/rhasspy/piper) and a voice
   (`en_US-lessac-medium`) in `models/`.
4. `make serve` in one terminal (llama-server, thinking disabled), then
   `make setup && make run` in another — press Enter, speak, listen.

Latency (end-of-speech → first audio) prints per turn; M0's job is to
measure it honestly and set the bar (spec §16).

## Measured on real hardware (M0 bench)

Pi 5 8GB / Cortex-A76 / DietPi (Debian 13), eMeet M0 Plus USB speakerphone.
whisper.cpp `ggml-base.en` + Qwen3-1.7B Q4_K_M via llama-server + Piper
`en_US-lessac-medium`. Median of 5 turns, voice preloaded, WiFi down:

| stage | median | note |
|---|---|---|
| ASR (whisper-cli) | 1.79s | 1.44s of it is the encoder — a **fixed 30s-window cost**, independent of how short the utterance is. Model load is only 85ms. |
| LLM → first sentence | 3.80s (1.34–4.09) | dominated by prefill of the grounded prompt at ~56 tok/s; decode runs ~9.8 tok/s |
| TTS (Piper) | 0.60s (0.42–1.62) | scales with sentence length, RTF ≈ 0.09. First call costs ~2.1s of voice load — `preload()` moves that off the learner's turn |
| **end-of-speech → first audio** | **7.31s (4.96–8.63)** | includes the `silence_stop_s` = 1.2s hangover the learner waits through |

> An earlier revision of this table said ~6.4s. That was wrong, and the bug is
> worth naming: the bench asked the *same* question every turn, so
> llama-server replayed a cached prompt and prefill collapsed from ~2.2s to
> ~0.10s from turn 2 on. `bench_loop.py` now rotates questions so every turn
> pays what a new question really costs.

**The bar is not met yet.** Spec §16 floated ~2–3s; the honest measured number
is ~7.3s. Where the time actually goes, in priority order:

1. **LLM prefill** — the biggest and most variable slice. The 124-token SYSTEM
   preamble is a shared prefix that llama-server caches, but the retrieved pack
   material after it differs per question and is re-prefilled every time.
   Retrieving `k=1` instead of `k=3` cuts ~110 tokens (~2s).
2. **ASR encoder** — whisper's fixed 30s window means a 1.6s question costs the
   same 1.44s as a 25s one. `ggml-tiny.en` or a persistent whisper-server are
   the levers; caching the model is not (load is already only 85ms).
3. **Silence hangover** — 1.2s of dead air before work even starts. Lowering
   `silence_stop_s` trades latency against clipping the learner.

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

Retrieval therefore has to be *quiet*: a weak match is no longer harmless
padding, it drags the answer off the question. It ignores stopwords and drops
chunks scoring under `Pack.MIN_RATIO` of the best, so returning nothing is a
normal, frequent outcome.

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
