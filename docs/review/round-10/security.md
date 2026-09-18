# Round 10 — Access control / sign-in / privacy — ACCEPT (0 blocking)

Reviewed at `0d79759`, every probe through the Django test client over the real sign-in flow. All
thirteen wave-8 items closed by reversion and execution. The weigh-ins measured rather than
reasoned: a 500-id selection keeps its count ahead of the bound; `_posted_action` agrees with
Django's resolution on eight `index` shapes, with no shape where Django runs one action and the
guard checked another; `/healthz` is acceptable under PLAN:292 and still behind `ALLOWED_HOSTS`;
`Host: *` makes the healthcheck red and nothing gates on it; dropping the referer costs nothing
downstream; HSTS on the plain-HTTP posture is ignored by the browser as the RFC requires.

Fresh sweep, clean: all thirteen model admins as both roles; the session epoch on revocation,
removal and ban; the removal cancel row names the canceller; the listing's lookup allow-list; a
guild admin's write scope on their own guild; `ScheduledRun.detail` carries no secret.

**What would change my verdict:** nothing withholds it. The first should-fix I would build is
SF10-2.

## SHOULD-FIX
- **SF10-1.** A refused bulk action's audit row does not say which action was attempted.
- **SF10-2.** A pending instance-admin removal survives the target's own stand-down and later
  strips a fresh re-appointment, with no window and nothing to cancel — reproduced end to end.
  Clearing the pending row on re-appointment leaves the suite green: nothing pins either way.
- **SF10-3.** `ALLOWED_HOSTS` does not strip whitespace while the healthcheck and two tests do, so
  `DJANGO_ALLOWED_HOSTS=a, b` makes every request for `b` a 400 on the live site.

## NIT
A dead negative assertion in the escalation guard; §7's access-log row stale on its first clause;
three non-authorization admins refuse without auditing; `history_view` is a pk-existence oracle for
internal row numbers; `/healthz` is unauthenticated and uncached with nothing rate-limiting it;
half of `make_a_plain_member_of` is inert.

For the owner: the reviewer's judgement that phase 1 owes no ban or account-deletion admin surface
rests on PLAN.md:299; §7 has no row saying so.
