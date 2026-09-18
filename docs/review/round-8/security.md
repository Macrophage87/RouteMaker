# Round 8 — Access control / sign-in / privacy — REVISE (1 blocking)

Reviewed at `60436a6`, every probe through the Django test client over the real Discord flow. All
round-7 items closed by reversion except two that could not be: `BorderCrossingAdmin.gis_widget` is
inert on a read-only form (N8-1) and the template's default `base_layer` was unpinned (SF8-1). Closed:
the widget on `JurisdictionAdmin` (12 failures), `Media.extend = False` (7), the version pin, the
narrowed rebuild mount (4), the per-directory chown, the object-level guild edit (2), both audit rows
(3), aliased-import resolution (4), `password_change/done/` (2), and the logout refusal over
HEAD/PUT/DELETE/OPTIONS (4). The weigh-ins agree with the record: the vendored `SOURCE` is honest,
`ol.js` carries no beacon, the parked basemap setting is the honest posture, actor `None` on the two
host-operator commands is right, and `admin_contact_email` is an `EmailField`.

**What would change my verdict:** a §7 row for the guild admin's audited mapping action beside its
three siblings, with a corrected `RoleMappingAdmin` docstring; or an owner decision on the record.

## BLOCKING
**B8-1.** PLAN.md:208, :210, :226 and :272 give the guild admin their own guild's role mapping
"through the dedicated audited mapping action". Executed as a guild admin: POST to their own guild's
mapping change and add → 403, refused audit row. The read-only form is what :272 asks for; the action
beside it is absent, and §7 records the re-invite token, the remap window and the unmapped-guild
alert from the same paragraph but not this one, though it presupposes the bot in the same way. The
docstring's stated reason — "a guild admin editing their own guild's mapping is the definition of
privilege escalation" — is wrong: `attach_standing` ignores `INSTANCE_ADMIN` rows and the scoping
blocks other guilds.

## SHOULD-FIX
- **SF8-1.** The shipped no-basemap `base_layer` → `null` survives; Django's `OLMapWidget.js` then
  builds `ol.source.OSM` and the vendored bundle contains `tile.openstreetmap.org`.
- **SF8-2.** `js_string_literal` is entirely unpinned: `mark_safe(value)` survives.
- **SF8-3.** PLAN:61 (instance admin enters the contact address at configuration) and PLAN:208
  (guild admin sets it) disagree; wave 6 cited only :208.

## NIT
N8-1 the inert widget; N8-2 a cross-guild `revoke_now` selection refused silently with no audit row;
N8-3 `actor_label()` names only the worker; N8-4 the version assertion passes on prose; N8-5 two
citations off by two lines; N8-6 no Content-Security-Policy anywhere.

Also executed: the anonymous sweep of the admin mount (everything 404), the guild-admin surface
re-derived over HTTP (seven models, nothing else), the listing re-probed as an oracle (three
disallowed lookups → 400), revocation end to end.

**Wave 7:** B8-1 recorded in §7 with the sibling rows and the docstring corrected; SF8-1 pinned with
a positive assertion; SF8-2 pinned on shape, each escape, a `</script>` payload and the `ensure_ascii`
property (the U+2028/U+2029 rows are equivalent mutants under it, recorded in source); SF8-3 a §7
owner-call row and a docstring sentence; N8-2 built (a REFUSED row keyed on the ids the scoping
dropped); N8-3 widened and pinned; N8-4 anchored; N8-6 a §7 row; F60, F62/F71 and F70 pinned.
