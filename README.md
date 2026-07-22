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

## Content packs (curriculum RAG)

The tutor grounds every answer in a content pack — chunks + spoken
explanations + a lesson plan (spec §7). Build one from any document:

```
python tools/build_pack.py topic.pdf --llm http://127.0.0.1:8080 -o pack.json
```

Heuristic mode (no `--llm`) needs nothing and always works; `--llm` polishes
titles/explanations through any OpenAI-compatible server (bench: llama-server;
production: the CoCo node's big model). Point `tutor.pack` in egg.yaml at the
result. With no llama-server reachable the device speaks the pack's canned
explanations directly — teaching works with zero LLM.

## Reuse from common-os

`os/wifi-manager` and the first-boot pattern are adapted from
[Uni-Phy/common-os](https://github.com/Uni-Phy/common-os). The Cloudflare
tunnel and web UI were deliberately not carried over.

## License

MIT (placeholder — confirm before public release).
