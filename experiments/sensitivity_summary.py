"""Savings of the online steady-state rule vs product triggers as summary size and re-fetch vary."""
import numpy as np

from main_tables import sim, synth_sessions, mean_cost, BASE

S = synth_sessions(250, seed=51)

if __name__ == "__main__":
    print("Claude Code prices; cost change of the online rule vs each product trigger (negative = cheaper)")
    print(f"{'summary':>8s} {'rho':>5s} {'H* @3.6k':>9s} | {'vs 92%, 200k':>12s} {'vs 92%, 1M':>11s} {'vs 150k ctx':>11s}")
    for sigma in (2_000, 5_000, 11_000, 20_000):
        for rho in (0.0, 0.1, 0.3):
            env = BASE.with_(prices=sim.CLAUDE_CODE, sigma_min=sigma, sigma_max=sigma, rho=rho)
            h_star = sim.eoq_history(env, float(np.mean(np.concatenate(S))))
            out = []
            for W, base in ((200_000, sim.FixedThreshold(0.92)), (1_000_000, sim.FixedThreshold(0.92)),
                            (1_000_000, sim.FixedContext(150_000))):
                e = env.with_(window=W)
                out.append(mean_cost(e, S, sim.ClosedForm())[0] / mean_cost(e, S, base)[0] - 1)
            print(f"{sigma / 1e3:7.0f}k {rho:5.1f} {h_star / 1e3:8.0f}k | "
                  + " ".join(f"{100 * x:+11.1f}%" for x in out), flush=True)
