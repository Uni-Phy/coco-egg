# coco-egg zero

**Offline-first edge voice tutor** — the first hardware endpoint of the
[CommonCompute (CoCo)](https://commoncompute.org) ecosystem.

A learner presses a button on the egg, asks a question aloud, and hears a
useful spoken answer — **with zero network dependency**. Cloud inference is
a later quality upgrade (Phase 2), never a requirement. Full design
rationale in [`docs/spec.md`](docs/spec.md).

## Architecture in one breath

button → mic (eMeet M0 Plus / ReSpeaker XVF3800) → whisper.cpp →
**Qwen3-0.6B via llama-server (llama.cpp), streamed** → Piper TTS spoken
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

Inference (llama-server, whisper-server) runs as containers now — no host
builds. The compose stack pulls the official
[llama.cpp](https://github.com/ggml-org/llama.cpp) and
[whisper.cpp](https://github.com/ggml-org/whisper.cpp) images.

1. `make models` — downloads the tutor LLM (Qwen3-0.6B Q4_K_M), the whisper
   ASR model (`ggml-base.en.bin`), the [Piper](https://github.com/rhasspy/piper)
   voice (`en_US-lessac-medium.onnx` + `.onnx.json`), and retrieval embeddings
   (`bge-small-en-v1.5-f16.gguf`) into `models/`.
2. `make up` — brings up the inference stack (llama-tutor, llama-embed,
   whisper) and the egg app. Press Enter in the egg TTY, speak, listen.

Latency (end-of-speech → first audio) prints per turn; M0's job is to
measure it honestly and set the bar (spec §16).

## Measured on real hardware (M0 bench)

Pi 5 8GB / Cortex-A76 / DietPi (Debian 13), eMeet M0 Plus USB speakerphone.
whisper.cpp `ggml-base.en` + **Qwen3-0.6B Q4_K_M** via llama-server (`-c 1024`)
+ Piper `en_US-lessac-medium`. Median of 6 rotating questions, voice preloaded:

| stage | median | note |
|---|---|---|
| ASR (whisper-cli) | 1.79s | 1.44s of it is the encoder — a **fixed 30s-window cost**, independent of how short the utterance is. Model load is only 85ms. |
| LLM → first sentence | 1.60s (0.70–3.53) | prefill ~149 tok/s, decode ~23.8 tok/s on the 0.6B. Includes retrieval; the `llm_first_sentence` turn event splits retrieval out separately so the console's stages sum to `first_audio` |
| TTS (Piper) | 0.58s (0.30–1.76) | scales with sentence length, RTF ≈ 0.09. First call costs ~2.1s of voice load — `preload()` moves that off the learner's turn |
| **end-of-speech → first audio** | **5.01s (4.01–7.67)** | includes the `silence_stop_s` = 1.2s hangover the learner waits through |

> An earlier revision of this table said ~6.4s. That was wrong, and the bug is
> worth naming: the bench asked the *same* question every turn, so
> llama-server replayed a cached prompt and prefill collapsed from ~2.2s to
> ~0.10s from turn 2 on. `bench_loop.py` now rotates questions so every turn
> pays what a new question really costs.

Whole-process RSS is **945 MB**, down from 2641 MB on the 1.7B at `-c 4096`.

**The bar is still not met.** Spec §16 floated ~2–3s; measured is ~5.0s. The
v0.3 model switch took ~2.3s out, and **the bottleneck has moved off the LLM**:

1. **ASR is now the largest single stage** at 1.78s, and 1.44s of that is
   whisper's fixed 30s-window encoder — a 1.6s question costs the same as a 25s
   one. `ggml-tiny.en`, a persistent whisper-server, or streaming decode are the
   levers; caching the model is not (load is already only 85ms).
2. **Silence hangover** — 1.2s of dead air before work even starts. A
   push-to-talk button (spec decision #5) removes it outright.
3. **LLM prefill** — still the most *variable* slice, and it is what the
   retrieval work keeps short.

Nothing here overlaps: the pipeline is fully serial. Streaming ASR plus
speculative retrieval on a partial transcript is the next structural win.

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
| lexical only | 33% | 0% |
| semantic + lexical tie-break | **87%** | 29% |

If the embedding server is unreachable it falls back to lexical — degraded, not
broken. Returning nothing stays a normal, frequent outcome.

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
