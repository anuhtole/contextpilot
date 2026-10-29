# ContextPilot

**When should a long-running LLM agent compact its context?** Production harnesses answer with a constant, usually a fraction of the context window:

- Claude Code compacts near the window limit (about 967k on 1M models), and its CLI refuses windows below 100k.
- Anthropic's compaction API defaults to 150k.
- OpenAI's Responses API takes a `compact_threshold`.
- Gemini CLI's documented default is 70% of the window.

ContextPilot treats the decision as an economic problem under real prompt-cache pricing.

- **Rent:** carrying history costs cache-read tokens on every call.
- **Buy:** compacting costs once. That covers the summary's output tokens, rewriting the cache prefix at the write price, re-fetching dropped state, and any quality risk.

Paper draft: [`paper/main.tex`](paper/main.tex). Derivations: [`THEORY.md`](THEORY.md).

## Findings

The parameters were measured on headless Claude Code: about 11k tokens remain after `/compact`, and re-fetch is about 0.1% of dropped tokens.

1. **The optimal compaction point does not depend on the window.** In steady state the problem is the Economic Order Quantity: `H* = σ + sqrt(2 g A / h)`. Here `σ` is the post-compaction size, `g` the growth per call, `A` the fixed buy cost and `h` the hold price. Re-fetch has its own closed form, given in `THEORY.md`.
   - At Claude Code prices, H\* is about 118k of history for our sessions (3.6k tokens per call) and about 58k for the slow pilot sessions.
2. **Anthropic's 150k API default is near-optimal for Claude-priced coding agents. Near-window triggers on 1M models are not.** The cost curve is flat near H\*, so triggers within 2x of it are fine. Compacting near a 1M window, however, costs about **20% more per session**: 20.5% simulated, and 21.4% replaying our 25 real sessions. In live high-growth runs, which back-load their growth, the realized gap against a 150k trigger was smaller, about 10% (finding 7). With 0.1x caching the excess is 37%, and without caching 27–65%. At 200k windows with Claude prices, no trigger matters by more than 1%.
3. **An online rule fixes the problem that no single threshold is robust.** Solving for H\* from a running growth estimate lands within **1.3%** of the best threshold tuned in hindsight in all 17 dataset × price × window settings. A threshold tuned once loses up to 13% when prices or quality costs change, and the 150k default loses up to 8.5% when summaries are 2k or 20k. Over adversarial sessions, the online rule and break-even stay within 1.15x of the offline optimum, while the 92% trigger reaches 1.50x.
4. **Ski-rental break-even tracks H\*** within `2b/h` calls (about 2 calls) without knowing the growth rate.
5. **Cold-cache rule.** With 1-hour cache entries, compacting when an idle gap expires the cache pays off immediately once history passes about 118k. Added to a 92% trigger at 1M, it cuts cost by 16%.
6. **Real-agent pilot** (18 runs of Claude Code with Sonnet 5.5, $18.43, driven by an external `/compact` controller, since the CLI refuses autocompact windows below 100k):
   - **Premature compaction is expensive:** it costs +32% (13 messages) to +143% (25 messages).
   - **Recall dipped after about 9 compactions:** 9.7 vs 11.7 of 12. With n=3 this is suggestive, not significant.
   - **The economic rule never reached its trigger,** so it matched `auto`.
   - **Fidelity:** the cost model reproduces the real bills at 7.9% mean absolute error.
7. **Real sessions that cross H\*:** 13 runs, about 110 calls and 20 bugs each, peaking at about 365k context; $60 including throttled runs.
   - **Savings were single-digit:** a 150k trigger saved −9.8% vs `auto` (95% CI −18.0 to −1.6), and the online rule −2.8% (CI −11 to +9).
   - **Why:**
     - Compaction cut cache-read rent by 39% as predicted.
     - But at 0.05x reads rent is only 41% of the bill, and the 2x cache rewrite plus summary output win most of it back.
     - These sessions also put 87–89% of their growth in the last 40% of calls, so there is little session left after H\* in which a compaction can pay off.
   - **The cost model called it:** replaying each run's real growth predicted −2.1% for the online rule and −7.0% for 150k. Even a hindsight-best threshold could save only 4–12%. Fidelity was 8.1% MAE over 13 runs.
   - **The steady-state rule misreads back-loaded growth.** A slow start depresses its growth estimate, so it compacted 3 times vs 2 for 150k. Break-even beats it on the same traces.
   - **Compaction costs irrecoverable detail:** exact-expression recall was 19.0, 17.5 and 15.0 of 20 at 0, 2 and 3 compactions. Bugs fixed and rules followed were unaffected.
   - **Claude Code's `--autocompact N` is a window size:** it fires about 70k below N.
   - Details: [`EVAL_PLAN.md`](EVAL_PLAN.md) and `results/highgrowth_summary.txt`.

8. **Horizon awareness is worth little, and growth tracking more** (simulation, `experiments/horizon.py`).
   - **The rule tested:** a gate that compacts only if the rent saved over the predicted rest of the session repays the buy. With out-of-sample length predictors it never changes a decision.
   - **Even an oracle gains only 1–2 points** over the best fixed threshold.
   - **Tracking recent growth (an EWMA) helps:** it halves the online rule's gap on the real back-loaded runs (+6.2% → +3.1% vs best fixed) and keeps the worst case at 1.13x.
   - **The case for adaptive rules is robustness:** a fixed 150k is near-best at Claude prices but +24.8% without caching.

**What that means.** The 20–40% steady-state gap is an upper envelope that only long, steadily growing sessions realize. For typical, back-loaded coding sessions at Claude cache prices, trigger placement is worth single-digit percent.

The tables in `paper/` are generated from `results/*.json` by `experiments/make_tables.py`.

## Layout

```
contextpilot/sim.py          cost model, policies (break-even, steady-state, cold-cache), offline optimum
experiments/                 trace extraction, sweeps, worst case, cold cache, fidelity, figures
bench/                       real-agent pilot: 12-bug workspace, hidden scorer, /compact controller
results/                     saved outputs; results/pilot/ledger.jsonl has every real run
paper/                       LaTeX draft + figures
tests/                       21 tests pinning the propositions to the code
THEORY.md, EVAL_PLAN.md      derivations; the full real-agent evaluation plan
```

## Reproduce

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
cd experiments
../.venv/bin/python closed_form.py   # cross-dataset sweep (needs data/swe_agent_traces.json)
../.venv/bin/python worst_case.py
../.venv/bin/python cold_cache.py
../.venv/bin/python fidelity.py      # simulator vs. real pilot bills
../.venv/bin/python figures.py
```

`data/` contains numeric token counts only: no message text, file paths, or tool arguments.

- `experiments/extract_traces.py` rebuilds `traces.json` from your own `~/.claude/projects`.
- `experiments/extract_swe_agent.py` rebuilds the SWE-agent traces from [nebius/SWE-agent-trajectories](https://huggingface.co/datasets/nebius/SWE-agent-trajectories) (CC-BY-4.0).

The pilot (`bench/run_pilot.py`) spends real API money. Each run is capped by `--max-budget-usd`, and the ledger enforces a total cap.

- High-growth runs use variants `h1`–`h5` and the `results/highgrowth/` ledger: `bench/run_highgrowth.sh`, then `experiments/highgrowth_summary.py`.
- Set `PILOT_TIMEOUT_S` to extend the per-run timeout.

Origin: a clean-room reimplementation and extension of a concept Anatole Seychal first prototyped in summer 2026.
