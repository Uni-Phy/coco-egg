# The console — design

Stream B (`docs/parallel-tasks.md`). One web page, served **by the egg**, that
shows what the egg just did:

> heard → retrieved chunks *with scores* → answer streaming in sentence by
> sentence → spoken, with per-stage timings

This document is the design for that view (B3) and the contract for the event
bus underneath it (B1, shipped in `device/coco_egg/events.py`). B2 — the HTTP
server — is the seam between them and is specified here only as far as the two
halves have to agree.

## 1. What this is, and what it is not

It is a **reasoning trace**. Every bug in this project so far was invisible
until someone printed the intermediate state, and each time that meant a
throwaway script: the VAD cut-off was only findable because the mis-heard
question could be read as text (`docs/model-notes.md` §4); the "I had a roti
for breakfast" hallucination turned out to be *retrieval*, not model ignorance,
and only after someone printed the retrieved chunk (§5); the bench's ~6.4s
median was wrong for a week because nobody printed per-turn prefill (README).
The console exists to make that state permanently visible instead of
reconstructing it with a script each time.

It is **not**:

- a control surface — it never triggers a turn (§9),
- a fleet dashboard — ShellHub is that (spec §9),
- a cloud service — it runs on the device, offline, or it is the wrong artifact
  (`docs/roadmap.md` v0.6).

Two facts drive nearly every decision below.

**The wait is 5.0–5.6s and will stay there for a while.** Spec §16 wanted 2–3s.
The remaining time is structural: 1.2s of VAD hangover that push-to-talk
deletes (v0.8), 1.78s of ASR of which 1.44s is whisper's fixed 30s-window
encoder (v0.4–0.5), and a fully serial pipeline. So the console does not get to
treat the wait as a loading state to be hidden. **Making the wait legible is
the feature.** A spinner for five seconds says "broken". A trace that fills in
— transcript at ~3.0s, retrieved chunks at ~3.1s, first sentence at ~4.6s —
says "working, and here is where the time went".

**Retrieval is 87% recall / 29% false positives, and its output never appears
in the answer.** A wrong chunk does not look like a retrieval bug; it looks
like the model being stupid. That is exactly how "why is the sky blue" got
filed as model ignorance for a week when it was the water-cycle chunk. So the
retrieval lane is not a debug detail tucked at the bottom — it is the second
thing on screen, and it shows scores.

## 2. Constraints

| | |
|---|---|
| Runs on | the Pi 5, served over the LAN. Viewed on a laptop or phone. |
| Network | none assumed. No CDN, no fonts, no build step, no npm. |
| Stack | one `.html`, one `.css`, one `.js`, vanilla, hand-written. Under ~600 lines total is the bar; if it needs a framework, the design is wrong. |
| Transport | Server-Sent Events. One direction, auto-reconnecting, plain text, ~40 lines of stdlib on the server. WebSockets buy nothing here. |
| Cost to the loop | zero. The bus drops events rather than making the egg wait; the HTTP server dying must not be visible to a learner. |
| Screen | the device has none. This page is the only screen the system has. |

Vanilla is not asceticism. There is no build step on a Pi in a classroom, and a
console that cannot be edited over ShellHub with `vi` at 2am the night before a
demo is not the console this project needs.

## 3. The reasoning-trace view

### 3.1 Anatomy of a turn

One turn is one **card**. A card has five lanes in pipeline order, top to
bottom, so the eye travels the same direction as the data:

```
┌───────────────────────────────────────────────────────────────────────────┐
│ coco-egg                        ● THINKING   3.4s          Calm │ Full    │
├───────────────────────────────────────────────────────────────────────────┤
│ ▼ turn 41 · live                                                          │
│                                                                           │
│  heard      "how does rain happen"                             asr 1.63s  │
│  ──────────────────────────────────────────────────────────────────────   │
│  retrieved  semantic · floor 0.58                           lookup 0.06s  │
│                                                                           │
│    Science & Maths · The water cycle                        ┊  ┊          │
│    ▐████████████████████████████████▌          0.71  kept   +0.13         │
│    Science & Maths · Photosynthesis                        ┊  ┊           │
│    ▐███████████████████████▌⊕                  0.62  cut    +0.04         │
│    Civics & History · Gram Panchayat                       ┊  ┊           │
│    ▐░░░░░░░░░░░░▌                              0.49  cut    −0.09         │
│                                            floor 0.58 ─────┘  └─ 0.92×best│
│  ──────────────────────────────────────────────────────────────────────   │
│  answer                                                      first 1.58s  │
│    1  Rain happens because of the water cycle.                ♪ spoken    │
│    2  The sun heats water in rivers and the sea until it…     ♪ speaking  │
│    3  ▌                                                                   │
│  ──────────────────────────────────────────────────────────────────────   │
│  hangover▓▓▓▓ asr▓▓▓▓▓▓▓ ·look· llm▓▓▓▓▓▓░░░ tts░░░░       3.4s / ~5.0s   │
│       1.20      1.63       0.06     1.58                                  │
└───────────────────────────────────────────────────────────────────────────┘
│ ▸ 14:31:52  "what rights do I have"      constitution 0.66        4.9s    │
│ ▸ 14:30:18  "why is the sky blue"        water-cycle 0.60  ⚠      5.4s    │
│ ▸ 14:29:40  "what is 7 times 8"          no lesson                4.2s    │
│ ▸ 14:28:02  (didn't catch that)                                     —     │
└───────────────────────────────────────────────────────────────────────────┘
```

**heard** — the ASR transcript, verbatim, in quotes. Verbatim matters: half of
what looks like tutor stupidity is a mis-heard question, and paraphrasing here
would hide it. Empty transcript renders as `(didn't catch that)`, §6.4.

**retrieved** — see §3.3. The header names the *path* (`semantic` /
`keyword`), which is also how the embedding-server outage surfaces (§6.1).

**answer** — one row per sentence, numbered, appearing at the moment the model
produced it. The `♪` marker moves independently: `sentence` events say
generated, `spoken` events say the learner is hearing it now. The gap between
the two is TTS plus playback, and being able to see the text run ahead of the
voice is what makes "streaming is the architecture, not an optimisation"
(spec §7) visible rather than asserted. A caret marks the sentence in flight.

**timeline** — §3.2.

### 3.2 Showing a five-second wait without looking frozen

Five mechanisms, in rough order of how much work they do.

**1. Content accretes; there is never an empty screen.** Each stage drops its
artifact as it finishes, so the card grows through the wait:

| ~elapsed | what appears |
|---|---|
| 0.0s | card opens, state `LISTENING` |
| 1.2s | hangover segment closes, state → `THINKING` |
| 3.0s | **the transcript** |
| 3.1s | **the retrieved chunks, with scores** |
| 4.6s | **sentence 1** |
| 5.2s | `♪ speaking` on sentence 1; sentences 2, 3 land behind it |

Only the ~1.5s between the chunks and the first sentence is genuinely
contentless, and that is a normal length for a pause. The 5s wait was never
one wait — it is four, and none of them is long enough to read as a hang once
each ends in something arriving.

**2. The timeline is a budget, not a spinner.** The track is pre-drawn with all
five segments at their **measured medians** (README): hangover 1.20, asr 1.79,
retrieval 0.05, llm 1.55, tts 0.58 — about 5.2s of track. Completed segments
fill solid with their real number under them. The running segment fills toward
*its own* median and stops there rather than reaching the end. This is possible
only because the latency was measured honestly, and it is the payoff for having
done so: the bar is predictive, so a normal turn visibly tracks a known shape.

**3. Overrun is a signal, not a stall.** When a stage passes its median the
segment keeps growing and turns amber, pushing the rest of the track right; the
total reads `6.8s / ~5.0s`. Nothing ever hits 100% and sits there — the single
worst thing a progress bar can do. A demo viewer reads "slower than usual",
which is true; we read "the LLM segment is at 3.4s, go look at prefill", which
is also true. One widget, two audiences, no extra code.

**4. A live elapsed counter,** 0.1s resolution, next to the state chip. Cheap
and unambiguous: a moving number is proof of life in a way an animation is not,
because an animation keeps running when the socket has died.

**5. The state chip speaks the device's own language** — `IDLE / LISTENING /
THINKING / SPEAKING / OFFLINE / ERROR`, the six `UiState` members, the same
six the LED ring will show (spec §5). One vocabulary across the LED, the TTY
and the console. When someone says "it's stuck in THINKING", all three agree
what that means.

What is deliberately *not* used: no indeterminate spinner, no "please wait", no
skeleton placeholders, and no fake progress. The device is slow for
understandable reasons, and the console's job is to make the reasons visible,
not to paper over them.

### 3.3 Retrieval, so a weak match is obvious at a glance

The requirement is not "show the scores" — a column of numbers buries a weak
match as thoroughly as showing nothing. It is: **at a glance, is this grounding
solid or is it a coin flip?**

Four devices, together:

**A windowed, fixed axis.** Cosine scores in practice run ~0.35–0.85 and the
floor is 0.58. Drawn on a 0–1 axis, 0.71 and 0.60 look nearly identical and the
whole design fails. So the bar axis is `floor − 0.15 … floor + 0.25` — the
floor sits ~37% across and a 0.02 margin is about 4% of bar width, which is
visible. The axis is **fixed, never auto-scaled to what's in view**: bars must
mean the same thing across turns, or the console is useless for tuning.

**Both cuts drawn on the bar,** as dotted vertical rules through the whole
group. There are two, and conflating them is the mistake to avoid: the absolute
floor (`MIN_SIMILARITY`, 0.58) and the relative one (`0.92 × best`, per
question). A chunk can clear the floor and still never reach the prompt because
a stronger chunk moved the relative rule past it — that is the Photosynthesis
row above, cut at 0.62 with a margin of +0.04 over the floor. Reading that as
"the floor is too high" would send you sweeping the wrong constant. Kept chunks
are solid and sit right of both rules; cut chunks are hollow. "Barely made it"
becomes a spatial fact — the bar end almost touching a rule — rather than
arithmetic the reader has to do.

A `⚠` sits on any individual row whose margin over the floor is under 0.03,
whether kept or cut. That is a row-level note; whether the *turn* is
suspicious is §3.4.

**Margin, signed, next to the score.** `+0.13` reads solid; `+0.02` reads
fragile; `−0.09` reads "this is why nothing matched". Margin is the number that
answers the question; the raw score is there for the record.

**Cut candidates stay on screen** (top 5 ranked, kept and cut alike). Half of
retrieval tuning is misses, and a miss is invisible in a list of hits. Seeing
`constitution 0.56, floor 0.58` is what tells you `MIN_SIMILARITY` is 0.02 too
high for that question — the tuning loop the roadmap wants (E1: "re-sweep
MIN_SIMILARITY once 5 courses are loaded; the knee will move"), moved out of a
CLI sweep and into the thing you are already looking at.

Two more markers:

- `⊕` where `LEXICAL_BONUS` fired. A chunk whose score only cleared the floor
  because of the +0.05 tie-break is a specific, recurring failure mode, and it
  is invisible in the final number.
- The path label. `semantic · floor 0.58` versus `keyword · relative floor` —
  and on the keyword path the axis switches to `0 … top×1.15` with a note that
  **idf scores are not comparable across questions**. Cosines and summed idf
  are different units; a UI that renders them on one scale is lying.

No hit renders as a sentence, not an empty box:

```
  retrieved   no lesson matched — answering from the model's own knowledge
              closest was  Civics & History · The constitution   0.56  (−0.02)
```

That is the *common* case, by design (v0.2, `tutor/prompts.py`), and it must
read as a decision the system made, not as something missing. The closest-miss
line is one row and it is where a needed pack announces itself.

One asymmetry to render honestly: on the **semantic** path every chunk is
scored, so a miss always has a closest candidate to name. On the **lexical**
path chunks that fail `_is_topic_match` are never scored at all, so a lexical
miss legitimately has nothing to show and `chunks` comes back empty. The
console must say `no candidates scored` there rather than implying the library
is empty — the difference is a property of the fallback, not of the packs.

### 3.4 The console flags its own suspicious turns

Reviewing turns by eye is how "why is the sky blue" survived a week. So the
console applies a rule and marks the card and its history row with `⚠`. A turn
is **weakly grounded** when any of:

| rule | catches |
|---|---|
| top score − floor < 0.03 | grounding that barely qualified |
| top − runner-up < 0.03 (runner-up kept *or* cut) | a coin flip between two lessons |
| top score − `LEXICAL_BONUS` < floor | a hit carried entirely by the tie-break |
| top and runner-up are different subjects and gap < 0.05 | cross-subject bleed — the "can the government stop me praying" → local government shape |
| `path == "lexical"` | running degraded; recall is 33%, not 87% |
| answer came from the pack fallback | no model was involved |

The thresholds live in one `const` at the top of the JS. They are a first
guess: they were derived from the *shape* of the two named failures, not from a
distribution, because we do not have one yet. `tools/eval_retrieval.py` output
across 5 loaded subjects is what should set them, and until then the flag is a
prompt to look, not a verdict. In `Full` mode a **"flagged only"** filter turns
the history column into a work queue.

This is the one place the console does more than mirror. It earns it: the
alternative is a human noticing 0.60 versus 0.58 on a card that scrolled past
during a demo, and we have direct evidence that humans do not.

## 4. Live and history, without a mode switch

**One column, newest first. The live turn is simply the top card, unfinished.**
There is no live view and no history view; there is a list, and one item in it
is still being written. When the turn ends the card stops changing — nothing
moves, nothing is "committed", no state transition to design.

- A new turn pushes in at the top; the previous card collapses to a one-line
  summary (`time · question · top hit + score · latency · ⚠?`).
- **A card the reader opened stays open.** Manual expansion pins it. The
  console must never close something you are reading because a child asked
  another question in the next room.
- If the reader has scrolled away or pinned a card, a new turn does not yank
  the viewport. A `↑ new turn` chip appears at the top; clicking it scrolls.
- Collapsed rows carry enough to scan without opening: the question, what
  grounded it, and the flag. That one line *is* the eval-review view.
- Expanding a past card gives exactly the live layout, minus the animation.
  Same DOM, same renderer, one code path. Everything is a replay of the same
  event list; "live" only means the list is still growing.

**On connect,** the page asks for the last N completed turns and replays them
into the same renderer, then attaches to the live stream. So a console opened
mid-turn, or ten minutes after a demo, shows the same thing. Backfill comes
from a turn log (§8), not from browser storage — the device is the record, and
two laptops must see the same history.

Retention in v1: last 200 turns in memory on the device, and whatever the turn
log holds on disk. Rotation is D3's job (spec §13); the console must not become
the reason transcripts are kept longer than policy allows (§10).

## 5. Four audiences, one screen

| audience | wants | frequency |
|---|---|---|
| **demo** — a visitor, 2 minutes, over your shoulder or on a projector | calm, large, legible, one turn, no jargon | often, and it is the highest-stakes use |
| **debugging** — us, at the bench | everything, to the millisecond, including the prompt and the error text | daily |
| **retrieval tuning** — us or a curriculum author | candidates and scores across many turns, the floor, the near misses | per pack |
| **eval review** — us, after a session | many turns at once, scannable, filterable to the bad ones | per release |

They conflict on exactly one axis: **density**. Demo wants one turn, big, with
numbers rounded away. Eval wants forty turns, small, with numbers. Debug wants
things demo would find alarming (stack traces, raw prompts, `ConnectionError`).

They do **not** conflict on content. Every audience wants the same facts from
the same event stream; they disagree about how many of them at once. That is a
rendering parameter, not a second application — so: **one page, one renderer,
one control.**

`Calm │ Full`, top right, persisted to `localStorage`, toggled with `d`. It
sets a class on `<body>`; the DOM is identical in both.

| | Calm | Full |
|---|---|---|
| turn cards open | live only | live + last 5 |
| retrieval candidates | kept, plus the top cut one | all 5, scores to 3 dp |
| timings | one bar, total in seconds | per-stage ms, plus the median it is being judged against |
| sentences | text | text + `sentence`/`spoken` timestamps |
| system prompt | hidden | collapsible, verbatim, with the grounded material |
| errors | one plain line | class, message, `where` |
| history rows | 8 | all, with a "flagged only" filter |
| `seq` / turn ids | hidden | shown (they are how you correlate with the JSONL) |

Two rules keep the disclosure honest:

1. **Degradations and flags render in both modes.** Calm is quieter, never
   less truthful. A demo that hides "running on the keyword fallback" is how
   you demo a broken egg without knowing.
2. **Calm is the default.** The expensive failure is a stranger seeing a wall
   of debug output; the cheap failure is an engineer pressing `d`.

The one genuine gap: eval review also wants **cross-turn aggregates** — how
often retrieval fired, how many turns were flagged, the score distribution
against the floor. That is a different question shape and it is deferred (§9);
the turn log is deliberately the substrate for it.

## 6. Failure and degraded states

Three visual registers, and **offline is not one of them**:

| register | means | look |
|---|---|---|
| normal | working as designed, including "no lesson matched" | neutral |
| degraded | running on a fallback; says which, and what still works | amber, named |
| failed | the learner got nothing | red, and only here |

The rule underneath: *state what is retained, not what is lost.* "Offline" is
the product (README, first line). A console that renders the device's normal
condition in red teaches everyone who sees it the wrong thing about the
product.

### 6.1 Embedding server down → keyword retrieval

Signal: `degraded{component: "embed", fallback: "lexical"}`, then
`retrieved{path: "lexical"}`.

```
  retrieved   keyword match · embedding server not reachable   ▲ degraded
              recall drops to ~33% on natural phrasing — a lesson may exist
              and not be found
```

The candidate list still renders, with the axis relabelled to idf and the
across-turn comparison warning attached. This is the degradation most likely to
be mistaken for "retrieval is bad": the numbers change meaning and the recall
falls by two thirds, and neither is visible in the answer. The turn is flagged
(§3.4). Not red — the egg is still teaching.

### 6.2 llama-server down → canned pack explanations

Signal: `degraded{component: "llama", fallback: "pack"}`.

```
  answer      from the lesson pack · tutor model not reachable  ▲ degraded
    1  Plants make their own food, and that is called photosynthesis.   ♪ spoken
```

Sentences are marked as pack text, not generated. This is the offline floor the
README calls out: curated subjects still teach with zero LLM. Amber, because
out-of-pack questions now get nothing — but the card should read as a reduced
capability, not a crash.

### 6.3 No pack match

**Not a degradation.** Normal register, §3.3. This is the majority case and the
deliberate v0.2 design. The only thing that changes in the card is the
retrieved lane, which states the decision and shows the closest miss.

If llama-server is *also* down and nothing matched, the reply is
`prompts.UNKNOWN` and the card says so plainly: `nothing to teach from — no
tutor model, and no lesson matched`. That is the true floor of the device, it
is honest, and it should look calm rather than broken because the egg is doing
the correct thing.

### 6.4 ASR heard nothing

Two different causes, and the console must not merge them:

| `turn.end.reason` | means | shown as |
|---|---|---|
| `no-audio` | nothing crossed `silence_rms` — nobody spoke, or the mic/level is wrong | `nothing heard` + the configured `silence_rms`, in Full |
| `no-speech` | audio was captured, whisper returned empty | `didn't catch that` + the captured duration |

Both are short, neutral, single-line cards — not errors. The distinction is the
whole point: a run of `no-audio` is a hardware or threshold problem, a run of
`no-speech` is an ASR or acoustics problem, and they were indistinguishable
during M0 bring-up. Config-tuning bugs of exactly this class already cost this
project a week (`config.py`, `silence_rms`).

### 6.5 Offline (no network)

Never a banner, never a colour. A footer line:

```
  network none · llama :8080 up · embed :8082 up · everything above ran on this device
```

`UiState.OFFLINE` renders neutral — the enum already documents it as
"informational only — the egg still works", and the console should not
contradict its own state machine. In a demo, that footer is the strongest claim
on the page.

### 6.6 The console lost the stream

The failure mode with the worst consequences, because **a dead socket and an
idle egg look identical: nothing happening.** Someone watches a silent page,
concludes the device has hung, and reboots a device that was fine.

So the console distinguishes them explicitly. `EventSource` reconnects on its
own; while it is down the state chip greys, reads `reconnecting…`, and the live
card dims. `GET /health` is polled on a 5s beat while disconnected so the page
can say which side is gone: `device not reachable` versus `stream dropped,
device up`. On reconnect it backfills from `Last-Event-ID` (§8) so the trace
closes its own gap rather than showing a hole.

### 6.7 A turn raised

`error{where, error, message}` from the loop's own `except`. Red, and the only
red: the learner asked and got nothing. Calm shows one line; Full shows the
class and message. The turn card stays in history — a failed turn is the most
worth reviewing.

## 7. Event schema — the contract

Shipped in `device/coco_egg/events.py`. Every event is a JSON object with this
envelope plus its own fields:

| field | type | |
|---|---|---|
| `seq` | int | strictly increasing, per process. The SSE `id:` — drives `Last-Event-ID` resume. |
| `turn` | int | which turn. `0` before any turn opens. |
| `t` | float | seconds since this turn began. Drives the timeline. |
| `ts` | float | unix wall clock. Drives history labels. |
| `kind` | str | one of the ten below. |

| kind | fields | emitted by |
|---|---|---|
| `turn.start` | — | `main.one_turn`, `main.bench_turn` |
| `state` | `state`: one of the six `UiState` names | `main.set_ui` |
| `heard` | `text` (may be `""`) | `main` after `transcribe` |
| `retrieved` | `question`, `path` `semantic\|lexical`, `scale` `cosine\|idf`, `floor`, `relative_floor`, `chunks[]` | `tutor.pack` |
| `sentence` | `index`, `text` | `tutor.llama_client` as generated |
| `spoken` | `index`, `text` | `main` after `play_wav` |
| `stage` | `stage`, `seconds` | `main`, `tutor.llama_client` |
| `degraded` | `component` `embed\|llama`, `fallback` `lexical\|pack`, `error?` | `tutor.llama_client` |
| `error` | `where`, `error` (class name), `message` | `main.run` |
| `turn.end` | `reason` `ok\|no-audio\|no-speech`, `reply?`, `latency_s?` | `main` |

`retrieved.chunks[]` — up to 5, ranked by score, **kept and cut alike**:

| field | |
|---|---|
| `id`, `title`, `subject` | chunk identity; `subject` is the pack topic |
| `score` | cosine (`scale: cosine`) or summed idf (`scale: idf`) |
| `kept` | did it reach the prompt |
| `lexical_bonus` | did `LEXICAL_BONUS` fire (semantic path only) |

`floor` and `relative_floor` are the two cuts, both drawn (§3.3):

| path | `floor` | `relative_floor` |
|---|---|---|
| `semantic` | `MIN_SIMILARITY`, currently 0.58 | `0.92 × best`, per question |
| `lexical` | `MIN_RATIO × best` — already relative, so both fields carry it | same |

Both are `0.0` when nothing scored. They come from the device rather than being
recomputed in the browser, so a swept constant moves in one place and the
console cannot silently draw last week's floor.

`stage.stage` values, **disjoint and summing to roughly `first_audio`**, with
their measured medians:

| stage | median | note |
|---|---|---|
| `hangover` | 1.20s | trailing silence before work starts. Deleted by push-to-talk (v0.8). |
| `asr` | 1.79s | 1.44s of it is whisper's fixed 30s-window encoder. |
| `retrieval` | ~0.05s | embed the question + rank. Times out into the lexical path. |
| `llm_first_sentence` | ~1.55s | prompt → first complete sentence. Excludes `retrieval`. |
| `tts` | 0.58s | first sentence only. |
| `first_audio` | 5.01s | end-of-speech → first audio. Measured, not summed — the authority. |

Note `llm_first_sentence` here excludes retrieval, where the README's 1.60s
figure includes it. The split is more honest for a timeline and the sum is
unchanged; `first_audio` remains the number the product is judged on.

**Ordering guarantees the renderer may rely on:** `turn.start` first and
`turn.end` last; `heard` before `retrieved`; `retrieved` before the `stage
retrieval` that times it; `degraded{embed}` before a `retrieved{lexical}` that
it caused; `stage llm_first_sentence` immediately before `sentence` 0;
`sentence` indices ascending; `spoken[i]` after `sentence[i]`. Everything else
is best-effort — render defensively, because a dropped event (§8) is a normal
outcome.

A real trace, captured from the fully degraded device (no llama-server, no
embedding server, and a question the lexical path is known to miss). Thirteen
events, 1733 bytes; `ts` elided here for width:

```json
{"seq":1,"turn":1,"t":0.0,  "kind":"turn.start"}
{"seq":2,"turn":1,"t":0.0,  "kind":"state","state":"THINKING"}
{"seq":3,"turn":1,"t":0.0,  "kind":"stage","stage":"hangover","seconds":1.2}
{"seq":4,"turn":1,"t":0.0,  "kind":"stage","stage":"asr","seconds":1.63}
{"seq":5,"turn":1,"t":0.0,  "kind":"heard","text":"how does rain happen"}
{"seq":6,"turn":1,"t":0.006,"kind":"degraded","component":"embed","fallback":"lexical"}
{"seq":7,"turn":1,"t":0.006,"kind":"retrieved","question":"how does rain happen",
 "path":"lexical","scale":"idf","floor":0.0,"relative_floor":0.0,"chunks":[]}
{"seq":8,"turn":1,"t":0.006,"kind":"stage","stage":"retrieval","seconds":0.006}
{"seq":9,"turn":1,"t":0.007,"kind":"degraded","component":"llama","fallback":"pack",
 "error":"ConnectionError"}
{"seq":10,"turn":1,"t":0.007,"kind":"stage","stage":"llm_first_sentence","seconds":0.001}
{"seq":11,"turn":1,"t":0.007,"kind":"sentence","index":0,"text":"I can't reach my tutor…"}
{"seq":12,"turn":1,"t":0.007,"kind":"sentence","index":1,"text":"What would you like…"}
{"seq":13,"turn":1,"t":0.007,"kind":"turn.end","reason":"ok","reply":"I can't reach…"}
```

That one trace renders as two amber degradations, an empty retrieval with an
explicit floor of 0.0, and a canned reply — the whole §6 story in one card, and
a useful thing to point a browser at while building the view.

### Bus guarantees the console depends on

- **Zero subscribers is the normal case.** With nobody watching, `emit()` takes
  a lock, sees an empty list and returns; the event is never built. Callers
  whose payload costs something (`pack._emit_retrieved`) check `active()`
  first, so ranking and formatting candidates does not happen on a device
  nobody is looking at.
- **A subscriber that raises is dropped**, logged once. It cannot propagate
  into `one_turn`.
- **A subscriber that is slow cannot block.** Delivery is synchronous, so
  anything that might do I/O uses `events.Stream` — a bounded queue that sheds
  its oldest event and counts the gap. Losing the middle of a trace is
  cosmetic; making a child wait is not. The console shows `stream.dropped` as
  a gap marker rather than pretending the trace is complete.

## 8. Serving it (for B2)

Sketch only — B2 owns the detail. Stdlib `ThreadingHTTPServer` on a daemon
thread, started from `main.run()` behind a `console.enabled` config flag, never
joined; if it dies the voice loop does not notice.

| route | |
|---|---|
| `GET /` | the three static files from `device/coco_egg/web/static/` |
| `GET /events` | SSE. One event per message, `id:` = `seq`, honours `Last-Event-ID`. Subscribes via `events.Stream`. |
| `GET /api/turns?limit=50` | completed turns, newest first, for backfill |
| `GET /health` | `{ok, uptime_s, llama, embed, packs, turns}` — the "is it me or the egg" probe (§6.6) |

GET-only, no write path (§9). Backfill is served by a `TurnLog` subscriber that
groups events between `turn.start` and `turn.end` and appends one JSON object
per turn beside `sync/` transcripts — the same rotation and retention rules
apply (spec §13). Budget: a turn is ~15 events and under 2KB, so a busy
classroom hour is well under a megabyte and the SSE fan-out is not a cost worth
optimising.

## 9. Deliberately not in v1

| left out | why |
|---|---|
| **Pack authoring / PDF upload** | Roadmap v0.6 item 2, and it needs write endpoints on a device that has none. Its value is the *preview what it retrieves* step, which depends on the retrieval trace being trustworthy first. Build the trace, use it, then build authoring on top. |
| **Learner profile editing** | Blocked on an undecided question — "who is the learner?" (roadmap v0.7). One egg serves a classroom; no identity, teacher-selected, and voice-ID are three different UIs. Building one now guarantees rework. |
| **Device / fleet status** | Lowest priority in the roadmap's own ordering, and ShellHub already covers access (spec §9). `/health` in the footer is as far as v1 goes. |
| **Cross-turn analytics / eval scorecard** | Real value, different shape — it needs the turn log and a fixed question set, and it is `tools/eval_answers.py` (E2) with a viewer, not a trace view. The turn log is designed as its substrate. |
| **Triggering a turn from the browser** | The tempting one. Rejected: the egg would speak aloud in a room the operator is not in, possibly a child's. It also converts a read-only page into a control surface and takes the entire auth question with it. Turns are triggered at the device. |
| **Editing thresholds live** | Sweeping `MIN_SIMILARITY` from the browser is a lovely idea and a write path into the tutor that changes behaviour mid-session. v1 *shows* the floor; `tools/eval_retrieval.py --sweep` moves it. Revisit when there is an eval gate that would catch a bad sweep. |
| **Playing the reply audio in the browser** | Needs WAV retention on a Pi's SD card and pulls in the §13 retention question for audio, which is stricter than for text. Text is the artifact that matters. |
| **Auth** | See §10 — flagged, not solved. |
| **Any framework, build step, or CDN asset** | The device is offline and has no build toolchain. |

## 10. Open questions

1. **Children's transcripts on an unauthenticated LAN page.** The console
   displays what children said, over HTTP, to anyone on the classroom network.
   Spec §13 treats voice capture as a first-class requirement, and this is the
   first surface that *displays* it. Recommendation, to escalate rather than
   assume: `console.enabled` defaults **off** in the deployed image and on for
   bench/demo; the page shows only this device's turns and no learner identity;
   retention is whatever D3 sets, and the console never extends it. A
   device-printed PIN is the obvious next step if this ships to a pilot.
2. **Flag thresholds are guesses** (§3.4). They encode the shape of two known
   failures, not a measured distribution. `tools/eval_retrieval.py` at 5
   subjects should set them; until then the flag means "look", not "wrong".
3. **The LED and the console should agree, and one of them is undesigned.**
   The state chip borrows `UiState` because that is what exists. The LED state
   language is an open Stream F decision (`docs/ux-brief.md`, on the `v0.3-ux`
   branch — not merged into `v0.3`, and not read for this document). If that
   work renames or splits the states, the console follows it rather than the
   other way round.
4. **Acknowledgement audio changes the timeline** (C3). "Let me think" at
   ~0.5s takes *perceived* first-audio from 5.0s to ~0.5s while the trace
   underneath is unchanged. The card will then need to show two numbers —
   acknowledged and answered — or it will look like the console is
   contradicting the demo. Worth deciding alongside C3, not after.
5. **Streaming ASR breaks the lane model** (C2). Speculative retrieval on a
   partial transcript means `heard` arrives incrementally and `retrieved` may
   fire more than once per turn, possibly on a transcript that later changes.
   The event schema can carry it (`heard` is repeatable, `retrieved` already
   carries the `question` it ran on) but the view assumes one of each. Revisit
   when C2 lands; do not pre-build for it.
