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

# A guild that deliberately ejects the bot has left the deployment, and its
# standing ends within this window. It applies to the *guild*, never to a member:
# an individual's role change or departure takes effect in seconds, because the
# case it guards against is someone about to lose their roles using the interval
# to read everything first.
GUILD_REMOVAL_GRACE = timedelta(minutes=15)

# The tier a guild-derived standing needs before it admits anyone. Per-route
# grants - owner, named collaborator, guild admin, instance admin - are
# independent of the tier; membership of a club is not.
MIN_TIER_FOR_GUILD_MEMBER = 3  # Visibility.SERVER
MIN_TIER_FOR_GUILD_REVIEWER = 2  # Visibility.REVIEWERS


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
        # Degraded: inside its window only, and the window is clamped to the
        # stated maximum rather than trusted from the row. A bug or a hostile
        # admin can write an arbitrary expiry into that column, and 72 hours from
        # the mark is the only number.
        if self.standing_valid_until is None:
            return False
        ceiling = self.state_since + MAX_STALE_GRANT
        return now < min(self.standing_valid_until, ceiling)


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
        if self.removed_at is not None:
            # Immediate. A removal is the one event whose whole purpose is to end
            # access now; a grace period here hands the person a window in which
            # to enumerate everything they were about to lose.
            return False
        return now - self.last_confirmed <= MAX_ROW_AGE

    @property
    def is_sanctioned(self) -> bool:
        """Under an active moderation action, as distinct from simply absent."""
        return self.removed_at is not None or self.timed_out_until is not None


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
    instance_admin_guild_ids: frozenset[int] = frozenset()

    @property
    def is_sanctioned_anywhere(self) -> bool:
        """Whether any guild has an active timeout or removal against them.

        A sanctioned member must not fall through to the guest tier and carry on
        commenting on that club's public routes; a timeout that does not stop
        someone posting is not a timeout.
        """
        return any(m.is_sanctioned for m in self.memberships)

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
    # The owner's audited per-route grants, which a single ordered level cannot
    # express: a view-only collaborator is not an editor, and a collaborator is
    # not automatically a reviewer.
    editor_ids: frozenset[int] = frozenset()
    reviewer_ids: frozenset[int] = frozenset()
    guest_comments_enabled: bool = True
    link_requires_login: bool = False

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
    """The single entry point. Every view and every admin queryset calls this.

    `has_link_token` is accepted and deliberately ignored. A link token is a read
    capability, not a level: honouring it here let a signed-in stranger reach
    GUEST on a route whose owner had switched guest comments off, because a
    public route's token URL sits alongside its slug URL and is no secret.
    `can_read` is the one place a token is consulted.
    """

    # 1. Ban and deletion come first and no per-route grant overrides them.
    if viewer.is_banned or viewer.is_deleted:
        return Level.NONE

    # 2. Guild state and membership row age, before any per-route consideration.
    usable = frozenset(
        m.guild_id
        for m in viewer.memberships
        if m.is_usable(now)
        and (standing := guilds.get(m.guild_id)) is not None
        and standing.grants_standing(now)
    )

    # Instance admin is a mapped Discord role like any other, so it is subject to
    # the same guild state and row age. A lapsed admin loses the admin along with
    # everything else, because one answer serves both.
    if viewer.is_instance_admin and (
        not viewer.instance_admin_guild_ids or (viewer.instance_admin_guild_ids & usable)
    ):
        return Level.INSTANCE_ADMIN

    # 3. Per-route grants, which the owner made explicitly and which therefore do
    # not depend on the tier.
    level = Level.NONE

    if viewer.is_authenticated and viewer.user_id == route.owner_id:
        level = max(level, Level.OWNER)

    if viewer.is_authenticated and viewer.user_id in route.collaborator_ids:
        level = max(level, Level.COLLABORATOR)

    if route.owning_guild_id in (viewer.admin_guild_ids & usable):
        level = max(level, Level.GUILD_ADMIN)

    # 4. Guild-derived standing, which the tier does gate. Belonging to a club
    # does not admit you to a route its owner has not shared with the club: the
    # tiers are cumulative upward, so server standing is admitted at server, link
    # and public, and nowhere below.
    audience = viewer_audience = usable & route.all_audience_guilds
    if audience and route.visibility >= MIN_TIER_FOR_GUILD_MEMBER:
        level = max(level, Level.MEMBER)

    # A reviewer in one club does not gain reviewer powers over another's routes.
    if (viewer.reviewer_guild_ids & viewer_audience) and (
        route.visibility >= MIN_TIER_FOR_GUILD_REVIEWER
    ):
        level = max(level, Level.REVIEWER)

    # 5. The guest floor: a signed-in user belonging to no audience guild may
    # comment on a public route and nothing else. Someone serving a timeout or
    # just removed is not eligible, since a moderation action that leaves them
    # posting is not a moderation action.
    if (
        level is Level.NONE
        and viewer.is_authenticated
        and route.visibility is Visibility.PUBLIC
        and route.guest_comments_enabled
        and not viewer.is_sanctioned_anywhere
    ):
        level = Level.GUEST

    return level


def can_read(
    viewer: Viewer,
    route: Route,
    guilds: dict[int, GuildStanding],
    now: datetime,
    has_link_token: bool = False,
) -> bool:
    """Whether this viewer may read the route at all.

    The one place a link token is honoured, and it grants reading only.
    """
    if viewer.is_banned or viewer.is_deleted:
        return False

    if resolve(viewer, route, guilds, now) >= Level.GUEST:
        return True

    if route.visibility is Visibility.PUBLIC:
        return True

    if route.visibility is Visibility.LINK and has_link_token:
        # link_requires_login reduces the unauthenticated surface to the generic
        # card, which is the lockdown posture a club reaches for when a route has
        # leaked and the ride is imminent.
        return viewer.is_authenticated or not route.link_requires_login

    return False


def can_edit(viewer: Viewer, route: Route) -> bool:
    """Whether this viewer may save a new version.

    Checked explicitly rather than by level comparison, because the owner's edit
    grant is orthogonal to the level lattice: a view-only collaborator sits at
    COLLABORATOR and must not thereby acquire save rights.
    """
    if viewer.is_banned or viewer.is_deleted or not viewer.is_authenticated:
        return False
    return viewer.user_id == route.owner_id or viewer.user_id in route.editor_ids


def can_review(viewer: Viewer, route: Route, viewer_level: Level) -> bool:
    """Whether this viewer may record approve or request-changes.

    Also explicit: COLLABORATOR sorts above REVIEWER in the lattice, so a level
    comparison would make every collaborator a reviewer and render the owner's
    audited review grant unenforceable.
    """
    if viewer.is_banned or viewer.is_deleted or not viewer.is_authenticated:
        return False
    if viewer.user_id in route.reviewer_ids:
        return True
    return viewer_level is Level.REVIEWER or viewer_level >= Level.GUILD_ADMIN


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
    return resolve(viewer, route, guilds, now) >= MARSHAL_DETAIL_MIN_STANDING
