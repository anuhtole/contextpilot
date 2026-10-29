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
    return [r for r in out if "-cal" not in r["tag"] and r.get("cost_usd")]


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


if __name__ == "__main__":
    main()
