"""Measured Claude Code compaction costs: generated summary tokens and the evicted prefix."""
import pytest

from contextpilot import sim

ENV = sim.Env(system=36_000, prices=sim.CLAUDE_CODE, window=1_000_000)


def test_only_the_generated_part_of_sigma_is_billed_as_output():
    full = ENV.with_(summary_out=None)
    h = 120_000
    assert sim.buy_cost(full, h) - sim.buy_cost(ENV, h) == pytest.approx(
        ENV.prices.out * (ENV.sigma_min - ENV.summary_out))


def test_summary_out_never_exceeds_sigma():
    small = ENV.with_(sigma_min=2_000, sigma_max=2_000)
    assert sim.summary_tokens(small, 50_000) == 2_000


def test_prefix_rewrite_adds_its_cache_premium_to_the_buy_cost():
    none = ENV.with_(prefix_rewrite=0.0)
    p = ENV.prices
    assert sim.buy_cost(ENV, 80_000) - sim.buy_cost(none, 80_000) == pytest.approx(
        (p.write - p.read) * ENV.prefix_rewrite)


@pytest.mark.parametrize("g", [700, 3_000, 6_000])
def test_closed_form_matches_numeric_optimum_with_measured_terms(g):
    assert sim.eoq_history(ENV, g) == pytest.approx(sim.steady_state_optimum(ENV, g), rel=0.02)
