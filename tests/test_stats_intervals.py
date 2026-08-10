"""Hand-computed anchors for api/stats_intervals.py, pinned to 4 decimal places."""
import numpy as np
import pandas as pd

from api.stats_intervals import (
    MAX_EXACT_PAIRS,
    hodges_lehmann_ci,
    median_ci,
    newcombe_rd_ci,
    wilson_interval,
)


def test_newcombe_rd_ci_matches_hand_computed_anchor():
    rd, lo, hi = newcombe_rd_ci(30, 100, 10, 100)
    assert round(rd, 4) == 0.2000
    assert round(lo, 4) == 0.0900
    assert round(hi, 4) == 0.3058
    assert -1.0 < lo < hi < 1.0
    assert not (lo <= 0.0 <= hi)


def test_wilson_interval_stays_within_zero_and_one():
    lo0, hi0 = wilson_interval(0, 10)
    lo10, hi10 = wilson_interval(10, 10)
    assert (round(lo0, 4), round(hi0, 4)) == (0.0000, 0.2775)
    assert (round(lo10, 4), round(hi10, 4)) == (0.7225, 1.0000)
    for lo, hi in [(lo0, hi0), (lo10, hi10)]:
        assert 0.0 <= lo <= hi <= 1.0


def test_median_ci_none_at_small_n_and_bracket_at_larger_n():
    assert median_ci(pd.Series([1, 2, 3, 4, 5])) == (None, None)
    lo, hi = median_ci(pd.Series(range(1, 21)))
    assert (lo, hi) == (6.0, 15.0)
    assert lo < 10.5 < hi


def test_hodges_lehmann_ci_recovers_known_shift():
    pre = pd.Series(np.arange(1, 31, dtype=float))
    post = pre + 4.0
    shift, lo, hi, subsampled = hodges_lehmann_ci(pre, post)
    assert shift == 4.0
    assert lo <= shift <= hi
    assert subsampled is False


def test_hodges_lehmann_ci_subsamples_above_max_exact_pairs():
    n = 2100
    assert n * n > MAX_EXACT_PAIRS
    pre = pd.Series(np.arange(n, dtype=float))
    post = pre + 2.0
    shift, lo, hi, subsampled = hodges_lehmann_ci(pre, post)
    assert subsampled is True
    assert shift == 2.0
    assert lo <= shift <= hi
