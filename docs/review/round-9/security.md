# Round 9 — Access control / sign-in / privacy — REVISE (2 blocking)

Reviewed at `17a912b`, every probe through the Django test client over the real sign-in flow. All
ten wave-7 items closed by reversion, and the U+2028/U+2029 equivalence re-confirmed (2988 green
with both rows deleted). Weighed and upheld: fabricated `revoke_now` ids produce a true, bounded
record with nothing private (except `object_id`, which is B9-1); `ensure_ascii` and the
`SafeString` order; the `admin_contact_email` owner call; `unwedge_job` as built; the epoch's raw
SQL is constant and read-only.

**What would change my verdict:** `record()` bounding `object_id` to its column, and
`_refuse_unpermitted_action` resolving the action the way Django does.

## BLOCKING
**B9-1.** `core/audit.py` passes `object_id` unbounded into a 64-character column while truncating
`detail`, a `TextField`. Executed as a guild admin: a change or delete URL padded to 120 characters
→ 500 and no refused row, where the unpadded attempt gives 403 and one row, on three of PLAN.md:326's
named tables; `delete_selected` with 25 rows ticked → 500 and no row; `revoke_now` at another
guild's pk with 20 extra ids → 500 and no row, defeating wave 7's own row in the scenario its
docstring is about. The one-line bound restores 403 plus one row everywhere and the suite stays
green, which is why it survived eight rounds.

**B9-2.** `_refuse_unpermitted_action` reads the *last* posted `action` while Django's
`response_action` reads the indexed one: `action=["delete_selected", ""]`, `index=0` → 200 "No
action selected" and no audit row on every guild-readable model. Nothing is deleted; the state the
guard's own docstring says it was written to end is back.

## SHOULD-FIX
- **SF9-1.** Two more copies of the "definition of privilege escalation" sentence survive in
  `auth_backend.py`.
- **SF9-2.** `int(profile["id"])` and `token.get("scope")` sit outside the callback's `try`: a
  malformed Discord payload is a 500 rather than a 400.

## NIT
N9-1 gunicorn's access log keeps `?q=<discord id>` from admin searches; N9-2 no HSTS anywhere;
N9-3 the two `record()` bounds are the wrong way round.

**Wave 8:** B9-1 closed — `object_id` bounded at the writer with the constant asserted equal to the
column, and both bulk paths write the first id with the count and the full list in `detail`;
measured on seven models, every probe 403 (or 302) plus one row. B9-2 closed — `_posted_action`
mirrors Django's `getlist`/`index` resolution including its `IndexError` fallback, which a naive
"first or none" would have handed back via `index=9`. SF9-1 and SF9-2 closed. `/healthz` added
(200 on `SELECT 1`, 503 otherwise, no session, no cache) for the api healthcheck. N9-1 closed on
the deploy branch by an access-log format without the query string or the referer, with a §7 row
for the residual; N9-2 closed by an HSTS header at the edge.
