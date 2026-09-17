"""A flat table of `assert CONSTANT == <PLAN's figure>`.

Round 3's mutation panel found the same shape of gap in ten different places:
a test computes its boundary from the constant it is testing, so the constant
can move by two orders of magnitude and the suite stays green. It already cost
one of them for real - `IDLE_SESSION_LIFETIME` is 14 days in the code and 30 in
PLAN.md, and nothing noticed until a reviewer read the two side by side.

Every expected value below is typed in by hand from PLAN.md, with the line it
came from quoted in the docstring, rather than computed from the module under
test or from any other constant in this codebase. That is what makes deleting
or rescaling the constant a real failure here instead of a tautology: the
right-hand side of each `==` does not move when the left-hand side does.

What is deliberately *not* here, and why: PLAN.md narrates the swap's lock
timeout and bounded retry, the LTS mph and AADT thresholds, and the weekly
rebuild's and nightly backup's exact cron timing, but never states a number
for any of them - those are implementation-chosen or domain-tuned values with
no plan figure to pin against, so a table entry for them would have to invent
the "plan's figure" it claims to check. Pinning them is someone else's test to
write once a number exists to write it against; see this file's owning
agent's report for the full list.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from croniter import croniter
from django.utils import timezone

REPO = Path(__file__).resolve().parents[1]


# --- Sessions --------------------------------------------------------------
# PLAN.md: "**Sessions.** Django's server-side sessions, rows in Postgres
# referenced by an HttpOnly, Secure, SameSite=Lax cookie; 30 days idle, 90 days
# absolute."


def test_absolute_session_lifetime_matches_plan() -> None:
    from core.revocation import ABSOLUTE_SESSION_LIFETIME
    from datetime import timedelta

    assert ABSOLUTE_SESSION_LIFETIME == timedelta(days=90)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "phase1/sec: PLAN.md states '30 days idle'; src/core/revocation.py's "
        "IDLE_SESSION_LIFETIME is 14 days. Owned by the security cluster (item 16 "
        "in handoff.md). This flips to a hard failure the moment it is fixed, "
        "which is the point - delete this xfail then, not before."
    ),
)
def test_idle_session_lifetime_matches_plan() -> None:
    from core.revocation import IDLE_SESSION_LIFETIME
    from datetime import timedelta

    assert IDLE_SESSION_LIFETIME == timedelta(days=30)


# --- Guild degradation and the membership cache -----------------------------
# PLAN.md: "the bot's gateway disconnected for 5 minutes ... raises the alert"
# and "Accidental loss ... marks the guild degraded and honors cached standing
# for a grace period, default 72 hours running from the alert" and "Deliberate
# removal of the bot from a guild ends that guild's standing within 15
# minutes" and "The maximum stale-grant window is 72 hours from the alert,
# everywhere, and that is the only number" (which states the row-age bound is
# the same figure) and "rows for people who have never signed in are purged
# after 30 days" and "A six-hourly worker sweep reconciles the cache".


def test_gateway_alert_after_matches_plan() -> None:
    from core.revocation import GATEWAY_ALERT_AFTER
    from datetime import timedelta

    assert GATEWAY_ALERT_AFTER == timedelta(minutes=5)


def test_degraded_window_matches_plan() -> None:
    from core.revocation import DEGRADED_WINDOW
    from datetime import timedelta

    assert DEGRADED_WINDOW == timedelta(hours=72)


def test_max_stale_grant_matches_plan() -> None:
    """"... that is the only number." PLAN is explicit that this and the
    row-age bound below are the same 72 hours, not two numbers that happen to
    agree today."""
    from core.standing import MAX_STALE_GRANT
    from datetime import timedelta

    assert MAX_STALE_GRANT == timedelta(hours=72)


def test_max_row_age_matches_plan() -> None:
    from core.standing import MAX_ROW_AGE
    from datetime import timedelta

    assert MAX_ROW_AGE == timedelta(hours=72)


def test_guild_removal_grace_matches_plan() -> None:
    from core.standing import GUILD_REMOVAL_GRACE
    from datetime import timedelta

    assert GUILD_REMOVAL_GRACE == timedelta(minutes=15)


def test_purge_never_signed_in_after_matches_plan() -> None:
    from core.membership import PURGE_NEVER_SIGNED_IN_AFTER
    from datetime import timedelta

    assert PURGE_NEVER_SIGNED_IN_AFTER == timedelta(days=30)


def test_membership_sweep_runs_every_six_hours() -> None:
    """Checked by firing the cron forward twice and measuring the gap, not by
    comparing the cron string to another copy of itself, so a schedule that
    still reads 'six-hourly' in a comment but no longer is gets caught."""
    from config.procrastinate import MEMBERSHIP_SWEEP_CRON
    from datetime import timedelta

    base = timezone.now()
    iterator = croniter(MEMBERSHIP_SWEEP_CRON, base)
    first = iterator.get_next(type(base))
    second = iterator.get_next(type(base))
    assert second - first == timedelta(hours=6)


# --- The weekly rebuild -----------------------------------------------------
# PLAN.md: "retried with exponential backoff up to 5 times, with per-type
# timeouts (export 2 minutes, push 5 minutes, rebuild 6 hours)."


def test_rebuild_job_timeout_matches_plan() -> None:
    from config.procrastinate import REBUILD_TIMEOUT_S

    assert REBUILD_TIMEOUT_S == 6 * 60 * 60


# --- Jurisdiction crossings --------------------------------------------------
# PLAN.md: "Crossings shorter than a configurable minimum, default 0.1 mile,
# are collapsed unless a control point lies inside them ..."


def test_default_min_crossing_matches_plan() -> None:
    """160.9344 m is 0.1 mile by the standard 1609.344 m/mile conversion,
    written out here rather than computed from `routemaker.geo.METRES_PER_MILE`
    so that constant moving cannot silently drag this one with it."""
    from pipeline.crossings import DEFAULT_MIN_CROSSING_M

    assert DEFAULT_MIN_CROSSING_M == pytest.approx(160.9344)


# --- Compose memory limits ---------------------------------------------------
# PLAN.md: "Compose memory limits: each Valhalla 2 GB, Photon 3 GB, PostGIS
# 4 GB, rebuild 8 GB, renderer 1 GB, bot 512 MB, API 2 GB, worker 2 GB, Caddy
# 256 MB, migrate 256 MB ..."

PLAN_MEMORY_LIMITS = {
    "valhalla-standard": "2G",
    "valhalla-no-trail": "2G",
    "valhalla-ebike": "2G",
    "photon": "3G",
    "postgis": "4G",
    "rebuild": "8G",
    "renderer": "1G",
    "bot": "512M",
    "api": "2G",
    "worker": "2G",
    "caddy": "256M",
    "migrate": "256M",
}


def _memory_mb(value: str) -> float:
    text = value.strip().upper()
    if text.endswith("G"):
        return float(text[:-1]) * 1024
    if text.endswith("M"):
        return float(text[:-1])
    raise ValueError(f"unrecognised memory limit: {value!r}")


@pytest.mark.parametrize("service", sorted(PLAN_MEMORY_LIMITS))
def test_compose_memory_limit_matches_plan(service: str) -> None:
    compose = yaml.safe_load((REPO / "compose.yaml").read_text())
    limits = compose["services"][service].get("deploy", {}).get("resources", {}).get("limits", {})
    assert "memory" in limits, f"{service} declares no memory limit"
    assert _memory_mb(limits["memory"]) == _memory_mb(PLAN_MEMORY_LIMITS[service]), (
        f"{service}: PLAN.md states {PLAN_MEMORY_LIMITS[service]}"
    )


def test_every_compose_memory_limit_is_covered_by_plan() -> None:
    """A service PLAN names but this table forgot would otherwise pass by
    omission rather than by being checked."""
    compose = yaml.safe_load((REPO / "compose.yaml").read_text())
    assert set(compose["services"]) == set(PLAN_MEMORY_LIMITS)
