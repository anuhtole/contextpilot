"""Decompose the gap between the pre-registered prediction (eoq vs auto, -35%) and the observed
high-growth result, one assumption at a time.

  0. as registered: pre-correction cost model, i.i.d. rescaled pilot increments at g=4k for
     120 calls, the pilot's empirical bias correction applied (size_highgrowth.py)
  1. same, without the bias correction
  2. corrected cost model (measured summary output and prefix rewrite), same synthetic design
  3. corrected model, the real auto runs' growth with call order shuffled (real g and length)
  4. corrected model, real growth in real order (the counterfactual replay)
  5. observed (live runs)
The live eoq rule chose its compaction points with the pre-correction model, so steps 3-4 replay
that rule; step 2 onward bill with the corrected model."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from contextpilot import sim  # noqa: E402
from fidelity import PILOT, calls_of, output_tokens  # noqa: E402
from highgrowth_summary import DecideWith, HG  # noqa: E402

BASE, OUT, SIGMA, WINDOW = 36_000, 700, 11_000, 1_000_000   # as registered
BIAS_UNCOMPACTED, BIAS_COMPACTED = -0.093, 0.051            # as registered
ORDERINGS, COMPLETE = ["v1L", "v2L", "v3L"], ["h1", "h2", "h3", "h5"]
REPS, CALLS, G = 30, 120, 4_000


def env(old):
    e = sim.Env(system=BASE, out_per_call=OUT, prices=sim.CLAUDE_CODE, window=WINDOW,
                sigma_frac=0.0, sigma_min=SIGMA, sigma_max=SIGMA)
    return e.with_(summary_out=None, prefix_rewrite=0.0) if old else e


def pilot_synthetic(seed=G + CALLS):
    rng = np.random.default_rng(seed)
    pools = [np.clip(np.diff(calls_of(PILOT / f"{o}-auto-r1.jsonl")[0]), 0, None) for o in ORDERINGS]
    return [rng.choice(p, CALLS) * (G / p.mean()) for p in (pools[i % 3] for i in range(REPS))]


def ratio(bill_env, seqs, decide_env, bias=False):
    eoq = [sim.run(bill_env, g, DecideWith(sim.ClosedForm(), decide_env)) for g in seqs]
    auto = [sim.run(bill_env, g, sim.WindowForced()) for g in seqs]
    if bias:
        corr = lambda c, k: c / (1 + (BIAS_COMPACTED if k else BIAS_UNCOMPACTED))  # noqa: E731
        return np.mean([corr(*e) for e in eoq]) / np.mean([corr(*a) for a in auto]) - 1
    return np.mean([c for c, _ in eoq]) / np.mean([c for c, _ in auto]) - 1


def real_growth():
    out = []
    for v in COMPLETE:
        ctx, _, _ = calls_of(HG / f"{v}-auto-r1.jsonl")
        total, _ = output_tokens(HG / f"{v}-auto-r1.jsonl")
        out.append((np.clip(np.diff(ctx, prepend=ctx[0]), 0, None), int(ctx[0]), total / len(ctx)))
    return out


def main():
    old, new = env(True), env(False)
    synth = pilot_synthetic()
    steps = [("as registered (bias-corrected)", ratio(old, synth, old, bias=True)),
             ("without bias correction", ratio(old, synth, old)),
             ("corrected cost model", ratio(new, synth, old))]
    rng = np.random.default_rng(0)
    shuffled, ordered = [], []
    for g, base, out in real_growth():
        e = new.with_(system=base, out_per_call=int(out))
        d = e.with_(summary_out=None, prefix_rewrite=0.0)
        shuffled.append(np.mean([ratio(e, [rng.permutation(g)], d) for _ in range(REPS)]))
        ordered.append(ratio(e, [g], d))
    steps += [("real growth, order shuffled", float(np.mean(shuffled))),
              ("real growth, real order (replay)", float(np.mean(ordered)))]
    led = {json.loads(l)["tag"]: json.loads(l) for l in (HG / "ledger.jsonl").read_text().splitlines() if l.strip()}
    obs = np.mean([led[f"{v}-eoq-r1"]["cost_usd"] / led[f"{v}-auto-r1"]["cost_usd"] - 1 for v in COMPLETE])
    steps.append(("observed", float(obs)))
    print("eoq vs auto, one assumption at a time:")
    for name, x in steps:
        print(f"  {name:36s} {100 * x:+6.1f}%")
    (HG / "prediction_gap.json").write_text(json.dumps(steps, indent=1))


if __name__ == "__main__":
    main()
