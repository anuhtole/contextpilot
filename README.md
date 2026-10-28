# ContextPilot

**When should a long-running LLM agent compact its context?** Every production harness today answers with a fixed threshold, usually a fraction of the context window. Examples: Claude Code at the window limit, the Anthropic compaction API at 150k tokens, Gemini CLI at 70%, and Codex at a configured token limit.

ContextPilot treats the decision as an online **rent-or-buy** problem.

- **Rent:** carrying history costs a little on every call, as cache-read tokens.
- **Buy:** compacting costs once. That covers the summary call, rewriting the cache prefix, any re-fetching of dropped state, and any quality risk.
- **The rule:** compact when the cumulative rent paid on the compactable excess reaches the current buy cost. This is the ski-rental break-even rule, which is 2-competitive for a single rent-or-buy phase. Randomized and prediction-augmented variants are included.

## Findings (trace-calibrated simulation)

### Setup

The simulator is calibrated on 25 real Claude Code sessions, using token counts only:

- 1,465 API calls.
- 94.6% of input tokens were cache reads.
- About 3.8k tokens were appended per call.
- Session length is roughly lognormal, with a median of 32 calls.

### Cost relative to a fixed 92%-of-window trigger

Each cell is the change in cost per session versus the 92% trigger, over 400 synthetic sessions. Negative means cheaper.

| Regime | Break-even | + hazard predictor | Best fixed threshold (hindsight) | Offline optimum |
|---|---|---|---|---|
| 200k window, no caching | −38.6% | −39.2% | −39.7% (20k) | −40.9% |
| 200k window, cached (0.1x read) | −14.8% | −16.4% | −17.1% (30k) | −18.4% |
| 200k window, cached (0.05x read) | −5.7% | −8.9% | −9.3% (30k) | −11.1% |
| 1M window, cached (0.1x read) | −47.5% | −48.9% | −49.6% (30k) | −50.4% |
| 1M window, cached (0.05x read) | −31.5% | −34.1% | −34.8% (30k) | −36.2% |

### What the results say

1. **Most of the gain comes from compacting early.** The cheapest schedules compact at about 30–60k tokens of history, whatever the window size. Window-relative triggers get worse as windows grow toward 1M tokens.
2. **Prompt caching shrinks the gain at 200k.** It makes rent about 10–20x cheaper, so savings at a 200k window fall from about 39% to 6–17%. Projections that ignore caching overstate savings.
3. **The case for break-even is robustness.** A threshold tuned once can fail badly when conditions change; break-even adapts without retuning. Excess cost versus the best threshold for each regime (`results/transfer.txt`):

   | Regime | Fixed 30k (tuned once) | Fixed 92% | Break-even |
   |---|---|---|---|
   | Cached, 0.1x read (tuning regime) | +0.0% | +17.7% | +2.6% |
   | Quality penalty of 200k tokens per compaction | **+51.1%** | −0.3% | +0.3% |
   | No caching, 1M window | +2.9% | **+186.4%** | +2.6% |

   Across all regimes tested, break-even stays within 1–4% of the best threshold for that regime, except when summaries are very lossy (+8–12%; see Limitations).
4. **Break-even has a closed form in steady state.** Under steady growth `g` with hold cost `h` and buy cost `K`, the rule fires at `sqrt(2K / (h·g))` calls. That is the Economic Order Quantity optimum, and `tests/test_sim.py` checks it.

## Limitations

These are cost results only. Compacting about 4 times per session instead of about once could hurt task success, and the simulator models quality only through two knobs:

- a re-fetch fraction `rho`
- a per-compaction penalty

[`EVAL_PLAN.md`](EVAL_PLAN.md) describes the real-agent evaluation that settles this.

Other limitations:

- The trace sample is small and comes from one user.
- Summary size and re-fetch are parametric.
- The offline optimum is a beam-search DP, so it approximates the true optimum.
- With lossy summaries (`rho=0.5`), plain break-even mis-prices the buy. The predictive variant recovers part of the gap.

## Related work

- **Timing.** No prior work found frames compaction timing as rent-or-buy (search as of 2026-10). Closest:
  - TokenPilot (arXiv 2606.17016): cache-aware eviction on a batch-turn schedule.
  - CliffCompaction (arXiv 2609.26779): truncation-only compaction.
  - Context Compaction Theory (arXiv 2608.01326): covers *what* to keep, not *when*.
- **Retention and masking.** The Complexity Trap (2508.21433), ACON (2510.00615), TRACER (2608.29363), ARC (2607.25066).
- **Online algorithms.** Karlin et al. (ski rental); Purohit, Svitkina & Kumar, NeurIPS 2018 (learning-augmented); Fleischer (Bahncard).

## Reproduce

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
cd experiments
../.venv/bin/python main_tables.py 300   # policy tables + real-trace replay (~2 min)
../.venv/bin/python sensitivity.py       # pricing / re-fetch / quality sweeps (~15 min)
../.venv/bin/python transfer.py          # tuned-threshold robustness
```

`data/traces.json` contains numeric usage counts only, with no message text or paths. `experiments/extract_traces.py` regenerates it from your own `~/.claude/projects` transcripts.

## Layout

```
contextpilot/sim.py        cost model, policies, offline optimum
experiments/               trace extraction and experiment scripts
results/                   saved outputs of the experiments
tests/                     model invariants (EOQ, optimum bound, monotonicity)
EVAL_PLAN.md               real-agent quality evaluation design
```

Origin: a clean-room reimplementation of a concept Anatole Seychal first prototyped in summer 2026.
