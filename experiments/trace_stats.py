"""Descriptive statistics of the local Claude Code traces and the pooled re-fetch fraction,
so every dataset number in the paper has a source in results/."""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from main_tables import SEQS, TRACES  # noqa: E402
from measure_refetch import measure, ROOT  # noqa: E402

HG = ROOT / "results" / "highgrowth"
EXCLUDED = {"h4-auto-r1", "h4-eoq-r1"}  # timed out, incomplete


def main():
    calls = [t for s in TRACES for t in s["turns"] if "in" in t]
    cached = sum(t["cr"] for t in calls) / sum(t["in"] + t["cr"] + t["cw"] for t in calls)
    lengths = [len(q) + 1 for q in SEQS]
    print(f"sessions {len(SEQS)}, calls {sum(lengths)}, increments {sum(len(q) for q in SEQS)}")
    print(f"mean growth {np.concatenate(SEQS).mean():.0f} tokens/call; median session {np.median(lengths):.0f} calls")
    print(f"input tokens served from cache: {100 * cached:.1f}%")
    print("calls by model:", dict(Counter(t.get("model") for t in calls).most_common()))
    print("sessions by source:", dict(Counter(s.get("src") for s in TRACES).most_common()))
    streams = [*sorted((ROOT / "results" / "pilot").glob("*-early-r1.jsonl")),
               *[p for p in sorted(HG.glob("h*-r1.jsonl")) if p.stem not in EXCLUDED and "-auto-" not in p.stem]]
    pilot_r = pilot_d = hg_r = hg_d = 0.0
    for p in streams:
        r, d, _ = measure(p)
        if p.parent.name == "pilot":
            pilot_r, pilot_d = pilot_r + r, pilot_d + d
        else:
            hg_r, hg_d = hg_r + r, hg_d + d
    print(f"re-fetch rho: pilot early arm {pilot_r / pilot_d:.3f} ({pilot_d / 1e3:.0f}k dropped), "
          f"high-growth compactions {hg_r / hg_d:.3f} ({hg_d / 1e3:.0f}k dropped), "
          f"pooled {(pilot_r + hg_r) / (pilot_d + hg_d):.3f}")


if __name__ == "__main__":
    main()
