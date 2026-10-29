"""Stress-test ratios: cost / offline optimum over randomly drawn hard sessions.

Sessions mix steady, bursty (heavy-tailed) and regime-switching growth, and every
prefix is evaluated, so a session may end right after a compaction. The sessions are
random draws from these families, not constructed against any particular policy.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextpilot import sim  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def adversarial_sessions(n, rng):
    for i in range(n):
        T = int(rng.integers(30, 160))
        kind = i % 3
        if kind == 0:
            g = np.full(T, float(rng.choice([500, 2_000, 4_000, 8_000])))
        elif kind == 1:
            g = rng.pareto(1.5, T) * 1_500 + 200
        else:
            switch = int(rng.integers(5, T - 5))
            g = np.concatenate([np.full(switch, 300.0), np.full(T - switch, 9_000.0)])
        yield np.minimum(g, 60_000.0)


def ratios(env, policies, sessions, stride=5):
    worst = {p.name: [] for p in policies}
    for g in sessions:
        for T in range(stride, len(g) + 1, stride):
            prefix = g[:T]
            opt = sim.hindsight_optimum(env, prefix, beam=8)
            for p in policies:
                worst[p.name].append(sim.run(env, prefix, p)[0] / opt)
    return {k: {"max": float(np.max(v)), "p99": float(np.percentile(v, 99)), "mean": float(np.mean(v))}
            for k, v in worst.items()}


if __name__ == "__main__":
    out = {}
    for W in (200_000, 1_000_000):
        env = sim.Env(system=30_000, out_per_call=1_000, window=W, prices=sim.CLAUDE_CODE)
        lindy = sim.empirical_residual([])  # no length data: Lindy fallback everywhere
        pols = [sim.BreakEven(), sim.ClosedForm(), sim.RandomizedBreakEven(), sim.ClosedFormRecent(10),
                sim.HorizonGated(sim.ClosedFormRecent(10), lindy, lam=0.5, label="Lindy"),
                sim.FixedThreshold(0.92), sim.FixedTokens(30_000), sim.FixedTokens(80_000)]
        res = ratios(env, pols, list(adversarial_sessions(150, np.random.default_rng(5))))
        out[f"{W // 1000}k"] = res
        print(f"\nwindow {W // 1000}k, Claude Code prices: cost / offline optimum over all prefixes")
        for name, r in sorted(res.items(), key=lambda kv: kv[1]["max"]):
            print(f"  {name:34s} max {r['max']:.3f}   p99 {r['p99']:.3f}   mean {r['mean']:.3f}", flush=True)
    (ROOT / "results" / "worst_case.json").write_text(json.dumps(out, indent=1))
