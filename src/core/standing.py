"""Authorization: one resolver, called everywhere.

Standing is decided by a single function taking a viewer and a route and
returning a level, with one permission check built on it. Ban, deletion
tombstone, guild state and window, membership row age, pending and timed-out
members, the maximum across audience guilds, the guest floor, owner, guild admin
and instance admin are all inputs to it in a stated precedence, rather than
prose spread across modules that two engineers would order differently.

Precedence, and the order matters:

1. Ban and deletion. No per-route grant overrides them.
2. Guild state and membership row age. A frozen cache expires on its own.
3. Per-route standing.

Two things this module refuses to do. It never reads an absent membership row as
permission - absence of a row is absence of standing, never unknown-therefore-
allow. And it never keys operational detail to a route's tier, because the tiers
are cumulative and a tier-based rule reads backwards: it would suppress marshal
data on a private route and serve it on a public one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum

# The maximum any stale grant may survive, measured from the moment an alert
# fires rather than from the end of a grace period. Stacking two windows would
# let the whole deployment carry stale grants for twice as long as a single lost
# guild does.
MAX_STALE_GRANT = timedelta(hours=72)

# How old a cached membership row may be before it grants nothing. The backstop
# for a frozen database, not the whole rule.
MAX_ROW_AGE = timedelta(hours=72)

# A deliberate removal must bite in minutes, while rows confirmed ten minutes ago
# still look fresh. That is why guild state exists alongside row age.
DELIBERATE_REMOVAL_GRACE = timedelta(minutes=15)


class Level(IntEnum):
    """Cumulative. Each level admits everyone below it."""

    NONE = 0
    GUEST = 10
    MEMBER = 20
    REVIEWER = 30
    COLLABORATOR = 40
    OWNER = 50
    GUILD_ADMIN = 60
    INSTANCE_ADMIN = 70


class GuildState(IntEnum):
    ACTIVE = 1
    DEGRADED = 2
    REVOKED = 3


class Visibility(IntEnum):
    """Route tiers, cumulative: each admits everyone the tier below admits."""

    PRIVATE = 1
    REVIEWERS = 2
    SERVER = 3
    LINK = 4
    PUBLIC = 5


# Operational detail is served at or above this standing, and never keyed to the
# route's tier. Token holders, guests and anonymous viewers never receive it at
# any tier, including on the owner's own public route.
MARSHAL_DETAIL_MIN_STANDING = Level.MEMBER


@dataclass(frozen=True)
class GuildStanding:
    """A configured guild's current state and the instant its standing expires."""

    guild_id: int
    state: GuildState
    state_since: datetime
    standing_valid_until: datetime | None = None

    def grants_standing(self, now: datetime) -> bool:
        if self.state is GuildState.REVOKED:
            return False
        if self.state is GuildState.ACTIVE:
            return True
        # Degraded: inside its window only.
        return self.standing_valid_until is not None and now < self.standing_valid_until


@dataclass(frozen=True)
class Membership:
    """A cached membership row. Absence of one is absence of standing."""

    guild_id: int
    role_ids: frozenset[int]
    last_confirmed: datetime
    pending: bool = False
    timed_out_until: datetime | None = None
    removed_at: datetime | None = None

    def is_usable(self, now: datetime) -> bool:
        if self.pending:
            return False
        if self.timed_out_until is not None and now < self.timed_out_until:
            return False
        if self.removed_at is not None and now >= self.removed_at + DELIBERATE_REMOVAL_GRACE:
            return False
        return now - self.last_confirmed <= MAX_ROW_AGE


@dataclass(frozen=True)
class Viewer:
    """Everything the resolver needs about who is asking."""

    user_id: int | None = None
    is_instance_admin: bool = False
    is_banned: bool = False
    is_deleted: bool = False
    memberships: tuple[Membership, ...] = ()
    admin_guild_ids: frozenset[int] = frozenset()
    reviewer_guild_ids: frozenset[int] = frozenset()

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None


@dataclass(frozen=True)
class Route:
    """Everything the resolver needs about what is being asked for."""

    owner_id: int
    visibility: Visibility
    owning_guild_id: int
    audience_guild_ids: frozenset[int] = frozenset()
    collaborator_ids: frozenset[int] = frozenset()
    reviewer_ids: frozenset[int] = frozenset()
    guest_comments_enabled: bool = True

    @property
    def all_audience_guilds(self) -> frozenset[int]:
        """The audience always includes the owning guild."""
        return self.audience_guild_ids | {self.owning_guild_id}


def resolve(
    viewer: Viewer,
    route: Route,
    guilds: dict[int, GuildStanding],
    now: datetime,
    has_link_token: bool = False,
) -> Level:
    """The single entry point. Every view and every admin queryset calls this."""

    # 1. Ban and deletion come first and no per-route grant overrides them.
    if viewer.is_banned or viewer.is_deleted:
        return Level.NONE

    if viewer.is_instance_admin:
        return Level.INSTANCE_ADMIN

    # 2. Guild state and row age, before any per-route consideration.
    usable = frozenset(
        m.guild_id
        for m in viewer.memberships
        if m.is_usable(now)
        and (standing := guilds.get(m.guild_id)) is not None
        and standing.grants_standing(now)
    )

    # 3. Per-route standing, highest wins.
    level = Level.NONE

    if viewer.is_authenticated and viewer.user_id == route.owner_id:
        level = max(level, Level.OWNER)

    if viewer.user_id in route.collaborator_ids:
        level = max(level, Level.COLLABORATOR)

    if viewer.user_id in route.reviewer_ids:
        level = max(level, Level.REVIEWER)

    # Guild admin only over their own guild's routes.
    if route.owning_guild_id in (viewer.admin_guild_ids & usable):
        level = max(level, Level.GUILD_ADMIN)

    # A reviewer in one club does not gain reviewer powers over another's routes.
    if (viewer.reviewer_guild_ids & usable) & route.all_audience_guilds:
        level = max(level, Level.REVIEWER)

    if usable & route.all_audience_guilds:
        level = max(level, Level.MEMBER)

    # The guest floor: a signed-in user belonging to no audience guild may
    # comment on a public route and nothing else.
    if (
        level is Level.NONE
        and viewer.is_authenticated
        and route.visibility is Visibility.PUBLIC
        and route.guest_comments_enabled
    ):
        level = Level.GUEST

    # A link token admits a reader, never a writer, and never adds standing to
    # someone who already has more.
    if level is Level.NONE and has_link_token and route.visibility >= Visibility.LINK:
        return Level.NONE if not viewer.is_authenticated else Level.GUEST

    return level


def can_read(
    viewer: Viewer,
    route: Route,
    guilds: dict[int, GuildStanding],
    now: datetime,
    has_link_token: bool = False,
) -> bool:
    """Whether this viewer may read the route at all."""
    if viewer.is_banned or viewer.is_deleted:
        return False
    level = resolve(viewer, route, guilds, now, has_link_token)
    if level >= Level.MEMBER:
        return True
    if route.visibility is Visibility.PUBLIC:
        return True
    if route.visibility is Visibility.LINK and has_link_token:
        return True
    return level >= Level.GUEST and route.visibility >= Visibility.LINK


def can_see_marshal_detail(
    viewer: Viewer,
    route: Route,
    guilds: dict[int, GuildStanding],
    now: datetime,
    has_link_token: bool = False,
) -> bool:
    """Marshal posts, SAG, sweep, bail-outs and the marshal cue sheet.

    Keyed to the viewer's resolved standing, never to the route's tier. A page
    that plots where your people will be tells that to everyone, including
    agencies you have not spoken to.
    """
    level = resolve(viewer, route, guilds, now, has_link_token)
    return level >= MARSHAL_DETAIL_MIN_STANDING
