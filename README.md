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

1. **The optimal compaction point does not depend on the window.** In steady state the problem is the Economic Order Quantity: `H* = s + sqrt(2 g A / h)`. Here `g` is the growth per call, `A` the fixed buy cost, `h` the per-token hold price, and `s` the post-compaction history. For coding agents H\* is in the tens of thousands of tokens, about 40k at Claude Code prices on our traces.
2. **Window-relative triggers are unboundedly suboptimal as windows grow.** The cost curve is flat near the optimum: being off by 2x costs only 25% more of the controllable cost. But a trigger at 92–97% of a 1M window sits about 12x past H\*. Against a 92%-of-window trigger at a 1M window, economic triggers save **21–70%** (25% at Claude Code prices).
3. **Ski-rental break-even tracks the optimum without knowing growth or horizon.** It fires within `2b/h` calls of the optimum. The same bound predicts its weakness: lossy summaries combined with 1-hour cache writes. An online steady-state rule, fed only a running estimate of `g`, fixes this. It lands within **0.4%** of the best threshold tuned in hindsight in all 17 dataset × price × window settings.
4. **No single fixed threshold is robust across regimes.** A threshold tuned in one regime costs +51% when compactions carry a quality cost. The 92% trigger costs +186% uncached at 1M. The economic rules stay within 1–4%. Over adversarial sessions, every economic policy is within 1.22x of the offline optimum, while the 92% trigger reaches 1.64x.
5. **Cold-cache rule.** With 1-hour cache entries (2x write), compacting when an idle gap has expired the cache pays off immediately once history passes about 67k. With 5-minute entries it practically never pays. Adding this rule alone to a 92% trigger cuts cost by **17%** at 1M.
6. **Real-agent pilot.** We drove headless Claude Code (Sonnet 5.5) through 13- and 25-message sessions using an external `/compact` controller.
   - **Cost of compacting too early:** compacting at 15k of history raised the bill by **+32%** on 13-message sessions and **+143%** on 25-message sessions.
   - **The economic rule was correctly idle:** it never fired, because these sessions stayed below the point where compaction pays back.
   - **Quality:** after about 9 compactions, recall of earlier fixes fell from 11.7 to 9.7 of 12, and one run left an untagged edit.
   - **The trigger floor:** the Claude Code CLI refuses autocompact windows below 100k, so testing earlier triggers required an external controller.
   - **Fidelity:** replaying each run's real growth through the cost model reproduces its dollar bill with a **7.9%** mean absolute error over 18 runs ($18.43 total).

## Results at a glance

| Setting | Break-even | Online steady-state rule | Best fixed (hindsight) | Offline opt |
|---|---|---|---|---|
| Our Claude Code sessions, Claude Code prices, 200k | −3.2% | −7.3% | −7.3% | −9.0% |
| Our Claude Code sessions, Claude Code prices, 1M | −21.1% | −25.1% | −25.0% | −26.5% |
| Our Claude Code sessions, uncached, 1M | −69.4% | −69.9% | −70.0% | −70.6% |
| SWE-agent (13k trajectories), uncached, 32k | −55.7% | −56.1% | −56.0% | −57.9% |
| SWE-agent, Claude Code prices, 128k | −2.4% | −2.5% | −1.8% | −5.7% |
| 25 real sessions replayed, Claude Code prices, 1M | −24.6% | −27.9% | −27.8% | −29.7% |

All figures are relative to a 92%-of-window trigger. Full tables are in `results/`.

## Layout

```
contextpilot/sim.py          cost model, policies (break-even, steady-state, cold-cache), offline optimum
experiments/                 trace extraction, sweeps, worst case, cold cache, fidelity, figures
bench/                       real-agent pilot: 12-bug workspace, hidden scorer, /compact controller
results/                     saved outputs; results/pilot/ledger.jsonl has every real run
paper/                       LaTeX draft + figures
tests/                       12 tests pinning the propositions to the code
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
