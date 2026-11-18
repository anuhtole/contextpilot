import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
import model2  # noqa: E402
from contextpilot import sim  # noqa: E402

FLAT = sim.Prices(read=0.1, write=2.0, out=5.0)


def test_rates_are_five_times_higher_only_above_the_tier():
    assert model2.multiple(100_000) == 1.0
    assert model2.multiple(100_001) == 5.0
    assert model2.multiple(500_000, tiered=False) == 1.0


def test_replay_bills_each_call_at_its_own_tier():
    # Arrange: two calls of 10k growth on a 95k prefix; the first prompt is 105k
    growth = np.array([10_000.0, 10_000.0])
    # Act
    tiered = model2.replay(95_000, growth, [], out_per_call=0, prices=FLAT)
    flat = model2.replay(95_000, growth, [], out_per_call=0, prices=FLAT, tiered=False)
    # Assert: both calls sit above 100k, so the whole bill is 5x
    assert flat == 0.1 * 95_000 + 2 * 10_000 + 0.1 * 105_000 + 2 * 10_000
    assert tiered == 5 * flat


def test_compacting_below_the_tier_pays_off_over_a_long_session():
    # Arrange: history reaches 80k on a 30k prefix, then grows 1k per call for 40 calls
    growth = np.concatenate([[0.0, 80_000.0], np.full(40, 1_000.0)])
    # Act
    kept = model2.replay(30_000, growth, [], out_per_call=0, prices=FLAT)
    compacted = model2.replay(30_000, growth, [2], out_per_call=0, prices=FLAT)
    # Assert
    assert compacted < kept


def test_growth_replaces_the_drop_at_a_compaction():
    ctx = np.array([20_000.0, 30_000.0, 40_000.0, 15_000.0, 25_000.0])
    g = model2.growth_of(ctx, [3])
    assert list(g) == [0.0, 10_000.0, 10_000.0, 10_000.0, 10_000.0]
