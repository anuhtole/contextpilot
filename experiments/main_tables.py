"""Experiments: fixed-threshold vs rent-or-buy compaction, calibrated on local traces."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextpilot import sim  # noqa: E402

RNG = np.random.default_rng(7)
TRACES_PATH = Path(__file__).resolve().parents[1] / "data" / "traces.json"
TRACES = json.loads(TRACES_PATH.read_text())


def trace_sequences():
    """Per-call positive context increments of each real session (compactions removed)."""
    seqs = []
    for s in TRACES:
        ctx = [t["in"] + t["cr"] + t["cw"] for t in s["turns"] if "in" in t]
        inc = [max(b - a, 0) for a, b in zip(ctx, ctx[1:])]
        if len(inc) >= 5:
            seqs.append(np.array(inc, dtype=float))
    return seqs


SEQS = trace_sequences()
POOL = np.concatenate(SEQS)
LOG_T = np.log([len(q) for q in SEQS])
MU, SD = LOG_T.mean(), LOG_T.std()


def synth_sessions(n, mu=MU, sd=SD, seed=7):
    rng = np.random.default_rng(seed)
    lengths = np.maximum(3, np.round(rng.lognormal(mu, sd, n))).astype(int)
    return [rng.choice(POOL, size=L) for L in lengths]


def mean_residual(mu=MU, sd=SD, n=200_000):
    """Hazard-based predictor: E[T - t | T > t] under the fitted lognormal."""
    draws = np.sort(np.random.default_rng(1).lognormal(mu, sd, n))
    table = {}
    def f(t):
        if t not in table:
            tail = draws[draws > t + 1]
            table[t] = float(tail.mean() - (t + 1)) if len(tail) else 1.0
        return table[t]
    return f


class LengthOracle:
    """Remaining-length predictor with multiplicative lognormal noise."""
    def __init__(self, noise, seed=3):
        self.noise, self.T = noise, 0
        self.rng = np.random.default_rng(seed)
    def __call__(self, t):
        return max(self.T - t - 1, 0) * float(self.rng.lognormal(0, self.noise))


def mean_cost(env, sessions, policy, oracle=None):
    costs, comps = [], []
    for g in sessions:
        if oracle is not None:
            oracle.T = len(g)
        c, k = sim.run(env, g, policy)
        costs.append(c)
        comps.append(k)
    return float(np.mean(costs)), float(np.mean(comps))


def best_fixed(env, sessions, grid):
    return min((mean_cost(env, sessions, sim.FixedTokens(k))[0], k) for k in grid)


def table(env, sessions, title, grid, quiet=False):
    rows = {}
    for p in [sim.WindowForced(), sim.FixedThreshold(0.95), sim.FixedThreshold(0.92),
              sim.FixedThreshold(0.80), sim.FixedThreshold(0.50),
              sim.BreakEven(), sim.RandomizedBreakEven(),
              sim.PredictiveBreakEven(mean_residual(), lam=0.5, label="hazard")]:
        rows[p.name] = mean_cost(env, sessions, p)
    for noise in (0.0, 0.5):
        o = LengthOracle(noise)
        p = sim.PredictiveBreakEven(o, lam=0.3, label=f"length oracle, noise={noise}")
        rows[p.name] = mean_cost(env, sessions, p, oracle=o)
    bf_cost, bf_k = best_fixed(env, sessions, grid)
    rows[f"best fixed in hindsight ({int(bf_k / 1000)}k)"] = (bf_cost, np.nan)
    rows["hindsight optimum (offline)"] = (float(np.mean([sim.hindsight_optimum(env, g) for g in sessions])), np.nan)
    if quiet:
        return rows
    base, opt = rows["fixed 92% of window"][0], rows["hindsight optimum (offline)"][0]
    print(f"\n## {title}")
    print(f"{'policy':44s} {'cost/session':>12s} {'vs fixed-92%':>12s} {'gap to opt':>10s} {'#compact':>8s}")
    for name, (c, k) in sorted(rows.items(), key=lambda kv: kv[1][0]):
        ks = "" if np.isnan(k) else f"{k:.2f}"
        print(f"{name:44s} {c / 1e6:11.3f}M {100 * (c / base - 1):+11.1f}% {100 * (c / opt - 1):+9.1f}% {ks:>8s}")
    return rows


GRID = [10_000, 20_000, 30_000, 45_000, 60_000, 80_000, 100_000, 130_000, 160_000]
BIG = [*GRID, 250_000, 400_000, 600_000, 900_000]
BASE = sim.Env(system=40_000, out_per_call=1_200)

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    print(f"traces: {len(SEQS)} sessions, {len(POOL)} increments, mean {POOL.mean():.0f} tok/call; "
          f"T ~ lognormal(mu={MU:.2f}, sd={SD:.2f}), median {np.exp(MU):.0f} calls")
    sessions = synth_sessions(n)
    table(BASE.with_(prices=sim.UNCACHED), sessions, "200k window, NO prompt caching", GRID)
    table(BASE, sessions, "200k window, prompt caching (0.1x read / 1.25x write)", GRID)
    table(BASE.with_(window=1_000_000, prices=sim.UNCACHED), sessions, "1M window, NO caching", BIG)
    table(BASE.with_(window=1_000_000), sessions, "1M window, prompt caching", BIG)
    table(BASE, SEQS, f"real-trace replay ({len(SEQS)} sessions), cached, 200k", GRID)
    table(BASE.with_(window=1_000_000), SEQS, f"real-trace replay ({len(SEQS)} sessions), cached, 1M", BIG)
