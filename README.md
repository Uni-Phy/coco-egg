# coco-egg zero

**Offline-first edge voice tutor** — the first hardware endpoint of the
[CommonCompute (CoCo)](https://commoncompute.org) ecosystem.

A learner presses a button on the egg, asks a question aloud, and hears a
useful spoken answer — **with zero network dependency**. Cloud inference is
a later quality upgrade (Phase 2), never a requirement. Full design
rationale in [`docs/spec.md`](docs/spec.md).

## Architecture in one breath

button → mic (eMeet M0 Plus / ReSpeaker XVF3800) → whisper.cpp →
small local LLM via Ollama → Piper TTS → speaker. Transcripts buffer
locally and sync opportunistically to the CoCo node, which fine-tunes the
on-device model and ships it back via OTA. Fleet access via ShellHub.

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
2. Install [Piper](https://github.com/rhasspy/piper) and a voice
   (`en_US-lessac-medium`) in `models/`.
3. Install [Ollama](https://ollama.com) and `ollama pull llama3.2:3b`
   (placeholder model — see spec open decision #1/#8).
4. `make setup && make run` — press Enter, speak, listen.

Latency (end-of-speech → first audio) prints per turn; M0's job is to
measure it honestly and set the bar (spec §16).

## Reuse from common-os

`os/wifi-manager` and the first-boot pattern are adapted from
[Uni-Phy/common-os](https://github.com/Uni-Phy/common-os). The Cloudflare
tunnel and web UI were deliberately not carried over.

## License

MIT (placeholder — confirm before public release).
