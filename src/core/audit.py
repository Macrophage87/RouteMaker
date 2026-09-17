"""The one writer for the audit log.

Split out of `admin` because about half of what the plan says must be audited is
not a model change with a request behind it: bans, revoke-now, loss
reclassification, re-invite issuance, grace-window lapses, and anything a worker
does. Those have no request and therefore no actor unless one is threaded in, so
the primitive takes an actor rather than a request and the admin's own helper is
a thin wrapper over it.

One rule about *when* this is called is load-bearing and is stated here because
it was got wrong once. Django runs `changeform_view` and `delete_view` inside
`transaction.atomic`, asks the ModelAdmin's `has_*_permission` hooks from inside
that block, and raises `PermissionDenied` when the answer is no. A refusal row
written from inside a permission hook is therefore rolled back with the
exception that refused the request - measured at 1 row outside a transaction and
0 rows inside - while the same hooks, called several times per page during
ordinary rendering, wrote ~20 rows for a read-only GET. The log recorded the
exact inverse of its purpose.

The fix is structural rather than a trick with connections: the refusal is
recorded from *outside* the atomic block, after it has already unwound, by
catching `PermissionDenied` around the view rather than writing from the hook
inside it. See `AuditedAdmin` in `admin.py`.

Two alternatives were considered and rejected.

`transaction.on_commit` is the wrong hook by construction: the transaction is
rolled back, so its callbacks are discarded. It records refusals never.

A second database connection would survive the rollback, but it buys nothing
here and costs three things: it doubles connection use on a path any anonymous
visitor can drive, it cannot see rows the current uncommitted transaction holds
(so an actor created in the same transaction is invisible and the foreign key
fails), and it makes the behaviour untestable under the ordinary transactional
test case. Unwinding first has none of those properties and is simply where the
write belongs.
"""

from __future__ import annotations


def record(
    actor,
    action: str,
    model: str,
    object_id,
    outcome: str,
    detail: str = "",
):
    """Write one audit row. `actor` is a User, or None for a worker.

    Narrow on purpose, like the membership cache: who acted on what and whether
    it was allowed, never a copy of the row.
    """
    from .models import AuditLogEntry

    return AuditLogEntry.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        model=model,
        object_id=str(object_id or ""),
        outcome=outcome,
        detail=detail[:2000],
    )


__all__ = ["record"]
