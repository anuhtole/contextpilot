"""Aggregate the real-agent pilot ledger by session length and arm."""
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

LEDGER = Path(__file__).resolve().parents[1] / "results" / "pilot" / "ledger.jsonl"
METRICS = ("cost_usd", "n_fixed", "recall_expression", "c1_untagged_lines", "c2_new_files", "compactions", "peak_context")


def main():
    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    groups = defaultdict(list)
    for r in rows:
        if r.get("cost_usd"):
            groups[("long" if r["variant"].endswith("L") else "short", r["arm"])].append(r)
    print(f"{'session':6s} {'arm':6s} {'n':>2s} {'cost $':>14s} {'vs auto':>8s} {'fixed/12':>8s} "
          f"{'recall/12':>9s} {'untagged':>8s} {'new files':>9s} {'compactions':>11s} {'peak ctx':>9s}")
    for length in ("short", "long"):
        auto = np.mean([r["cost_usd"] for r in groups[(length, "auto")]]) if groups[(length, "auto")] else np.nan
        for arm in ("auto", "eoq", "early"):
            g = groups[(length, arm)]
            if not g:
                continue
            m = {k: np.mean([r[k] for r in g]) for k in METRICS}
            sd = np.std([r["cost_usd"] for r in g])
            print(f"{length:6s} {arm:6s} {len(g):2d} {m['cost_usd']:8.3f}±{sd:5.3f} {100 * (m['cost_usd'] / auto - 1):+7.1f}% "
                  f"{m['n_fixed']:8.1f} {m['recall_expression']:9.1f} {m['c1_untagged_lines']:8.1f} "
                  f"{m['c2_new_files']:9.1f} {m['compactions']:11.1f} {m['peak_context'] / 1e3:8.1f}k")
    print(f"total pilot spend in ledger: ${sum(r.get('cost_usd') or 0 for r in rows):.2f}")


if __name__ == "__main__":
    main()
