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

## 4. Options, not yet decided

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
