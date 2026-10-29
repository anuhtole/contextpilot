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
# Claude Code writes 1-hour cache entries (2x) and Sonnet/Opus 5.5 read cache at 0.05x.
CLAUDE_CODE = Prices(read=0.05, write=2.0, out=5.0, name="Claude Code (0.05x read, 1h 2x write)")


@dataclass(frozen=True)
class Env:
    system: int = 20_000        # static prefix (system prompt + tools), stays cached
    window: int = 200_000       # hard context limit
    out_per_call: int = 600     # mean output tokens per call
    # Claude Code leaves ~11k tokens after /compact regardless of history (pilot: 9-15k),
    # and re-fetch of dropped content was ~0.1% of dropped tokens (results/refetch.txt).
    sigma_frac: float = 0.0     # summary size as a fraction of history (0 = constant)
    sigma_min: int = 11_000
    sigma_max: int = 11_000
    rho: float = 0.0            # fraction of compacted history re-fetched afterwards
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


def eoq_history(env, g):
    """Closed-form steady-state optimum for a constant summary size sigma.

    With s = sigma + rho*H, a cycle of n calls ends at H = (sigma + g n)/(1 - rho);
    the per-call cost is h g n (1 + rho) / (2 (1 - rho)) + A'/n with
    A' = r S + o sigma + P + w sigma / (1 - rho), so
    n* = sqrt(2 A' (1 - rho) / (h g (1 + rho))) and H* = (sigma + g n*) / (1 - rho).
    For rho = 0 this is the EOQ H* = sigma + sqrt(2 g A / h), A = r S + (o + w) sigma + P.
    Independent of the window. Use steady_state_optimum when sigma depends on H."""
    p, rho, sig = env.prices, env.rho, env.sigma_min
    a = p.read * env.system + p.out * sig + env.penalty + max(p.write, p.read) * sig / (1 - rho)
    n = np.sqrt(2 * a * (1 - rho) / (hold_rate(env) * g * (1 + rho)))
    return float((sig + g * n) / (1 - rho))


def steady_state_rate(env, g, h):
    """Long-run cost per call (excluding terms independent of the trigger) of always
    compacting at history h while history grows by g per call."""
    s = post_history(env, h)
    n = (h - s) / g
    if n <= 1:
        return np.inf
    return hold_rate(env) * (s + g * (n - 1) / 2) + buy_cost(env, h) / n


_GRID = np.geomspace(500, 4e6, 1200)


def steady_state_optimum(env, g):
    """Exact steady-state optimal compaction point for any summary-size model.
    eoq_history is its square-root approximation when sigma and s are constant."""
    rates = [steady_state_rate(env, g, h) for h in _GRID]
    return float(_GRID[int(np.argmin(rates))])


def call_cost(env, h, g):
    p = env.prices
    held = env.system + h
    return p.read * held + env.quality * h + p.write * g + p.out * env.out_per_call


def cold_buy_cost(env, h):
    """Incremental cost of compacting right after the prompt cache expired.

    Not compacting forces a rewrite of the whole prefix at the write price; compacting
    reads it once uncached (1.0) for the summary and writes only the short new prefix
    (system + s). Negative whenever (write - 1)(system + h) > out*sigma + write*(system + s)."""
    p = env.prices
    s = post_history(env, h)
    return ((1.0 - p.write) * (env.system + h) + p.out * sigma(env, h)
            + p.write * (env.system + s) + env.penalty)


def run(env, g, policy, cold=None):
    """Simulate one session; returns (total cost, number of compactions).

    cold[t] marks calls that follow an idle gap longer than the cache TTL: the
    prefix must be rewritten at the write price instead of read at the read price."""
    h, cost, n_compact = 0.0, 0.0, 0
    state = policy.reset(env)
    for t, gt in enumerate(g):
        is_cold = cold is not None and bool(cold[t])
        forced = env.system + h + gt > env.window
        wants = h > 0 and (forced or policy.should_compact(env, state, t, h, gt)
                           or (is_cold and policy.compact_when_cold(env, h)))
        if wants and is_cold:
            cost += cold_buy_cost(env, h) + env.prices.write * (env.system + h)
            h = post_history(env, h)
            n_compact += 1
            state = policy.on_compact(env, state)
            cost += call_cost(env, h, gt) - env.prices.read * (env.system + h)  # prefix already paid
            h += gt
            state = policy.observe(env, state, t, h, gt)
            continue
        if is_cold:
            cost += (env.prices.write - env.prices.read) * (env.system + h)
        if wants:
            cost += buy_cost(env, h)
            h = post_history(env, h)
            n_compact += 1
            state = policy.on_compact(env, state)
        cost += call_cost(env, h, gt)
        h += gt
        state = policy.observe(env, state, t, h, gt)
    return cost, n_compact


class Policy:
    name = "base"
    def reset(self, env): return {}
    def should_compact(self, env, s, t, h, g): return False
    def compact_when_cold(self, env, h): return False
    def on_compact(self, env, s): return self.reset(env)
    def observe(self, env, s, t, h, g=0.0): return s


class WindowForced(Policy):
    name = "window-forced (100%)"


class FixedThreshold(Policy):
    def __init__(self, frac):
        self.frac = frac
        self.name = f"fixed {int(round(frac * 100))}% of window"
    def should_compact(self, env, s, t, h, g):
        return env.system + h >= self.frac * env.window


class FixedContext(Policy):
    """Product-style trigger on total context tokens (e.g. the 150k API default)."""
    def __init__(self, tokens):
        self.tokens = tokens
        self.name = f"fixed {tokens // 1000}k context"
    def should_compact(self, env, s, t, h, g):
        return env.system + h >= self.tokens


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
    def observe(self, env, s, t, h, g=0.0):
        excess = max(h - post_history(env, h), 0.0)
        return {**s, "rent": s["rent"] + hold_rate(env) * excess}
    def should_compact(self, env, s, t, h, g):
        return s["rent"] >= buy_cost(env, h)


class ClosedForm(Policy):
    """Compact when history reaches the steady-state optimum for the observed growth.
    g_hat is a running mean shrunk toward g0 for the first few calls; no tuning to data.
    The optimum is cached on g_hat rounded to 2% buckets."""
    def __init__(self, g0=2_000.0, prior_calls=3):
        self.g0, self.k0 = g0, prior_calls
        self.name = "steady-state optimum (online g)"
        self._cache = {}
    def _target(self, env, g_hat):
        key = (id(env), round(np.log(max(g_hat, 1.0)) / 0.02))
        if key not in self._cache:
            self._cache[key] = steady_state_optimum(env, g_hat)
        return self._cache[key]
    def reset(self, env): return {"sum": 0.0, "n": 0}
    def on_compact(self, env, s): return s  # growth estimate persists across compactions
    def observe(self, env, s, t, h, g=0.0): return {"sum": s["sum"] + g, "n": s["n"] + 1}
    def should_compact(self, env, s, t, h, g):
        g_hat = (self.k0 * self.g0 + s["sum"]) / (self.k0 + s["n"])
        return h >= self._target(env, g_hat)


class ColdAware(Policy):
    """Wraps a policy and also compacts on a cold cache whenever that is cheaper right now."""
    def __init__(self, inner):
        self.inner = inner
        self.name = f"{inner.name} + cold-cache rule"
    def reset(self, env): return self.inner.reset(env)
    def should_compact(self, env, s, t, h, g): return self.inner.should_compact(env, s, t, h, g)
    def on_compact(self, env, s): return self.inner.on_compact(env, s)
    def observe(self, env, s, t, h, g=0.0): return self.inner.observe(env, s, t, h, g)
    def compact_when_cold(self, env, h): return cold_buy_cost(env, h) < 0


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


class ClosedFormRecent(ClosedForm):
    """ClosedForm with an exponentially weighted growth estimate (half-life in calls), so a
    late growth burst raises the target instead of being averaged away by a slow start."""
    def __init__(self, half_life=10.0, g0=2_000.0):
        super().__init__(g0=g0)
        self.alpha = 1.0 - 0.5 ** (1.0 / half_life)
        self.name = f"steady-state optimum (recent g, half-life {half_life:g})"
    def reset(self, env): return {"g": self.g0}
    def observe(self, env, s, t, h, g=0.0): return {"g": (1 - self.alpha) * s["g"] + self.alpha * g}
    def should_compact(self, env, s, t, h, g):
        return h >= self._target(env, s["g"])


class HorizonGated(Policy):
    """Compact only when the inner trigger fires and the rent saved over the rest of the
    session repays the buy: hold_rate * (h - s(h)) * (1 + R(t)) >= K(h), with R(t) the
    predicted calls remaining after this one. A steady-state trigger ignores the horizon,
    so near the end of a session it buys compactions that cannot pay back.
    Robustness: whatever the predictor says, compact once the rent paid on the compactable
    excess since the last compaction reaches K / lam (break-even, delayed by 1 / lam)."""
    def __init__(self, inner, remaining_fn, lam=0.5, label="predictor"):
        self.inner, self.remaining_fn, self.lam = inner, remaining_fn, lam
        self.name = f"{inner.name} + horizon gate ({label}, lam={lam:g})"
    def reset(self, env): return {"inner": self.inner.reset(env), "rent": 0.0}
    def on_compact(self, env, s): return {"inner": self.inner.on_compact(env, s["inner"]), "rent": 0.0}
    def observe(self, env, s, t, h, g=0.0):
        excess = max(h - post_history(env, h), 0.0)
        return {"inner": self.inner.observe(env, s["inner"], t, h, g), "rent": s["rent"] + hold_rate(env) * excess}
    def should_compact(self, env, s, t, h, g):
        buy = buy_cost(env, h)
        if s["rent"] >= buy / self.lam:
            return True
        if not self.inner.should_compact(env, s["inner"], t, h, g):
            return False
        saving_per_call = hold_rate(env) * max(h - post_history(env, h), 0.0)
        return saving_per_call * (1 + self.remaining_fn(t)) >= buy


def empirical_residual(lengths, min_tail=5):
    """Predicted calls remaining after call t: E[T - t - 1 | T > t + 1] over training session
    lengths. With fewer than min_tail longer sessions it falls back to the Lindy estimate
    t + 1 (a session that has lasted t + 1 calls is expected to last about as long again)."""
    lengths = np.sort(np.asarray(lengths, dtype=float))
    table = {}
    def f(t):
        if t not in table:
            tail = lengths[lengths > t + 1]
            table[t] = float(tail.mean() - (t + 1)) if len(tail) >= min_tail else float(t + 1)
        return table[t]
    return f


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
