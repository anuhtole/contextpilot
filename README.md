# ContextPilot

**When should a long-running LLM agent compact its context?** Production harnesses answer with a constant, usually a fraction of the context window:

- Claude Code compacts near the window limit by default; `--autocompact N` takes a window of at least 100k and fires about 70k below it.
- Anthropic's compaction API defaults to a 150k-input-token trigger (minimum 50k).
- OpenAI's Responses API takes a `compact_threshold`, with no documented default.
- Gemini CLI compacts at `model.compressionThreshold`, a fraction of the window that defaults to 0.5.

ContextPilot treats the decision as an economic problem under real prompt-cache pricing.

- **Rent:** carrying history costs cache-read tokens on every call.
- **Buy:** compacting costs once. That covers the summary's output tokens, rewriting the cache prefix at the write price, re-fetching dropped state, and any quality risk.

Paper draft: [`paper/main.tex`](paper/main.tex). Derivations: [`THEORY.md`](THEORY.md).

## Findings

Every cost term is measured from Claude Code's usage counters (`experiments/fidelity.py`, `results/trace_stats.txt`):
- after `/compact`, about 11k tokens of conversation remain;
- the summary call generates about 5.2k of them as output (4.4k at ~50k context, 6.3k at 100–200k);
- about 8.6k of the session-specific prefix is evicted from the cache and rewritten;
- re-fetch of dropped history is ρ ≈ 0.007.

Measured this way, the model reproduces real bills to within **0.8%**: on 18 pilot runs, and on 12 high-growth runs with parameters taken from the pilot alone.

1. **The optimal compaction point does not depend on the window.** In steady state the problem is the Economic Order Quantity: `H* = σ + sqrt(2 g A / h)`, with `A = rS + oσ_out + wσ + (w−r)S_r + P` (see `THEORY.md`).
   - At Claude Code prices H\* is about 109k of history at 3.6k tokens per call, and about 54k at the pilot's 700.
2. **The 150k compaction default is close to optimal for Claude-priced coding agents, but not robust.**
   - At 3.6k per call the 150k trigger sits at x ≈ 1.0 of the optimum.
   - It is 2.3x too late for slow sessions, and 29% worse than the best fixed threshold without caching.
   - **Near-window triggers on 1M models are the clear inefficiency.** In trace-driven simulation, the 92% trigger costs about 28% more than compacting near H\*. The online rule is 21.6% cheaper on synthetic sessions and 22.6% cheaper replaying our 25 sessions; it is 38.8% cheaper with 0.1x caching and 66% without.
   - At 200k windows with Claude prices, every trigger is within 1%.
3. **The online rule is robust under i.i.d. growth.**
   - It stays within 1.6% of the hindsight-best threshold in all 17 settings.
   - A threshold tuned once loses up to 16.5% when caching changes.
   - In stress tests it stays within 1.14x of an offline optimum, against 1.52x for the 92% trigger at 1M.
4. **Ski-rental break-even tracks H\*** to within `2b/h` calls without knowing the growth rate.
5. **Cold-cache rule.** With 1-hour cache entries, compacting when an idle gap expires the cache pays off once history passes about 88k. Added to a 92% trigger at 1M, it cuts cost by 17%.
6. **Real-agent pilot** (18 runs, Sonnet 5.5, external `/compact` controller):
   - Compacting at 15k of history (about 1.4σ, so only 2–5k tokens dropped each time) costs +32% to +143%.
   - The economic rule's target was never reached.
7. **Real sessions past H\*:** four paired orderings, about 110 calls and 20 bugs each, peaking near 365k.
   - **Savings were single-digit and not significant.** A 150k trigger cost −9.8% vs `auto` (paired-t 95% CI −25.8 to +6.3; exact permutation p = 0.25). The online rule cost −2.8% (CI −21.9 to +16.3).
   - **Our recorded prediction (−35%) failed.**
     - Its gap decomposes into an empirical bias correction that should not have been applied (10 points) and back-loaded growth (16 points): 87–89% of growth arrives in the last 40% of calls.
     - See `experiments/prediction_gap.py` and the prediction-vs-outcome table in the paper.
   - **Mechanism.** History rent was 29% of the `auto` bill, and compaction cut it by more than half. Cache rewrites and summary output then won back 79% of the online rule's saving but only 34% of the 150k trigger's.
   - **Recall of exact buggy expressions** was 19.0, 17.5 and 15.0 of 20 at 0, 2 and 3 compactions. This is descriptive at n = 4.
   - **Claude Code's `--autocompact N` is a window size:** it fires about 70k below N.
   - **Attrition:** one ordering was lost to account rate limiting, and 14 throttled partial runs ($18.06) are excluded.
8. **Horizon awareness is worth little** (simulation, `experiments/horizon.py`).
   - **The gate:** it compacts only if the rent saved over the predicted remaining session repays the buy. With out-of-sample length predictors it never changes a decision, and with an oracle it adds 0.3–1.9 points.
   - **Recent-growth tracking** (EWMA; exploratory, designed after the real runs) cuts the online rule's gap on the real back-loaded growth from +5.1% to +1.6% vs best fixed. It is slightly worse elsewhere.

**What that means.** Steady-state savings are a ceiling that only long, steadily growing sessions realize. For back-loaded coding sessions at Claude cache prices, trigger placement is worth single-digit percent. The calibrated cost model can tell a deployer in advance which regime they are in.

The tables in `paper/` are generated from `results/*.json` by `experiments/make_tables.py`.

## Layout

```
contextpilot/sim.py          cost model, policies (break-even, steady-state, cold-cache), offline optimum
experiments/                 trace extraction, sweeps, worst case, cold cache, fidelity, figures
bench/                       real-agent pilot: 12-bug workspace, hidden scorer, /compact controller
results/                     saved outputs; results/pilot/ledger.jsonl has every real run
paper/                       LaTeX draft + figures
tests/                       tests pinning the propositions and measured cost terms to the code
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
../.venv/bin/python highgrowth_summary.py && ../.venv/bin/python prediction_gap.py
../.venv/bin/python horizon.py && ../.venv/bin/python make_tables.py
../.venv/bin/python figures.py
```

`data/` contains numeric token counts only: no message text, file paths, or tool arguments.

- `experiments/extract_traces.py` rebuilds `traces.json` from your own `~/.claude/projects`.
- `experiments/extract_swe_agent.py` rebuilds the SWE-agent traces from [nebius/SWE-agent-trajectories](https://huggingface.co/datasets/nebius/SWE-agent-trajectories) (CC-BY-4.0).

The pilot (`bench/run_pilot.py`) spends real API money. Each run is capped by `--max-budget-usd`, and the ledger enforces a total cap.

- High-growth runs use variants `h1`–`h5` and the `results/highgrowth/` ledger: `bench/run_highgrowth.sh`, then `experiments/highgrowth_summary.py`.
- Set `PILOT_TIMEOUT_S` to extend the per-run timeout.

Origin: a clean-room reimplementation and extension of a concept Anatole Seychal first prototyped in summer 2026.
