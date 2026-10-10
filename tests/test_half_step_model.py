"""Half steps in the costs: the graph's marks, the rolling chart and the ranking's figures
(OWNER-DECISIONS 441i-441l, 461a; docs/stress/stress-number.md section 3).

What is pinned here, without a router or a database:

- the Lua transform's half-step marks (lua/routemaker_remap.lua `HALF_*`) are the ones the
  Python model of Valhalla's costing (`routemaker.calm.edge_factor`) reads, and modelled there
  they land where the docs say: 3.5 near the midpoint between LTS 3 and LTS 4, 2.5 short of
  its midpoint and never above LTS 3;
- the nine steps (1, 1.5, ... 4.5, 5) stay in order at every slider position, as the rolling
  chart prices them (`calm.road_multiplier`, with and without the edge's attributes);
- the ranking's LTS 3 / LTS 4 / Avoid metres count half steps at their midpoints
  (`refine.stress_totals`, `stress_weight_m`, `lts4_by_leg`).
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import presets, refine, routing
from routemaker import calm
from routemaker.calm import Road

LUA = Path(__file__).resolve().parent.parent / "lua" / "routemaker_remap.lua"
POSITIONS = [round(i / 10, 1) for i in range(11)]
STEPS = [(1, False), (1, True), (2, False), (2, True), (3, False), (3, True), (4, False),
         (4, True), (5, False)]  # fmt: skip


def lua_constant(name: str) -> str:
    found = re.search(rf'^M\.{name} = "([^"]+)"', LUA.read_text(), re.M)
    assert found, name
    return found.group(1)


def marked(base: Road, tier: int, half: bool) -> Road:
    """The edge as the graph holds it for a step: the transform's marks on `base`."""
    if tier >= 4:
        return dataclasses.replace(base, lanes=calm.GRADED_LANES)
    if half and tier == 3:
        return dataclasses.replace(base, lanes=calm.HALF_GRADED_LANES)
    if half and tier == 2:
        return dataclasses.replace(base, lanes=calm.HALF_LOW_LANES)
    return base


BASES = [
    Road(road_class=c, lanes=2, cycle_lane=lane, speed_limit_kph=kph, density=20)
    for c in ("secondary", "primary", "trunk")
    for lane in ("none", "dedicated")
    for kph in (40, 56, 72)
]


class TestTheLuaMarks:
    def test_the_transform_writes_what_the_model_reads(self) -> None:
        assert int(lua_constant("HALF_GRADED_SPEED")) == calm.HALF_GRADED_SPEED_KPH
        assert int(lua_constant("HALF_GRADED_LANES")) == calm.HALF_GRADED_LANES
        assert int(lua_constant("HALF_LOW_LANES")) == calm.HALF_LOW_LANES
        assert int(lua_constant("GRADED_LANES")) == calm.GRADED_LANES
        assert int(lua_constant("GRADED_SPEED")) == calm.GRADED_SPEED_KPH

    def test_three_and_a_half_is_read_at_its_own_speed_never_below_90_kmh(self) -> None:
        slow = Road(road_class="secondary", lanes=calm.HALF_GRADED_LANES, speed_limit_kph=40)
        fast = dataclasses.replace(slow, speed_limit_kph=105)
        assert calm.road_speed_kph(slow) == 90
        assert calm.road_speed_kph(fast) == 105

    @pytest.mark.parametrize("u", [0.05, 0.3, 0.6, 0.9])
    @pytest.mark.parametrize(
        "base", BASES, ids=lambda r: f"{r.road_class}-{r.cycle_lane}-{r.speed_limit_kph:.0f}"
    )
    def test_modelled_the_marks_land_between_their_levels(self, base, u) -> None:
        f = {(t, h): calm.edge_factor(marked(base, t, h), t, u) for t, h in STEPS if t < 5}
        assert f[(2, False)] <= f[(2, True)] <= f[(3, False)] <= f[(3, True)] <= f[(4, False)]
        # 3.5 adds about half of LTS 4's extra over LTS 3 (0.8 to 1.2 of the midpoint).
        mid35 = (f[(4, False)] - f[(3, False)]) / 2
        assert 0.8 <= (f[(3, True)] - f[(3, False)]) / mid35 <= 1.2
        # 2.5 stops short of its midpoint where the slider counts stress (a lift that reached it
        # would price 2.5 above LTS 3 at the fast end), and never passes LTS 3.
        if u <= 0.6:
            mid25 = (f[(3, False)] - f[(2, False)]) / 2
            assert 0.1 <= (f[(2, True)] - f[(2, False)]) / mid25 <= 0.55


def ladder(pricing: calm.Pricing, base: Road | None) -> list[float]:
    out = []
    for tier, half in STEPS:
        road = marked(base, tier, half) if base is not None else None
        ratio, _own = calm.road_multiplier(tier, "none", road, pricing, half)
        out.append(ratio)
    return out


class TestTheNineSteps:
    @pytest.mark.parametrize("u", POSITIONS)
    @pytest.mark.parametrize(
        "exposure",
        [presets.EXPOSURE_STANDARD, presets.EXPOSURE_STRESS_AVERSE],
        ids=["std", "averse"],
    )
    @pytest.mark.parametrize("base", [None, BASES[0], BASES[4]], ids=["no-edge", "sec", "pri"])
    def test_they_stay_in_order_at_every_slider_position(self, u, exposure, base) -> None:
        weights = (exposure.lts3, exposure.lts4, exposure.avoid)
        pricing = calm.Pricing(use_roads=u, rate=0.5 * (1 - u), weights=weights)
        values = ladder(pricing, base)
        pairs = list(zip(values, values[1:], strict=False))
        if u == 1.0 and base is not None:
            # The one known exception, at `use_roads` 1.0 (stress 0, the direct end): there
            # Valhalla prices LTS 2 and LTS 3 the same (the sidepath penalty is 3 x (1 - u),
            # nothing), so 2.5's lane mark puts it above both, by 15% at most. Every other
            # neighbour keeps its order. (docs/stress/stress-number.md section 3.)
            two, two_half, three = values[2], values[3], values[4]
            assert two == pytest.approx(three) and two_half <= 1.15 * three
            pairs = [p for i, p in enumerate(pairs) if i not in (3,)]
        assert all(a <= b + 1e-9 for a, b in pairs), values
        # 4.5 is never priced as Avoid.
        assert values[-2] < values[-1] or pricing.rate == 0

    def test_a_half_step_the_graph_does_not_carry_yet_takes_the_midpoint_figure(self) -> None:
        pricing = calm.Pricing(use_roads=0.3, rate=0.2)
        unmarked = BASES[0]
        ratio, own = calm.road_multiplier(3, "none", unmarked, pricing, half=True)
        assert ratio == pytest.approx(calm.multiplier(3, "none", pricing, half=True))
        assert own is False
        ratio, own = calm.road_multiplier(3, "none", marked(unmarked, 3, True), pricing, True)
        assert own is True
        low = calm.road_multiplier(3, "none", unmarked, pricing)[0]
        high = calm.road_multiplier(4, "none", marked(unmarked, 4, False), pricing)[0]
        assert low < ratio < high

    def test_the_rolling_chart_reads_a_pieces_half_step(self) -> None:
        pricing = calm.Pricing(use_roads=0.3, rate=0.2)
        road = marked(BASES[0], 3, True)
        whole, _ = calm.piece_steps([(100.0, 3, "none", road)], pricing)
        half, exact = calm.piece_steps([(100.0, 3, "none", road, True)], pricing)
        assert half[0].ratio > whole[0].ratio and exact
        # Through the section tiers too, while the section has the piece's own level.
        sections = [calm.Step(0.0, 100.0, 1.0, 3)]
        again, _ = calm.piece_steps([(100.0, 3, "none", road, True)], pricing, sections)
        assert again[0].ratio == pytest.approx(half[0].ratio)


def piece(metres=100.0):
    return SimpleNamespace(metres=metres, lon=0.0, lat=0.0)


def analysis(pieces, classes, **kw) -> refine.Analysis:
    stress = dict.fromkeys(("1", "2", "3", "4", "5", "unknown"), 0.0)
    for p, c in zip(pieces, classes, strict=True):
        stress[c[0]] += p.metres
    totals = refine.stress_totals(stress, refine.half_metres(pieces, classes))
    return refine.Analysis(
        length_m=sum(p.metres for p in pieces),
        cost_s=0.0,
        exposure_m=0.0,
        climb_m=0.0,
        pieces=pieces,
        classes=classes,
        events=None,
        **totals,
        **kw,
    )


def cls(tier, half=False):
    return routing.PieceClass(tier, "none", half=half)


class TestTheRankingsFigures:
    def test_half_steps_count_at_their_midpoints(self) -> None:
        stress = {"1": 0.0, "2": 0.0, "3": 100.0, "4": 200.0, "5": 50.0, "unknown": 0.0}
        halves = {"1": 10.0, "2": 40.0, "3": 60.0, "4": 30.0}
        totals = refine.stress_totals(stress, halves)
        # lts4_m: LTS 4 and Avoid, plus half of each 3.5 metre.
        assert totals["lts4_m"] == 200.0 + 50.0 + 0.5 * 60.0
        # lts3_m: LTS 3, plus half of each 2.5 metre, less the half of 3.5 counted as LTS 4.
        assert totals["lts3_m"] == 100.0 + 0.5 * 40.0 - 0.5 * 60.0
        assert totals["avoid_m"] == 50.0 and totals["lts45_m"] == 30.0

    def test_lts2_counts_one_and_a_half_and_two_and_a_half_at_their_midpoints(self) -> None:
        # 1.5 is half LTS 2; 2.5 half LTS 2 and half LTS 3 (the kids' LTS 2 weight reads it).
        stress = {"1": 80.0, "2": 120.0, "3": 0.0, "4": 0.0, "5": 0.0, "unknown": 0.0}
        halves = {"1": 20.0, "2": 40.0, "3": 0.0, "4": 0.0}
        totals = refine.stress_totals(stress, halves)
        assert totals["lts2_m"] == 120.0 + 0.5 * 20.0 - 0.5 * 40.0
        assert totals["lts3_m"] == 0.5 * 40.0
        # Each metre of 2.5 is counted once in all: half as LTS 2, half as LTS 3.
        whole = refine.stress_totals(stress, dict.fromkeys(halves, 0.0))
        assert totals["lts2_m"] + totals["lts3_m"] == whole["lts2_m"] + 0.5 * 20.0

    def test_the_worth_figure_weighs_lts2_with_its_half_steps(self) -> None:
        pieces = [piece(), piece(), piece()]
        classes = [cls("1", True), cls("2"), cls("2", True)]
        read = analysis(pieces, classes, lts2_weight=0.5)
        w = refine.WORTH_WEIGHTS
        lts2 = 50.0 + 100.0 + 50.0  # 1.5's half, LTS 2, 2.5's half
        expected = w.lts3 * 50.0 + w.lts3 * 0.5 * lts2  # 2.5's other half is LTS 3
        assert read.lts2_m == lts2
        assert refine.stress_weight_m(
            read, refine.Context.__new__(refine.Context)
        ) == pytest.approx(expected)

    def test_the_worth_figure_counts_four_and_a_half_at_the_midpoint_of_lts4_and_avoid(
        self,
    ) -> None:
        pieces = [piece(), piece(), piece(), piece()]
        classes = [cls("3"), cls("3", True), cls("4", True), cls("5")]
        read = analysis(pieces, classes)
        w = refine.WORTH_WEIGHTS
        expected = (
            w.lts3 * (100.0 + 100.0 - 50.0)  # LTS 3 and 3.5's half
            + w.lts4 * (100.0 + 50.0)  # 4.5 and 3.5's half (Avoid apart)
            + w.avoid * 100.0
            + (w.avoid - w.lts4) / 2 * 100.0  # 4.5's lift to the midpoint
        )
        assert refine.stress_weight_m(
            read, refine.Context.__new__(refine.Context)
        ) == pytest.approx(expected)
        # 4.5 weighs between LTS 4 and Avoid.
        w45 = w.lts4 + (w.avoid - w.lts4) / 2
        assert w.lts4 < w45 < w.avoid

    def test_the_lts4_hold_counts_three_and_a_half_as_half_a_metre(self) -> None:
        pieces = [piece(100.0), piece(100.0), piece(100.0), piece(100.0)]
        classes = [cls("4"), cls("3", True), cls("3"), cls("4", True)]
        read = analysis(pieces, classes, via_m=[200.0])
        # Leg 1: LTS 4 (100) and 3.5 (half of 100); leg 2: LTS 3 (0) and 4.5 (100).
        assert refine.lts4_by_leg(read) == [150.0, 100.0]
