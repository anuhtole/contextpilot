"""Summarize the high-growth real-session grid: paired cost differences, quality, and fidelity.

Pairs are runs on the same ordering (h1-h5) under different arms. Reports the mean paired %
difference with a paired-t 95% CI and an exact two-sided sign-flip permutation p, then the simulator's
prediction error on every run (same predict() as fidelity.py)."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fidelity import predict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HG = ROOT / "results" / "highgrowth"
COMPARISONS = [("eoq", "auto"), ("150k", "auto"), ("eoq", "150k")]
QUALITY = ["n_fixed", "recall_expression", "recall_function", "c1_untagged_lines", "c2_new_files",
           "c5_rule5_violations", "audit_linecount_ok", "audit_lastdef_ok", "compactions", "peak_context", "calls"]


def rows():
    out = [json.loads(l) for l in (HG / "ledger.jsonl").read_text().splitlines() if l.strip()]
    return [r for r in out if "-cal" not in r["tag"] and r.get("cost_usd") and r["status"] == 0]


T_975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571}  # two-sided 95% Student t quantiles


def sign_flip_p(diffs):
    """Exact two-sided paired permutation test: share of the 2^n sign flips whose mean is at
    least as extreme as the observed one. With n = 4 the smallest attainable p is 0.125."""
    d = np.asarray(diffs)
    flips = np.array(np.meshgrid(*[[-1, 1]] * len(d))).reshape(len(d), -1).T
    return float(np.mean(np.abs((flips * d).mean(axis=1)) >= abs(d.mean()) - 1e-12))


def t_interval(diffs):
    d = np.asarray(diffs)
    half = T_975[len(d) - 1] * d.std(ddof=1) / np.sqrt(len(d))
    return d.mean() - half, d.mean() + half


def paired(by, a, b):
    keys = sorted(set(by[a]) & set(by[b]))
    diffs = np.array([by[a][k]["cost_usd"] / by[b][k]["cost_usd"] - 1 for k in keys])
    if not len(diffs):
        return None
    return {"n": len(diffs), "mean": diffs.mean(), "ci": t_interval(diffs), "p": sign_flip_p(diffs), "each": diffs}


def main():
    rs = rows()
    by = {}
    for r in rs:
        by.setdefault(r["arm"], {})[r["variant"]] = r
    complete = sorted(set.intersection(*(set(by[a]) for a in ("auto", "eoq", "150k"))))
    unpaired = [r["tag"] for r in rs if r["variant"] not in complete]
    by = {a: {v: r for v, r in runs.items() if v in complete} for a, runs in by.items()}
    print(f"{len(rs)} completed runs; paired orderings {', '.join(complete)}; unpaired (excluded): {', '.join(unpaired)}\n")
    print(f"{'arm':6s} {'n':>2s} {'mean $':>7s} " + " ".join(f"{q[:12]:>12s}" for q in QUALITY))
    for arm, runs in by.items():
        vals = list(runs.values())
        print(f"{arm:6s} {len(vals):2d} {np.mean([r['cost_usd'] for r in vals]):7.3f} "
              + " ".join(f"{np.mean([r.get(q) or 0 for r in vals]):12.1f}" for q in QUALITY))
    print()
    for a, b in COMPARISONS:
        if a in by and b in by and (res := paired(by, a, b)):
            print(f"{a} vs {b}: {100 * res['mean']:+.1f}% (paired t 95% CI {100 * res['ci'][0]:+.1f} to "
                  f"{100 * res['ci'][1]:+.1f}), exact two-sided permutation p={res['p']:.3f}, n={res['n']}, "
                  f"each {' '.join(f'{100 * d:+.0f}%' for d in res['each'])}")
    paired_runs = [r for runs in by.values() for r in runs.values()]
    errs = [predict(HG / f"{r['tag']}.jsonl")[0] / r["cost_usd"] - 1 for r in paired_runs]
    print(f"\nsimulator fidelity: mean abs error {100 * np.mean(np.abs(errs)):.1f}% over the {len(errs)} paired runs")
    for r in rs:
        if r["variant"] not in complete:
            e = predict(HG / f"{r['tag']}.jsonl")[0] / r["cost_usd"] - 1
            print(f"  unpaired {r['tag']}: {100 * e:+.1f}% (ran under heavy throttling)")
    breakdown = {a: bill_breakdown([by[a][v] for v in complete]) for a in ("auto", "eoq", "150k")}
    print(f"\nbill breakdown, mean $ per run over {', '.join(complete)} (CLI modelUsage totals):")
    for a, parts in breakdown.items():
        total = sum(x for k, x in parts.items() if k != "history rent")
        print(f"  {a:5s} " + "  ".join(f"{k} ${x:.2f}" for k, x in parts.items())
              + f"  | history rent ${parts['history rent']:.2f} = {100 * parts['history rent'] / total:.0f}% of bill"
                if "history rent" in parts else "")
    print("\ncounterfactual policies on each auto run's real growth (simulated % vs auto):")
    cf = {v: counterfactual(by["auto"][v]) for v in complete}
    for v, res in cf.items():
        print(f"  {v}: " + "  ".join(f"{k} {100 * x:+.1f}%" for k, x in res.items()))
    print("\nper ordering, predicted (replay of auto growth) vs observed paired difference vs auto:")
    for arm, key in (("eoq", "eoq (live rule)"), ("150k", "150k")):
        obs = [by[arm][v]["cost_usd"] / by["auto"][v]["cost_usd"] - 1 for v in complete]
        pred = [cf[v][key] for v in complete]
        print(f"  {arm:5s} " + "  ".join(f"{v} {100 * p:+.1f}/{100 * o:+.1f}" for v, p, o in zip(complete, pred, obs))
              + f"  | mean {100 * np.mean(pred):+.1f}/{100 * np.mean(obs):+.1f}")
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
    """Mean $ per run by token type; 'history rent' is cache-read spend net of reading the static prefix."""
    from fidelity import calls_of
    parts = {}
    for r in runs:
        u = model_usage(r["tag"])
        for k, name in PART_NAMES.items():
            parts[name] = parts.get(name, 0.0) + u[k] * PRICE_PER_TOKEN[k] / len(runs)
        ctx, _, _ = calls_of(HG / f"{r['tag']}.jsonl")
        prefix_reads = ctx[0] * len(ctx) * PRICE_PER_TOKEN["cacheReadInputTokens"]
        parts["history rent"] = parts.get("history rent", 0.0) + (
            u["cacheReadInputTokens"] * PRICE_PER_TOKEN["cacheReadInputTokens"] - prefix_reads) / len(runs)
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
    # The live eoq arm chose its compaction points with the pre-correction model (all of sigma billed
    # as output, no prefix rewrite), so the live arm is replayed with those decisions.
    live_eoq = DecideWith(sim.ClosedForm(), env.with_(summary_out=None, prefix_rewrite=0.0))
    res = {name: sim.run(env, g, pol)[0] / base - 1 for name, pol in
           [("eoq (live rule)", live_eoq), ("eoq (corrected model)", sim.ClosedForm()),
            ("150k", sim.FixedContext(150_000)), ("break-even", sim.BreakEven())]}
    res["best fixed"] = min(sim.run(env, g, sim.FixedTokens(int(h)))[0] for h in np.linspace(40e3, 400e3, 73)) / base - 1
    late = g[int((1 - LATE_FRACTION) * len(g)):].sum() / g.sum()
    return {**res, "late growth share": late}


class DecideWith:
    """Wraps a policy so its decisions use a different cost model than the one being billed."""
    def __init__(self, inner, decide_env):
        self.inner, self.decide_env, self.name = inner, decide_env, inner.name
    def reset(self, env): return self.inner.reset(self.decide_env)
    def on_compact(self, env, s): return self.inner.on_compact(self.decide_env, s)
    def observe(self, env, s, t, h, g=0.0): return self.inner.observe(self.decide_env, s, t, h, g)
    def compact_when_cold(self, env, h): return False
    def should_compact(self, env, s, t, h, g): return self.inner.should_compact(self.decide_env, s, t, h, g)


def table(by, complete, breakdown, cf):
    lines = [r"\begin{tabular}{lrrrrrrr}", r"\toprule",
             r"Arm & Cost (\$) & vs.\ auto & Reads (history) & Writes & Output & Compactions & Recall /20\\", r"\midrule"]
    for a in ("auto", "150k", "eoq"):
        runs = [by[a][v] for v in complete]
        cost = np.mean([r["cost_usd"] for r in runs])
        rel = "---" if a == "auto" else f"${100 * np.mean([by[a][v]['cost_usd'] / by['auto'][v]['cost_usd'] - 1 for v in complete]):+.1f}\\%$"
        b = breakdown[a]
        lines.append(f"{a} & {cost:.2f} & {rel} & {b['read']:.2f} ({b['history rent']:.2f}) & {b['write']:.2f} & {b['output']:.2f} & "
                     f"{np.mean([r['compactions'] for r in runs]):.1f} & {np.mean([r['recall_expression'] for r in runs]):.1f}\\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (ROOT / "paper" / "table_highgrowth.tex").write_text("\n".join(lines) + "\n")
    (HG / "summary.json").write_text(json.dumps({"orderings": complete, "breakdown": breakdown, "counterfactual": cf},
                                                indent=1))


if __name__ == "__main__":
    main()
