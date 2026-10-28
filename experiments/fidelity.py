"""Simulator fidelity on the real-agent pilot: replay each run's observed context growth
through the cost model and compare predicted dollars with Claude Code's reported cost."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextpilot import sim  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "results" / "pilot"
USD_PER_INPUT_TOKEN = 2.0e-6     # Sonnet 5.5 list input price
SUMMARY_TOKENS = 11_000


class AtCalls(sim.Policy):
    """Compacts right before the given call indices (replays the controller's choices)."""
    def __init__(self, calls):
        self.calls = set(calls)
        self.name = "replay"
    def should_compact(self, env, s, t, h, g):
        return t in self.calls


def calls_of(stream):
    """Per-call context sizes, output sizes, and indices of calls that follow a compaction."""
    ctx, out, after_compact, seen, pending = [], [], [], set(), False
    for line in stream.read_text().splitlines():
        r = json.loads(line)
        if r.get("type") == "system" and r.get("subtype") == "compact_boundary":
            pending = True
        m = r.get("message", {}) if r.get("type") == "assistant" else {}
        if m.get("usage") and m.get("id") not in seen:
            seen.add(m["id"])
            u = m["usage"]
            ctx.append(u["input_tokens"] + u["cache_read_input_tokens"] + u["cache_creation_input_tokens"])
            out.append(u["output_tokens"])
            if pending:
                after_compact.append(len(ctx) - 1)
                pending = False
    return np.array(ctx, float), np.array(out, float), after_compact


def predict(stream):
    ctx, out, compact_at = calls_of(stream)
    base = ctx[0]
    # reconstruct uncompacted growth: increments between consecutive calls, skipping compaction drops
    g = np.diff(ctx, prepend=base)
    g[0] = 0.0
    for i in compact_at:
        g[i] = max(ctx[i] - ctx[i - 1], 0.0) if ctx[i] > ctx[i - 1] else float(np.median(g[g > 0]))
    env = sim.Env(system=int(base), out_per_call=int(out.mean()), prices=sim.CLAUDE_CODE, window=10_000_000,
                  sigma_frac=0.0, sigma_min=SUMMARY_TOKENS, sigma_max=SUMMARY_TOKENS, rho=0.0)
    cost, _ = sim.run(env, g, AtCalls(compact_at))
    # the first call writes the whole static prefix to the cache
    cost += (env.prices.write - env.prices.read) * base
    return cost * USD_PER_INPUT_TOKEN, len(compact_at)


if __name__ == "__main__":
    rows = [json.loads(l) for l in (PILOT / "ledger.jsonl").read_text().splitlines() if l.strip()]
    errs = []
    print(f"{'run':16s} {'actual $':>9s} {'predicted $':>11s} {'error':>7s} {'compactions':>11s}")
    for r in rows:
        stream = PILOT / f"{r['tag']}.jsonl"
        if not stream.exists() or not r.get("cost_usd"):
            continue
        pred, k = predict(stream)
        err = pred / r["cost_usd"] - 1
        errs.append(err)
        print(f"{r['tag']:16s} {r['cost_usd']:9.3f} {pred:11.3f} {100 * err:+6.1f}% {k:11d}")
    print(f"mean absolute error {100 * np.mean(np.abs(errs)):.1f}% over {len(errs)} runs")
