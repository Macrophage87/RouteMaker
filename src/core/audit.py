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

# `AuditLogEntry.object_id` is a CharField of this width. Named rather than
# spelled inline so the two cannot drift apart silently; the model asserts the
# same number in tests/test_admin_scoping.py.
OBJECT_ID_MAX = 64


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

    The actor's primary key is written alongside the foreign key rather than
    read back through it. The key is `SET_NULL`, so once an account is deleted
    the row is indistinguishable from one a worker wrote with no actor at all -
    and the plan wants those told apart: "Audit log rows keep the numeric actor
    id and display 'deleted user'". Recorded here, at the one writer, because a
    column populated by some call sites and not others answers nothing.

    Both values are bounded here, at the writer, and both bounds are the ones
    the column actually has: `object_id` to the 64 characters of its CharField
    and `detail` to a length its TextField will always take. Only `detail` used
    to be bounded, which had it exactly the wrong way round - the unbounded
    value was the one with the narrow column behind it. A guild admin could
    therefore choose whether their refusal was recorded at all, by padding the
    object id in the URL they posted at past 64 characters: the refusal raised
    `PermissionDenied`, the wrapper in `admin.py` tried to write the row, the
    column rejected it, and what reached the client was a 500 with nothing in
    the log. Truncating at the writer is what makes "refused and audited"
    unconditional, because no caller can be relied on to have measured its own
    identifier - the bulk paths join a whole selection into it.
    """
    from .models import AuditLogEntry

    actor_pk = getattr(actor, "pk", None)
    return AuditLogEntry.objects.create(
        actor=actor if actor_pk else None,
        actor_user_id=actor_pk,
        action=action,
        model=model,
        object_id=str(object_id or "")[:OBJECT_ID_MAX],
        outcome=outcome,
        detail=detail[:2000],
    )


__all__ = ["OBJECT_ID_MAX", "record"]
