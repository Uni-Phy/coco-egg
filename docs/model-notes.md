# Tutor model & runtime notes — measured on the M0 bench

Pi 5 8GB / Cortex-A76 / DietPi. All numbers from `tools/bench_loop.py` and the
llama-server config sweep, against the real grounded prompt the tutor sends.
Re-measure on XVF3800 hardware at M1 (spec §5 tags M0 numbers "M0 Plus").

## 1. llama.cpp config tuning is exhausted

Sweep of Qwen3-1.7B-Q4_K_M, same 280-token grounded prompt:

| config | RssAnon | RSS | prefill | decode |
|---|---|---|---|---|
| `-c 4096` (was the default) | 1584 MB | 2641 MB | 56.3 t/s | 9.8 t/s |
| `-c 1024` | 1246 MB | 2303 MB | 56.4 t/s | 9.7 t/s |
| `-c 1024 -fa on` | 1246 MB | 2303 MB | 54.8 t/s | 9.7 t/s |
| `-c 1024 -fa on` + q8_0 KV | 1191 MB | 2248 MB | 49.5 t/s | 9.7 t/s |
| `-c 1024 -fa on -ub 128` | 1230 MB | 2287 MB | 49.9 t/s | 9.6 t/s |
| `-c 768 -fa on -ub 256` + q8_0 KV | 1173 MB | 2230 MB | 46.4 t/s | 9.5 t/s |

**Prefill sits at ~56 t/s and decode at ~9.8 t/s no matter what.** These are
memory-bandwidth and compute limits of the A76, not misconfiguration. Flash
attention, KV quantisation and smaller ubatch all *cost* 8–17% prefill to buy
marginal memory — on this CPU they are the wrong trade.

The one free win: **`-c 1024` saves 338 MB at zero speed cost.** The tutor
prompt is ~330 tokens and the reply is capped well under 600 chars, so 4096 of
context was paying for KV cache we never address. Nothing above 1024 is
reachable by the current prompt.

The build is already correct: Release, `GGML_NATIVE=ON`, `GGML_CPU_REPACK=ON`,
dotprod present. The A76 has no i8mm and no SVE, which is why prefill is only
~5.7x decode instead of the 10–30x seen on newer cores. `GGML_CPU_KLEIDIAI` is
OFF and is the one build flag still untested.

## 2. The real lever is model size

Qwen3-0.6B-Q4_K_M (378 MB file) vs Qwen3-1.7B-Q4_K_M (1056 MB), both `-c 1024`:

| | 1.7B | 0.6B | |
|---|---|---|---|
| RSS | 2303 MB | **945 MB** | −59% |
| prefill | 56 t/s | **149 t/s** | 2.7x |
| decode | 9.7 t/s | **23.8 t/s** | 2.5x |

## 3. …but thin models break exactly where v0.2 opened up

Same prompt, same grounding, same sampling. The 0.6B is **equal on
pack-grounded questions and better on arithmetic**, and **unreliable the
moment it answers from its own knowledge**:

| question | 1.7B | 0.6B |
|---|---|---|
| What is photosynthesis? | correct | correct, 2.5x faster |
| What are fractions? | correct, uses the roti example | correct, uses the roti example |
| What is 7 times 8? | right answer, rambling **wrong** workings | "7 multiplied by 8 is 56." — better |
| Who was Ashoka? | vague but not wrong | **wrong** — "ruler of the Gupta Empire" |
| Why is the sky blue? | correct (Rayleigh scattering) | **wrong** — hallucinated a water-cycle answer |
| What did I have for breakfast? | "I don't know what you had" | **hallucinated** — "I had a piece of roti" |

Two findings worth carrying forward:

**Retrieval precision becomes safety-relevant as the model gets thinner.** Both
models were handed the same false-positive water-cycle chunk for "why is the
sky blue". The 1.7B ignored it and answered correctly; the 0.6B built its whole
wrong answer out of it. A weak model cannot resist bad grounding, so
`Pack.MIN_RATIO` and retrieval quality matter *more*, not less, at low
parameter counts.

**Thin model and open tutor are in tension.** Under v0.1's pack-only scope the
0.6B would be a straight win. v0.2 made the model's own knowledge load-bearing,
which is the one thing 0.6B is bad at. Pick two of: small, open, trustworthy.

## 4. Decided: keep the cascade, text stays the interface

**[FIXED 2026-07-27]** The device keeps `whisper → small LLM → Piper`. A single
end-to-end voice-to-voice model was considered for the device and rejected.

The measurement that decides it: decode speed here tracks memory bandwidth
almost exactly — 0.6B/378MB gives 23.8 t/s and 1.7B/1056MB gives 9.8 t/s, both
implying **~9–10 GB/s effective**. So decode ≈ bandwidth ÷ model size, and a 3B
Q4 lands ~5 t/s, a 7B ~2 t/s.

A speech-to-speech model emits audio codec tokens at roughly 100–200 per second
of speech and must sustain that continuously or the voice stutters. The
credible open S2S models are 3B–9B. That is **~100+ tokens/sec needed against
~2–5 available** — an order-of-magnitude gap, not a tuning gap.

Meanwhile Piper synthesises at RTF 0.09, ~11x realtime. A purpose-built vocoder
makes audio far more cheaply than an LLM generating audio tokens, and that
asymmetry is structural, not an artifact of current models.

It would also not save what it appears to. Deleting ASR and TTS removes 2.4s of
our 7.31s; the LLM's 3.80s stays and gets *worse*, because the model is bigger
and audio tokens in are far more numerous than text tokens.

And it breaks RAG. Retrieval needs a text key — `Pack.retrieve()` matches
question tokens against chunks. A true end-to-end model exposes no transcript,
so we would need an ASR anyway. Text is also what makes transcripts (the CoCo
node's fine-tuning input, spec §3), the eval set, safety review and debugging
possible — the VAD bug found during M0 bring-up was only visible because the
mis-heard question could be read as text.

Where voice-to-voice *does* fit: the **M2 cloud route** (spec §3 — cloud is a
quality upgrade when online, never a dependency). Natural prosody and
interruption when connected, local cascade as the offline floor. Worth watching
speech-in/text-out models (Ultravox, Qwen2-Audio) for M1+, though today they
are larger than what we run and mostly wrap a Whisper encoder anyway.

Per-stage efficiency, which is what makes the split worth keeping:

| stage | measured | verdict |
|---|---|---|
| whisper (audio→text) | 1.79s | structurally wasteful — fixed 30s window whatever the utterance length |
| small LLM (reason+generate) | 3.80s | the bottleneck, and the only stage worth optimising |
| Piper (text→audio) | 0.60s, RTF 0.09 | ~11x realtime, effectively free |

Corollary worth holding onto: **the thinner the model, the more the pack has to
carry.** Model size and retrieval quality trade off directly (see §3). Note the
weak stage is *reasoning*, not generation — retrieval-grounded generation was
indistinguishable between 0.6B and 1.7B.

## 5. Taken (v0.3): 0.6B + a subject library

**[DECIDED 2026-07-27]** Move to Qwen3-0.6B at `-c 1024`, and put the
intelligence the model gives up into curated subject packs plus a per-learner
layer. Measured after the switch:

| | 1.7B `-c 4096` | 0.6B `-c 1024` |
|---|---|---|
| RSS | 2641 MB | **945 MB** |
| perceived end-to-end | 7.31s median | **5.01s median** |

The bottleneck moved: **ASR (1.78s) is now the largest single stage**, not the
LLM. The next structural win is streaming ASR + speculative retrieval, not more
model work.

What the packs actually fixed — the 0.6B's measured failures from §3, re-run
with two subjects loaded (science/maths + civics/history):

- "Who was Ashoka?" — was "ruler of the Gupta Empire"; now correct and
  detailed, grounded on the civics pack. **This is the bet working.**
- New subjects answer correctly on first contact (Gram Panchayat, fundamental
  rights) purely from adding a pack — no code, no model change.
- "Why is the sky blue?" and "what did I have for breakfast?" — the wrong
  answers turned out **not** to be model ignorance. Both were *false-positive
  retrieval*: "breakfast" matched the fractions lesson on the single word
  "have" (that lesson mentions a roti, so the tutor claimed it ate one), and
  "sky" matched the water cycle on one word. Fixed by requiring a topic match
  (a title hit, or more than one shared content word) rather than any overlap.

That is the §3 corollary paying out concretely: at 0.6B, retrieval precision
*is* answer correctness. The same two bad chunks were harmless to the 1.7B.

Accepted risk, chosen deliberately: out-of-pack questions are still answered
from model knowledge rather than refused, so the 0.6B can still be confidently
wrong outside curated subjects ("I had a sandwich for breakfast!"). The eval
set should measure this so it can be revisited with data.

Also fixed in passing: the 0.6B ends cheerful answers with emoji far more often
than the 1.7B, and the reply is *spoken* — emoji are now stripped before TTS,
targeting pictograph blocks only so Devanagari survives.

## 6. Options, not yet decided

- **Stay 1.7B, buy back time elsewhere** — acknowledgement audio, `tiny.en`
  ASR (1.44s → ~0.5s), trim the 1.2s VAD hangover. No quality risk.
- **Route by grounding** — 0.6B when the pack hits, 1.7B when it doesn't.
  Costs both models resident (~3.2 GB) or a model-swap stall.
- **Fine-tune a small model** on curriculum + tutor behaviour. This is the CoCo
  node's stated job (spec §3: the node is the model factory, the egg is the
  delivery vehicle) and the real answer to low-param specialist intelligence.
- **Rebuild llama.cpp with KleidiAI** — the only untested runtime lever.

Whichever we pick, it needs an eval set to decide it. The table in §3 was
hand-judged on nine questions; that is enough to disqualify 0.6B-as-is, and
not enough to choose between the options above.

## 7. Correction: the v0.3 retrieval fix zeroed recall

The topic-match rule in §5 was verified against 14 questions and called
correct. Those questions all used the pack's own vocabulary ("What is
photosynthesis?", "What are fractions?") — so precision was measured and
**recall never was**. Re-measured on natural phrasing:

| | recall | false positives |
|---|---|---|
| topic-match rule (shipped) | **0/7** | 0/3 |
| any-overlap (v0.2) | 4/7 | 2/3 |

"how does rain happen" does not find the water cycle; "what rights do I have"
does not find the constitution; "what is one half" does not find fractions.
Curated packs only fire when the learner already knows the technical term.

Neither setting ships: 0/7 recall makes the library decorative, 2/3 false
positives makes a 0.6B hallucinate from the wrong lesson. Token matching
cannot deliver both, which makes semantic retrieval a prerequisite for the
course library rather than an improvement to it. See docs/roadmap.md.

## 8. llama-server RSS grows ~11MB per request and never returns it

Measured on the bench Pi, 2026-07-28, tutor server (Qwen3-0.6B, `-c 1024`):

| | RSS |
|---|---|
| freshly started | 984 MB |
| after 20 varied requests | 1213 MB (+229 MB) |
| after ~11 hours of use | **5801 MB** |

About 11 MB per request with a *varied* prompt, not reclaimed. The box has
8 GB and **no swap**, so extrapolating from a fresh start this reaches the
ceiling in roughly 500-600 questions — inside a single classroom day.

It is not a config problem: `-c 1024` caps the KV cache, and a fresh process
with the same flags sits at 984 MB. The growth tracks distinct prompts, which
points at llama-server's prompt-cache/slot state accumulating per unique
prefix — every question retrieves different pack material, so every prompt is
a new prefix, and a tutor is close to the worst case for that.

Consequences we already saw: a `bench_loop` run against the bloated server
produced a 12.6s LLM first-sentence outlier against a 2.6s median, and the
perceived e2e max was 16.8s. A demo that has been running for hours will not
behave like one just started.

**This raises the priority of systemd units (parallel-tasks D1) from hygiene
to containment.** A unit with `MemoryMax=` plus `Restart=always` bounds the
blast radius without solving the leak. Worth testing next: llama-server's slot
and cache-reuse flags, whether the `/slots` endpoint can release state, and
whether a newer llama.cpp build fixes it.

Practical bench note: restart the tutor server before any timing measurement
or demo, or the numbers are measuring the leak rather than the model.

## 9. Reverted to Qwen3-1.7B for the v0.4 release

**[DECIDED 2026-07-29]** §5 took the 0.6B for speed and RAM. Measured again on
the release container, with semantic retrieval, 143 chunks and conversation
memory all in place, the accuracy gap is decisive and the RAM argument is gone:

| | 0.6B | 1.7B |
|---|---|---|
| perceived end-to-end | ~5.0s | **8.32s** |
| LLM first sentence | 2.34s | 3.53s |
| container memory | ~1.0 GB | 1.49 GB (3 GB cap) |
| "will a magnet stick to copper?" | **"Yes"** — wrong | "will **not** stick" |
| "does a magnet stick to aluminium?" | **"Yes"** — wrong | "**doesn't** stick" |
| "what did I have for breakfast?" | invents a sandwich | "I'm not sure what you had" |

The yes-bias is the reason. §3 recorded it, and a prompt guard was written and
measured and did not fix it — the 0.6B still produced *"Yes, a magnet can stick
to an aluminum spoon. It works on iron, nickel and cobalt, but not on
aluminum"*, agreeing and contradicting inside one sentence. That is a model
capability limit, and a bigger model clears it.

The trade is accuracy over speed, taken deliberately. 8.3s is bad, but 5.0s was
also nowhere near the ~2-3s bar, so the choice was never fast-vs-slow — it was
wrong-and-slow against right-and-slower. A tutor that tells a child a magnet
sticks to copper has failed at the thing it exists to do.

RAM stopped being the argument once the leak was capped: `mem_limit: 3g` plus
`restart: unless-stopped` bounds the container either way, and the 1.7B sits at
1.49 GB of that.

**This is not permanent.** The route back to a small model is the behaviour
fine-tune in §4's plan — train faithfulness and negation handling into a 0.6B
from the transcripts we now record, rather than hoping a prompt will hold it.
That is the whole point of the model-factory loop (spec §3).

## 10. Openers are not questions, and the first turn is not free (v0.4)

Two small changes, both aimed at the first thirty seconds of a demo rather than
the median turn.

**Openers.** *"Let's study physics"* retrieved the measurement-units lesson and
answered with a lecture about metres. The bug is not retrieval quality — the
lesson genuinely is inside physics. It is that a whole subject is not a
question, so retrieval picks an arbitrary lesson within it and the learner never
gets asked what they actually wanted. Same for *"hello"*, which has no subject at
all.

`llama_client.is_opener()` classes a turn as an opener when it starts with a
greeting or a proposal (`let's`, `shall we`, `can we`, `i want to`, `teach me`)
and contains no interrogative. Openers skip retrieval entirely and get
`prompts.OPENER`, which asks the model to reply warmly and invite a specific
question.

The rule is uniform on purpose: an opener never grounds, *even when it names
something we teach*. "I want to learn about fractions" is better answered with
"great — what about them?" than with a lesson chosen on the learner's behalf,
and the real question that follows grounds normally (`retrieval_query` carries
the subject across).

The risk this creates is the opposite failure — swallowing a real question — so
`test_opener.py` asserts that no question shipped by any course is ever classed
as an opener. That guard is load-bearing: the eval calls `retrieve_semantic()`
directly and would never see this rule fire.

**Warming.** The static system prefix was prefilled on whichever turn came
first. `llama_client.warm()` now pays it at startup, on a background thread,
alongside loading the pack. Measured against the live server, with the nonce
placed first so the prompt is genuinely novel:

| | prefill | time |
|---|---|---|
| cold | 172 tokens | 3339 ms |
| warmed | 16 tokens | 365 ms |

**~3.0s off the first turn.** First turn only — every later turn already shared
that prefix, which is the point of the ordering in `build_messages()`.

Worth recording how the first attempt lied: with the nonce *appended* to the
system prompt, the "cold" run reported 31 tokens, because the server still had
the real SYSTEM cached from live turns and only recomputed the tail. Prefix
caching is prefix-based — a benchmark for it has to differ at the first token or
it measures nothing.

## 11. Jyotisha as the demo course, and a quiz that never asks the model (v0.5)

**The course.** Jyotisha is taught as what it actually is — the Indian sky and
calendar tradition. Twenty chunks: panchanga, tithi, nakshatra, rashi,
navagraha, Rahu and Ketu as the nodes where the moon's path crosses the sun's,
precession and the ayanamsa, the lunisolar calendar and the adhika masa, why
Sankranti is fixed while Diwali moves, Aryabhata on eclipses, Jantar Mantar.

The framing was a judgement call worth recording. The course separates the
astronomy, which is checkable and genuinely was centuries ahead, from the
predictive tradition, which is presented as *what the tradition holds*. One
chunk addresses the science question head-on rather than leaving it implied:
studies have not found an effect, the calendar still works, both are true.
Teaching it any other way would mean either asserting predictions to children as
fact, or dismissing a living tradition — and the pack is the authority the model
defers to, so whatever it says is what gets taught.

Two chunk titles were hand-corrected after the build. The 1.7B titled the
paragraph about Aryabhata, Brahmagupta and Madhava "Indian Mathematics", and the
one about farmers needing an accurate calendar "Calendar and Seasons". Both name
something real in the text but not what the chunk is *about*, and a title is a
retrieval key at 3x weight — so the title was fixed rather than the eval label
bent to match it.

Measured with the course in, at 163 chunks / 9 subjects: **recall 82%, false
positives 12%** (was 82% / 6% at 143 chunks / 8 subjects). Recall held; 16 of
the 20 new questions land, in line with the rest of the library. Some of the FP
rise is this course's own negatives — "what did I have for lunch" now reaches
the digestion lesson.

**The quiz.** `tutor/quiz.py` is deliberately LLM-free. The reasoning is
latency-shaped: a quiz turn is question, verdict, next question, and at ~3.5s of
generation apiece it stops being a game. Authored questions plus an accept-list
cost only TTS, about 1.4s, and cannot be hallucinated. It is the same call as
`build_pack.llm_polish` refusing to generate `explain` — being confidently wrong
while *marking* a child is the worst failure mode the device has.

The cost is stated rather than hidden: judging is substring matching, so a
correct answer phrased unusually is marked wrong. Accept-lists carry numerals
and words both (whisper returns either), and a wrong verdict always speaks the
answer.

Two things that only showed up when it ran: "let's play a quiz" is a textbook
`is_opener()` match, so the router in `tutor/__init__.py` has to check the quiz
FIRST or a request to play gets answered with an invitation to ask a question
instead. And the verdict originally spliced the answer after "the answer is",
which spoke as *"The answer is The two points where..."* — answers are full
sentences, several of them proper nouns, so the answer now follows as its own
sentence.

## 12. Three faults found in a real session, not by reading code (v0.5)

The device logs and transcripts from 2026-07-29 are the source for all of this.
Each fault was invisible in tests and obvious in a transcript, which is the
argument for having built the transcripts.

**A named subject returned the previous answer, word for word.** After two turns
about kickboxing, the single word *"Astrology."* came back with the kickboxing
reply verbatim. The transcript shows retrieval had done its job — it grounded on
`planets` at 0.659 — and the model ignored it entirely:

    heard      : "Astrology."
    retrieved  : planets (0.659), celestial-motion (0.642), both kept
    llm_first_sentence: 10.335s
    reply      : "Kickboxing is a sport where you use your fists and feet..."

A bare noun carries no instruction. With nothing telling it what to do, the
strongest thing in context wins, and that is whatever the tutor last said.
`is_topic_nomination()` now catches one or two content words with no
interrogative, adds an explicit "this is a NEW subject" instruction, and **drops
the history for that turn**. Instruction alone was not enough on a 1.7B; the
previous answer is right there and repeating it is the path of least resistance.

The eval guard immediately caught the rule over-reaching: *"is zero just
nothing"* reduces to one content token, because `nothing` is a stopword, and
looked like a bare noun. Yes/no questions open with an auxiliary, so those are
excluded — anchored at the start, since mid-sentence they are ordinary words
("let's DO maths"), which is why they were kept out of `_WH` in §10.

**The history window destroyed the prompt cache on every turn once full.** §5
claimed computed tokens "stay flat as a conversation deepens". That was only ever
true *while the window was still filling*. `History` was a deque with `maxlen=3`,
so from the fourth turn on every append evicted one — shifting the prefix
immediately after the system message and re-prefilling the whole conversation.
The module docstring had even named the failure mode ("a window that turns over
every turn would defeat the point") without noticing it described the code.

Measured against the live server:

| history | prefill | time |
|---|---|---|
| `[h1 h2 h3]` appending, nothing evicted | 74 tokens | 1550 ms |
| `[h2 h3 h4]` one turn evicted | 203 tokens | 4039 ms |

About **2.5s per turn, forever**, and the reason that astrology turn took 10.3s
to its first sentence. Eviction is now batched: the window grows to the cap and
then drops back in one go, so most turns are pure appends onto a cached prefix —
one expensive turn in three instead of three in three.

**Retrieval missed the question the course exists to answer.** *"Do the stars
decide my future"* retrieved `stars-and-light`, `star-patterns` and
`celestial-motion` — the sky course — and never reached Jyotisha. The
`jyotisha-and-science` chunk covers precisely this, but in the words of a study:
"personality or life events", "the predictive side". Nobody asks it that way.

This is the shape of the recall plateau in §7 made concrete. Semantic retrieval
matches meaning, not telepathy, and no floor was going to bridge "decide my
future" to "predict life events". The fix is content: a chunk saying the same
true thing in the vocabulary a learner brings — future, horoscope, lucky, exam,
marry. **When a question is important and retrieval misses it, write the chunk
that answers it in the asker's words.** Cheaper and more reliable than tuning.

Corollary worth keeping: an ungrounded question is not a neutral outcome on a
subject like this one. Before the fix the model answered the future question
from its own knowledge, unframed — *"astrology is a way people have used to
understand the connections between the stars and our lives"*. After it:
*"The stars don't decide your future. Your choices and effort matter more."*
