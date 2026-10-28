import math

import numpy as np
import pytest

from contextpilot import sim

UNCACHED_FLAT = sim.Env(system=10_000, window=10_000_000, out_per_call=0,
                        sigma_min=2_000, sigma_max=2_000, rho=0.0, prices=sim.UNCACHED)


def test_no_growth_means_no_compaction():
    _, n = sim.run(sim.Env(), np.zeros(50), sim.BreakEven())
    assert n == 0


def test_window_forced_only_compacts_at_the_limit():
    env = sim.Env(window=100_000, system=20_000)
    g = np.full(30, 5_000.0)  # crosses 80k of history at call 16
    _, n = sim.run(env, g, sim.WindowForced())
    assert n >= 1
    _, n_short = sim.run(env, g[:10], sim.WindowForced())
    assert n_short == 0


def test_lower_fixed_threshold_compacts_more_often():
    env = sim.Env()
    g = np.full(100, 4_000.0)
    _, n50 = sim.run(env, g, sim.FixedThreshold(0.5))
    _, n92 = sim.run(env, g, sim.FixedThreshold(0.92))
    assert n50 > n92


def test_break_even_interval_matches_eoq_in_steady_state():
    """Cumulative rent = buy cost fires near sqrt(2K / (h g)) calls after a compaction."""
    g, env = 1_000.0, UNCACHED_FLAT
    T = 2_000
    _, n = sim.run(env, np.full(T, g), sim.BreakEven())
    observed_interval = T / n
    s, h = env.sigma_min, env.prices.read
    n_eoq = next(k for k in range(1, T)
                 if h * g * k * k / 2 >= sim.buy_cost(env, s + g * k))
    assert observed_interval == pytest.approx(n_eoq, rel=0.1)
    assert n_eoq == pytest.approx(math.sqrt(2 * sim.buy_cost(env, s + g * n_eoq) / (h * g)), rel=0.1)


@pytest.mark.parametrize("prices", [sim.UNCACHED, sim.CACHED])
def test_hindsight_optimum_lower_bounds_online_policies(prices):
    env = sim.Env(window=200_000, prices=prices)
    rng = np.random.default_rng(0)
    for _ in range(5):
        g = rng.integers(500, 9_000, size=int(rng.integers(10, 60))).astype(float)
        opt = sim.hindsight_optimum(env, g, beam=20)
        for p in (sim.BreakEven(), sim.FixedThreshold(0.92), sim.FixedTokens(30_000)):
            assert opt <= sim.run(env, g, p)[0] * (1 + 1e-9)


def test_break_even_stays_near_optimum_on_steady_sessions():
    env = sim.Env(window=1_000_000)
    g = np.full(150, 3_800.0)
    opt = sim.hindsight_optimum(env, g)
    cost, _ = sim.run(env, g, sim.BreakEven())
    assert cost <= 1.10 * opt


def test_quality_penalty_reduces_compactions():
    g = np.full(150, 3_800.0)
    _, n0 = sim.run(sim.Env(window=1_000_000), g, sim.BreakEven())
    _, n1 = sim.run(sim.Env(window=1_000_000, penalty=200_000), g, sim.BreakEven())
    assert n1 < n0
