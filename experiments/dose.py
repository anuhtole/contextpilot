"""Dose-response of task quality on compaction count (EVAL_PLAN.md, quality cost of extra compactions).

Pools the paired high-growth runs (auto, 150k, eoq on h1-h3, h5) with the dose runs (100k, 70k, and
h6-h7 under all arms). The primary estimate is the slope of exact-expression recall (/20) on realized
compactions with an ordering fixed effect; its p is a within-ordering permutation of compaction counts
and its CI an ordering-cluster bootstrap. The slope converts to a per-compaction penalty P in tokens
(one lost fact = one re-read of its module), which is compared with the 200k trigger's break-even.
Writes results/dose.txt and results/dose.json.
"""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "results" / "highgrowth", ROOT / "results" / "dose"]
ARMS = ["auto", "150k", "eoq", "100k", "70k"]
TOKENS_PER_FACT = 25_000  # a 1.4-3.3k-line module re-read, about 15-35k tokens
BREAK_EVEN_P = 180_000    # warm 200k trigger vs the 490k default, in-the-wild replay
N_PERM, N_BOOT, SEED = 10_000, 10_000, 0
SECONDARY = ["n_fixed", "recall_function", "c5_rule5_violations", "audit_linecount_ok", "audit_lastdef_ok",
             "cost_usd", "peak_context", "calls"]


def load(rep=1):
    rows = []
    for d in SOURCES:
        path = d / "ledger.jsonl"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            r = json.loads(line) if line.strip() else None
            if r and "-cal" not in r["tag"] and r["rep"] == rep and r["status"] == 0 and r.get("cost_usd"):
                rows.append({**r, "rho": refetch_rate(d / f"{r['tag']}.jsonl")})
    return rows


def refetch_rate(stream):
    """Distinct files re-read after a compaction that had been read before it, per compaction.

    Chunked reads of one file within a stretch between compactions do not count; this isolates
    what a summary made the agent fetch again."""
    if not stream.exists():
        return None
    earlier, current, refetched, n_compact = set(), set(), set(), 0
    for line in stream.read_text(errors="ignore").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") == "system" and e.get("subtype") == "compact_boundary":
            earlier, current, n_compact = earlier | current, set(), n_compact + 1
            continue
        if e.get("type") != "assistant":
            continue
        for c in e.get("message", {}).get("content", []) or []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Read":
                f = (c.get("input") or {}).get("file_path")
                current = current | {f}
                refetched = refetched | ({f} & earlier)
    return len(refetched) / n_compact if n_compact else None


def complete_orderings(rows):
    """Orderings run under at least two arms; the fixed effect needs within-ordering variation."""
    by = {}
    for r in rows:
        by.setdefault(r["variant"], []).append(r)
    return {v: rs for v, rs in by.items() if len({r["arm"] for r in rs}) >= 2}


def fe_slope(groups):
    """OLS slope of recall on compactions after demeaning both within each ordering."""
    x = np.concatenate([g[:, 0] - g[:, 0].mean() for g in groups])
    y = np.concatenate([g[:, 1] - g[:, 1].mean() for g in groups])
    return float((x @ y) / (x @ x)) if x @ x else float("nan")


FRESH = {"h6", "h7"}  # every arm run in the 2026-11 batch: the primary, date-unconfounded slope


def analyze(rows, only=None):
    groups = {v: np.array([[r["compactions"], r["recall_expression"]] for r in rs], float)
              for v, rs in complete_orderings(rows).items() if only is None or v in only}
    if not groups:
        return None
    gs = list(groups.values())
    slope = fe_slope(gs)
    rng = np.random.default_rng(SEED)
    perm = [fe_slope([np.column_stack([rng.permutation(g[:, 0]), g[:, 1]]) for g in gs]) for _ in range(N_PERM)]
    p = float(np.mean(np.abs(perm) >= abs(slope) - 1e-12))
    boot = [fe_slope([gs[i] for i in rng.integers(len(gs), size=len(gs))]) for _ in range(N_BOOT)]
    lo, hi = np.nanpercentile(boot, [2.5, 97.5])
    worst = -lo  # facts lost per compaction at the pessimistic CI bound
    return {"orderings": sorted(groups), "n_runs": int(sum(len(g) for g in gs)),
            "slope_facts_per_compaction": slope, "ci95": [float(lo), float(hi)], "perm_p": p,
            "P_tokens": max(0.0, -slope) * TOKENS_PER_FACT, "P_tokens_upper": max(0.0, worst) * TOKENS_PER_FACT,
            "break_even_P": BREAK_EVEN_P, "200k_stands": bool(max(0.0, worst) * TOKENS_PER_FACT < BREAK_EVEN_P)}


def arm_table(rows):
    """Arm means over the orderings that enter the regression."""
    keep = set(complete_orderings(rows))
    out = {}
    for a in ARMS:
        rs = [r for r in rows if r["arm"] == a and r["variant"] in keep]
        if rs:
            out[a] = {"n": len(rs), **{k: float(np.mean([r[k] for r in rs if r.get(k) is not None]))
                                        for k in ["compactions", "recall_expression", "rho", *SECONDARY]
                                        if any(r.get(k) is not None for r in rs)}}
    return out


def drift(rows_r1):
    """h1 auto re-run (rep 2) against the original; the plan stops on > 2 facts or > 10% cost."""
    r2 = [r for r in load(rep=2) if r["variant"] == "h1" and r["arm"] == "auto"]
    r1 = [r for r in rows_r1 if r["variant"] == "h1" and r["arm"] == "auto"]
    if not (r1 and r2):
        return None
    d_recall = r2[0]["recall_expression"] - r1[0]["recall_expression"]
    d_cost = r2[0]["cost_usd"] / r1[0]["cost_usd"] - 1
    return {"recall_delta": d_recall, "cost_delta": d_cost, "ok": abs(d_recall) <= 2 and abs(d_cost) <= 0.10}


def main():
    rows = load()
    res = {"primary": analyze(rows, FRESH), "pooled": analyze(rows), "arms": arm_table(rows), "drift": drift(rows)}
    lines = []
    for name in ("primary", "pooled"):
        pr = res[name]
        if pr is None:
            lines.append(f"{name}: no data yet")
            continue
        lines += [f"{name}: {pr['n_runs']} runs on {', '.join(pr['orderings'])}",
                  f"  recall slope {pr['slope_facts_per_compaction']:+.2f} facts/compaction "
                  f"(95% CI {pr['ci95'][0]:+.2f} to {pr['ci95'][1]:+.2f}, permutation p = {pr['perm_p']:.3f})",
                  f"  P = {pr['P_tokens'] / 1e3:.0f}k tokens/compaction (upper {pr['P_tokens_upper'] / 1e3:.0f}k) "
                  f"vs break-even {BREAK_EVEN_P / 1e3:.0f}k: 200k {'stands' if pr['200k_stands'] else 'does not stand'}"]
    lines += ["", f"{'arm':6} {'n':>2} {'comp':>5} {'recall':>6} {'fixed':>5} {'refet':>5} {'$':>5}"]
    for a, t in res["arms"].items():
        lines.append(f"{a:6} {t['n']:>2} {t['compactions']:>5.1f} {t['recall_expression']:>6.1f} "
                     f"{t['n_fixed']:>5.1f} {t.get('rho', float('nan')):>5.1f} {t['cost_usd']:>5.2f}")
    if res["drift"]:
        d = res["drift"]
        lines += ["", f"drift (h1 auto re-run): recall {d['recall_delta']:+d}, cost {d['cost_delta']:+.1%}, "
                      f"{'ok' if d['ok'] else 'FAILED gate'}"]
    (ROOT / "results" / "dose.txt").write_text("\n".join(lines) + "\n")
    (ROOT / "results" / "dose.json").write_text(json.dumps(res, indent=2))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
