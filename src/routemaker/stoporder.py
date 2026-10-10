"""The best order to visit a ride's stops in (OWNER-DECISIONS 449, "Stops in any order").

A rider who has placed several stops can ask for them in the order that rides
least. The start stays first and the destination stays last; in a loop the
start is also the finish, so the loop's points arrive here with the start
again at the end and both ends are fixed the same way. Only the stops between
the two ends move.

The costs are a square matrix, `cost[i][j]` the cost of riding from point i to
point j, which need not equal `cost[j][i]` (one-way streets, climbs). A
missing cost (None, or infinity) is a pair the router could not join. Small
problems are solved exactly (Held-Karp dynamic programming over the subsets of
stops); past `EXACT_MAX_STOPS` the order is improved by local moves from
several starting orders, which is not guaranteed optimal and says so (`exact`).

The rider's own order wins any tie and any saving smaller than
`MIN_SAVING_FRACTION` of it: a reshuffle that buys nothing is not worth the
rider relearning their stop numbers.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

# Held-Karp is 2^k * k^2 steps for k stops: about 1.4 million at 13, measured
# at about a quarter of a second in Python. Twenty-three stops (the API's 25
# points less the two ends) would be about 4.4 billion, so past this the local
# search takes over.
EXACT_MAX_STOPS = 13

# The local search starts from the rider's order, the nearest-neighbour order
# and this many shuffles of the stops (seeded, so an answer is repeatable). On
# 200 random near-metric problems of ten stops, eight shuffles brought every
# answer within 1% of the exact one, where without them nine were more than
# 2% off; 23 stops take about a second.
RESTARTS = 8
SEED = 449

# A new order must save at least this share of the rider's order's cost.
MIN_SAVING_FRACTION = 0.01

# The local search's moves are each O(k^2) evaluations of an O(k) total; this
# bounds the improvement rounds so a pathological matrix cannot spin.
MAX_ROUNDS = 200


@dataclass(frozen=True)
class Ordered:
    """The order chosen, as indices into the points given, first and last included."""

    order: list[int]
    # The cost of the rider's own order and of the chosen one; infinity where a
    # leg could not be joined.
    before: float
    after: float
    # Whether the order is proven the cheapest (exact search) or only improved.
    exact: bool

    @property
    def changed(self) -> bool:
        return self.order != list(range(len(self.order)))


def _leg(cost: Sequence[Sequence[float | None]], i: int, j: int) -> float:
    value = cost[i][j]
    if value is None or value != value:  # None, or NaN
        return math.inf
    return float(value)


def total(cost: Sequence[Sequence[float | None]], order: Sequence[int]) -> float:
    """The cost of riding the points in `order`."""
    return sum(_leg(cost, a, b) for a, b in zip(order, order[1:], strict=False))


def _held_karp(cost, n: int) -> list[int]:
    """The cheapest order of points 1..n-2 between fixed ends 0 and n-1, exactly."""
    stops = list(range(1, n - 1))
    k = len(stops)
    # best[(mask, j)]: cheapest cost from 0 through the stops in mask, ending at stops[j].
    best: dict[tuple[int, int], float] = {}
    parent: dict[tuple[int, int], int] = {}
    for j, stop in enumerate(stops):
        best[(1 << j, j)] = _leg(cost, 0, stop)
    for mask in range(1, 1 << k):
        for j in range(k):
            if not mask & (1 << j):
                continue
            here = best.get((mask, j), math.inf)
            if here == math.inf:
                continue
            for nxt in range(k):
                if mask & (1 << nxt):
                    continue
                key = (mask | (1 << nxt), nxt)
                value = here + _leg(cost, stops[j], stops[nxt])
                if value < best.get(key, math.inf):
                    best[key] = value
                    parent[key] = j
    full = (1 << k) - 1
    end, end_cost = None, math.inf
    for j in range(k):
        value = best.get((full, j), math.inf) + _leg(cost, stops[j], n - 1)
        if value < end_cost:
            end, end_cost = j, value
    if end is None:
        return list(range(n))
    path = []
    mask, j = full, end
    while True:
        path.append(stops[j])
        previous = parent.get((mask, j))
        mask &= ~(1 << j)
        if previous is None:
            break
        j = previous
    return [0, *reversed(path), n - 1]


def _nearest_neighbour(cost, n: int) -> list[int]:
    left = list(range(1, n - 1))
    order = [0]
    while left:
        here = order[-1]
        nxt = min(left, key=lambda stop: (_leg(cost, here, stop), stop))
        order.append(nxt)
        left.remove(nxt)
    return [*order, n - 1]


def _improve(cost, order: list[int]) -> list[int]:
    """Local search over the middle: move a run of one to three stops elsewhere
    (or-opt), and reverse a run (2-opt, re-costed whole since costs are not
    symmetric). First improvement, until no move helps."""
    best = list(order)
    best_cost = total(cost, best)
    for _ in range(MAX_ROUNDS):
        improved = False
        n = len(best)
        for length in (1, 2, 3):
            for i in range(1, n - length):
                run = best[i : i + length]
                rest = best[:i] + best[i + length :]
                for at in range(1, len(rest)):
                    if at == i:
                        continue
                    candidate = rest[:at] + run + rest[at:]
                    value = total(cost, candidate)
                    if value < best_cost - 1e-9:
                        best, best_cost, improved = candidate, value, True
                        break
                if improved:
                    break
            if improved:
                break
        if not improved:
            for i in range(1, n - 2):
                for j in range(i + 1, n - 1):
                    candidate = best[:i] + best[i : j + 1][::-1] + best[j + 1 :]
                    value = total(cost, candidate)
                    if value < best_cost - 1e-9:
                        best, best_cost, improved = candidate, value, True
                        break
                if improved:
                    break
        if not improved:
            break
    return best


def best_order(cost: Sequence[Sequence[float | None]]) -> Ordered:
    """The order of the points that costs least with the first and last fixed.

    `cost` is n by n. With fewer than two stops between the ends there is
    nothing to choose, and the rider's order comes back unchanged.
    """
    n = len(cost)
    if any(len(row) != n for row in cost):
        raise ValueError("the cost matrix is not square")
    own = list(range(n))
    before = total(cost, own)
    if n < 4:
        return Ordered(own, before, before, exact=True)
    exact = n - 2 <= EXACT_MAX_STOPS
    if exact:
        chosen = _held_karp(cost, n)
    else:
        starts = [own, _nearest_neighbour(cost, n)]
        shuffler = random.Random(SEED)
        for _ in range(RESTARTS):
            middle = own[1:-1]
            shuffler.shuffle(middle)
            starts.append([0, *middle, n - 1])
        chosen = min((_improve(cost, start) for start in starts), key=lambda o: total(cost, o))
    after = total(cost, chosen)
    if after == math.inf or not _worth_it(before, after):
        return Ordered(own, before, before, exact=exact)
    return Ordered(chosen, before, after, exact=exact)


def _worth_it(before: float, after: float) -> bool:
    if before == math.inf:
        return after < math.inf
    return before - after > before * MIN_SAVING_FRACTION
