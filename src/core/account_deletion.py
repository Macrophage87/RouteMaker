"""Deleting an account (Google Play's account-deletion rule: a rider can delete their account
inside the app and from a web page that works without it).

One page does both: GET /delete-account says what is deleted and what is kept, and, signed in,
offers the one button; signed out, it offers Sign in with Discord, which comes back here.
Settings > Account links to it, so the app and the web share one confirmation and one code path.

The account row itself is deleted, not flagged. What is the rider's own goes with it, by the
models' CASCADE (sessions, My Go with Home, synced settings, saved routes and their versions, the
AI assistant key), or here, before it (shared links, suggestions still waiting, agree or disagree
on others' suggestions, the bot's cached Discord roles). What is the map's record is kept with
the link to the account cleared (SET_NULL): a decided suggestion, and an admin's edits and
rulings. The audit log keeps an account number, never a Discord id (`audit.record`), and one row
says this account was deleted. Signing in again with the same Discord account makes a new, empty
account; a banned account cannot reach this page, and its ban tombstone is kept by the ban.

The deployment's last instance admin is refused (`check_last_instance_admin`), as every other
path that removes one is: there is no login that could restore an admin.
"""

from __future__ import annotations

from html import escape

from django.contrib.auth import logout as django_logout
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from . import ratelimit

PATH = "/delete-account"
CONFIRM_FIELD = "confirm"

TITLE = "Delete your RouteMaker account"
DELETED = [
    "Your saved routes and their earlier versions",
    "Your settings kept with the account, and My Go, including Home",
    "Links you shared while signed in: they stop working",
    "Your AI assistant key",
    "Your suggestions and hazard reports still waiting for review, and your agree or disagree "
    "on other riders' suggestions",
]
KEPT = [
    "Suggestions already approved or declined, and map changes made from them, as part of the "
    "map's history, with nothing linking them to you",
    "A note that an account was deleted, and when, under an account number",
    "Database backups, until they age out, usually within a week",
]
ON_DEVICE = (
    "Routes kept for offline use and choices made while signed out stay in your browser or the "
    "app until you clear its storage."
)
BANNED = (
    "A banned account cannot sign in, so it cannot use this page: ask the map's admin on Discord "
    "to delete it."
)
AGAIN = "You can sign in with Discord again later; you start with a new, empty account."
LAST_ADMIN = (
    "You are the map's only admin, so the account cannot be deleted yet. Make another account "
    "an admin first."
)
NOT_CONFIRMED = "Tick the box to confirm, then press Delete my account."
DONE = "Your account is deleted, and you are signed out on every device."


class LastAdminRefused(RuntimeError):
    """The account is the deployment's last instance admin."""


def delete_account(user) -> None:
    """Delete `user`'s account and everything that is theirs alone; see the module's docstring.

    Raises `LastAdminRefused` for the last instance admin, with nothing changed.
    """
    from . import shared_routes
    from .audit import record
    from .models import (
        AuditLogEntry,
        CachedMembership,
        JunctionSuggestion,
        LastInstanceAdmin,
        MassHazard,
        SharedRoute,
        StressSuggestion,
        StressSuggestionReview,
        User,
        check_last_instance_admin,
    )

    now = timezone.now()
    with transaction.atomic():
        # Every live admin row is locked, in one order, before the count: two admins deleting at
        # once would otherwise each see the other and leave none.
        list(
            User.objects.select_for_update()
            .filter(Q(is_instance_admin=True) | Q(pk=user.pk))
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        user = User.objects.get(pk=user.pk)
        try:
            check_last_instance_admin(user, removing=True)
        except LastInstanceAdmin as error:
            raise LastAdminRefused(str(error)) from error

        # A shared link turns off as the Turn off button does (the link then says so, rather than
        # "not found"), and its tombstone names no account.
        for row in SharedRoute.objects.filter(owner=user, revoked_at__isnull=True):
            shared_routes.revoke(row, now)
        SharedRoute.objects.filter(owner=user).update(owner=None)

        # Waiting contributions are the rider's to take back; decided ones are the map's record,
        # kept with the account number cleared as well as the link.
        waiting = ["pending", "sent_to_discord"]
        for model, field in (
            (StressSuggestion, "suggester"),
            (MassHazard, "reporter"),
            (JunctionSuggestion, "suggester"),
        ):
            theirs = Q(**{field: user}) | Q(**{f"{field}_user_id": user.pk})
            model.objects.filter(theirs, status__in=waiting).delete()
            model.objects.filter(theirs).update(**{field: None, f"{field}_user_id": None})
        StressSuggestionReview.objects.filter(reviewer_user_id=user.pk).delete()

        # The bot's view of this person's Discord roles; it names who belongs to which club.
        CachedMembership.objects.filter(discord_user_id=user.discord_user_id).delete()

        record(
            None,
            "delete_account",
            "user",
            user.pk,
            AuditLogEntry.Outcome.ALLOWED,
            detail="deleted by the account holder",
        )
        # The rest goes by CASCADE: the sessions (so every device is signed out at its next
        # request), My Go, settings, saved routes and versions, the assistant key.
        user.delete()


def _page(body: str, status: int = 200) -> HttpResponse:
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(TITLE)}</title>"
        '<meta name="robots" content="noindex">'
        "<style>"
        "body{font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:0 auto;padding:1rem;"
        "color:#1a1a1a;background:#fff}"
        "@media (prefers-color-scheme:dark){body{color:#eee;background:#121212}a{color:#8cf}}"
        "h1{font-size:1.5rem}h2{font-size:1.1rem;margin-top:1.5rem}"
        "button{font:inherit;padding:.6rem 1rem;min-height:44px;border-radius:6px;"
        "border:2px solid #a00;background:#a00;color:#fff;cursor:pointer}"
        "label{display:flex;gap:.5rem;align-items:flex-start;margin:1rem 0}"
        "input[type=checkbox]{width:1.4rem;height:1.4rem;flex:none}"
        ".note{font-weight:600}"
        "</style></head><body><main>"
        f"<h1>{escape(TITLE)}</h1>{body}"
        '<p><a href="/">Back to RouteMaker</a></p>'
        "</main></body></html>"
    )
    response = HttpResponse(html, status=status, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = "noindex"
    response["Vary"] = "Cookie"
    return response


def _list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(i)}.</li>" for i in items) + "</ul>"


def _explanation() -> str:
    return (
        "<h2>Deleted at once</h2>"
        + _list(DELETED)
        + "<p>You are signed out on every device.</p>"
        + "<h2>Kept</h2>"
        + _list(KEPT)
        + "<h2>On your phone or computer</h2>"
        + f"<p>{escape(ON_DEVICE)}</p>"
        + f"<p>{escape(AGAIN)}</p>"
        + f"<p>{escape(BANNED)}</p>"
    )


def _form(request, problem: str = "") -> str:
    said = f'<p class="note" role="alert">{escape(problem)}</p>' if problem else ""
    return (
        f'{said}<form method="post" action="{PATH}">'
        f'<input type="hidden" name="csrfmiddlewaretoken" value="{escape(get_token(request))}">'
        f'<label><input type="checkbox" name="{CONFIRM_FIELD}" value="yes" required> '
        "I understand that deleting my account cannot be undone.</label>"
        '<button type="submit">Delete my account</button></form>'
    )


def _signed_out() -> str:
    from .auth_views import sign_in_available

    if not sign_in_available():
        return "<p>Sign-in is not set up on this server, so it holds no accounts to delete.</p>"
    return (
        f'<p><a href="/auth/login?next={PATH}">Sign in with Discord</a> to delete your account. '
        "In the app, it is under Settings, Account, Delete account.</p>"
    )


@require_http_methods(["GET", "POST"])
@ratelimit.rate_limited(ratelimit.SIGN_IN)
@csrf_protect
def page(request):
    """GET: what deletion does, and the button (signed in) or the sign-in link. POST: delete."""
    from .api import signed_in

    if not signed_in(request):
        return _page(_signed_out() + _explanation(), status=200 if request.method == "GET" else 401)
    if request.method == "GET":
        return _page(_explanation() + _form(request))
    if request.POST.get(CONFIRM_FIELD) != "yes":
        return _page(_explanation() + _form(request, NOT_CONFIRMED), status=400)
    try:
        delete_account(request.user)
    except LastAdminRefused:
        return _page(_explanation() + _form(request, LAST_ADMIN), status=409)
    django_logout(request)
    return _page(f'<p class="note" role="status">{escape(DONE)}</p><p>{escape(AGAIN)}</p>')
