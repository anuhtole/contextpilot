"""Rent-or-buy context compaction simulator.

All costs are in units of the base input-token price. A session is a sequence of
per-call context increments g_t (tokens appended between calls) with an unknown
horizon T. Before each call a policy may compact: history H is replaced by a
summary of size sigma(H), and a fraction rho of H is re-fetched (recovery).
"""
from dataclasses import dataclass, replace
import numpy as np


@dataclass(frozen=True)
class Prices:
    read: float    # per context token read each call (1.0 uncached, 0.1 cached)
    write: float   # per newly appended token (1.0 uncached, 1.25 cached)
    out: float     # per output token (5x input for Claude)
    name: str = ""


UNCACHED = Prices(read=1.0, write=1.0, out=5.0, name="uncached")
CACHED = Prices(read=0.1, write=1.25, out=5.0, name="cached")
CACHED_55 = Prices(read=0.05, write=1.25, out=5.0, name="cached (5.5-gen 0.05x read)")


@dataclass(frozen=True)
class Env:
    system: int = 20_000        # static prefix (system prompt + tools), stays cached
    window: int = 200_000       # hard context limit
    out_per_call: int = 600     # mean output tokens per call
    sigma_frac: float = 0.05    # summary size as a fraction of history
    sigma_min: int = 2_000
    sigma_max: int = 12_000
    rho: float = 0.10           # fraction of compacted history re-fetched afterwards
    quality: float = 0.0        # optional context-rot price per token held per call
    penalty: float = 0.0        # quality cost per compaction, in base-input-token units
    prices: Prices = CACHED

    def with_(self, **kw):
        return replace(self, **kw)


def sigma(env, h):
    return float(np.clip(env.sigma_frac * h, env.sigma_min, env.sigma_max))


def post_history(env, h):
    return sigma(env, h) + env.rho * h


def hold_rate(env):
    """Marginal per-call cost of carrying one more history token."""
    return env.prices.read + env.quality


def buy_cost(env, h):
    """One-time cost of compacting history h: summary call + prefix rewrite premium."""
    p = env.prices
    read_for_summary = p.read * (env.system + h)
    write_summary = p.out * sigma(env, h)
    rewrite_premium = max(p.write - p.read, 0.0) * post_history(env, h)
    return read_for_summary + write_summary + rewrite_premium + env.penalty


def call_cost(env, h, g):
    p = env.prices
    held = env.system + h
    return p.read * held + env.quality * h + p.write * g + p.out * env.out_per_call


def run(env, g, policy):
    """Simulate one session; returns (total cost, number of compactions)."""
    h, cost, n_compact = 0.0, 0.0, 0
    state = policy.reset(env)
    for t, gt in enumerate(g):
        forced = env.system + h + gt > env.window
        if h > 0 and (forced or policy.should_compact(env, state, t, h, gt)):
            cost += buy_cost(env, h)
            h = post_history(env, h)
            n_compact += 1
            state = policy.on_compact(env, state)
        cost += call_cost(env, h, gt)
        h += gt
        state = policy.observe(env, state, t, h)
    return cost, n_compact


class Policy:
    name = "base"
    def reset(self, env): return {}
    def should_compact(self, env, s, t, h, g): return False
    def on_compact(self, env, s): return self.reset(env)
    def observe(self, env, s, t, h): return s


class WindowForced(Policy):
    name = "window-forced (100%)"


class FixedThreshold(Policy):
    def __init__(self, frac):
        self.frac = frac
        self.name = f"fixed {int(round(frac * 100))}% of window"
    def should_compact(self, env, s, t, h, g):
        return env.system + h >= self.frac * env.window


class FixedTokens(Policy):
    """Fixed absolute history threshold; swept to find the best-in-hindsight value."""
    def __init__(self, tokens):
        self.tokens = tokens
        self.name = f"fixed {tokens // 1000}k history"
    def should_compact(self, env, s, t, h, g):
        return h >= self.tokens


class BreakEven(Policy):
    """Deterministic ski rental: compact once rent paid on the compactable excess
    since the last compaction reaches the current buy cost. Under steady linear
    growth this fires at the EOQ-optimal interval sqrt(2K / (hold * g))."""
    name = "ski-rental break-even"
    def reset(self, env): return {"rent": 0.0}
    def observe(self, env, s, t, h):
        excess = max(h - post_history(env, h), 0.0)
        return {**s, "rent": s["rent"] + hold_rate(env) * excess}
    def should_compact(self, env, s, t, h, g):
        return s["rent"] >= buy_cost(env, h)


class RandomizedBreakEven(BreakEven):
    """Randomized ski rental: buy at fraction z of break-even, z ~ e^z/(e-1) on [0,1]."""
    name = "ski-rental randomized"
    def __init__(self, seed=0):
        self.rng = np.random.default_rng(seed)
    def reset(self, env):
        return {"rent": 0.0, "z": float(np.log1p(self.rng.random() * (np.e - 1)))}
    def should_compact(self, env, s, t, h, g):
        return s["rent"] >= s["z"] * buy_cost(env, h)


class PredictiveBreakEven(BreakEven):
    """Learning-augmented ski rental (Purohit et al. 2018 style). remaining_fn(t)
    predicts calls left. If the prediction says the compaction pays back, act at
    lam * break-even; otherwise defer to break-even / lam. lam -> 1 ignores the
    predictor (robust); lam -> 0 trusts it fully (consistent)."""
    def __init__(self, remaining_fn, lam=0.5, label="predictor"):
        self.remaining_fn = remaining_fn
        self.lam = lam
        self.name = f"ski-rental + {label} (lam={lam})"
    def should_compact(self, env, s, t, h, g):
        buy = buy_cost(env, h)
        saving_per_call = hold_rate(env) * max(h - post_history(env, h), 0.0)
        pays_back = saving_per_call * self.remaining_fn(t) > buy
        return s["rent"] >= (self.lam * buy if pays_back else buy / self.lam)


def hindsight_optimum(env, g, beam=6):
    """Offline schedule optimized with full knowledge of g (beam DP over compaction
    times; state = segment start and post-compaction history)."""
    T = len(g)
    starts = {0: [(0.0, 0.0)]}
    best = np.inf
    for i in range(T):
        for c0, h0 in sorted(starts.pop(i, []))[:beam]:
            h, c = h0, c0
            for j in range(i, T):
                if j > i and env.system + h + g[j] > env.window:
                    break
                c += call_cost(env, h, g[j])
                h += g[j]
                if j + 1 < T:
                    starts.setdefault(j + 1, []).append((c + buy_cost(env, h), post_history(env, h)))
            else:
                best = min(best, c)
    return best
