"""Summarize the high-growth real-session grid: paired cost differences, quality, and fidelity.

Pairs are runs on the same ordering (h1-h5) under different arms. Reports the mean paired %
difference with a bootstrap 95% CI and an exact one-sided sign test, then the simulator's
prediction error on every run (same predict() as fidelity.py)."""
import json
import sys
from math import comb
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fidelity import predict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HG = ROOT / "results" / "highgrowth"
BOOT = 10_000
COMPARISONS = [("eoq", "auto"), ("150k", "auto"), ("eoq", "150k")]
QUALITY = ["n_fixed", "recall_expression", "recall_function", "c1_untagged_lines", "c2_new_files",
           "c5_rule5_violations", "audit_linecount_ok", "audit_lastdef_ok", "compactions", "peak_context", "calls"]


def rows():
    out = [json.loads(l) for l in (HG / "ledger.jsonl").read_text().splitlines() if l.strip()]
    return [r for r in out if "-cal" not in r["tag"] and r.get("cost_usd") and r["status"] == 0]


def sign_test(diffs):
    """One-sided exact sign test that the first arm is cheaper (ties dropped)."""
    neg, n = sum(d < 0 for d in diffs), sum(d != 0 for d in diffs)
    return sum(comb(n, k) for k in range(neg, n + 1)) / 2 ** n if n else 1.0


def paired(by, a, b, rng):
    keys = sorted(set(by[a]) & set(by[b]))
    diffs = np.array([by[a][k]["cost_usd"] / by[b][k]["cost_usd"] - 1 for k in keys])
    if not len(diffs):
        return None
    boot = [rng.choice(diffs, len(diffs)).mean() for _ in range(BOOT)]
    return {"n": len(diffs), "mean": diffs.mean(), "ci": np.percentile(boot, [2.5, 97.5]), "p": sign_test(diffs),
            "each": diffs}


def main():
    rs, rng = rows(), np.random.default_rng(0)
    by = {}
    for r in rs:
        by.setdefault(r["arm"], {})[r["variant"]] = r
    print(f"{len(rs)} runs, total ${sum(r['cost_usd'] for r in rs):.2f}\n")
    print(f"{'arm':6s} {'n':>2s} {'mean $':>7s} " + " ".join(f"{q[:12]:>12s}" for q in QUALITY))
    for arm, runs in by.items():
        vals = list(runs.values())
        print(f"{arm:6s} {len(vals):2d} {np.mean([r['cost_usd'] for r in vals]):7.3f} "
              + " ".join(f"{np.mean([r.get(q) or 0 for r in vals]):12.1f}" for q in QUALITY))
    print()
    for a, b in COMPARISONS:
        if a in by and b in by and (res := paired(by, a, b, rng)):
            print(f"{a} vs {b}: {100 * res['mean']:+.1f}% (95% CI {100 * res['ci'][0]:+.1f} to "
                  f"{100 * res['ci'][1]:+.1f}), sign-test p={res['p']:.3f}, n={res['n']}, "
                  f"each {' '.join(f'{100 * d:+.0f}%' for d in res['each'])}")
    errs = []
    for r in rs:
        pred, _ = predict(HG / f"{r['tag']}.jsonl")
        errs.append(pred / r["cost_usd"] - 1)
    print(f"\nsimulator fidelity: mean abs error {100 * np.mean(np.abs(errs)):.1f}% over {len(errs)} runs")
    complete = sorted(set.intersection(*(set(by[a]) for a in ("auto", "eoq", "150k"))))
    breakdown = {a: bill_breakdown([by[a][v] for v in complete]) for a in ("auto", "eoq", "150k")}
    print(f"\nbill breakdown, mean $ per run over {', '.join(complete)} (CLI modelUsage totals):")
    for a, parts in breakdown.items():
        print(f"  {a:5s} " + "  ".join(f"{k} ${x:.2f}" for k, x in parts.items()))
    print("\ncounterfactual policies on each auto run's real growth (simulated % vs auto):")
    cf = {v: counterfactual(by["auto"][v]) for v in complete}
    for v, res in cf.items():
        print(f"  {v}: " + "  ".join(f"{k} {100 * x:+.1f}%" for k, x in res.items()))
    table(by, complete, breakdown, cf)


# The CLI's per-message stream usage under-reports output ~5x; modelUsage on the final result is exact.
PRICE_PER_TOKEN = {"cacheReadInputTokens": 0.05 * 2e-6, "cacheCreationInputTokens": 2 * 2e-6,
                   "outputTokens": 10e-6, "inputTokens": 2e-6}
PART_NAMES = {"cacheReadInputTokens": "read", "cacheCreationInputTokens": "write", "outputTokens": "output",
              "inputTokens": "input"}
LATE_FRACTION = 0.4  # share of growth arriving in the last 40% of calls


def model_usage(tag):
    last = None
    for line in (HG / f"{tag}.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r.get("type") == "result" and r.get("modelUsage"):
            last = r["modelUsage"]
    return next(iter(last.values()))


def bill_breakdown(runs):
    parts = {}
    for r in runs:
        u = model_usage(r["tag"])
        for k, name in PART_NAMES.items():
            parts[name] = parts.get(name, 0.0) + u[k] * PRICE_PER_TOKEN[k] / len(runs)
    return parts


def counterfactual(auto_row):
    """Re-run the auto session's real per-call growth under each policy in the cost model."""
    from contextpilot import sim
    from fidelity import calls_of
    ctx, _, _ = calls_of(HG / f"{auto_row['tag']}.jsonl")
    g = np.clip(np.diff(ctx, prepend=ctx[0]), 0, None)
    out_per_call = model_usage(auto_row["tag"])["outputTokens"] / len(ctx)
    env = sim.Env(system=int(ctx[0]), out_per_call=int(out_per_call), prices=sim.CLAUDE_CODE, window=1_000_000,
                  sigma_frac=0.0, sigma_min=11_000, sigma_max=11_000)
    base, _ = sim.run(env, g, sim.WindowForced())
    res = {name: sim.run(env, g, pol)[0] / base - 1 for name, pol in
           [("eoq", sim.ClosedForm()), ("150k", sim.FixedContext(150_000)), ("break-even", sim.BreakEven())]}
    res["best fixed"] = min(sim.run(env, g, sim.FixedTokens(int(h)))[0] for h in np.linspace(40e3, 400e3, 73)) / base - 1
    late = g[int((1 - LATE_FRACTION) * len(g)):].sum() / g.sum()
    return {**res, "late growth share": late}


def table(by, complete, breakdown, cf):
    lines = [r"\begin{tabular}{lrrrrrrr}", r"\toprule",
             r"Arm & Cost (\$) & vs.\ auto & Read & Write & Output & Compactions & Recall /20\\", r"\midrule"]
    for a in ("auto", "150k", "eoq"):
        runs = [by[a][v] for v in complete]
        cost = np.mean([r["cost_usd"] for r in runs])
        rel = "---" if a == "auto" else f"${100 * np.mean([by[a][v]['cost_usd'] / by['auto'][v]['cost_usd'] - 1 for v in complete]):+.1f}\\%$"
        b = breakdown[a]
        lines.append(f"{a} & {cost:.2f} & {rel} & {b['read']:.2f} & {b['write']:.2f} & {b['output']:.2f} & "
                     f"{np.mean([r['compactions'] for r in runs]):.1f} & {np.mean([r['recall_expression'] for r in runs]):.1f}\\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (ROOT / "paper" / "table_highgrowth.tex").write_text("\n".join(lines) + "\n")
    (HG / "summary.json").write_text(json.dumps({"orderings": complete, "breakdown": breakdown, "counterfactual": cf},
                                                indent=1))


if __name__ == "__main__":
    main()
