"""In-the-wild replay: what would other compaction triggers have cost on real Claude Code sessions?

Replays every logged session's per-call context growth (and its cache misses, at the same calls)
under each policy, at the session's own model prices, against the trigger Claude Code actually used
(~490k on a 1M window). The fixed-trigger row that claims real-world utility is leave-one-out: each
session gets the trigger that minimised the summed cost of the *other* sessions, so nothing is tuned
on the session it is scored on.

    python experiments/wild.py            # replay data/wild_traces.json
    python experiments/wild.py --refresh  # re-extract the snapshot from ~/.claude/projects first
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextpilot import replay, sim, traces  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "wild_traces.json"
OUT_TXT, OUT_JSON = ROOT / "results" / "wild.txt", ROOT / "results" / "wild.json"
API_DEFAULT = 150_000
COUNTED = {"490k default": sim.FixedContext(replay.DEFAULT_TRIGGER), "150k": sim.FixedContext(API_DEFAULT),
           "closed form": sim.ClosedForm()}


def load(refresh):
    if refresh or not SNAPSHOT.exists():
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(traces.load_sessions()))
    return json.loads(SNAPSHOT.read_text())


def leave_one_out(grid_costs, grid=replay.TRIGGER_GRID):
    """Per session: its cost under the trigger that was best on all other sessions, and that trigger."""
    total = grid_costs.sum(axis=0)
    picks = [int(np.argmin(total - row)) for row in grid_costs]
    return np.array([row[k] for row, k in zip(grid_costs, picks)]), np.array([grid[k] for k in picks])


def arms(sessions, cold):
    """Dollar cost of each session under each policy: {arm: array over sessions}."""
    grid = replay.trigger_costs(sessions, cold=cold)
    loo, loo_k = leave_one_out(grid)
    run = lambda p: np.array([replay.cost(s, p, cold)[0] for s in sessions])  # noqa: E731
    out = {
        f"Claude Code default ({replay.DEFAULT_TRIGGER // 1000}k)": run(sim.FixedContext(replay.DEFAULT_TRIGGER)),
        f"API default ({API_DEFAULT // 1000}k)": run(sim.FixedContext(API_DEFAULT)),
        "closed form (online g)": run(sim.ClosedForm()),
        "break-even": run(sim.BreakEven()),
        "fixed trigger, leave-one-out": loo,
        "hindsight best fixed (per session)": grid.min(axis=1),
    }
    return out, loo_k


def fidelity(sessions):
    logged = np.array([replay.logged_dollars(s) for s in sessions])
    obs = np.array([replay.cost(s, replay.ObservedSchedule(traces.compaction_calls(s)))[0] for s in sessions])
    return logged, obs


def report(label, sessions, cold, lines, record):
    costs, loo_k = arms(sessions, cold)
    base_name = next(iter(costs))
    base = costs[base_name]
    lines.append(f"\n{label}: {len(sessions)} sessions, {sum(map(traces.n_calls, sessions))} calls, "
                 f"cache misses {'replayed' if cold else 'ignored'}; baseline {base_name} ${base.sum():.2f}")
    lines.append(f"  {'policy':38s} {'total $':>9s} {'saved':>7s} {'median':>7s} {'helped':>7s} {'hurt':>5s}")
    rows = {}
    for name, c in costs.items():
        rel = c / base - 1
        helped, hurt = int((rel < -0.01).sum()), int((rel > 0.01).sum())
        lines.append(f"  {name:38s} {c.sum():9.2f} {1 - c.sum() / base.sum():+7.1%} {-np.median(rel):+7.1%} "
                     f"{helped:7d} {hurt:5d}")
        rows[name] = {"total_usd": float(c.sum()), "per_session_usd": c.round(4).tolist()}
    ks, counts = np.unique(loo_k, return_counts=True)
    lines.append("  leave-one-out triggers chosen: " + ", ".join(f"{k // 1000}k x{n}" for k, n in zip(ks, counts)))
    record[f"{label} / {'cold' if cold else 'warm'}"] = rows


def main():
    sessions = load("--refresh" in sys.argv)
    groups = {src: [s for s in sessions if s["src"] == src] for src in ("main", "subagent")}
    lines = [f"In-the-wild replay over {len(sessions)} local Claude Code sessions "
             f"(observer and /private/tmp benchmark sessions excluded)."]

    logged, obs = fidelity(sessions)
    err = obs / logged - 1
    lines.append(f"\nFidelity (observed compaction schedule replayed vs logged list-price bill): "
                 f"logged ${logged.sum():.2f}, simulated ${obs.sum():.2f} ({obs.sum() / logged.sum() - 1:+.1%}); "
                 f"per-session error median {np.median(err):+.1%}, IQR [{np.percentile(err, 25):+.1%}, "
                 f"{np.percentile(err, 75):+.1%}]")

    record = {"fidelity": {"logged_usd": logged.round(4).tolist(), "simulated_usd": obs.round(4).tolist()}}
    for cold in (True, False):
        for src, group in groups.items():
            report(src, group, cold, lines, record)
        report("all", sessions, cold, lines, record)

    g = replay.pooled_growth(groups["main"])
    counts = {name: sum(replay.cost(s, p)[1] for s in groups["main"]) for name, p in COUNTED.items()}
    record["main_compactions"] = {"logged": sum(len(traces.compaction_calls(s)) for s in groups["main"]), **counts}
    lines.append(f"\nPooled main-session growth {g:,.0f} tokens/call; main-session compactions: "
                 + ", ".join(f"{k} {v}" for k, v in record["main_compactions"].items()))
    text = "\n".join(lines)
    print(text)
    OUT_TXT.write_text(text + "\n")
    OUT_JSON.write_text(json.dumps(record))


if __name__ == "__main__":
    main()
