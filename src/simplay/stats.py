"""Small statistics helpers shared by the analysis and the playground."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval; the right binomial CI for small n and rates near 0 or 1."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar(a: int, b: int) -> float:
    """Exact two-sided McNemar P from the discordant counts of two paired checks."""
    n = a + b
    if n == 0:
        return 1.0
    k = min(a, b)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2**n)


def cluster_bootstrap(
    items: Sequence[tuple[object, bool]],
    seed: int = 1,
    rounds: int = 4000,
) -> tuple[float, float]:
    """Percentile CI for a rate, resampling whole clusters.

    Mutants on the same source line are not independent, so the clusters are
    source lines rather than mutants.
    """
    clusters: dict[object, list[bool]] = {}
    for key, hit in items:
        clusters.setdefault(key, []).append(hit)
    keys = list(clusters)
    if not keys:
        return (0.0, 0.0)
    rng = random.Random(seed)
    rates = []
    for _ in range(rounds):
        picks = [clusters[keys[rng.randrange(len(keys))]] for _ in keys]
        flat = [h for c in picks for h in c]
        rates.append(sum(flat) / len(flat))
    rates.sort()
    return (rates[int(0.025 * rounds)], rates[int(0.975 * rounds)])


def fmt_rate(hits: int, n: int) -> str:
    if not n:
        return "   -/-"
    lo, hi = wilson(hits, n)
    return f"{hits:3d}/{n:<3d} = {hits / n:.3f}  [{lo:.3f}, {hi:.3f}]"


def table(rows: Sequence[Sequence[str]], headers: Sequence[str]) -> str:
    """Left-aligned fixed-width table."""
    widths = [max(len(str(r[i])) for r in [headers, *rows]) for i in range(len(headers))]
    out = ["  ".join(str(h).ljust(w) for h, w in zip(headers, widths, strict=True))]
    for r in rows:
        out.append("  ".join(str(c).ljust(w) for c, w in zip(r, widths, strict=True)))
    return "\n".join(out)
