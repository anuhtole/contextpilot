"""Robustness: a threshold tuned in one regime vs break-even, evaluated across regimes."""
from main_tables import sim, synth_sessions, mean_cost, BASE
S = synth_sessions(300, seed=21)
regimes = {
    "cached 0.1x (tuning regime)": BASE,
    "cached 0.05x (newer models)": BASE.with_(prices=sim.CACHED_55),
    "lossy summaries rho=0.5": BASE.with_(rho=0.5),
    "quality penalty 200k/compaction": BASE.with_(penalty=200_000),
    "no caching": BASE.with_(prices=sim.UNCACHED),
}
for W in (200_000, 1_000_000):
    print(f"\nwindow {W//1000}k: excess cost vs best-of-row (lower is better)")
    for name, env in regimes.items():
        env = env.with_(window=W)
        c = {"fixed 30k (tuned once)": mean_cost(env, S, sim.FixedTokens(30_000))[0],
             "fixed 92%": mean_cost(env, S, sim.FixedThreshold(0.92))[0],
             "break-even": mean_cost(env, S, sim.BreakEven())[0]}
        best = min(mean_cost(env, S, sim.FixedTokens(k))[0] for k in (20_000,30_000,45_000,60_000,100_000,160_000,250_000))
        print(f"  {name:34s} " + "  ".join(f"{k}: {100*(v/best-1):+5.1f}%" for k, v in c.items()))
