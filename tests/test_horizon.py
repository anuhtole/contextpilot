"""Horizon-aware compaction: the gate, its robustness fallback, recent-growth tracking, and residual estimates."""
import numpy as np

from contextpilot import sim

ENV = sim.Env(system=36_000, out_per_call=600, window=1_000_000, prices=sim.CLAUDE_CODE)
NO_FALLBACK = 1e-9  # lam this small never triggers the rent fallback


def oracle(T):
    return lambda t: max(T - t - 1, 0)


def test_gate_with_unbounded_horizon_matches_inner_policy():
    g = np.full(400, 3_000.0)
    inner = sim.run(ENV, g, sim.ClosedForm())
    gated = sim.run(ENV, g, sim.HorizonGated(sim.ClosedForm(), lambda t: 1e12, lam=NO_FALLBACK))
    assert gated == inner


def test_oracle_gate_never_costs_more_and_skips_unrecoupable_compactions():
    strictly_better = 0
    for T in range(60, 400, 7):
        g = np.full(T, 3_000.0)
        inner, _ = sim.run(ENV, g, sim.ClosedForm())
        gated, _ = sim.run(ENV, g, sim.HorizonGated(sim.ClosedForm(), oracle(T), lam=NO_FALLBACK))
        assert gated <= inner + 1e-6
        strictly_better += gated < inner - 1e-6
    assert strictly_better > 0


def test_fallback_bounds_a_pessimistic_predictor():
    g = np.full(600, 3_000.0)
    inner, _ = sim.run(ENV, g, sim.ClosedForm())
    cost, k = sim.run(ENV, g, sim.HorizonGated(sim.ClosedForm(), lambda t: 0.0, lam=0.5))
    assert k > 0
    assert cost <= 1.3 * inner


def test_recent_growth_tracks_a_late_burst():
    g = np.concatenate([np.full(60, 500.0), np.full(80, 6_000.0)])
    pol = sim.ClosedFormRecent(half_life=10)
    s = pol.reset(ENV)
    for t, gt in enumerate(g):
        s = pol.observe(ENV, s, t, 0.0, gt)
    assert abs(s["g"] - 6_000) / 6_000 < 0.05


def test_empirical_residual_within_and_beyond_the_data():
    f = sim.empirical_residual([10, 20, 30], min_tail=1)
    assert f(4) == (5 + 15 + 25) / 3
    assert f(100) == 101  # Lindy fallback: expect about as many calls again
