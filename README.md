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
2. **Anthropic's 150k API default is near-optimal for Claude-priced coding agents. Near-window triggers on 1M models are not.** The cost curve is flat near H\*, so triggers within 2x of it are fine. Compacting near a 1M window, however, costs about **20% more per session**: 20.5% simulated, and 21.4% replaying our 25 real sessions. With 0.1x caching the excess is 37%, and without caching 27–65%. At 200k windows with Claude prices, no trigger matters by more than 1%.
3. **An online rule fixes the problem that no single threshold is robust.** Solving for H\* from a running growth estimate lands within **1.3%** of the best threshold tuned in hindsight in all 17 dataset × price × window settings. A threshold tuned once loses up to 13% when prices or quality costs change, and the 150k default loses up to 8.5% when summaries are 2k or 20k. Over adversarial sessions, the online rule and break-even stay within 1.15x of the offline optimum, while the 92% trigger reaches 1.50x.
4. **Ski-rental break-even tracks H\*** within `2b/h` calls (about 2 calls) without knowing the growth rate.
5. **Cold-cache rule.** With 1-hour cache entries, compacting when an idle gap expires the cache pays off immediately once history passes about 118k. Added to a 92% trigger at 1M, it cuts cost by 16%.
6. **Real-agent pilot** (18 runs of Claude Code with Sonnet 5.5, $18.43, driven by an external `/compact` controller, since the CLI refuses autocompact windows below 100k):
   - **Premature compaction is expensive:** it costs +32% (13 messages) to +143% (25 messages).
   - **Recall dipped after about 9 compactions:** 9.7 vs 11.7 of 12. With n=3 this is suggestive, not significant.
   - **The economic rule never reached its trigger,** so it matched `auto`.
   - **Fidelity:** the cost model reproduces the real bills at 7.9% mean absolute error.

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

Origin: a clean-room reimplementation and extension of a concept Anatole Seychal first prototyped in summer 2026.
