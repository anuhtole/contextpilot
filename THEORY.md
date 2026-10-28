# Theory: when to compact an agent's context

All costs are in units of the base input-token price.

## Notation

**Prices**
- `r`: cache-read price per token, for example 0.1 or 0.05.
- `w`: cache-write price per token, for example 1.25 for the 5-minute cache or 2 for the 1-hour cache.
- `o`: output price per token, about 5.
- `h = r + q`: per-call cost of holding one history token. Here `q` is an optional context-rot (quality) price.

**Session**
- `S`: static prefix (system prompt plus tools).
- `H`: conversation history.
- `g`: mean tokens appended per call.

**Compaction.** Compacting history `H` replaces it with:
- a summary of size `σ(H)`, and
- re-fetched state `ρH`.

So the post-compaction history is `s(H) = σ(H) + ρH`.

Its one-time "buy" cost is

```
K(H) = r(S + H)            read the history for the summary call
     + o σ(H)              write the summary
     + (w − r) s(H)        rewrite premium for the new, short prefix
     + P                   optional quality penalty per compaction
```

`K` is affine in `H` with slope `b = r + (w − r)ρ`. Its intercept, evaluated at the post-compaction state, is

```
A = K(H) − b (H − s(H))
```

## 1. The optimal compaction point (EOQ form)

Consider the steady state: compact at history `H`, regrow from `s` at `g` tokens per call, and repeat. A cycle lasts `n = (H − s)/g` calls.

- Holding the excess above `s` costs `h·g·n(n−1)/2` per cycle.
- The buy costs `A + b·g·n` per cycle.

Ignoring terms that do not depend on `n`, the average cost per call is

```
f(n) = h g n / 2 + A / n + b g + const
```

**Proposition 1.** The cost-optimal interval and compaction point are

```
n* = sqrt( 2A / (h g) )
H* = s + sqrt( 2 g A / h )
```

This is the Economic Order Quantity (Harris, 1913) with ordering cost `A` and holding cost `h·g`. Two properties follow:

- **H\* does not depend on the context window `W`.**
- H\* scales as `sqrt(g)` and as `1/sqrt(h)`. Cheaper cache reads make later compaction optimal, but only by the square root: halving `r` raises H\* by √2.

The fixed point is solved numerically because `σ` and `s` depend on `H`; see `sim.eoq_history`. When the summary size grows with `H`, the square-root form overstates H\*. `sim.steady_state_optimum` minimizes the exact steady-state cost per call instead, and that is what the online policy uses: it lands within 0.4% of the best threshold tuned in hindsight in every setting (`results/closed_form.txt`). With Claude Code prices (`r = 0.05`, `w = 2`, `o = 5`), `S = 40k` and `ρ = 0.1`:

| Growth `g` (tokens/call) | H\* |
|---|---|
| 500 | about 23k |
| 2,000 | about 47k |
| 3,800 | about 86k |
| 8,000 | about 175k |

## 2. Flatness, and why window-relative triggers fail

**Proposition 2 (EOQ flatness).** For an interval `n = x·n*`,

```
f_ctrl(x n*) / f_ctrl(n*) = (x + 1/x) / 2
```

where `f_ctrl` is the part of the cost the trigger controls. Consequences:

- Being off by 2x in either direction costs only 25% of the controllable cost. That is why any trigger in the right *order of magnitude* is close to optimal.
- A trigger set as a fraction τ of the window compacts at `H_W = τW − S`. That gives `x ≈ (τW − S − s) / (H* − s)`, which **grows linearly in W**.

**Corollary 3.** Window-relative triggers have unbounded excess cost as `W → ∞`. Example: Claude Code compacts at about 96.7% of a 1M window. With `g = 3.8k`, that is `x ≈ 12`, so the controllable cost is about **6x** the optimum. The 1M-window simulations show the same thing: break-even and the closed form save 31–50% against a 92%-of-window trigger.

**Proposition 4 (no fixed threshold is robust).** A fixed absolute threshold `H0` has `x = (H0 − s)/(H* − s)`, and H\* moves with the ratio `A/h`, which differs across:

- cache pricing,
- summary cost,
- the quality penalty `P`.

If `A/h` ranges over a factor `F` across the regimes a product serves, some regime sees `x ≥ √F`, and the excess cost grows without bound in `F`. Empirically (`results/transfer.txt`), a 30k threshold tuned once costs +51% when `P = 200k`.

## 3. The ski-rental break-even rule tracks EOQ automatically

The break-even rule compacts when the cumulative rent on the compactable excess reaches the current buy cost: `h·Σ_k (H_k − s(H_k)) ≥ K(H)`.

In steady state this is `h·g·n(n+1)/2 ≥ A + b·g·n`. Solving:

```
n_BE = (b/h − 1/2) + sqrt( (b/h − 1/2)^2 + n*^2 )   ≤   n* + 2b/h
```

**Proposition 5.** The break-even rule fires within an additive `2b/h` calls of the EOQ optimum, with no knowledge of `g`, of the prices beyond the current `K`, or of the session length.

- With no re-fetch (`ρ = 0`), `b/h = r/h ≤ 1`, so the overshoot is at most about 2 calls. By Proposition 2 that is negligible.
- With re-fetch, `b/h = 1 + (w/r − 1)ρ`. With 1-hour caching (`w/r = 40`) and `ρ = 0.1`, `b/h ≈ 4.9`, so break-even overshoots by up to about 10 calls.
- This explains why plain break-even degrades when summaries are lossy (+8–12% in `results/transfer.txt`). The closed-form rule `H ≥ s + sqrt(2ĝA/h)`, with `ĝ` a running mean of observed growth, corrects for it.

**Single-phase competitiveness.** Within one rent-or-buy phase (one regrowth cycle) with nondecreasing per-call rent:

- the break-even rule is `(2 + ε)`-competitive against an adversary who picks when the session ends, where `ε` is the largest single-call rent divided by `K`;
- buying at a random fraction `z` of break-even, with `z ~ e^z/(e−1)` on [0, 1], gives `e/(e−1)` in expectation.

These are the classic bounds (Karlin et al., 1988). The multi-phase case — the regrowth state depends on past decisions — is evaluated empirically against an offline beam-search optimum in `experiments/worst_case.py`.

## 4. The cold-cache rule

After an idle gap longer than the cache TTL, the next call must rewrite the whole prefix at `w`. Compacting at that moment costs:

- an uncached read for the summary, `(S + H)`,
- the summary output, `o·σ`,
- a rewrite of only the short new prefix, `w·(S + s)`,

instead of `w·(S + H)`. The incremental buy cost is therefore

```
K_cold(H) = (1 − w)(S + H) + o σ + w (S + s) + P
```

**Proposition 6.** When `w > 1`, compacting on a cold cache is immediately cheaper than not compacting whenever

```
(w − 1)(S + H) > o σ + w (S + s) + P
```

It also removes all future rent on the dropped history.

- 1-hour cache (`w = 2`), `S = 30k`: compact on a cold cache once history exceeds about **67k**.
- 5-minute cache (`w = 1.25`): the threshold is about **841k**, so in practice never.

The cold-cache rule therefore matters specifically for harnesses that buy 1-hour cache entries. In 1.5% of the inter-call gaps in our local Claude Code sessions, the gap exceeds an hour. Adding this rule alone to a 92%-of-window trigger cuts simulated cost by **17%** at 1M (`results/cold_cache.txt`). Economic triggers already keep the context small, so for them the rule adds little.

## What is new here

- **Prior work.** Product triggers are fixed thresholds. Prior papers study what to keep (Tirmazi et al. 2026; ACON; TRACER) or cache-stable eviction schedules (TokenPilot). Classic ski rental and EOQ are textbook results.
- **Our contribution:**
  1. Casting compaction *timing* under real prompt-cache pricing as an EOQ / rent-or-buy problem.
  2. The window-independence and flatness results, which show that window-relative triggers are unboundedly suboptimal as windows grow.
  3. The `2b/h` tracking bound that explains when break-even works and when it does not.
  4. The cold-cache rule, with its threshold.
