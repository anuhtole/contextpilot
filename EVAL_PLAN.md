# Real-agent quality evaluation plan (draft, 2026-10-28)

## Status after the pilot (`bench/`, 18 runs, $18.43)

- **Harness pivot.** The pilot ran on headless Claude Code rather than mini-swe-agent. The Claude Code CLI refuses `--autocompact` windows below 100k, so arms are driven by an external controller that sends `/compact` between user turns.
- **Established:**
  - Premature compaction costs +32% (13 messages) and +143% (25 messages).
  - After about 9 compactions, cross-compaction recall falls from 11.7 to 9.7 of 12.
  - The economic trigger correctly stays idle below H\*.
  - The cost model reproduces real bills at 7.9% mean absolute error.
- **Not established:** that the economic trigger *saves* money in real runs, because no pilot session grew past H\* (about 60k of history).
- **Next experiment:** high-growth sessions in which the agent reads whole files (g of 4k or more per call), comparing `auto` with `eoq`. Expect about $3–5 per run.
- **Remaining plan:** the SWE-bench design below is still the path to a full-paper result.

## Next: high-growth real sessions (designed 2026-10-28, not yet run, needs budget approval)

Sizing: `experiments/size_highgrowth.py` → `results/highgrowth_sizing.json`. It replays the pilot's real per-call increments rescaled to the target growth, on the fidelity-checked simulator (7.9% MAE) with the pilot's bias corrected.

**What this experiment can and cannot show.** At Claude Code prices H\* + base ≈ 160k, so `eoq` and `--autocompact 150k` are predicted to cost the same (within 1%, and within 3% even at g = 1.5k). No real-session design on Claude can separate them at n = 5. It *can* show, with real bills:
1. Near-window compaction (the 1M default) costs 30–40% more than a trigger near H\* once sessions cross H\*.
2. The economic trigger reaches that optimum with no tuning, matching the best product setting.
3. Task quality and constraint retention survive 3–4 compactions.
4. The simulator predicts compacted sessions that cross H\* (a pre-registered prediction, falsifiable).
The online rule's advantage over a fixed 150k stays a simulation result across prices and windows (Table 1), and the paper states it that way.

**Workload (`bench/build.py --high-growth`).**
- 24 injected bugs in 8 large stdlib modules (1.4–3k lines each): argparse, configparser, tarfile, pathlib, dataclasses, datetime, http.cookiejar, optparse.
- Bugs are described by symptom only (a failing call and its wrong output, no line hint), so the agent has to read the code.
- About 30 follow-up messages: fix requests, then "audit `<module>` end to end and record risky spots in NOTES.md", which forces whole-file reads.
- Target g ≈ 4k tokens per call. That is close to our real Claude Code sessions (3.6k), so the high growth is realistic, not contrived.
- Target about 120 calls per session, which puts the uncompacted peak near 500k: about 3x H\* of 123k.
- Five task orderings (v1H–v5H). Each repetition is one ordering, run under every arm, so the comparisons are paired.
- Quality uses the same instruments as the pilot: hidden differential probes (fixed /24), constraint rules 1–4 from message 1, and NOTES.md recall.
- One new probe is a constraint added at message 10 ("never touch `__all__`"). It tests retention of state introduced mid-session, which is what a summary is most likely to drop.

**Arms (n = 5 each, paired by ordering):**

| Arm | Mechanism | Predicted $/run | Compactions |
|---|---|---|---|
| auto | CLI default on the 1M window (never fires at 500k) | $6.8 | 0 |
| eoq | external `/compact` at the online H\* | $4.4 | about 3.5 |
| 150k | CLI-native `--autocompact 150000` | $4.4 | about 4 |
| far (optional) | `--autocompact 400000` (3x H\*) | $5.2 | about 1 |

- The `150k` arm also controls for the mechanism: native autocompaction versus our external `/compact`.
- `far` is the dose-response point that tests linear excess (Corollary 3).

**Pre-registered predictions** (simulator, g = 4k, 120 calls):
- eoq vs auto: −35% ± 6%.
- eoq vs 150k: within ±5%.
- far vs auto: −22% ± 8%.
- Quality is non-inferior: fixed ≥ 23/24 and recall drops by no more than 1/12.

**Statistics.**
- Paired differences per ordering, with a bootstrap 95% CI on the % cost difference.
- An exact sign test. Its minimum one-sided p at n = 5 is 1/32 = 0.031, so all 5 pairs must agree.
- Simulated SD is about 3% per run against a predicted effect of about 35%, so power is ample if the effect is real.
- Quality and recall are reported descriptively. n = 5 cannot establish non-inferiority, only detect gross harm.

**Cost and gates.** Sonnet 5.5 list prices, 1-hour cache.

| Stage | Runs | Estimate |
|---|---|---|
| 0. Calibration gate: 2 truncated auto runs (40 calls) plus one `--autocompact 150000` smoke test | 3 | $4 |
| 1. Core: auto + eoq × 5 | 10 | $56 |
| 2. + 150k × 5 | 5 | $22 |
| 3. + far × 5 (optional) | 5 | $26 |

- The fidelity error and the uncertainty in g give a ±15% band.
- Recommended cap: **$95** for stages 0–2, or **$125** with `far`.
- The minimal version (stages 0–1) costs $65.

**Gate rules.**
- After stage 0, if measured g < 2.5k, change the workload (bigger audits) before going on. Do not run the full grid on sessions that never cross H\*: that was the pilot's failure.
- Raise `PER_RUN_CAP_USD` from 3 to 10, and set the ledger cap to the approved total.
- Wall-clock is about 20–25 min per run. Run three sessions in parallel: about 2.5 hours for stages 0–2.

**Risks.**
- The agent may grep instead of reading whole files, keeping g low. The calibration gate catches this.
- Native autocompaction may leave a different σ than `/compact`. It is measured from `compact_metadata`.
- Anthropic rate limits under parallel runs.

The simulator shows that compacting by break-even is cheaper than window-relative triggers, and that it holds up when conditions change. It cannot show that early compaction **keeps task success intact**. The cheapest schedules compact about 4 times per session, while a 92% trigger compacts about once. This plan tests that with a real agent and real API bills.

## Research questions

- **RQ1 (non-inferiority):** Does break-even compaction keep the task solve rate within 3 points of fixed-92%?
- **RQ2 (cost):** What is the realized $ per solved task for each policy, using the cache-read and cache-write counts the API reports?
- **RQ3 (what to buy):** Is it better for a compaction to summarize history, to mask recoverable tool outputs, or to do both? Here the "buy" is the compaction action itself.
- **RQ4 (state loss):** Does early compaction drop irrecoverable user constraints more often than late compaction?
- **RQ5 (simulator fidelity):** How close is the simulator's cost prediction for each policy to the realized cost?

## Harness

- **Agent:** [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent), a bash-only agent loop of about 100 lines.
  - It has one obvious place to hook in: right before each model call.
  - It is already used for SWE-bench, so results are comparable to published numbers.
- **Hook:** `policy.should_compact(state)` runs before every call. It reuses `contextpilot/sim.py`, with the buy cost and the hold rate computed from live usage counts.
- **Compaction actions:**
  - `summarize`: an LLM summary of the history, capped at 12k tokens, with a fixed prompt. All user turns are kept verbatim.
  - `mask`: every tool output older than the last 3 calls is replaced with `[output elided: re-run <command> to view]`. No LLM call is needed.
  - `hybrid`: mask first, and summarize only if history is still above the break-even target.
- **Model:** Claude Sonnet 5.5 for the main runs. One replication pair (A1 vs A4) on a second model family checks that the result generalizes.
- **Logging:** for every call, record input, cache_read, cache_write and output tokens, and whether a compaction happened. Also record repeated tool calls, defined as the same command re-run after a compaction. This is the signal for the re-fetch fraction `rho`.

## Workloads

1. **SWE-bench Verified** (500 tasks). Most single tasks never reach 92% of a 200k window. That makes it a clean test of whether *extra, earlier* compactions hurt.
2. **Chained sessions.** Five SWE-bench tasks from the same repository run back to back in one session. This produces 150k–600k-token contexts, like real long coding sessions, so the window-limit policies actually fire.
3. **Constraint-retention probes (RQ4).** In chained sessions the first user turn sets 3 durable constraints. Examples: "never edit `setup.py`", "add a test for every fix", "do not use `sed -i`". Violations are checked automatically at the end. This measures loss of irrecoverable state directly.

## Arms

| Arm | Trigger | Buy action |
|---|---|---|
| A0 | window-forced (100%) | summarize |
| A1 | fixed 92% of window (status quo) | summarize |
| A2 | fixed 150k (Anthropic API default) | summarize |
| A3 | fixed 30k (best in simulation, tuned once) | summarize |
| A4 | break-even | summarize |
| A5 | break-even | mask |
| A6 | break-even | hybrid |
| A7 | break-even + hazard predictor | hybrid |

## Metrics and analysis

- **Primary:** solve rate, plus $ per solved task at list prices.
- **Secondary:**
  - total and peak tokens
  - number of compactions
  - re-fetch rate
  - constraint-violation rate
  - wall-clock time
- **Tests:**
  - Paired comparison on identical tasks: McNemar for solve rate, paired bootstrap for cost.
  - The non-inferiority margin of 3 points is pre-registered before the full runs.
  - Results are reported as a cost-vs-solve-rate Pareto plot.
- **Sample size:** about 15% of paired outcomes are expected to be discordant. With that, about 400 paired tasks give 80% power for a 3-point non-inferiority margin at one-sided α=0.05. So A1 and A4 run all 500 tasks, and the other arms run a stratified 150-task subset.
- **RQ5:** fit `rho` and the per-compaction penalty from the pilot, re-run the simulator, and compare predicted against realized cost per arm.

## Budget and staging

The per-run cost below is an estimate. The pilot will measure it.

| Stage | Runs | Estimated cost |
|---|---|---|
| Pilot: 50 tasks × A1, A3, A4, A5 | 200 | $60–200 |
| Main: 500 × (A1, A4) + 150 × the other arms | ~1,900 | $600–1,900 |
| Chained sessions: 40 chains × 4 arms | 160 long sessions | $300–800 |

Ways to fund it:

- academic API credit programs
- Berkeley compute
- shrinking the main stage to 300 tasks, which raises the detectable margin to about 4 points

**Go/no-go after the pilot:** proceed only if A4 or A5 is no more than 5 points worse than A1 on the pilot and at least 15% cheaper per solved task.

## Expected outcomes

- **Positive:** break-even with `mask` or `hybrid` is non-inferior to A1 and 20–45% cheaper per solved task on chained sessions. The paper claim becomes: robust, parameter-free compaction timing with a closed-form EOQ link and real-agent validation.
- **Negative but publishable:** early compaction hurts solve rate or constraint retention. The quality penalty is then measured, the break-even rule is retuned around it, and the paper reports the cost-quality frontier and where window-relative triggers are actually right.

## Risks

- **SWE-bench contamination or saturation:** results are reported as deltas between arms, not as absolute solve rates.
- **Summary-prompt sensitivity:** one fixed prompt is used in every summarize arm, and an ablation with a second prompt runs on 50 tasks.
- **Cache behaviour differs between providers:** cache multipliers are logged per run, and the realized bill is never assumed from prices alone.

## Timeline (6 weeks)

| Weeks | Work |
|---|---|
| 1–2 | Hook into mini-swe-agent, add usage logging, build the constraint probes, run the pilot |
| 3–4 | Main runs and chained sessions |
| 5 | Analysis and simulator recalibration (RQ5) |
| 6 | Write-up as a 4-page workshop paper, release the code |
