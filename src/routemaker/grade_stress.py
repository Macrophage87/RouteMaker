"""The hill factor: one stress figure, traffic weight times hill (OWNER-DECISIONS 409).

FOLLOWUP-GRADE-STRESS. The owner, 2026-10-05, on Connecticut Avenue NW: "It's a bit weird
here because of a hill. I'd definitely ride down it, but not so much up." Asked whether it
should go in the route ranking or the router's costs, and from what grade, the owner,
2026-10-10: "Maybe make it multiplicitive? Hill distance * traffic-relative distance." And,
2026-10-11: "Why not combine it all into a single stress metric? Basically you calculate
the uphill portion and then the traffic stress portion. Multiply the two together." "The
sliders control the various coefficients for each component." "So a fine with hills will
basically be multiplying everything by 1." "We wanted some stress for extreme downhills."

So every stretch of a route counts, in the calm search's stress figures,

    stress-weighted metres = run x traffic weight(tier) x hill factor

    hill factor = 1 + coefficient x extra

- the traffic weight is the ride's own exposure weight for the tier (`core.presets.Exposure`),
  and the stress slider sets how much it counts, as before;
- `extra` is how much more than the flat a metre of the window costs, in effort-equivalent
  metres (`routemaker.effort`, the standard cycling power model, Martin et al. 1998), over
  the effort model's windows of at least 300 m (a sample's noise is not a steep pitch):
  - on a climb of at least GRADE_FROM, `effort_factor(grade) - 1`;
  - on a descent steeper than the ride type's brake grade (`presets.BRAKE_GRADES`,
    OWNER-DECISIONS 56: "a point where you're riding the breaks"), what a climb as steep
    as the excess would be, `effort_factor(grade - brake grade) - 1`: the shape of
    `climbs.descent_cost_s`, which weighs the excess past the brake grade as a climb's
    excess past CLIMB_FREE_GRADE. A ride type with no brake grade gets none;
  - 0 on the flat, on gentle climbs and on gentle descents, so the factor is 1 there;
- the coefficient is the hills slider's (`coefficient_for`): FACTOR at its detent, 0 at
  "fine with hills" (the factor exactly 1 everywhere), twice FACTOR at full avoid.

Pure: no database, no router. The calm search's figures read it (`core.refine.analyse`);
the router's costs, the graph and what the rider is shown (the map's LTS colours, the
stress chart, the summary's LTS miles) do not (no rebuild).
"""

from __future__ import annotations

from collections.abc import Sequence

from routemaker import effort

# The grade where the uphill stress starts, rise over run: 3%, where the avoid half already
# starts to price a sustained climb (`routemaker.climbs.CLIMB_FREE_GRADE`: grades up to it
# "are ridden seated all day"). A default for the owner to confirm with before and after
# routes.
GRADE_FROM = 0.03
# The hill factor's coefficient at the hills slider's detent (`coefficient_for`): the share
# of a window's extra effort that counts. At 0.25 a climb of 0.62 mi (1 km) at 4% (about
# 130 ft (40 m) gained; about 2.75 extra effort-metres a metre at 198 lb (90 kg)) has a
# factor of about 1.69, so it counts 0.43 mi (690 m) of LTS 3 more than the same road on
# the flat, at LTS 3's weight of 1, and 0.86 mi (1,380 m) more on LTS 4 (weight 2); at 6%
# (factor about 2.03), 0.64 mi (1,030 m) and 1.28 mi (2,060 m). A default for the owner to
# confirm.
FACTOR = 0.25


def coefficient_for(hills: int) -> float:
    """The hill factor's coefficient at a hills slider position (-100 to 100, detent 0;
    the owner: "The sliders control the various coefficients for each component"):
    FACTOR at the detent, rising in proportion to the avoid half's weight (-hills/100)
    to twice FACTOR at full avoid, and falling with the right half to 0 at its end, "fine
    with hills" (and Mountain Goat's seeking end), where the factor is 1 everywhere."""
    return FACTOR * min(2.0, max(0.0, 1.0 - hills / 100))


def hill_windows(
    profile: Sequence[tuple[float, float | None]],
    grade_from: float = GRADE_FROM,
    mass_kg: float = effort.MASS_KG,
    brake_grade: float | None = None,
) -> list[tuple[float, float, float]]:
    """The windows of a profile ((metres along, elevation or None),
    `core.routing.grade_profile`) that count: (start, end, extra) for each of the effort
    model's windows rising at `grade_from` or more (`extra` the extra effort-equivalent
    metres per metre over the flat, `effort.effort_factor` - 1) or, with a `brake_grade`,
    falling more steeply than it (`extra` that of a climb as steep as the excess)."""
    out = []
    for start, end, rise in effort.windows_along(profile):
        run = end - start
        if run <= 0:
            continue
        grade = rise / run
        if grade >= grade_from:
            out.append((start, end, effort.effort_factor(grade, mass_kg) - 1.0))
        elif brake_grade is not None and -grade > brake_grade:
            out.append((start, end, effort.effort_factor(-grade - brake_grade, mass_kg) - 1.0))
    return out


def hill_factors(
    windows: Sequence[tuple[float, float, float]],
    lengths: Sequence[float],
    coefficient: float,
) -> list[float]:
    """Each piece's hill factor, the pieces `lengths` metres long in the order ridden:
    1 + `coefficient` x its windows' extra per metre, shared by overlap, so the piece's
    metres times its factor are its run plus `coefficient` x the extra over it. Exactly 1
    where no window reaches or the coefficient is 0."""
    out = [1.0] * len(lengths)
    if coefficient == 0 or not windows:
        return out
    j, along = 0, 0.0
    bounds = []
    for metres in lengths:
        bounds.append((along, along + metres))
        along += metres
    for w_start, w_end, extra in windows:
        # The pieces are in order and so are the windows: skip those that end before.
        while j < len(bounds) and bounds[j][1] <= w_start:
            j += 1
        k = j
        while k < len(bounds) and bounds[k][0] < w_end:
            a, b = bounds[k]
            overlap = min(w_end, b) - max(w_start, a)
            if overlap > 0 and b > a:
                out[k] += coefficient * extra * overlap / (b - a)
            k += 1
    return out
