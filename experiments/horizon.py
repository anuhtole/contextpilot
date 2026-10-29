"""Horizon-aware compaction vs the steady-state rule, break-even and product triggers, in simulation.

Every horizon predictor is fit out of sample:
  - real Claude Code replay (25 sessions): leave-one-out over the other sessions' lengths;
  - synthetic and SWE-agent sessions: lengths from a disjoint training draw;
  - the high-growth real runs: lengths of the 25 local sessions only (a transfer test).
"oracle" knows the true remaining length and bounds the value of horizon information.
Costs are reported relative to a fixed 92%-of-window trigger, as in the paper's Table 1.
Stress-test ratios for these rules are in worst_case.py, on the same sessions as the other policies."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from contextpilot import sim  # noqa: E402
from closed_form import GRID, swe_agent  # noqa: E402
from fidelity import calls_of  # noqa: E402
from main_tables import SEQS, synth_sessions  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HG = ROOT / "results" / "highgrowth"
HG_ORDERINGS = ["h1", "h2", "h3", "h5"]
LAM = 0.5
HALF_LIFE = 10
LOCAL_ENV = sim.Env(system=40_000, out_per_call=1_200, prices=sim.CLAUDE_CODE)
SWE_ENV_SIGMA = 2_000  # SWE-agent contexts peak near 10k, so summaries are assumed 2k (as in closed_form.py)


def policies(train_lengths, T):
    """Fresh policies for one session; train_lengths excludes that session."""
    emp = sim.empirical_residual(train_lengths)
    def oracle(t):
        return max(T - t - 1, 0)
    return {
        "150k context": sim.FixedContext(150_000),
        "break-even": sim.BreakEven(),
        "learned ski rental (hazard)": sim.PredictiveBreakEven(emp, lam=LAM, label="empirical"),
        "steady-state": sim.ClosedForm(),
        "steady-state, recent g": sim.ClosedFormRecent(HALF_LIFE),
        "horizon-gated": sim.HorizonGated(sim.ClosedForm(), emp, lam=LAM, label="empirical"),
        "horizon-gated, recent g": sim.HorizonGated(sim.ClosedFormRecent(HALF_LIFE), emp, lam=LAM, label="empirical"),
        "horizon-gated, recent g, oracle": sim.HorizonGated(sim.ClosedFormRecent(HALF_LIFE), oracle, lam=LAM, label="oracle"),
    }


def evaluate(env, sessions, train_for, label, with_optimum=False):
    """train_for(i) gives the training lengths for session i."""
    base = np.array([sim.run(env, g, sim.FixedThreshold(0.92))[0] for g in sessions])
    costs, comps = {}, {}
    for i, g in enumerate(sessions):
        for name, pol in policies(train_for(i), len(g)).items():
            c, k = sim.run(env, g, pol)
            costs.setdefault(name, []).append(c)
            comps.setdefault(name, []).append(k)
    best = min(np.sum([sim.run(env, g, sim.FixedTokens(int(h)))[0] for g in sessions]) for h in GRID)
    row = {"setting": label, "n": len(sessions), "base": float(base.sum()),
           "policies": {n: {"vs_92": float(np.sum(c) / base.sum() - 1), "vs_best_fixed": float(np.sum(c) / best - 1),
                            "compactions": float(np.mean(comps[n]))} for n, c in costs.items()},
           "best_fixed_vs_92": float(best / base.sum() - 1)}
    if with_optimum:
        opt = float(np.sum([sim.hindsight_optimum(env, g) for g in sessions]))
        row["optimum_vs_92"] = opt / base.sum() - 1
        for n, c in costs.items():
            row["policies"][n]["vs_optimum"] = float(np.sum(c) / opt - 1)
    print_row(row)
    return row


def print_row(row):
    opt = f"  optimum {100 * row['optimum_vs_92']:+.1f}%" if "optimum_vs_92" in row else ""
    print(f"\n## {row['setting']} (n={row['n']}): best fixed {100 * row['best_fixed_vs_92']:+.1f}% vs 92%{opt}")
    for name, p in sorted(row["policies"].items(), key=lambda kv: kv[1]["vs_92"]):
        o = f"  vs opt {100 * p['vs_optimum']:+5.1f}%" if "vs_optimum" in p else ""
        print(f"  {name:34s} vs 92% {100 * p['vs_92']:+6.1f}%  vs best fixed {100 * p['vs_best_fixed']:+5.1f}%{o}"
              f"  compactions {p['compactions']:.2f}", flush=True)


def high_growth_sessions():
    """Real per-call growth of the uncompacted (auto) high-growth runs."""
    out = []
    for v in HG_ORDERINGS:
        ctx, _, _ = calls_of(HG / f"{v}-auto-r1.jsonl")
        out.append(np.clip(np.diff(ctx, prepend=ctx[0]), 0, None))
    return out


def main():
    out = {"rows": []}
    seq_lengths = [len(q) for q in SEQS]
    loo = lambda i: seq_lengths[:i] + seq_lengths[i + 1:]  # noqa: E731
    for W in (1_000_000, 200_000):
        out["rows"].append(evaluate(LOCAL_ENV.with_(window=W), SEQS, loo,
                                    f"real Claude Code replay, {W // 1000}k, Claude Code prices", with_optimum=True))
    hg = high_growth_sessions()
    hg_env = LOCAL_ENV.with_(system=36_000, out_per_call=520, window=1_000_000)
    out["rows"].append(evaluate(hg_env, hg, lambda i: seq_lengths,
                                "real high-growth runs (auto growth), 1M, Claude Code prices", with_optimum=True))
    synth, train = synth_sessions(300, seed=31), [len(s) for s in synth_sessions(2_000, seed=99)]
    for pr in (sim.CLAUDE_CODE, sim.CACHED, sim.UNCACHED):
        out["rows"].append(evaluate(LOCAL_ENV.with_(window=1_000_000, prices=pr), synth, lambda i: train,
                                    f"synthetic local (300), 1M, {pr.name}"))
    swe, system, out_tok = swe_agent(3_000)
    swe_test, swe_train = swe[:1_500], [len(s) for s in swe[1_500:]]
    swe_env = sim.Env(system=int(system), out_per_call=int(out_tok), sigma_min=SWE_ENV_SIGMA, sigma_max=SWE_ENV_SIGMA,
                      window=128_000, prices=sim.CLAUDE_CODE)
    out["rows"].append(evaluate(swe_env, swe_test, lambda i: swe_train, "SWE-agent (1500), 128k, Claude Code prices"))
    (ROOT / "results" / "horizon.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
