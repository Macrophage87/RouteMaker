"""`pytest.approx` for a line: a list of (lon, lat) points.

pytest 9.2 refuses `pytest.approx` on a list of tuples ("does not support
nested data structures"). Before it, the tuples were not compared approximately
at all: each fell back to plain `==`. This compares each point coordinate by
coordinate, and either side may hold tuples or lists.

The default tolerance is absolute, 1e-6 degrees (about 4 in [0.1 m]): one unit
of a polyline6 shape, which is what most of these lines have been through. A
relative tolerance would be wider than that at -77 degrees.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import pytest

POLYLINE6_UNIT = 1e-6


class approx_points:  # noqa: N801 - read like pytest.approx at the call site
    def __init__(self, points: Iterable[Sequence[float]], **tolerance: float) -> None:
        self.points = [tuple(point) for point in points]
        self.tolerance = tolerance or {"abs": POLYLINE6_UNIT}

    def __eq__(self, actual: object) -> bool:
        try:
            got = [tuple(point) for point in actual]  # type: ignore[attr-defined]
        except TypeError:
            return False
        return len(got) == len(self.points) and all(
            g == pytest.approx(w, **self.tolerance) for g, w in zip(got, self.points, strict=True)
        )

    def __repr__(self) -> str:
        return f"approx_points({self.points!r}, {self.tolerance!r})"
