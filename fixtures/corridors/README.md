# Named corridors

Stretches of a street the owner has judged by what they are, not by the tags the
classifier reads. Read by the rebuild from its image (`routemaker.corridors`,
applied at the end of CLASSIFY_STRESS); nothing here is loaded into the database,
and an approved stress override row on a way still outranks it.

A file is `{"version": 1, "corridors": [...]}`. A corridor is `id`, `streets` (names
without their quadrant), `axis` (a `[lon, lat]` polyline down the middle of the road's
cross-section), `reason` (the owner's words and decision numbers) and `entries`. An
entry is `id`, `role` (`through` or `side`), `along_m` (`[from, to]` metres along the
axis from its first point), `tier` (1 to 5, 5 being Avoid), and the owner's `reason` and
the map `evidence`; both are required on every entry. A way is matched by its street
name and where it lies, never by id, so an OSM split, merge or renumbering does not stop
it applying: it is a *through* lane when its mean offset from the axis is within
`through_max_offset_m` (7 m), a *side* lane when further out and within
`side_max_offset_m` (20 m), by position and not by its `lanes` tag, and an entry takes a
way with at least half of its length inside `along_m`. A way with a protected lane, a
separate bikeway, a path-class facility, or a trail class is exempt (decision 294). An
entry that matches no way is warned about in the rebuild log.

This is not a generic underpass or speed rule (decision 294): the circle underpasses, K Street's
surface lanes and Virginia Avenue stay as the base classifier rates them. Dupont Circle's
Connecticut Avenue underpass is not a corridor: its access and LTS 4 are override rows
(`fixtures/overrides/2026-10-05-owner-dupont-underpass.json`, decision 416). The at-grade
parts of a named street keep their current rating (decision 296).

| File | Decision |
|---|---|
| `2026-10-04-owner-north-capitol-underpasses.json` | North Capitol Street NW/NE (decisions 284, 286, 295, 296). First underpass, M St to about P St: through lanes Avoid (the study's northern 100 m trimmed), surface side lanes and the pickup LTS 4. Second underpass, Rhode Island Ave, T St to V St: underpass lanes LTS 4, the narrower side lanes LTS 3. Way 468472149, tagged lanes=2, is a side lane (LTS 4), and so is 930215092 on the east side, which the study had as Avoid. |
| `2026-10-05-owner-connecticut-north-of-r.json` | Connecticut Avenue NW (decisions 408, 409; kept by 411, from R St north by 413): "I'd say it's LTS4 north of R." R St NW to Calvert St NW, about 0.85 mi (1.37 km): both carriageways of the divided part and the two-way part over the Taft Bridge, LTS 4 (posted 25 mph, so the classifier gives LTS 3); north of Calvert St the classifier's own 30 mph LTS 4 stands. Through lanes within 10 m of DC's centre line (the carriageways are up to about 8 m out); no side entry. The hill (409's "I'd definitely ride down it, but not so much up") is backlog FOLLOWUP-GRADE-STRESS. `tests/data/connecticut_ways.json` holds the extract's ways for its test. |
| `2026-10-05-owner-south-capitol-mlk-to-mississippi.json` | South Capitol Street (decision 432): "Change south captiol street from MLK ave to Missisipi ave to LTS4. There's no other routes through there." Martin Luther King Jr Ave SE (38.8357 N) to Mississippi Ave SE (38.8309 N), about 0.34 mi (0.55 km), the undivided four- and five-lane road: LTS 4, so it stays routable with the normal LTS 4 warning. The classifier gives LTS 3 (posted 25 mph); the five ways were Avoid by rows of the east-of-the-Anacostia file (141, 144), which are taken out of that file and listed under its `retire`, so loading it withdraws the rows already loaded: an approved row outranks a corridor. The axis is DC's Roadway Block centre line (blocks dc-4642170-0, dc-4642513-0, dc-4641163-0), extended 60 m north. `tests/data/south_capitol_ways.json` holds the extract's ways for its test; VALIDATE's `REBUILD_SENTINEL_STRETCHES` holds the stretch at LTS 4. |

`scripts/analysis/arterial_verify.py` classifies the live extract read-only and tabulates
every way of the corridor against the owner's targets.
