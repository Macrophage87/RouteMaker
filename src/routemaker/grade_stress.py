"""Uphill on a busy road counts worse than downhill: the uphill stress term.

FOLLOWUP-GRADE-STRESS (OWNER-DECISIONS 409). The owner, 2026-10-05, on Connecticut
Avenue NW: "It's a bit weird here because of a hill. I'd definitely ride down it, but
not so much up." Asked whether it should go in the route ranking or the router's costs,
and from what grade, the owner, 2026-10-10: "Maybe make it multiplicitive? Hill distance
* traffic-relative distance."

So a climb's extra effort is multiplied by the road's traffic weight:

    uphill stress (metres) = FACTOR x sum over rising windows of at least GRADE_FROM
                             of  run x (effort factor(grade) - 1) x traffic weight(tier)

- the "hill distance" is the climb's extra effort-equivalent distance, the run times
  how much more than the flat a metre at that grade costs (`routemaker.effort`, the
  standard cycling power model, Martin et al. 1998), over the effort model's windows
  of at least 300 m (a sample's noise is not a steep pitch). A descent adds nothing:
  its factor is floored at the flat, so downhill is unchanged;
- the "traffic-relative distance" is the ride's own exposure weight for the tier the
  climb is ridden on (`core.presets.Exposure`: LTS 3 once, LTS 4 twice and Avoid three
  times, eight and sixteen on the stress-averse ride types; LTS 2 only where the ride
  weighs it). A quiet street (LTS 1 and 2) weighs nothing, so a climb there costs what
  it does today, and the same climb on a busy road costs more the busier the road.

Pure: no database, no router. The calm search's ranking reads it (`core.refine`); the
router's costs and the graph do not (no rebuild).
"""

from __future__ import annotations

from collections.abc import Sequence

from routemaker import effort

# The grade where the uphill stress starts, rise over run: 3%, where the avoid half already
# starts to price a sustained climb (`routemaker.climbs.CLIMB_FREE_GRADE`: grades up to it
# "are ridden seated all day"). A default for the owner to confirm with before and after
# routes.
GRADE_FROM = 0.03
# The share of the climb's extra effort that counts, per unit of traffic weight. At 0.25
# a climb of 0.62 mi (1 km) at 4% (about 130 ft (40 m) gained; about 2.75 extra
# effort-metres a metre at 198 lb (90 kg)) counts about 0.43 mi (690 m) of quiet riding on
# LTS 3 and 0.86 mi (1,380 m) on LTS 4 at the standard weights; at 6%, 0.64 mi (1,030 m)
# and 1.28 mi (2,060 m). A default for the owner to confirm.
FACTOR = 0.25


def uphill_windows(
    profile: Sequence[tuple[float, float | None]],
    grade_from: float = GRADE_FROM,
    mass_kg: float = effort.MASS_KG,
) -> list[tuple[float, float, float]]:
    """The climbs of a profile ((metres along, elevation or None),
    `core.routing.grade_profile`) that count: (start, end, extra) for each of the
    effort model's windows rising at `grade_from` or more, `extra` the extra
    effort-equivalent metres per metre over the flat (`effort.effort_factor` - 1)."""
    out = []
    for start, end, rise in effort.windows_along(profile):
        run = end - start
        if run <= 0 or rise / run < grade_from:
            continue
        out.append((start, end, effort.effort_factor(rise / run, mass_kg) - 1.0))
    return out


def uphill_by_tier(
    windows: Sequence[tuple[float, float, float]],
    stretches: Sequence[tuple[float, float, str]],
) -> dict[str, float]:
    """The climbs' extra effort-equivalent metres by the stress tier they are ridden on:
    each window's extra per metre times its overlap with each stretch ((start, end, tier),
    in metres along the route, in order). Tiers no climb reaches are left out."""
    out: dict[str, float] = {}
    j = 0
    for w_start, w_end, extra in windows:
        # The stretches are in order and so are the windows: skip those that end before.
        while j < len(stretches) and stretches[j][1] <= w_start:
            j += 1
        k = j
        while k < len(stretches) and stretches[k][0] < w_end:
            s_start, s_end, tier = stretches[k]
            overlap = min(w_end, s_end) - max(w_start, s_start)
            if overlap > 0:
                out[tier] = out.get(tier, 0.0) + overlap * extra
            k += 1
    return out


def uphill_stress_m(by_tier: dict[str, float], weights: dict[str, float]) -> float:
    """The uphill stress in metres of quiet riding: FACTOR times each tier's climbing
    (`uphill_by_tier`) times the ride's traffic weight for it (0 where it has none)."""
    return FACTOR * sum(weights.get(tier, 0.0) * metres for tier, metres in by_tier.items())
