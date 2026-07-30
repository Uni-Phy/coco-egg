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
> Add user to `audio` and `docker` groups:
> ```shell
> sudo usermod -aG audio,docker $USER
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
make build  # rebuilds egg and whisper images. Only needed after a Dockerfile edit.
```

## Updating a device

`device/`, `fixtures/`, `tools/` and `egg.yaml` are bind-mounted into the egg
container, so a code or content change is a pull and a restart — no image
rebuild unless the Dockerfile changed.

```shell
git pull && docker restart egg
```

Give it ~15s before the first question: `tutor.warm()` is loading the pack and
prefilling the static prompt prefix in the background, and racing it costs you
the ~3.0s that buys.

Then check it on real hardware, which is the only check that counts:

```shell
docker exec -it egg python tools/relcheck.py
```

A device needs a GitHub **deploy key** to pull. If the key is not one of ssh's
default names it will never be offered, and `git pull` fails with
`Permission denied (publickey)` while `ssh -i <key> -T git@github.com`
authenticates perfectly — point `~/.ssh/config` at it:

```
Host github.com
    IdentityFile ~/.ssh/id_coco
    IdentitiesOnly yes
```

## If the tutor says "I can't reach my tutor brain"

That is the offline fallback: llama-server is unreachable. It has twice been
the same cause, so check this first.

```shell
ss -ltnp | grep :8080      # who owns the port?
docker ps -a | grep llama  # exited (255) with no network attached?
```

A **bare-metal `llama-server` grabbing port 8080 before docker can** is the
culprit. There is a `llama-server.service` systemd unit on the bench Pi that
starts one at boot; it binds `127.0.0.1`, so it answers `curl localhost:8080`
from the host while being invisible to every container — which makes it look
like the model is fine and the app is broken. Docker's `llama-tutor` then fails
its port bind, exits 255, and gets no network at all.

Pick one deployment model and stick to it. The compose stack is the documented
one, so:

```shell
sudo systemctl disable --now llama-server
docker compose -f deploy/docker-compose.yml up -d --force-recreate llama-tutor
```

The device survives reboots on its own once nothing is competing for the port —
every service is `restart: unless-stopped`.

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
| **end-of-speech → first audio** | **8.32s (5.57–10.02)** | includes the `silence_stop_s` = 1.1s hangover the learner waits through |

**Model choice is a deliberate accuracy-over-speed trade.** Qwen3-0.6B runs the
same loop at ~5.0s, but it answers "Yes" to yes/no questions regardless of the
lesson in front of it — *"Yes, a magnet will stick to a copper wire"* — and
invents facts, *"I had a sandwich for breakfast"*. Prompting could not fix the
yes-bias; a bigger model did. For a tutor teaching children, confidently wrong
is a worse failure than slow.

*This README previously claimed the 1.7B "gets all three of those right". It did
not.* Sampled six times it fabricated the breakfast answer four times — *"You had
something warm and tasty for breakfast!"* — and the original claim came from a
single run at temperature 0.7. Fixed by telling the model explicitly that it
cannot see the student's own life, and now verified 5/5 by `make model-check`,
which samples the flaky cases rather than trusting one run. **A case that fails a
third of the time is invisible to a single sample**, which is how the wrong claim
got written down.

## Swapping the tutor model

Swapping is a continuous process, so it is a registry plus two commands:

```shell
make model-list                    # candidates, and which is live
make model-use NAME=qwen3-1.7b     # fetch if needed, restart llama-tutor
make model-check                   # accuracy cases + prefill/decode split
```

`models.json` is the tracked registry; the live choice lands in `deploy/.env`
(gitignored — a bench and a device may legitimately differ). Swapping the tutor
model does **not** affect retrieval, which uses the embed model, so `make eval`
is a separate and unchanged gate.

`model-check`'s accuracy cases are not invented: each is a real failure a real
model produced on this device. Qwen3-0.6B stays registered as `KNOWN BAD` on
purpose — the harness must fail on it, and if it ever passes, the harness is
broken rather than the model.

**The latency bar is still not met.** Spec §16 floated ~2–3s. Where the time
goes now:

1. **LLM first sentence** — 3.53s, back to being the largest stage on the 1.7B.
   Behaviour fine-tuning a smaller model is the way back down; see
   `docs/model-notes.md`.
2. **ASR** — 2.07s, a fixed 30s-window encoder cost. `ggml-tiny.en` is the lever.
3. **Silence hangover** — 1.1s of dead air before work starts. A push-to-talk
   button (spec decision #5) removes it outright. (It was documented as 1.2s
   until v0.6: `int(1.2 / 0.1)` is 11, not 12, so the device had always used
   1.1s. The arithmetic is `round()` now and the default says 1.1.)

Say nothing after pressing and the device gives up after **`no_speech_s` = 4s**,
rather than recording to `max_utterance_s`. It used to hold the room for 30
seconds, which reads as a hang rather than a miss.

**On a grounded turn the LLM stage is prefill-bound, not decode-bound** — 186
prompt tokens / 3756 ms of prefill against 28 tokens / 2822 ms of decode, so 57%
of it is spent before a single word is generated. That matters when choosing a
lever: a faster-decoding model improves the smaller half, while **shrinking the
prompt improves the larger one**. Grounding and conversation history are what
fill it, which is why the history fix in v0.5 (below) was worth ~2.5s a turn.

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
| semantic + lexical tie-break | **82%** | 12% |

Measured inside the release container at 164 chunks / 9 subjects. Recall
plateaus near 82% however loose the floor gets (`--sweep`), so the remaining
misses are a **ranking** problem, not a threshold one — "why does it get dark at
night" loses to the moon lesson rather than failing to clear the bar.

When a question matters and retrieval misses it, the fix is usually a chunk, not
a threshold. *"Do the stars decide my future"* reached the sky course's
starlight lessons and never got near Jyotisha, because the chunk that answers it
was written in the words of a study ("personality or life events") and nobody
asks it that way. Writing it in the asker's vocabulary fixed it; no floor would
have.

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

## Quiz mode — the egg as quiz master

Say **"quiz me"**, *"let's play a quiz"* or *"ask me some questions"* and the
device turns into a quiz master: it asks, you answer aloud, it marks you and
keeps score. *"Stop"* ends it early, *"say that again"* repeats, *"I don't
know"* passes without being marked harshly. `quiz me on the sky` limits the
round to a matching subject.

**No model is involved, and that is the design.** A quiz turn is a question, a
verdict and the next question — at 3.5s of generation each that stops being a
game. Questions are authored in the pack and marked against a generous
accept-list, so a turn costs only TTS (~1.4s) and cannot be hallucinated. Same
reasoning that keeps `explain` away from the LLM in `build_pack.py`: being
confidently wrong while claiming to *mark* a child is the worst failure the
device has available.

The cost is real: judging is string matching, so an unusually phrased correct
answer gets marked wrong. Accept-lists carry numerals and words both, and a
wrong verdict always states the answer rather than only the miss. A pack with no
authored questions says so instead of inventing any.

```
learner> let's play a quiz
egg    > Alright! 3 questions on Jyotisha. Question 1. How many rashis are there?
learner> twelve
egg    > Correct! Twelve. The sun spends about a month in each.
```

## The console — what the egg is doing, and why

`http://<device>:8090` while the app is running. Two views, one page, because
they want the same events.

**The student view is an egg** that shows state: breathing amber when idle,
green while it listens, filling while it thinks, steady blue while it speaks. It
is a renderer of `presentation.CUES` and holds no colours of its own — the table
arrives over `/cues`, which is the **same one the M1 LED ring driver will read**.
That is most of why it exists: the screenless device needs its ring designed and
watched before the hardware lands, and this way the driver becomes a second
renderer rather than a redesign.

Motion carries the meaning, not colour. No two states share a motion, so the cue
survives colour blindness, a diffuser washed out by classroom daylight, and a
renderer holding nothing but GPO pins. THINKING grows toward the outline and
never closes it, so an overrun visibly slows instead of sitting at 100% looking
stuck.

**Press `space` to talk** (or tap the egg). It goes through the same trigger
queue as Enter in the terminal — the console is a second *caller* of one route,
not a second route, so GPIO at M1 becomes a third caller rather than a third
branch. A press while the egg is still answering is refused, not banked, so an
impatient tap does not queue four turns.

**Press `d` for the dev trace** — the reasoning behind the answer:

```
› which star was the moon sitting in when i was born
  ▸ nakshatra              0.781  +lex
  ▸ rashi-and-nakshatras   0.702
    kundali-map            0.648        semantic · floor 0.62
  A nakshatra is a patch of sky the moon travels through. …
  hangover 1.2s   retrieval 0.4s   llm_first_sentence 3.5s   tts 1.3s
```

Every candidate with its score and whether it was kept, the reply as it streams,
per-stage timings with slow ones flagged, and degraded fallbacks. It shows the
difference between *retrieved nothing* and *new subject, deliberately not
grounded* — invisible in the spoken answer, and the cause of a whole afternoon's
confusion before it existed.

See it without a device, mic or models:

```shell
python tools/console_demo.py          # space advances a scripted turn
python tools/console_demo.py --auto   # free-run
```

**No authentication yet — it lands in v0.7.** It serves only live events — never stored
transcripts — and says so on the page, but it is a LAN port carrying what
children said aloud. Demo it while you are watching it; set `console.enabled:
false` in `egg.yaml` for anything else.

## Jokes, and why they are not generated

Say **"tell me a joke"**, then *"another one"*. Asked for a joke the 1.7B tells
the same joke — not a similar one, the same one, because joke variety is exactly
what a small model has none of. So jokes are authored (`fixtures/jokes.json`)
and, more importantly, **dealt from a deck rather than picked at random**: every
joke is told once before any is told twice, and the deck survives a restart.

That second part is the one that matters at a party. With 44 jokes and random
choice, the chance of hearing a repeat inside ten draws is about 68% — which
reads as a broken device, not as luck. Quiz questions come off the same dealer,
so round two is not round one again.

Jokes are deliberately **not** a content pack and never enter the retrieval
corpus: a punchline that can be retrieved will eventually be retrieved for a
real question. Setup and punchline are spoken as two sentences, because the
device speaks one at a time and that split is the comic pause.

## No speaker, no microphone: use a phone

Open **`https://egg.local:8090`** on a phone and it becomes the egg's audio
hardware — tap the egg to talk into the phone, tap **listen** to hear the answer
come back out of it. Several people can listen at once, which one small speaker
cannot do. The device needs no USB speakerphone at all.

It is the same pipeline, not a browser-shaped copy of one. `/listen` puts the
recording on the same trigger queue the button and the space bar use, and
everything after the transcript — retrieval, the tutor, TTS — neither knows nor
cares where the question was recorded.

```yaml
audio:
  output: browser     # device | browser | both
```

**Two constraints worth knowing before you demo it.**

**HTTPS is required, and the warning is unavoidable.** A browser refuses
`getUserMedia` outside a secure context, so the microphone simply does not exist
on `http://`. The console therefore serves HTTPS with a certificate it generates
itself into `state/`, and the first visit on each phone shows a "not private"
warning to tap through. There is no way around that without a real domain and a
real CA, which an offline classroom device does not have.

You do not have to type the scheme. The port sniffs its first byte — a TLS
handshake starts `0x16`, an HTTP request starts with a method — and answers
plain HTTP with a redirect to HTTPS. Before that it was TLS-only, so a phone
given `egg.local:8090` tried `http://` first, had its connection dropped, and
showed *"cannot open the page"* — the same message it shows for a device that
is not on the network at all. That cost an evening of debugging mDNS and the
subnet for a missing eight characters.

**The certificate must name the address people type.** `hostname -I` runs inside
the container and returns the *container's* address, so the LAN address is
invisible from in there. Name it yourself, then delete the cert to regenerate:

```yaml
console:
  cert_hosts: [egg.local, 10.10.10.186]
```

Both phone-hotspot ranges (`172.20.10.x`, `192.168.43.x`) are covered
automatically, so moving between a WiFi network and a hotspot does not mean a
new certificate and a fresh warning.

**`egg.local` needs mDNS on the device** — `avahi-daemon` plus a hostname of
`egg`. On DietPi also set `AUTO_SETUP_NET_HOSTNAME=egg` in `/boot/dietpi.txt`,
or a rebuild reasserts the old name and the URL stops resolving. Note Android's
mDNS support is patchier than iOS's; the IP always works.

### When it answers but you hear nothing

Every one of these has happened, and none of them looked like what it was. Read
the log first: if it printed `reply:`, the pipeline is fine and the problem is
purely where the audio went.

**Check the mixer before anything else.** A USB speakerphone can come up at
zero, and `aplay` reports success while playing into it:

```shell
amixer -c 0 sset PCM 90% unmute && sudo alsactl store   # store, or a reboot re-mutes
```

**Check the routing.** `audio.output: browser` deliberately skips `play_wav`,
so the device speaker is silent by design. The startup banner names the routing
rather than the ALSA device, because a line reading `audio out: plughw:…` about
a speaker that is off by configuration is worse than no line at all:

```
audio out:  plughw:CARD=Plus,DEV=0 + browser
```

**On iOS, reload the page before you conclude anything.** Clips are fetched and
played through Web Audio, not an `<audio src>`, because a media element on iOS
loads through AVFoundation — which does *not* share Safari's certificate
exception. On a self-signed console that renders the page perfectly and fails
every clip. The page is served `no-store` so a phone cannot hold yesterday's
JavaScript against today's device.

Clip failures are flashed on the page. They used to be skipped silently, which
is the single reason this class of bug kept looking like a network fault.

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
