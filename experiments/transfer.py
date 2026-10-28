"""Robustness: a threshold tuned once (at the cached 0.1x optimum) vs adaptive rules, across regimes."""
import numpy as np
from main_tables import sim, synth_sessions, mean_cost, BASE
S = synth_sessions(300, seed=21)
regimes = {
    "cached 0.1x (tuning regime)": BASE,
    "cached 0.05x (newer models)": BASE.with_(prices=sim.CACHED_55),
    "Claude Code prices": BASE.with_(prices=sim.CLAUDE_CODE),
    "re-fetch rho=0.3": BASE.with_(rho=0.3),
    "quality penalty 200k/compaction": BASE.with_(penalty=200_000),
    "no caching": BASE.with_(prices=sim.UNCACHED),
}
for W in (200_000, 1_000_000):
    print(f"\nwindow {W//1000}k: excess cost vs best-of-row (lower is better)")
    for name, env in regimes.items():
        env = env.with_(window=W)
        c = {"fixed 83k (tuned once)": mean_cost(env, S, sim.FixedTokens(83_000))[0],
             "fixed 92%": mean_cost(env, S, sim.FixedThreshold(0.92))[0],
             "break-even": mean_cost(env, S, sim.BreakEven())[0],
             "online steady-state": mean_cost(env, S, sim.ClosedForm())[0]}
        best = min(mean_cost(env, S, sim.FixedTokens(int(k)))[0] for k in np.geomspace(5_000, 900_000, 30))
        print(f"  {name:34s} " + "  ".join(f"{k}: {100*(v/best-1):+5.1f}%" for k, v in c.items()))
