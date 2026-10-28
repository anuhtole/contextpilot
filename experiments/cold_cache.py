"""Value of the cold-cache rule: compact when an idle gap has expired the prompt cache.

Idle gaps are Bernoulli per call at the rate measured in local Claude Code sessions
(1.5% of inter-call gaps exceed the 1-hour TTL; 3.5% exceed 5 minutes).
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextpilot import sim  # noqa: E402
from main_tables import synth_sessions  # noqa: E402

COLD_RATE = {"1h TTL": 0.015, "5m TTL": 0.035}


def mean_cost(env, sessions, colds, policy):
    return float(np.mean([sim.run(env, g, policy, cold=c)[0] for g, c in zip(sessions, colds)]))


if __name__ == "__main__":
    sessions = synth_sessions(400, seed=41)
    for ttl, prices in (("1h TTL", sim.CLAUDE_CODE), ("5m TTL", sim.CACHED_55)):
        rng = np.random.default_rng(9)
        colds = [rng.random(len(g)) < COLD_RATE[ttl] for g in sessions]
        for W in (200_000, 1_000_000):
            env = sim.Env(system=40_000, out_per_call=1_200, window=W, prices=prices)
            base = mean_cost(env, sessions, colds, sim.FixedThreshold(0.92))
            print(f"\n{ttl}, {prices.name}, {W // 1000}k window (vs fixed 92% without the rule)")
            for inner in (sim.FixedThreshold(0.92), sim.BreakEven(), sim.ClosedForm()):
                plain = mean_cost(env, sessions, colds, inner)
                aware = mean_cost(env, sessions, colds, sim.ColdAware(inner))
                print(f"  {inner.name:30s} {100 * (plain / base - 1):+6.1f}%  -> with cold-cache rule "
                      f"{100 * (aware / base - 1):+6.1f}%", flush=True)
