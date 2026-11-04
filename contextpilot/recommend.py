"""Recommend a compaction trigger from your own Claude Code logs.

Reads only per-call token counts from ~/.claude/projects (no message text), fits the growth rate,
and prints the closed-form trigger, what it would have saved on your sessions against Claude Code's
~490k default, and the settings that apply it.
"""
import argparse
import json
from collections import Counter

import numpy as np

from contextpilot import replay, sim, traces

# Claude Code's autoCompactWindow fires about this far below the configured value (measured 70-85k).
AUTOCOMPACT_LEAD = 75_000
AUTOCOMPACT_RANGE = (100_000, 1_000_000)
API_MIN_TRIGGER = 50_000  # compact_20260112 rejects triggers below 50k input tokens
ROUND = 10_000


def _round(x):
    return int(ROUND * round(x / ROUND))


def pick_model(sessions, model=None):
    if model:
        if model not in replay.MODEL_PRICES:
            raise ValueError(f"unknown model {model!r}; known: {', '.join(replay.MODEL_PRICES)}")
        return model
    return Counter(map(replay.model_of, sessions)).most_common(1)[0][0]


def typical_env(sessions, model):
    """An Env with the median static prefix and mean output of the sessions, at the model's prices."""
    system = float(np.median([traces.context(s)[0] for s in sessions]))
    out = float(np.mean([t["out"] for s in sessions for t in traces.calls(s)]))
    return sim.Env(system=int(system), window=replay.WINDOW, out_per_call=int(out), sigma_frac=0.0,
                   sigma_min=11_000, sigma_max=11_000, prices=replay.prices_for(model))


def settings_for(trigger):
    lo, hi = AUTOCOMPACT_RANGE
    return {"autoCompactWindow": int(min(max(trigger + AUTOCOMPACT_LEAD, lo), hi)),
            "api_compact_trigger": int(max(trigger, API_MIN_TRIGGER))}


def recommend(sessions, model=None):
    """Recommendation for the main (non-subagent) sessions, or all sessions if there are none."""
    main = [s for s in sessions if s["src"] == "main"] or list(sessions)
    if not main:
        raise ValueError("no sessions with enough API calls to fit")
    model = pick_model(main, model)
    env, g = typical_env(main, model), replay.pooled_growth(main)
    trigger = _round(env.system + sim.steady_state_optimum(env, g))
    grid = replay.trigger_costs(main)
    base = np.array([replay.cost(s, sim.FixedContext(replay.DEFAULT_TRIGGER))[0] for s in main])
    rec = np.array([replay.cost(s, sim.FixedContext(trigger))[0] for s in main])
    rel = rec / base - 1
    return {
        "sessions": len(main), "calls": int(sum(map(traces.n_calls, main))), "model": model,
        "growth_per_call": round(g), "static_prefix": env.system, "trigger": trigger,
        "hindsight_trigger": int(replay.TRIGGER_GRID[int(np.argmin(grid.sum(axis=0)))]),
        "default_trigger": replay.DEFAULT_TRIGGER,
        "default_usd": round(float(base.sum()), 2), "recommended_usd": round(float(rec.sum()), 2),
        "saved_frac": round(float(1 - rec.sum() / base.sum()), 4) if base.sum() else 0.0,
        "helped": int((rel < -0.01).sum()), "hurt": int((rel > 0.01).sum()),
        **settings_for(trigger),
    }


def format_report(r):
    return "\n".join([
        f"{r['sessions']} sessions, {r['calls']} API calls, priced as {r['model']}",
        f"context growth {r['growth_per_call']:,} tokens/call, static prefix {r['static_prefix']:,} tokens",
        "",
        f"recommended trigger: compact at ~{r['trigger'] // 1000}k context "
        f"(best in hindsight on these logs: {r['hindsight_trigger'] // 1000}k)",
        f"replayed on your sessions vs the {r['default_trigger'] // 1000}k default: "
        f"${r['default_usd']:.2f} -> ${r['recommended_usd']:.2f} ({r['saved_frac']:+.1%} saved; "
        f"{r['helped']} sessions cheaper, {r['hurt']} dearer)",
        "",
        "apply it:",
        f'  Claude Code  ~/.claude/settings.json  {{"autoCompactWindow": {r["autoCompactWindow"]}}}',
        f'  Claude API   context_management edits: {{"type": "compact_20260112", '
        f'"trigger": {{"type": "input_tokens", "value": {r["api_compact_trigger"]}}}}}',
        "",
        "Estimates replay your logged token growth through the cost model; they do not measure how",
        "more frequent compaction changes the work itself.",
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="contextpilot recommend", description=__doc__.splitlines()[0])
    ap.add_argument("--projects", default=traces.PROJECTS, help="Claude Code projects directory")
    ap.add_argument("--model", help="fit the trigger at this model's prices; the replay keeps each "
                    f"session's own ({', '.join(replay.MODEL_PRICES)})")
    ap.add_argument("--min-calls", type=int, default=traces.MIN_CALLS)
    ap.add_argument("--json", action="store_true", help="print the recommendation as JSON")
    args = ap.parse_args(argv)
    sessions = traces.load_sessions(args.projects, args.min_calls)
    try:
        r = recommend(sessions, args.model)
    except ValueError as e:
        ap.exit(1, f"contextpilot recommend: {e}\n")
    print(json.dumps(r, indent=2) if args.json else format_report(r))
    return r
