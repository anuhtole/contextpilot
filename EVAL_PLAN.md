# Real-agent quality evaluation plan (draft, 2026-10-28)

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
