"""Size the high-growth real-session experiment before spending: predicted $ per run and per arm.

Growth sequences are the pilot's real per-call increments, rescaled to a target mean, so the
lumpiness of real tool output is kept. Costs use the fidelity-checked simulator (7.9% MAE) at
Claude Code prices, then the pilot's measured bias is applied as a correction."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextpilot import sim  # noqa: E402
from fidelity import PILOT, calls_of, USD_PER_INPUT_TOKEN  # noqa: E402

BASE, OUT, SIGMA, WINDOW = 36_000, 700, 11_000, 1_000_000
BIAS_UNCOMPACTED, BIAS_COMPACTED = -0.093, 0.051  # pilot: sim error (pred/actual - 1) by run type
GROWTH = [3_000, 4_000, 6_000]
CALLS = [100, 140]
ORDERINGS = ["v1L", "v2L", "v3L"]
SIM_REPS = 30


def env():
    return sim.Env(system=BASE, out_per_call=OUT, prices=sim.CLAUDE_CODE, window=WINDOW,
                   sigma_frac=0.0, sigma_min=SIGMA, sigma_max=SIGMA, rho=0.0)


def growth_sequences(mean_g, n_calls, reps, seed=0):
    rng = np.random.default_rng(seed)
    pools = [np.clip(np.diff(calls_of(PILOT / f"{o}-auto-r1.jsonl")[0]), 0, None) for o in ORDERINGS]
    return [rng.choice(p, n_calls) * (mean_g / p.mean()) for p in (pools[i % len(pools)] for i in range(reps))]


def arms(e, mean_g):
    h_star = sim.steady_state_optimum(e, mean_g)
    far = int(BASE + 3 * h_star)
    return {
        "auto (1M)": sim.WindowForced(),
        "eoq (online H*)": sim.ClosedForm(),
        "--autocompact 150k": sim.FixedContext(150_000),
        f"fixed {far // 1000}k (3x H*)": sim.FixedContext(far),
    }, h_star


def usd(cost, k):
    first_write = (sim.CLAUDE_CODE.write - sim.CLAUDE_CODE.read) * BASE
    return (cost + first_write) * USD_PER_INPUT_TOKEN / (1 + (BIAS_COMPACTED if k else BIAS_UNCOMPACTED))


def size(e, g, n):
    policies, h_star = arms(e, g)
    seqs = growth_sequences(g, n, SIM_REPS, seed=g + n)
    row = {"g": g, "calls": n, "H_star": h_star, "peak_uncompacted": BASE + g * n, "arms": {}}
    for name, pol in policies.items():
        res = [sim.run(e, s, pol) for s in seqs]
        dollars = np.array([usd(c, k) for c, k in res])
        row["arms"][name] = {"usd_mean": float(dollars.mean()), "usd_sd": float(dollars.std()),
                             "compactions": float(np.mean([k for _, k in res]))}
    return row


def main():
    e, out = env(), []
    for g in GROWTH:
        for n in CALLS:
            row = size(e, g, n)
            auto = row["arms"]["auto (1M)"]["usd_mean"]
            print(f"\ng={g} calls={n}  H*={row['H_star'] / 1e3:.0f}k history  "
                  f"uncompacted peak={row['peak_uncompacted'] / 1e3:.0f}k")
            for name, a in row["arms"].items():
                print(f"  {name:24s} ${a['usd_mean']:5.2f} ± {a['usd_sd']:.2f}  {a['compactions']:4.1f} compactions  "
                      f"{100 * (a['usd_mean'] / auto - 1):+6.1f}% vs auto")
            out.append(row)
    (Path(__file__).resolve().parents[1] / "results" / "highgrowth_sizing.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
