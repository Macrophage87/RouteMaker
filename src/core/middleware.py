"""Per-request session and standing enforcement.

The session epoch exists on the user row and the session row, but a value
nothing reads revokes nothing: without this middleware, ban, suspension,
deletion and sign-out-everywhere all leave the person signed in.
"""

from __future__ import annotations

from django.contrib.auth import logout
from django.utils import timezone

from .auth_backend import attach_standing, session_is_current
from .models import Session


class SessionEpochMiddleware:
    """Rejects a session issued under a stale epoch, and refreshes its clock."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            key = request.session.session_key
            row = Session.objects.filter(session_key=key, user=user).first() if key else None
            if row is None or not session_is_current(
                user, row.issued_epoch, row.created_at, row.last_seen_at
            ):
                # Ban, suspension, deletion, or sign-out-everywhere. Ending it
                # here is what makes those actions mean anything.
                if row is not None:
                    row.delete()
                logout(request)
            else:
                # An UPDATE against the primary key rather than `save()`.
                # `save(update_fields=...)` on a row that has gone since it was
                # read - swept, or revoked by another request between the SELECT
                # above and here - raises `DatabaseError("Save with update_fields
                # did not affect any rows")`, which is a 500 on an ordinary
                # request for a clock refresh that does not matter. An UPDATE
                # matching nothing is simply a no-op, which is the right
                # behaviour when the session it would have touched is gone.
                Session.objects.filter(pk=row.pk).update(last_seen_at=timezone.now())
                attach_standing(user)
        return self.get_response(request)
