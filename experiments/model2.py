"""Second-model replication on Haiku 5.5 (EVAL_PLAN.md, second-model replication).

Checks the registered predictions against results/model2/: the dose-response slope (from dose.py),
the arm costs under Haiku's long-context price tier, and bill fidelity. Fidelity replays each run's
realized growth and compaction schedule call by call, with the structural terms measured on Sonnet
(11k kept, 5.2k summary output, 8.6k prefix evicted) and Haiku's billed rates: every rate is
multiplied by 5 on calls whose prompt exceeds 100k tokens.
Writes results/model2.txt and results/model2.json.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextpilot import sim  # noqa: E402

import dose  # noqa: E402
import fidelity  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "model2"
ARMS = ["auto", "150k", "100k", "70k"]
USD_PER_INPUT_TOKEN = 0.10e-6    # Haiku 5.5 billed input price at or below the tier
HAIKU = sim.Prices(read=0.1, write=2.0, out=5.0, name="Haiku 5.5 (0.1x read, 1h 2x write)")
TIER_TOKENS, TIER_MULTIPLE = 100_000, 5.0
KEPT, SUMMARY_OUT, PREFIX_REWRITE = 11_000, sim.CLAUDE_CODE_SUMMARY_OUT, sim.CLAUDE_CODE_PREFIX_REWRITE
PREDICTED_USD = {"auto": 1.34, "150k": 0.74, "100k": 0.32, "70k": 0.28}   # registered after calibration
COST_BAND, MIN_SAVING_70K, FIDELITY_BAND = 0.25, 0.70, 0.03
SLOPE_RANGE, SLOPE_EXCLUDED, CLIFF_FACTS, LOW_RECALL, MAX_LOW_RUNS = (-0.5, 0.3), -1.3, 3.0, 5, 3


def multiple(prompt, tiered=True):
    return TIER_MULTIPLE if tiered and prompt > TIER_TOKENS else 1.0


def replay(base, growth, compact_at, out_per_call, prices=HAIKU, tiered=True):
    """Bill in base-input-token units for a session compacted right before the calls in compact_at."""
    at, history, units = set(compact_at), 0.0, 0.0
    for t, g in enumerate(growth):
        if t in at and history > 0:
            units += multiple(base + history, tiered) * (prices.read * (base + history) + prices.out * SUMMARY_OUT)
            history = KEPT
            units += multiple(base + history + g, tiered) * (prices.write - prices.read) * (KEPT + PREFIX_REWRITE)
        units += multiple(base + history + g, tiered) * (
            prices.read * (base + history) + prices.write * g + prices.out * out_per_call)
        history += g
    return units


def growth_of(ctx, compact_at):
    """Per-call growth with compaction drops replaced, as in fidelity.predict."""
    g = np.diff(ctx, prepend=ctx[0])
    for i in compact_at:
        g[i] = max(ctx[i] - ctx[i - 1], 0.0) if ctx[i] > ctx[i - 1] else float(np.median(g[g > 0]))
    return g


def predict(stream, tiered=True):
    ctx, out, compact_at = fidelity.calls_of(stream)
    measured = fidelity.output_tokens(stream)
    out_per_call = (measured[0] - measured[1]) / len(ctx) if measured else out.mean()
    units = replay(ctx[0], growth_of(ctx, compact_at), compact_at, out_per_call, tiered=tiered)
    units += (HAIKU.write - HAIKU.read) * fidelity.first_write(stream)
    return units * USD_PER_INPUT_TOKEN


def share_above_tier(stream):
    ctx, _, _ = fidelity.calls_of(stream)
    return float(np.mean(ctx > TIER_TOKENS))


def kept_tokens(stream):
    """post_tokens of every compaction in the stream."""
    kept = []
    for line in stream.read_text(errors="ignore").splitlines():
        e = json.loads(line)
        if e.get("type") == "system" and e.get("subtype") == "compact_boundary":
            kept.append(e.get("compact_metadata", {}).get("post_tokens"))
    return [k for k in kept if k]


def arm_means(rows, key):
    return {a: float(np.mean([r[key] for r in rows if r["arm"] == a])) for a in ARMS}


def step_contrast(rows):
    """Exploratory: per ordering, auto recall minus the mean recall of its compacted arms."""
    by = {}
    for r in rows:
        by.setdefault(r["variant"], []).append(r)
    return {v: float(np.mean([r["recall_expression"] for r in rs if r["arm"] == "auto"])
                     - np.mean([r["recall_expression"] for r in rs if r["arm"] != "auto"]))
            for v, rs in sorted(by.items())}


def main():
    rows = [{**r, "stream": OUT / f"{r['tag']}.jsonl"} for r in dose.load(sources=[OUT])]
    rows = [{**r, "predicted": predict(r["stream"]), "flat": predict(r["stream"], tiered=False),
             "above_tier": share_above_tier(r["stream"])} for r in rows]
    fit = dose.analyze(rows)
    slope, (lo, hi) = fit["slope_facts_per_compaction"], fit["ci95"]
    cost, recall = arm_means(rows, "cost_usd"), arm_means(rows, "recall_expression")
    compacted = [r for r in rows if r["compactions"] > 0]
    low = [r["tag"] for r in compacted if r["recall_expression"] <= LOW_RECALL]
    fid = sum(r["predicted"] for r in rows) / sum(r["cost_usd"] for r in rows) - 1
    fid_arm = {a: sum(r["predicted"] for r in rows if r["arm"] == a) / sum(r["cost_usd"] for r in rows if r["arm"] == a) - 1
               for a in ARMS}
    kept = [k for r in compacted for k in kept_tokens(r["stream"])]
    saving_70k = 1 - cost["70k"] / cost["auto"]
    step = step_contrast(rows)

    checks = {
        "1 slope in range, CI excludes -1.3": SLOPE_RANGE[0] <= slope <= SLOPE_RANGE[1] and lo > SLOPE_EXCLUDED,
        "2 no cliff (70k within 3 facts of auto)": abs(recall["70k"] - recall["auto"]) <= CLIFF_FACTS,
        "3 cost 70k > 100k > 150k (flat-price prediction)": cost["70k"] > cost["100k"] > cost["150k"],
        "3b order auto > 150k > 100k > 70k": cost["auto"] > cost["150k"] > cost["100k"] > cost["70k"],
        "3b each arm within 25% of table": all(abs(cost[a] / PREDICTED_USD[a] - 1) <= COST_BAND for a in ARMS),
        "3c 70k at least 70% below auto": saving_70k >= MIN_SAVING_70K,
        "4 fidelity within 3%": abs(fid) <= FIDELITY_BAND,
        "5 at most 3 compacted runs recall <= 5": len(low) <= MAX_LOW_RUNS,
    }

    lines = [f"Haiku 5.5 replication: {len(rows)} runs, ${sum(r['cost_usd'] for r in rows):.2f}",
             f"slope {slope:+.2f} facts/compaction (95% CI {lo:+.2f} to {hi:+.2f}, p = {fit['perm_p']:.3f})", "",
             f"{'arm':6s} {'comp':>5s} {'recall':>6s} {'$':>6s} {'table $':>8s} {'vs table':>9s} "
             f"{'replay $':>9s} {'fidelity':>9s} {'flat $':>7s} {'>100k':>6s}"]
    for a in ARMS:
        rs = [r for r in rows if r["arm"] == a]
        lines.append(f"{a:6s} {np.mean([r['compactions'] for r in rs]):5.1f} {recall[a]:6.1f} {cost[a]:6.2f} "
                     f"{PREDICTED_USD[a]:8.2f} {100 * (cost[a] / PREDICTED_USD[a] - 1):+8.0f}% "
                     f"{np.mean([r['predicted'] for r in rs]):9.2f} {100 * fid_arm[a]:+8.1f}% "
                     f"{np.mean([r['flat'] for r in rs]):7.2f} {100 * np.mean([r['above_tier'] for r in rs]):5.0f}%")
    lines += ["", f"fidelity, all runs: {100 * fid:+.1f}%",
              f"70k vs auto: {100 * saving_70k:.0f}% cheaper; recall gap {recall['auto'] - recall['70k']:.1f} facts",
              f"kept after compaction: {np.mean(kept) / 1e3:.1f}k (n = {len(kept)})",
              f"compacted runs recalling <= {LOW_RECALL}: {len(low)} of {len(compacted)} {low}",
              "exploratory, auto minus mean of compacted arms, per ordering: "
              + ", ".join(f"{v} {d:+.1f}" for v, d in step.items()) + f" (mean {np.mean(list(step.values())):+.1f})",
              ""] + [f"{'PASS' if ok else 'FAIL'}  {name}" for name, ok in checks.items()]
    text = "\n".join(lines)
    print(text)
    (ROOT / "results" / "model2.txt").write_text(text + "\n")
    (ROOT / "results" / "model2.json").write_text(json.dumps({
        "runs": len(rows), "fit": fit, "cost": cost, "recall": recall, "predicted_usd": PREDICTED_USD,
        "fidelity": fid, "fidelity_by_arm": fid_arm, "saving_70k": saving_70k, "kept_tokens": float(np.mean(kept)),
        "low_recall_runs": low, "step_contrast": step, "checks": {k: bool(v) for k, v in checks.items()},
        "flat_usd": arm_means(rows, "flat"), "replay_usd": arm_means(rows, "predicted"),
        "share_above_tier": arm_means(rows, "above_tier")}, indent=1))


if __name__ == "__main__":
    main()
