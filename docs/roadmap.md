# Roadmap: v0.3 → 1.0

Three things we want: **courses from PDFs**, a **learner layer**, a **web
console**. This orders them by what blocks what, and maps the end state onto
spec §16 so `1.0` means something concrete: **1.0 = M1 exit** — one finished
egg, fully useful with no network, remotely manageable when connected.

## The constraint that sets the order

Retrieval is the binding constraint on all three, and it is currently broken
for real learners. Measured on the 2-subject library:

| | recall on natural phrasing | false positives |
|---|---|---|
| topic-match rule (v0.3, shipped) | **0/7** | 0/3 |
| any-overlap (v0.2) | 4/7 | 2/3 |

Questions that retrieve nothing today, despite the subject being loaded:
"how does rain happen" (water cycle), "what rights do I have" (constitution),
"who runs my village" (panchayat), "how do animals breathe" (respiration),
"what is one half" (fractions), "tell me about the king who became a buddhist"
(Ashoka).

Lexical overlap only fires when the learner already knows the pack's
vocabulary. Tightening it for precision zeroed recall; loosening it for recall
brings back the hallucinations (the 0.6B answered a breakfast question from
the fractions lesson because both contain "have"). **You cannot have both with
token matching**, and at 0.6B a retrieval miss means the learner gets the
model's unaided, unreliable knowledge instead of our curated material.

So: **adding more PDFs multiplies content that will not be found.** Retrieval
comes first, or the course library is decorative.

---

## v0.4 — make retrieval work (the keystone)

- **Semantic retrieval.** Embed chunks and questions; rank by similarity.
  `onnxruntime` is already on the device (Piper uses it), so a small sentence
  embedding model (~90MB, e.g. a MiniLM/BGE-small class model) is an ONNX file
  and a cosine, not a new runtime. Alternative: `llama-server --embedding`,
  keeping one runtime family. Cost is ~50–100ms per query and a one-off embed
  per chunk — affordable now that RSS dropped to 945MB of 8GB.
- **Hybrid scoring.** Embeddings for recall, the lexical/title signal for
  precision, so an exact term match still wins. Keep `MIN_RATIO`-style cutoff:
  returning nothing must stay a normal outcome.
- **Eval harness.** Recall, precision, and answer correctness as regression
  tests. Non-negotiable once courses are a library: without it, adding
  chemistry silently breaks biology and nobody notices until a demo.

*Exit: the seven questions above retrieve the right lesson, and the three
known false positives still return nothing.*

## v0.5 — SHIPPED, but not this list

What actually shipped as v0.5: the Jyotisha demo course (21 chunks), quiz mode,
and three faults found in a real session — the verbatim-repeat on a subject
change, the history window re-prefilling every turn, and a retrieval miss on the
question the course exists to answer. See `docs/model-notes.md` §11–12.

The items below were the *plan* for v0.5 and did not ship. They move to v0.6.
Left here rather than rewritten, because the gap between what was planned and
what a week of real use demanded is the more useful record.

## v0.5 (planned) — courses at scale (goal 1)

- **PDF → pack, hardened.** `tools/build_pack.py` already does .txt/.md/.pdf
  with `--llm` polish (the civics pack was built this way). Needs: better
  chunking than fixed 700 chars, reliable titles (titles carry the retrieval
  signal), and quality checks on the output.
- **Pack registry** — versions, enable/disable, which subjects are live. The
  loaded set is already the supported-subject list; make it manageable.
- **Node sync** — spec M1 requires content-pack sync from the CoCo node when a
  link exists. Buffer-and-forward, never blocking the loop.

**Open decision: where does PDF→pack run?** On-device is feasible (the Pi did
the LLM polish in ~30s for 3 chunks) and keeps it offline-capable. On the node
gives better chunking from a bigger model. Recommend: node when connected,
device as fallback, same tool either way.

## v0.6 — auth, then the rest of the console

The console itself shipped in v0.5, and it shipped the view this section argued
for: the reasoning trace, plus the student cue view that doubles as the LED
prototype. What is left is what makes it safe and what makes it useful beyond
watching.

- **Authentication. This gates everything else here**, and it is the reason the
  console is demo-while-watching today. The page carries what children said
  aloud, and it is currently an open LAN port. Nothing below ships before it.
- Transcript browser — the first thing auth unlocks, and by far the most
  sensitive. Also the input to the profile loop in v0.7.
- Authoring: upload a PDF → build → *preview what it retrieves* → publish.
- Learner profile editing.
- Device/fleet status. Still lowest priority; ShellHub already covers access.

Carried from the v0.5 plan, which did not ship: PDF→pack hardening, a pack
registry, and node sync.

### What the console section originally argued, kept because it held up

**It runs on the device**, not the node — offline-first is the product, and a
console you cannot open in a classroom with no internet is the wrong artifact.

The prioritisation question answered: the first and possibly only view worth
building is the **reasoning trace** —

> heard → retrieved chunks *with scores* → answer streaming in → spoken,
> with per-stage timings

because one view serves four audiences at once: it *is* the demo (you watch
the egg think), it *is* the debug tool (every bug found during M0 bring-up was
invisible without one — each needed a throwaway script), it *is* how retrieval
gets tuned, and it *is* the eval viewer.

Then, in order:

1. Transcript browser — what learners actually asked, which is also the input
   to the profile loop below.
2. **Authoring**: upload a PDF → build → *preview what it retrieves* → publish.
   The preview step is the point; publishing a pack blind is how you regress.
3. Learner profile editing.
4. Device/fleet status — lowest priority, ShellHub already covers access.

Note there is no HTTP server in the device app today; `main.py` is a TTY menu.
This is genuinely new surface area.

## v0.7 — the learner layer grows up (goal 2)

Today the profile is static YAML → prompt. To actually adapt:

- **Profile shapes retrieval**, not just tone — prefer chunks at their level,
  their examples, subjects they are working through.
- **Learn from transcripts.** Device logs → sync → node analyses → profile
  updates → back down. Spec §3 already assigns transcript analysis to the node;
  this closes that loop.
- Keep it schema-free. It grows by writing keys, not migrations.

**Open decision: who is the learner?** One egg in a classroom serves many
children. Options: no identity (one shared profile per egg — simplest, and
maybe right for v1), a teacher-selected profile, or voice identification (real
work, and a privacy question with minors). This gates the profile design and
the console's shape, so decide it before v0.6 UI work.

## v0.8 — hardware and the UX that needs it (M1 parts)

Tracked on `v0.3-ux`; see `docs/ux-brief.md`.

- XVF3800 mic array, LED state ring, push-to-talk button, enclosure.
- **Push-to-talk deletes the 1.2s VAD hangover** — pure latency win, no model
  change, and it resolves spec decision #5.
- Acknowledgement audio ("let me think") — takes *perceived* first-audio to
  ~0.5s. Biggest demo lever available; a design call, not an engineering one.
- Barge-in: hardware AEC is confirmed capable (measured — a full-volume tone
  records at the noise floor). Spec decision #3's "when the UX is ready" is the
  only remaining gate.
- Bluetooth audio fallback, ShellHub enrolment, container/OTA update path.

## v1.0 = M1 exit (spec §17)

A learner triggers it, asks aloud, hears a useful answer **with no network**;
latency meets the bar set at M0; BT fallback works; it appears in ShellHub and
is remotely updatable; no plaintext cloud secrets; it looks like a product.

---

## Latency, for reference

Currently **5.01s** median perceived (spec §16 wanted 2–3s). Where the
remaining time is, and which version takes it:

| | cost | fixed by |
|---|---|---|
| ASR (whisper, fixed 30s-window encoder) | 1.78s | v0.4–0.5: `tiny.en` or streaming decode |
| VAD hangover | 1.2s | v0.8: push-to-talk |
| LLM first sentence | 1.60s | mostly done (0.6B) |
| TTS | 0.58s | already ~11x realtime |

ASR is now the largest single stage — more model work will not help. And the
pipeline is entirely serial: streaming ASR plus speculative retrieval on a
partial transcript is the one structural change that beats tuning.

## Carried risk

Out-of-pack questions are answered from model knowledge rather than refused
(deliberate, see model-notes §5). With a 0.6B that means confident wrong
answers outside curated subjects. Retrieval recall is what shrinks the
out-of-pack surface — another reason v0.4 comes first. The eval harness should
measure it so this can be revisited with data.

---

## Performance track (added 2026-07-29, from Jenya's review)

Measured first, because the obvious lever was the wrong one. On a grounded turn
the LLM stage is **prefill-bound**: 186 prompt tokens / 3756 ms of prefill
against 28 tokens / 2822 ms of decode — 57% of the stage before a word is
generated. A faster-decoding model improves the smaller half.

1. **Model swap to LFM2.5 1.2B.** Reported on Pi 5: 71 t/s prefill, 15 t/s
   decode, against our measured 49.5 / 9.9. Applying those ratios projects
   6.58s → 4.80s on a grounded turn, saving ~1.8s. Worth doing. Gate it on the
   three accuracy cases that forced the 0.6B → 1.7B move (magnet/copper,
   magnet/aluminium, breakfast) plus `make eval` — 1.2B sits between the model
   that failed them and the one that passes, so "similar quality" is a claim to
   test, not assume.
2. **Shrink the prompt.** Same lever as (1) and it compounds with it, since
   prefill is the larger half. `grounding_full_chunks` is already 1; the
   remaining spend is the system prefix and history.
3. **First audio on a clause boundary, not a sentence.** Streaming already
   speaks sentence one as it lands, so the lever is not `max_reply_chars` (a
   whole-reply cap) but *when the first chunk is considered speakable*. Splitting
   the first utterance at a comma would start audio sooner without shortening
   the answer. Cheap, and the risk is prosody — a clipped-sounding fragment.
4. **ASR: `ggml-tiny.en` before Moonshine.** Both attack the same thing (whisper
   pads every utterance to a fixed 30s encoder window, so 2.07s is paid whatever
   the length). `tiny.en` is a URL change on the server we already run; Moonshine
   is a new runtime. Try the cheap one first. Moonshine's noise-robustness trade
   is genuinely cheaper for us than for most — the eMeet has hardware AEC.
5. **Silero VAD** for the 1.2s hangover, if hands-free must stay. Push-to-talk
   (spec decision #5) removes it outright and is still the simpler answer.
6. **Orange Pi 5 Pro (DDR5).** Decode is memory-bandwidth-bound, so the +29–58%
   is the right physics. Correctly ranked last: it means migrating the whole
   DietPi and audio stack for a gain that (2) and (3) partly deliver in software.

**Model swapping is a continuous process, so it needs a harness, not a
procedure.** One command to switch models, one to run the regression — the three
accuracy cases, `make eval`, and the prefill/decode split — so a candidate is a
ten-minute decision instead of a vibe. That harness comes before (1).
