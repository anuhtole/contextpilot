# Real-agent quality evaluation plan (draft, 2026-10-28)

## Status after the pilot (`bench/`, 18 runs, $18.43)

- **Harness pivot.** The pilot ran on headless Claude Code rather than mini-swe-agent. The Claude Code CLI refuses `--autocompact` windows below 100k, so arms are driven by an external controller that sends `/compact` between user turns.
- **Established:**
  - Premature compaction costs +32% (13 messages) and +143% (25 messages).
  - After about 9 compactions, cross-compaction recall falls from 11.7 to 9.7 of 12.
  - The economic trigger correctly stays idle below H\*.
  - The cost model reproduced real bills at 7.9% MAE at the time. Two measurement biases were later found to roughly cancel; with every term measured the error is 0.8% (see the results below).
- **Not established by the pilot:** that the economic trigger *saves* money in real runs, because no pilot session grew past H\* (about 60k of history).
- **Follow-up done:** high-growth sessions that do cross H\*; see the results section below. Real savings were single-digit, and the cost model predicted that.
- **Remaining plan:** the SWE-bench design below is still the path to a full-paper result.

## Results: high-growth real sessions (run 2026-10-28/29; $60.01 of $95 approved)

The paper (§5.1) holds the authoritative write-up. The numbers below were regenerated on 2026-10-29 after an independent review found two cost-model measurement errors:
- **Summary output was overcharged.** The summary call generates about 5.2k output tokens, not all 11k of σ.
- **Prefix eviction was missing.** About 8.6k of the prefix is evicted and rewritten at each compaction.

Outputs: `results/highgrowth_summary.txt`, `results/highgrowth/{summary,prediction_gap}.json`, `paper/table_highgrowth.tex`.

**Runs and attrition.**
- Four paired orderings (h1, h2, h3, h5) completed under all three arms.
- h4 completed only under `150k`, after three throttled attempts on the account's five-hour rate-limit window.
- 14 partial runs ($18.06) are excluded and archived in `ledger_timeouts.jsonl` and `timeouts/`.

**Cost (paired, n = 4):**
- `150k` vs `auto`: −9.8% (paired-t 95% CI −25.8 to +6.3; exact two-sided permutation p = 0.25).
- `eoq` vs `auto`: −2.8% (−21.9 to +16.3; p = 0.75).
- `eoq` vs `150k`: +8.1% (−8.6 to +24.7).
- At n = 4 the smallest attainable p is 0.125.

**Recorded predictions** (commit cd8e116) and outcomes:

| Prediction | Outcome |
|---|---|
| eoq vs auto −35% ± 6% | −2.8%: failed |
| eoq vs 150k within ±5% | +8.1%: point estimate outside |
| far arm −22% ± 8% | not run |
| bugs ≥ 23/24 | 20/20 on the 20-bug variant: met |
| recall drop ≤ 1/12 | eoq −4/20: failed |

**Protocol deviations:** 20 bugs instead of 24, an external 150k trigger instead of the CLI's, and n = 4 instead of 5.

**Why it failed** (`experiments/prediction_gap.py`):

| Step | eoq vs auto | Change |
|---|---|---|
| As recorded | −34.9% | |
| Without the empirical bias correction (an artifact) | −24.6% | +10.3 |
| Corrected cost model | −26.1% | −1.5 |
| Real growth and length, order shuffled | −20.4% | +5.7 |
| Real order: back-loading, the largest effect | −4.6% | +15.8 |
| Observed | −2.8% | |

**Mechanism.** History rent (cache reads net of the static prefix) was 29% of the `auto` bill, and compaction cut it by more than half. Cache rewrites and summary output then won back 79% of eoq's read saving and 34% of 150k's.

**Fidelity.** With every term measured, the model reproduces the 18 pilot bills to 0.8% MAE, and the 12 paired high-growth bills to 0.6%. Using pilot-only parameters (held out), the high-growth error is 0.8%.

**Quality.** All arms fixed 20/20 bugs and broke no rule. Exact-expression recall was 19.0, 17.5 and 15.0 of 20; this is descriptive.

## Horizon-aware rules (simulation only, 2026-10-29)

Code: `sim.HorizonGated`, `sim.ClosedFormRecent`, `sim.empirical_residual` (tests in `tests/test_horizon.py`). Results: `results/horizon.{txt,json}` and `paper/table_horizon.tex`. The stress-test ratios are in `results/worst_case.json`, on the same 150 sessions as every other policy.

- **The learned horizon gate never changes a decision.** With an oracle it adds 0.3–1.9 points over its inner rule.
- **Recent-growth tracking** (EWMA, half-life 10) was designed after seeing the real runs, so it is exploratory.
  - On the real back-loaded growth it improves the online rule from +5.1% to +1.6% vs the best fixed threshold.
  - It is slightly worse on i.i.d. and replayed sessions (+0.2% → +0.4%) and on the stress test (1.155 vs 1.140).
- **A fixed 150k** is within about 1% of the best at Claude prices but 29% worse uncached.

## Design: quality cost of extra compactions (written 2026-11-03, before any runs)

**Question.** The in-the-wild replay (§`sec:wild`) says a 200k trigger would have cut the user's real bills by 12% warm and 29% with cache misses. It only pays if each extra compaction costs less quality than it saves. In base-input-token units, the warm 200k saving is gone once one compaction costs about **P ≈ 180k tokens**; counting cache misses, it stays positive past P = 400k (table below, from `replay.py` with `sim.Env.penalty`). This experiment measures quality loss per compaction on a real agent, so P can be estimated rather than assumed.

| P per compaction | Online, warm | 200k, warm | Online, with misses | 200k, with misses |
|---|---|---|---|---|
| 0 | −12.1% | −12.4% | −29.8% | −28.6% |
| 50k | −9.2% | −8.7% | −25.5% | −26.6% |
| 100k | −8.3% | −5.1% | −22.4% | −24.7% |
| 200k | −3.8% | +1.9% | −10.4% | −20.8% |
| 400k | −2.7% | +15.1% | −8.8% | −13.3% |

**Design: a dose-response on compaction count.** Same workload, model (Sonnet 5.5) and harness as the high-growth runs, so the 12 completed paired runs are reused unchanged.

| Arm | Trigger (external `/compact`) | Compactions (expected) | Status |
|---|---|---|---|
| auto | none (1M window) | 0 | h1, h2, h3, h5 done |
| 150k | 150k context | 2 | done |
| eoq | online H\* | 3 | done |
| 100k | 100k context | about 4–5 | new |
| 70k | 70k context | about 7–9 | new |

- New runs: `100k` and `70k` on h1, h2, h3, h5 (8 runs), plus two new orderings h6 and h7 under all five arms (10 runs). That gives 6 orderings × 5 arms = 30 runs, 18 of them new.
- h4 stays excluded: it never completed the paired set.
- Exact compaction counts for the new arms are sized on the simulator from the `auto` runs' real increments before anything is spent (step 0).

**Outcomes.**
- **Primary:** exact-expression recall (/20, `score.py` `recall_expression`), regressed on the *realized* compaction count with an ordering fixed effect. The slope is "facts lost per compaction". Test: permutation of arm labels within ordering (two-sided), plus a bootstrap 95% CI on the slope.
- **Secondary:** bugs fixed (/20; saturated so far, reported for gross harm only), rule-5 and constraint violations, the two audits, re-fetch rate ρ (reads of a file already read), and dollars per run.
- **Cost-quality frontier:** dollars vs recall, one point per arm, with paired CIs.

**Pre-registered predictions.**
- Slope ≈ −1.3 facts per compaction (extrapolated from 19.0 → 15.0 over 3), 95% interval −0.6 to −2.0.
- Linear, not a cliff: the 70k arm's recall is within 2 facts of the linear fit from the other four arms.
- Bugs fixed stays ≥ 19/20 in every arm.
- `100k` costs within ±8% of `150k`; `70k` costs more than `150k` (compaction overhead dominates below H\*).

**Converting to P.** A lost fact costs the agent a re-read of the module it came from: 1.4–3.3k lines, about 15–35k tokens, so about 25k per fact. At the predicted slope, P ≈ 1.3 × 25k ≈ 33k tokens per compaction: well below 180k, so the 200k recommendation would stand. The measured ρ cross-checks this: it is the share of facts actually re-fetched rather than lost silently.

**Decision rule (fixed now).**
- If the slope's upper CI bound implies P < 180k (fewer than about 7 facts lost per compaction): keep the 200k default in `recommend` and report the measured P in the paper.
- If P lies above 180k: `recommend` switches to the online rule with the measured penalty, and the paper says that fixed early triggers trade quality for cost.
- A cliff (the 70k arm falls more than 2 facts below the line) is reported as a limit on compaction count, and `recommend` caps expected compactions per session at the count before the cliff.
- Silent loss (recall falls while ρ does not rise) is the worst case for P: then P is not bounded by re-read cost, and the paper says so.

**Budget and gates.** Sonnet 5.5, 1-hour cache, observed $2.7–3.5 per completed run.

| Step | Runs | Estimate |
|---|---|---|
| 0. Sizing on the simulator; add `100k`/`70k` to `CONTEXT_TRIGGERS` and h6/h7 to the run script (free) | 0 | $0 |
| 1. Smoke test: one `70k` run truncated at 40 messages, to confirm the trigger fires | 1 | $1 |
| 2. Drift check: re-run h1 `auto` | 1 | $3.5 |
| 3. Dose arms on h1, h2, h3, h5 | 8 | $25 |
| 4. h6, h7 × 5 arms | 10 | $31 |

- Estimate: about $60. Last time partial runs from rate limiting added 30% ($18 on $60).
- **Proposed cap: $90**, enforced by the ledger (`CAP=90`), with `PER_RUN_CAP_USD` = 10 unchanged.
- Run two sessions in parallel rather than three (`HEADROOM=20`): three in parallel caused most of the throttled runs.
- **Gate after step 2:** if the h1 `auto` re-run differs from the original by more than 2 recall facts or 10% in cost, stop and report model drift before spending more.
- **Gate after step 3:** if all 8 dose runs show recall within 1 fact of `auto`, step 4 still runs (it is the replication), but the cliff analysis is dropped.

**Risks.**
- Recall /20 is coarse, and bugs fixed is saturated: a real quality effect could hide under the ceiling. Changing the workload would break pairing with the 12 runs, so it stays fixed; the paper states the ceiling.
- Compaction count is partly an outcome (the agent's growth decides it), so the regression uses realized counts and also reports the arm-level means.
- One model only. Opus 5.5 would cost about 2× and is out of scope for this cap.
- Model drift since 2026-10-29 is caught by the step 2 gate.

**Protocol amendment (2026-11-05, after steps 1–2, before any dose run; $5.91 spent).**
- Step 1 passed: the truncated `70k` run compacted 7 times in 40 messages ($2.83, above the $1 estimate).
- Step 2 **failed its gate**: the h1 `auto` re-run recalled 15/20 against 20/20 originally, and cost 11.7% less ($3.08 vs $3.49).
- A single re-run cannot separate model drift from run-to-run noise. A 5-fact swing with zero compactions says the per-run noise is about as large as the whole 19 → 15 effect seen earlier, so the gate's 2-fact threshold was set too tight. Either way, comparing new dose runs with the old 10-29 runs could be confounded by run date.
- **Amended design:**
  - The **primary estimate is the slope on h6 and h7 alone**, all five arms run fresh in this batch. No arm is compared across run dates.
  - The pooled slope (h1–h3, h5 old arms plus new dose arms, and h6–h7) is secondary. Its gap from the primary slope is reported as the run-date check, along with the h1 `auto` pair.
  - Run order: h6 and h7 first, then the dose arms on h1, h2, h3, h5, so a cap stop drops secondary runs first.
  - Predictions, decision rule and cap ($90 total on `results/dose/ledger.jsonl`) are unchanged.
- Power at a noise SD of about 3.5 facts: the fresh slope's SE is about 0.4 (10 runs, compactions 0–8), so the predicted −1.3 is about 3 SE from zero. The pooled slope's SE is about 0.25.

**Outcome (runs 2026-11-05 and 2026-11-12).** The full design completed: six orderings by five arms, 30 runs, at $71.28 of $90.
- First batch (11-05): 8 of 18 queued runs went silent mid-session (API hangs, not the rate limit) and were dropped ($6.38). An interim write-up on 11-09 used the 20 runs then available.
- Second batch (11-12): the remaining 10 cells (70k on all six orderings; 100k on h1, h2, h3, h5) all completed.
- **Deviation:** every 70k run and four 100k runs are a week younger than the other arms of their ordering, h6 and h7 included. The primary estimate is no longer a single batch.

| Prediction | Result | Verdict |
|---|---|---|
| Slope −1.3 (−0.6 to −2.0) | Primary +0.23 (CI −0.15 to +0.90, p = 0.78, 10 runs); pooled −0.05 (−0.39 to +0.32, p = 0.84, 30 runs) | Failed: both CIs exclude −0.6 |
| 70k within 2 facts of the line from the other four arms | Primary +1.2 above the line; pooled +3.6 above | Held on primary; missed on pooled, in the harmless direction. No cliff |
| Bugs fixed ≥ 19/20 | 20/20 in all 30 runs | Held |
| 100k within ±8% of 150k cost | $3.29 vs $2.90 (+13%, n = 6) | Failed |
| 70k costs more than 150k | $3.65 vs $2.90 (+26%) | Held |

- **Decision rule:** the upper bound gives P ≤ 4k (primary) or 10k (pooled), under 180k, so the 200k default in `recommend` stands.
- **Silent loss applies:** ρ ≤ 0.2 while two of 24 compacted runs dropped to 4–5 recall (h7 at 150k, h6 at 100k). P is therefore not bounded by re-read cost, and the paper says so.
- **Noise:** recall was bimodal (28 runs at 12–20, two at 4–5), not the SD 3.5 assumed. The primary CI resamples only two orderings; the pooled CI is the more reliable.

## Design: high-growth real sessions (written 2026-10-28, before the runs)

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
