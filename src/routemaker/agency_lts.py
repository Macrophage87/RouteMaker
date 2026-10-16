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
LTS5. We should keep that unless there's a clear case for downgrading").
Montgomery's 0.5 ("None") is no rating and is dropped before it gets here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from .stress import Stress, StressResult

# How local an agency is. Lower wins: a county's rating over a state's.
COUNTY = 1
STATE = 2

# The agencies whose ratings may set a tier, with their display names and how
# local each is. An agency's layer is added here only once the owner has
# approved its download and its licence allows publishing a derivative:
# Arlington's Bike Comfort Index and Alexandria's Transport Streets are for
# internal comparison only (OWNER-DECISIONS 152, 153, 155) and never appear.
AGENCIES: dict[str, tuple[str, int]] = {
    "moco": ("Montgomery County Planning", COUNTY),
    # The District is its own local government: its rating ranks with a county's.
    "ddot": ("DDOT", COUNTY),
    "mdot-sha": ("MDOT SHA", STATE),
}

AGENCY_RULE = "agency rating"

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
# 2026-10-16 (Alex311 request 26-00041150), so its flag is True; its Transport Streets speeds
# reach the map only with v0.8.0's rebuild. Arlington's stays False until it answers.
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


def chosen(ratings: Iterable[AgencyRating]) -> AgencyRating | None:
    """The rating the map uses: the most local agency's. Two agencies at the same
    rank on one way (two counties meeting at a line) take the higher level, the
    stress-averse reading."""
    ranked = sorted(ratings, key=lambda r: (r.rank, -r.level))
    return ranked[0] if ranked else None


def apply(result: StressResult, ratings: Iterable[AgencyRating]) -> StressResult:
    """The way's tier with the agency's level in place of the classifier's.

    The classifier's tier is kept (`formula_tier`, `formula_rule`) and every
    rating is recorded (`agency_ratings`), for the road panel. An agency rating
    replaces the formula's only; a tier the owner set comes later and wins."""
    ratings = tuple(ratings)
    pick = chosen(ratings)
    if pick is None:
        return result
    tier, half = tier_of(pick.level)
    # The other agencies' levels are in `agency_ratings`, not the rule: the
    # rule's commas separate the reasons appended after it (`stress.rural_floor`).
    why = f"{AGENCY_RULE}: {pick.name} LTS {pick.level:g}"
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
