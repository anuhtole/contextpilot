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


def test_closed_form_point_is_window_independent_and_scales_with_root_hold_price():
    base = sim.Env(system=30_000, prices=sim.CLAUDE_CODE, rho=0.0, sigma_min=4_000, sigma_max=4_000)
    h1 = sim.eoq_history(base, 3_000)
    assert sim.eoq_history(base.with_(window=1_000_000), 3_000) == pytest.approx(h1)
    cheaper = base.with_(prices=sim.Prices(read=0.025, write=2.0, out=5.0))
    s = sim.post_history(base, h1)
    # halving the hold price raises the excess by about sqrt(2) (A also shrinks slightly)
    ratio = (sim.eoq_history(cheaper, 3_000) - s) / (h1 - s)
    assert 1.2 < ratio < math.sqrt(2) + 1e-9


def test_break_even_overshoot_is_bounded_by_two_b_over_h():
    g = 2_000.0
    env = sim.Env(system=30_000, window=10_000_000, out_per_call=0, prices=sim.CLAUDE_CODE,
                  rho=0.1, sigma_min=4_000, sigma_max=4_000)
    _, n = sim.run(env, np.full(3_000, g), sim.BreakEven())
    interval = 3_000 / n
    h_star = sim.eoq_history(env, g)
    n_star = (h_star - sim.post_history(env, h_star)) / g
    b = env.prices.read + (env.prices.write - env.prices.read) * env.rho
    assert n_star - 1 <= interval <= n_star + 2 * b / sim.hold_rate(env) + 1


def test_cold_cache_compaction_pays_only_with_expensive_writes():
    one_hour = sim.Env(system=30_000, prices=sim.CLAUDE_CODE)
    five_min = sim.Env(system=30_000, prices=sim.CACHED)
    assert sim.cold_buy_cost(one_hour, 150_000) < 0
    assert sim.cold_buy_cost(five_min, 150_000) > 0


def test_cold_aware_never_costs_more_on_cold_calls():
    env = sim.Env(window=1_000_000, prices=sim.CLAUDE_CODE)
    rng = np.random.default_rng(1)
    for _ in range(10):
        g = rng.integers(1_000, 8_000, size=80).astype(float)
        cold = rng.random(80) < 0.05
        plain = sim.run(env, g, sim.FixedThreshold(0.92), cold=cold)[0]
        aware = sim.run(env, g, sim.ColdAware(sim.FixedThreshold(0.92)), cold=cold)[0]
        assert aware <= plain * (1 + 1e-9)
