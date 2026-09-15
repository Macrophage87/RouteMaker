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
                row.last_seen_at = timezone.now()
                row.save(update_fields=["last_seen_at"])
                attach_standing(user)
        return self.get_response(request)


class AuditFlushMiddleware:
    """Writes the refusal rows the admin buffered during the request.

    Django checks `has_*_permission` inside `transaction.atomic()` and, on a no,
    raises PermissionDenied - which rolls back anything that check wrote. A
    refusal recorded there is therefore erased by the very refusal it records,
    and the log fills up with the permission probes from read-only pages instead.

    This runs after the response has been produced, so the admin's transaction
    has already ended one way or the other and the row survives independently of
    it. It must stay outside any request-wrapping transaction for that reason.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .admin import flush_deferred_audit

        try:
            return self.get_response(request)
        finally:
            flush_deferred_audit(request)
