"""Agency bicycle stress ratings, in the owner's order of precedence (v0.7.0).

The owner, 2026-10-13: "1. Ratings from Community Input (including my judgment)
win over everything 2. Ratings from the local government win over a formula
3. If neither are available, we use the formula criteria." And, of Maryland's
statewide layer against Montgomery's: "Where they differ, put the county level
over the state." So a way an agency rates takes that agency's level in place of
the classifier's tier, the most local agency's where several rate it, and the
owner's own rules and rows still rank above (`stress.rural_floor`, the override
rows in `pipeline.overrides`).

Every rating held for a way is kept beside the one used, because the owner asked
for "all the relevant information in the tab when viewing the road": the road
panel lists each, with which one the map uses and why.

Levels are the agency's own numbers on our scale: 1 to 4 with half steps, and 5
for an agency's highest level, which is Avoid ("if any ratings agency has it as
LTS5. We should keep that unless there's a clear case for downgrading"), except
Montgomery's 5, which means very high stress and is our 4.5 (`READ_AS`).
Montgomery's 0.5 ("None") is no rating and is dropped before it gets here. MDOT SHA's
5 is a ban, not a level: it also closes the way to bicycles (`PROHIBITING_LEVELS`).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, replace

from .stress import Stress, StressResult

# How local an agency is. Lower wins: a county's rating over a state's.
COUNTY = 1
STATE = 2

# The agencies whose ratings may set a tier, with their display names and how
# local each is. An agency's layer is added here only once the owner has
# approved its download and its licence allows publishing a derivative:
# Arlington's Bike Comfort Index is for internal comparison only (OWNER-DECISIONS
# 152, 155) and never appears. Alexandria's layers are cleared (CC0, the city's
# OpenData portal, Alex311 request 26-00041150, 2026-10-16) but rate nothing:
# Transport Streets has posted speeds and no LTS, Bike Lane Routes facility types
# only, so the city's speeds reach the classifier as street facts
# (`agency_roads.parse_alexandria_transport_streets`), not as a rating here.
AGENCIES: dict[str, tuple[str, int]] = {
    "moco": ("Montgomery County Planning", COUNTY),
    # The District is its own local government: its rating ranks with a county's.
    "ddot": ("DDOT", COUNTY),
    "mdot-sha": ("MDOT SHA", STATE),
}

AGENCY_RULE = "agency rating"

# An agency layer older than the bike facilities on the ground. DDOT's is its 2020 Level of
# Traffic Stress (`scripts/install_agency_lts.py`), from before K Street's, Irving Street's and
# other lanes since. The owner, 2026-10-21, of 14th Street NW ("there's a bike lane on 14th street
# but it's not shown that way"; "It's some frankenstein hybrid of LTS4 and LTS1"), choosing
# "Formula wins where newer": the layer stays, but where a bike facility is mapped on the way the
# formula's tier stands, since the formula reads the facility as it is now. The rating is still
# recorded for the road panel.
SUPERSEDED_WHERE_FACILITY = {"ddot": "DDOT's 2020 layer predates the bike facility mapped here"}
# The road panel's `used` where every rating on the way was set aside.
FORMULA_USED = "formula"

# An agency level that says bicycles may not use the road at all, which is a fact about
# access and not a stress level (the owner, 2026-10-19: "MDOT LTS 5 means that bikes are
# prohibited. MoCo LTS5 is extremely high stress but allowed." and "Just don't draw them or
# consider them for routing."). MDOT SHA's 5 is "Bicycle access is prohibited by managing
# roadway agency" (its LTS methodology; `scripts/install_agency_lts.py`). So any such
# rating closes the way to bicycles whichever agency's level the map uses
# (`pipeline.agency_ratings.prohibited_closures`); DDOT's 5 stays Avoid, and Montgomery's
# is our 4.5 (`READ_AS`).
PROHIBITING_LEVELS: dict[str, float] = {"mdot-sha": 5.0}
# The way's `rm:no_bicycle` reason, and the road panel's code for it
# (`core.segment_info.ACCESS_WORDS`).
PROHIBITED_NO_BICYCLE = "mdot_prohibited"

# An agency level that means something else on our scale, as the level the map uses. The owner,
# 2026-10-19: "5 in our case means technically legal, but not a real option. MoCo's mean very
# high stress, what our 4.5 means." (and of Darnestown Road at Dawsonville: "While it can be very
# high stress, it's not a complete No, as there's no real alternatives"). So Montgomery's 5 is our
# 4.5, urban and rural alike, and so are its LTS 5 rows of 2026-10-01 (`row_level`). Our
# own 5, Avoid, stays for roads that are legal but not a real option: motorway-like roads, a
# hand-set Avoid, a side path riders are asked to use. MDOT SHA's 5 is a ban and DDOT's 5 Avoid.
READ_AS: dict[str, dict[float, float]] = {"moco": {5.0: 4.5}}
# The reason after the agency's level in the rule (`apply`), read back by the road panel
# (`core.segment_info`). No comma: the rule's commas separate its reasons.
READ_AS_REASON = "our LTS 4.5"


def map_level(agency: str, level: float) -> float:
    """An agency's level as the map uses it: its own, except where `READ_AS` says otherwise."""
    return READ_AS.get(agency, {}).get(float(level), level)


def row_level(adjustment_id: str | None, level: float) -> float:
    """An override row's level as the map uses it: an agency's rating loaded as a row
    (`adjustment_source`; Montgomery's `moco-lts5-*`) reads as that agency's level does
    (`map_level`), and the owner's and the community's rows are their own."""
    source = adjustment_source(adjustment_id)
    return map_level(source, level) if source in AGENCIES else level


def prohibiting(ratings: Iterable[AgencyRating]) -> AgencyRating | None:
    """The rating among `ratings` that prohibits bicycles (`PROHIBITING_LEVELS`), or None."""
    for rating in ratings:
        if PROHIBITING_LEVELS.get(rating.agency) == rating.level:
            return rating
    return None


# Agencies whose ratings the owner may see in Review, an instance admin's view and not public,
# before their public use is confirmed (the owner, 2026-10-16: "You can display them in review as
# that's not public. At least until I get a response back from Arlington and Alexandria"; "They can
# still inform them"). Each is its name; whether its public use is confirmed is
# `PUBLIC_USE_CONFIRMED`'s alone. Review reads their files whatever the flag (it is not public),
# and it never lets them decide a level: a ruling one informs is the admin's own owner override.
# They reach the tiles, the road panel, routing, an export, a share card or a link preview only
# through `AGENCIES` and the pipeline, never through Review.
PENDING_AGENCIES: dict[str, str] = {
    "arlington": "Arlington",
    "alexandria": "Alexandria",
}
# The one switch: an agency's public use confirmed, by its key. While False, Review labels it
# "(pending permission)", counts it in a disagreement's spread as information only, and offers
# no one-click "Use" of its level. The City of Alexandria confirmed CC0 for its OpenData data on
# 2026-10-16 (Alex311 request 26-00041150) and its two layers are cleared (docs/SOURCES.md, "City
# of Alexandria"), so its flag is True. Arlington's stays False until it answers.
PUBLIC_USE_CONFIRMED: dict[str, bool] = {
    "arlington": False,
    "alexandria": True,
}
PENDING_LABEL = " (pending permission)"


def public_use_confirmed(agency: str) -> bool:
    """Whether an agency's ratings may reach a public surface: `PUBLIC_USE_CONFIRMED`'s flag for
    one of `PENDING_AGENCIES` (False while unset), True for any other."""
    if agency not in PENDING_AGENCIES:
        return True
    return PUBLIC_USE_CONFIRMED.get(agency, False)


def review_name(agency: str) -> str:
    """A `PENDING_AGENCIES` agency's name in Review: "Arlington (pending permission)" until its
    public use is confirmed."""
    name = PENDING_AGENCIES[agency]
    return name if public_use_confirmed(agency) else name + PENDING_LABEL


# Whose rating an approved override row is. Most rows are the owner's own call, but
# some carry an agency's rating that was loaded as a row before v0.7.0 read the
# agency layers directly: `fixtures/overrides/2026-10-01-owner-moco-lts5-avoid.json`
# holds Montgomery County Planning's LTS 5, and the road panel called it "Owner
# override" (the owner, 2026-10-14: "It's also listed as owner override when it was
# county data"). The row's adjustment id says whose it is, by its prefix: ids are
# stable across rebuilds and shared by every way of one stretch.
OWNER = "owner"
COMMUNITY = "community"
ADJUSTMENT_SOURCES: tuple[tuple[str, str], ...] = (
    ("moco-lts5-", "moco"),
    ("mdot-sha-", "mdot-sha"),
    ("ddot-", "ddot"),
    # A reviewed rider suggestion (the owner's order of 2026-10-13: "Ratings from
    # Community Input (including my judgment) win over everything").
    ("community-", COMMUNITY),
)
SOURCE_NAMES = {OWNER: "Owner", COMMUNITY: "Community"}


def adjustment_source(adjustment_id: str | None) -> str:
    """Whose rating an override row is: an agency key of `AGENCIES`, `community`,
    or `owner` (every other row: the owner's own call)."""
    for prefix, source in ADJUSTMENT_SOURCES:
        if (adjustment_id or "").startswith(prefix):
            return source
    return OWNER


def source_name(source: str) -> str:
    """A source key (`adjustment_source`'s, or an agency's) as the road panel names it."""
    if source in AGENCIES:
        return AGENCIES[source][0]
    return SOURCE_NAMES.get(source, source)


@dataclass(frozen=True)
class AgencyRating:
    """One agency's level for one way."""

    agency: str
    level: float

    @property
    def name(self) -> str:
        return AGENCIES[self.agency][0]

    @property
    def rank(self) -> int:
        return AGENCIES[self.agency][1]


def level_problem(level: float) -> str | None:
    """Why a level cannot be used, or None: 1 to 5 in half steps, not 5.5."""
    if level * 2 != int(level * 2):
        return f"level {level} is not a whole or half step"
    if not 1 <= level <= 5:
        return f"level {level} is outside 1 to 5"
    return None


def tier_of(level: float) -> tuple[Stress, bool]:
    """A level as (tier, half): 2.5 is LTS 2 and a half; 5 is Avoid."""
    if level_problem(level):
        raise ValueError(level_problem(level))
    whole = int(level)
    return Stress(whole), level != whole


def set_aside(rule: str | None) -> frozenset[str]:
    """The agencies whose rating `apply` set aside on a way, read from its rule."""
    return frozenset(
        agency for agency, reason in SUPERSEDED_WHERE_FACILITY.items() if reason in (rule or "")
    )


def chosen(ratings: Iterable[AgencyRating]) -> AgencyRating | None:
    """The rating the map uses: the most local agency's. Two agencies at the same
    rank on one way (two counties meeting at a line) take the higher level, the
    stress-averse reading."""
    ranked = sorted(ratings, key=lambda r: (r.rank, -map_level(r.agency, r.level)))
    return ranked[0] if ranked else None


def apply(
    result: StressResult, ratings: Iterable[AgencyRating], facility_mapped: bool = False
) -> StressResult:
    """The way's tier with the agency's level in place of the classifier's.

    The classifier's tier is kept (`formula_tier`, `formula_rule`) and every
    rating is recorded (`agency_ratings`), for the road panel. An agency rating
    replaces the formula's only; a tier the owner set comes later and wins.
    The level used is `map_level`'s: Montgomery's 5 is LTS 4.5. With `facility_mapped` (a
    bike path or lane on the way) an agency in SUPERSEDED_WHERE_FACILITY is not used."""
    ratings = tuple(ratings)
    usable = [r for r in ratings if not (facility_mapped and r.agency in SUPERSEDED_WHERE_FACILITY)]
    # Each set-aside rating's reason, appended to the rule: the road panel reads it back
    # (`set_aside`) to tell which rating was used.
    reasons = sorted({SUPERSEDED_WHERE_FACILITY[r.agency] for r in ratings if r not in usable})
    pick = chosen(usable)
    if pick is None:
        if not ratings:
            return result
        return replace(
            result,
            rule=", ".join([result.rule, *reasons]),
            formula_tier=result.tier,
            formula_rule=result.rule,
            agency_ratings=tuple(sorted(ratings, key=lambda r: r.rank)),
        )
    level = map_level(pick.agency, pick.level)
    if level < pick.level and result.tier is Stress.AVOID:
        # A level read as a lower one (Montgomery's 5 as 4.5) does not lower the
        # formula's own Avoid (a bike-legal motorway, a side path's road): the
        # agency's highest level agrees with it. The rating is still recorded.
        return replace(result, agency_ratings=tuple(sorted(ratings, key=lambda r: r.rank)))
    tier, half = tier_of(level)
    # The other agencies' levels are in `agency_ratings`, not the rule: the
    # rule's commas separate the reasons appended after it (`stress.rural_floor`).
    why = f"{AGENCY_RULE}: {pick.name} LTS {pick.level:g}"
    if level != pick.level:
        why += f", {READ_AS_REASON}"
    why = ", ".join([why, *reasons])
    return replace(
        result,
        tier=tier,
        half=half,
        rule=why,
        formula_tier=result.tier,
        formula_rule=result.rule,
        agency_ratings=tuple(sorted(ratings, key=lambda r: r.rank)),
        # A tier set afresh drops the smoothing record, as an override row does.
        unsmoothed_tier=None,
    )


# The rebuild's list of the roads review RL-3 is about (the owner, 2026-10-16: "defer to local
# government ratings"; the formula holds a painted lane on a two-way street with two or more
# lanes each way at LTS 3, `stress.painted_lane_two_way_multilane`): each such road in the
# District or rated by DDOT or Montgomery, with the agency's level beside the formula's, for his
# review. A Virginia road is listed too, scope `comparison`, with the formula's level alone: the
# admin-only Review puts Arlington's level beside it from its own file
# (`core.stress_review.pending_ratings`), so Arlington's ratings never reach this report.
PAINTED_LANE_REPORT_NAME = "painted-lane-agency-vs-formula.csv"
PAINTED_LANE_AGENCIES = ("ddot", "moco")
PAINTED_LANE_COMPARISON = "comparison"
PAINTED_LANE_COLUMNS = (
    "way_id",
    "name",
    "state",
    "scope",
    "agency",
    "agency_level",
    "formula_level",
    "formula_rule",
    "differs",
)


def painted_lane_row(
    way_id: int, name: str, state: str, result: StressResult
) -> dict[str, str] | None:
    """One road's row of `PAINTED_LANE_REPORT_NAME`, or None where it is out of scope (not in
    the District, not rated by DDOT or Montgomery, not in Virginia). The caller has already
    found it to be one of the RL-3 roads."""
    local = [r for r in result.agency_ratings if r.agency in PAINTED_LANE_AGENCIES]
    pick = chosen(local)
    if pick is not None:
        scope = "DC" if pick.agency == "ddot" else "MoCo"
    elif state == "DC":
        scope = "DC"
    elif state == "VA":
        scope = PAINTED_LANE_COMPARISON
    else:
        return None
    level = map_level(pick.agency, pick.level) if pick else None
    formula = result.formula_tier if result.formula_tier is not None else result.tier
    rule = result.formula_rule if result.formula_rule is not None else result.rule
    return {
        "way_id": str(way_id),
        "name": name,
        "state": state,
        "scope": scope,
        "agency": pick.agency if pick else "",
        "agency_level": f"{level:g}" if pick else "",
        "formula_level": str(int(formula)),
        "formula_rule": rule,
        "differs": ("yes" if level != int(formula) else "no") if pick else "",
    }


def painted_lane_report_csv(rows: Iterable[dict[str, str]]) -> str:
    """`PAINTED_LANE_REPORT_NAME` from `painted_lane_row`'s rows, ordered by way."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=PAINTED_LANE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in sorted(rows, key=lambda r: int(r["way_id"])):
        writer.writerow(row)
    return out.getvalue()
