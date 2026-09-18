# Round 10 — Cycling / DC-region domain — REVISE (1 blocking)

Reviewed at `0d79759`. Twenty-six of twenty-seven wave-8 items closed by reversion and execution;
the revisit cell's cosine floor is an equivalent mutant with proof (unreachable below 89.43° of
latitude). Round 9's B2 — the agency, the count and its year — is closed end to end and could not
be broken. Round 9's B1 is not closed on the general key forms.

**What would change my verdict:** the worst-side rule applied within a side as well as across
them, on both provisions and on the shoulder's width fallback, with the general-key-plus-negative-
side combinations pinned.

## BLOCKING
**B1.** `_side_values` unions the general keys (`cycleway`, `cycleway:both`) with the side key and
`_facility_rank` takes the best value in the union, so a side's `no` is discarded whenever a
general key asserts a facility; `_shoulder_on_side` does the same. Executed on the 35 mph four-lane
secondary round 9 used: `cycleway:left=track` + `cycleway:right=no` → LTS4 (wave 8's fix works);
`cycleway=track` + `cycleway:right=no` → **LTS1**; `cycleway:both=track` + `:right=no` → LTS1;
`cycleway=lane` + `:right=no` → LTS3. The shoulder mirror at 35 mph: `shoulder=yes` +
`shoulder:width=2.4` + `shoulder:right=no` → LTS3. And row 67's headline symptom — provisioning
the second side is a penalty — reproduces on round 9's own 25 and 30 mph roads with the general
key. `is_top_tier` flips on both, which PLAN.md:325's Beginner invariant and the road-exposure
report key on. A specific-wins replacement (a side key present answers alone; else the general
keys) leaves the whole suite green: not one test pairs a general key with a negative side key.
Residual: the shoulder's width fallback reads `shoulder:width` for a side tagged `no`.

## SHOULD-FIX
- **SF-1.** The agency string is the raw `--volume-source` argument, not casefolded, while the tier
  lookup is; and `SOURCE_TIERS` carries two keys for one agency (`mdot-sha`, `mdsha`). One agency
  becomes several `volume_source` values; the DDL is bare `text`.
- **SF-2.** The one-way carve-out is keyed on `oneway` alone; `oneway:bicycle=no` with
  `cycleway:left=opposite_lane` takes the union though the with-flow rider has no facility.
- **SF-3.** Widths are still side-blind while values are side-aware: surveying one side of a
  both-sides lane lowers the tier and surveying the second raises it back; a track's width can rate
  the painted lane on the other side "adequate".

## NIT
The cosine floor equivalent (record it); `parse_maxspeed_mph("0")` → 0.0; `conflation.rank` never
consults the year.

Checked and clean: km/h and implicit maxspeed parsing, odd lane totals, `living_street`/`service`
defaults, `access=customers`/`destination`/`dismount` declining the track write, sharrows and the
other non-facilities, the two resolvers against the eighteen rows after the e-bike change.
