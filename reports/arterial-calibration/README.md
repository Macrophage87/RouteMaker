# Arterial calibration and override re-match: live-extract checks

Read-only runs of `scripts/analysis/arterial_verify.py` over the 2026-10-03 extract
(`source.osm.pbf`), roads only, with the rebuild's own conflation and classifier:

- `smoothing.md`, `arterial-verify-summary.json`: the AADT smoothing's region-wide effect
  (decision 296) and 1st Street NW way 483241819 (LTS 3 to LTS 2).
- `north-capitol.md`: every way of the named corridor against the owner's targets
  (0 mismatches).
- `rematch-live.md`, `.csv`, `override-rematch-summary.json`: all 232 access and 1,551
  stress rows the live database holds (the fixtures at origin/main), run through the
  re-match against that extract: one is missing today, Harford Road way 424993005, and the
  re-match declines it with its reason; the working tree's 1,785 rows all apply.
