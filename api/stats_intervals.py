"""Shared confidence-interval helpers for comparison and descriptive templates.

Newcombe's hybrid score method is used for the risk-difference interval rather
than the Wald interval because QI cell counts are often small and Wald
misbehaves near 0 and 100 percent. The pooled-variance mean-difference
interval matches the equal-variance t-test the caller already runs. The
Hodges-Lehmann shift with a Moses order-statistic interval is the
distribution-free companion to the Mann-Whitney test used in the
non-parametric branch, and needs no bootstrap or new dependency.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

Z_95 = 1.959963984540054
CI_LEVEL = 0.95
MIN_EXPECTED_CELL_COUNT = 5
MAX_EXACT_PAIRS = 4_000_000
HL_SUBSAMPLE_PER_GROUP = 2000


def wilson_interval(x: int, n: int) -> tuple[float, float]:
    """Wilson score interval for a single proportion x / n."""
    if n == 0:
        return (0.0, 1.0)
    z = Z_95
    denom = n + z * z
    centre = (x + z * z / 2) / denom
    half = z / denom * math.sqrt(x * (n - x) / n + z * z / 4)
    return (max(0.0, centre - half), min(1.0, centre + half))


def newcombe_rd_ci(
    x_post: int, n_post: int, x_pre: int, n_pre: int
) -> tuple[float, float, float]:
    """Newcombe's hybrid score interval for a risk difference (post minus pre)."""
    p_post, p_pre = x_post / n_post, x_pre / n_pre
    l_post, u_post = wilson_interval(x_post, n_post)
    l_pre, u_pre = wilson_interval(x_pre, n_pre)
    rd = p_post - p_pre
    lower = rd - math.sqrt((p_post - l_post) ** 2 + (u_pre - p_pre) ** 2)
    upper = rd + math.sqrt((u_post - p_post) ** 2 + (p_pre - l_pre) ** 2)
    return rd, max(-1.0, lower), min(1.0, upper)


def mean_diff_ci(pre, post) -> tuple[float, float, float]:
    """Pooled-variance t interval for a difference in means (post minus pre).

    Matches `stats.ttest_ind(pre, post)`, which defaults to `equal_var=True`,
    so the interval and the p-value describe the same model. Requires
    n1 + n2 > 2; the caller only reaches this branch after Shapiro-Wilk,
    which itself needs at least 3 per group.
    """
    n1, n2 = len(pre), len(post)
    sp2 = ((n1 - 1) * pre.var(ddof=1) + (n2 - 1) * post.var(ddof=1)) / (n1 + n2 - 2)
    se = math.sqrt(sp2 * (1 / n1 + 1 / n2))
    tcrit = float(stats.t.ppf(0.975, n1 + n2 - 2))
    diff = float(post.mean() - pre.mean())
    return diff, diff - tcrit * se, diff + tcrit * se


def hodges_lehmann_ci(pre, post) -> tuple[float, float, float, bool]:
    """Hodges-Lehmann shift estimate with a Moses order-statistic interval.

    The shift is the median of all pairwise post - pre differences, the
    distribution-free companion to the Mann-Whitney test that the Wilcoxon
    branch already runs. Both inputs must already be null-free; the only
    caller passes an already-dropna'd series, so this does not drop again.

    Subsamples to HL_SUBSAMPLE_PER_GROUP values per group when the full
    pairwise comparison would exceed MAX_EXACT_PAIRS, since uploads have no
    row limit and an unguarded outer product could exhaust memory.
    `np.linspace` indexing is deterministic, so there is no RNG and repeated
    runs give identical output.
    """
    a, b = np.sort(np.asarray(pre, dtype=float)), np.sort(np.asarray(post, dtype=float))
    subsampled = False
    if len(a) * len(b) > MAX_EXACT_PAIRS:
        subsampled = True
        a = a[np.linspace(0, len(a) - 1, min(len(a), HL_SUBSAMPLE_PER_GROUP)).astype(int)]
        b = b[np.linspace(0, len(b) - 1, min(len(b), HL_SUBSAMPLE_PER_GROUP)).astype(int)]
    d = np.sort(np.subtract.outer(b, a).ravel())
    n1, n2, N = len(a), len(b), d.size
    shift = float(np.median(d))
    se = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    k = int(math.floor(N / 2 - Z_95 * se))
    if k < 0:
        k = 0
    return shift, float(d[k]), float(d[N - 1 - k]), subsampled


def mean_ci(values) -> tuple[float | None, float | None]:
    """Student t interval on the mean, dropping nulls first."""
    s = values.dropna()
    n = len(s)
    if n < 2:
        return (None, None)
    m = s.mean()
    half = float(stats.t.ppf(0.975, n - 1)) * s.std(ddof=1) / math.sqrt(n)
    return (m - half, m + half)


def median_ci(values) -> tuple[float | None, float | None]:
    """Distribution-free order-statistic interval on the median.

    Returns (None, None) at n <= 5, where no 95 percent interval exists.
    """
    s = np.sort(values.dropna().to_numpy(dtype=float))
    n = s.size
    if n < 2:
        return (None, None)
    k = int(stats.binom.ppf(0.025, n, 0.5))
    if k < 1:
        return (None, None)
    return (float(s[k - 1]), float(s[n - k]))
