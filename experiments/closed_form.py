"""Does the closed-form EOQ rule predict the best fixed threshold across datasets and prices?

For each dataset x price regime x window: cost of each policy relative to the
fixed 92%-of-window trigger, the best fixed threshold found by grid search in
hindsight, and the closed-form point H* = s + sqrt(2 g A / h) from mean growth.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextpilot import sim  # noqa: E402
from main_tables import SEQS, synth_sessions  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REGIMES = [sim.UNCACHED, sim.CACHED, sim.CACHED_55, sim.CLAUDE_CODE]
GRID = np.unique(np.geomspace(1_000, 1_500_000, 48).astype(int))   # independent of H*


def swe_agent(n, seed=0):
    rows = json.loads((ROOT / "data" / "swe_agent_traces.json").read_text())
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(rows), size=min(n, len(rows)), replace=False)
    sel = [rows[i] for i in pick]
    out = float(np.mean([np.mean(r["out"]) for r in sel]))
    system = float(np.median([r["system"] for r in sel]))
    return [np.array(r["g"], dtype=float) for r in sel], system, out


def mean_cost(env, sessions, policy):
    return float(np.mean([sim.run(env, g, policy)[0] for g in sessions]))


def evaluate(env, sessions, label):
    g_mean = float(np.mean(np.concatenate([s[1:] for s in sessions])))
    h_eoq = sim.eoq_history(env, g_mean)
    h_star = sim.steady_state_optimum(env, g_mean)
    base = mean_cost(env, sessions, sim.FixedThreshold(0.92))
    grid = [(mean_cost(env, sessions, sim.FixedTokens(int(k))), int(k)) for k in GRID]
    best_cost, best_k = min(grid)
    online = mean_cost(env, sessions, sim.ClosedForm())
    row = {
        "setting": label, "g_mean": round(g_mean), "eoq_formula_H": round(h_eoq), "closed_form_H": round(h_star), "best_fixed_H": best_k,
        "break_even": mean_cost(env, sessions, sim.BreakEven()) / base - 1,
        "closed_form_online": online / base - 1,
        "online_vs_best": online / best_cost - 1,
        "api_default_150k": mean_cost(env, sessions, sim.FixedContext(150_000)) / base - 1,
        "window_70pct": mean_cost(env, sessions, sim.FixedThreshold(0.70)) / base - 1,
        "best_fixed": best_cost / base - 1,
        "optimum": float(np.mean([sim.hindsight_optimum(env, g) for g in sessions])) / base - 1,
    }
    print(f"{label:58s} g={row['g_mean']:5d}  EOQ={h_eoq / 1e3:6.1f}k  H*={row['closed_form_H'] / 1e3:6.1f}k  best={best_k / 1e3:6.1f}k  "
          f"online vs best {100 * row['online_vs_best']:+5.1f}%  | vs fixed-92%: "
          f"BE {100 * row['break_even']:+6.1f}%  online {100 * row['closed_form_online']:+6.1f}%  "
          f"150k {100 * row['api_default_150k']:+6.1f}%  70%W {100 * row['window_70pct']:+6.1f}%  "
          f"best {100 * row['best_fixed']:+6.1f}%  opt {100 * row['optimum']:+6.1f}%", flush=True)
    return row


if __name__ == "__main__":
    rows = []
    local = synth_sessions(300, seed=31)
    local_env = sim.Env(system=40_000, out_per_call=1_200)
    swe, swe_system, swe_out = swe_agent(1_500)
    # SWE-agent contexts peak near 10k, so its summaries are assumed 2k (not Claude Code's 11k)
    swe_env = sim.Env(system=int(swe_system), out_per_call=int(swe_out), sigma_min=2_000, sigma_max=2_000)
    for W in (200_000, 1_000_000):
        for pr in REGIMES:
            rows.append(evaluate(local_env.with_(window=W, prices=pr), local, f"Claude Code traces | {pr.name} | {W // 1000}k"))
    for W in (32_000, 128_000):
        for pr in REGIMES:
            rows.append(evaluate(swe_env.with_(window=W, prices=pr), swe, f"SWE-agent (n=1500) | {pr.name} | {W // 1000}k"))
    rows.append(evaluate(local_env.with_(window=1_000_000, prices=sim.CLAUDE_CODE), SEQS,
                         f"real-trace replay ({len(SEQS)}) | Claude Code prices | 1000k"))
    (ROOT / "results" / "closed_form.json").write_text(json.dumps(rows, indent=1))
