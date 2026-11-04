"""Replay real Claude Code sessions under alternative compaction triggers.

Each session's logged per-call context growth is re-run through the cost model at its own
model's prices. Costs are in base-input-token units; dollars() converts with the list price.
"""
import numpy as np

from contextpilot import sim, traces

# (input $ per MTok, cache-read multiple of input). Claude Code writes 1-hour cache entries (2x)
# and every listed model prices output at 5x input. Fable 5's cache read is assumed standard (0.1x);
# Fable 5.1 introduced the 0.025x rate ($0.25/MTok).
MODEL_PRICES = {
    "claude-opus-5-5": (4.0, 0.05),
    "claude-sonnet-5-5": (2.0, 0.10),
    "claude-fable-5-1": (10.0, 0.025),
    "claude-fable-5": (10.0, 0.10),
}
FALLBACK_MODEL = "claude-opus-5-5"
CACHE_WRITE, OUTPUT = 2.0, 5.0

# Claude Code's built-in auto-compaction fired at 487-490k context in every logged session that
# reached it (Opus 5.5 and Fable 5.1, 1M window); lower compaction points were manual /compact.
DEFAULT_TRIGGER = 490_000
WINDOW = 1_000_000
TRIGGER_GRID = np.arange(100_000, 610_000, 10_000)


def model_of(session):
    m = traces.dominant_model(session)
    return m if m in MODEL_PRICES else FALLBACK_MODEL


def prices_for(model):
    _, read = MODEL_PRICES[model]
    return sim.Prices(read=read, write=CACHE_WRITE, out=OUTPUT, name=model)


def env_for(session):
    ctx = traces.context(session)
    out = np.mean([t["out"] for t in traces.calls(session)])
    return sim.Env(system=int(ctx[0]), window=WINDOW, out_per_call=int(out),
                   sigma_frac=0.0, sigma_min=11_000, sigma_max=11_000, prices=prices_for(model_of(session)))


def dollars(session, units):
    return units * MODEL_PRICES[model_of(session)][0] / 1e6


def logged_dollars(session):
    """What the session's logged usage cost at list price (1-hour cache writes)."""
    price, read = MODEL_PRICES[model_of(session)]
    units = sum(t["in"] + CACHE_WRITE * t["cw"] + read * t["cr"] + OUTPUT * t["out"] for t in traces.calls(session))
    return units * price / 1e6


class ObservedSchedule(sim.Policy):
    """Compacts exactly before the calls where the real session compacted."""
    name = "observed schedule"
    def __init__(self, at):
        self.at = set(at)
    def should_compact(self, env, s, t, h, g):
        return t in self.at


def cost(session, policy, cold=True):
    """Simulated dollars and compactions for one session under a policy.

    cold=True replays the logged cache misses at the same calls: idle gaps are the user's, but what
    a miss costs depends on how much history the policy kept."""
    misses = traces.cold_calls(session) if cold else None
    units, n = sim.run(env_for(session), traces.increments(session), policy, cold=misses)
    return dollars(session, units), n


def trigger_costs(sessions, grid=TRIGGER_GRID, cold=True):
    """Dollar cost of every session under every fixed context trigger: shape (sessions, grid)."""
    return np.array([[cost(s, sim.FixedContext(int(k)), cold)[0] for k in grid] for s in sessions])


def pooled_growth(sessions):
    """Mean per-call context growth over all calls of all sessions."""
    return float(np.concatenate([traces.increments(s)[1:] for s in sessions]).mean())
