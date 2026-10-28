"""Sensitivity of savings (vs fixed 92% of window) to cache price, recovery, and quality penalty."""
import numpy as np
from main_tables import sim, synth_sessions, mean_cost, best_fixed, mean_residual, BASE, GRID, BIG

S = synth_sessions(400, seed=11)
HZ = mean_residual()

def row(env, grid, label):
    f92 = mean_cost(env, S, sim.FixedThreshold(0.92))[0]
    be, k_be = mean_cost(env, S, sim.BreakEven())
    pr, _ = mean_cost(env, S, sim.PredictiveBreakEven(HZ, lam=0.5))
    bf, k = best_fixed(env, S, grid)
    opt = np.mean([sim.hindsight_optimum(env, g) for g in S])
    print(f"{label:46s} break-even {100*(be/f92-1):+6.1f}%  +hazard {100*(pr/f92-1):+6.1f}%  best-fixed {100*(bf/f92-1):+6.1f}% (@{k//1000}k)  opt {100*(opt/f92-1):+6.1f}%  compactions {k_be:.1f}")

for W, grid in ((200_000, GRID), (1_000_000, BIG)):
    print(f"\n### window {W//1000}k  (savings vs fixed 92%; negative = cheaper)")
    for pr in (sim.UNCACHED, sim.CACHED, sim.CACHED_55):
        row(BASE.with_(window=W, prices=pr), grid, f"prices={pr.name}")
    for rho in (0.0, 0.3, 0.5):
        row(BASE.with_(window=W, rho=rho), grid, f"cached, re-fetch rho={rho}")
    for pen in (50_000, 200_000, 500_000):
        row(BASE.with_(window=W, penalty=pen), grid, f"cached, quality penalty {pen//1000}k tok/compaction")
    row(BASE.with_(window=W, quality=0.05), grid, "cached, context-rot 0.05/tok/call")
