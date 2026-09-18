# Round 6 — Cycling / DC-region domain — ACCEPT (0 blocking)

Reviewed at `00ee400` (the wave-4 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-5 disposition of every item is in `../../../handoff.md` §3.


All round-5 items closed by reversion (26 mutations, each with the exact edit). Fresh campaign 37
mutations: 36 killed, 1 survivor (SF-D4). Provision-hierarchy property re-run independently over
1,069,200 cases (9 classes × 9 speeds × 10 widths × 6 lanes × 10 AADT × 11 parking × urban/rural):
0 failures; the ~19,800 cases where a shouldered road rates below a bike-laned one are Furth's
table making a narrow painted lane worse than bare mixed traffic at ≤25 mph, correctly excluded.
Python↔Lua width parser identical on 33 cases. Purple Line recomputed: leave 8.835 (−76.9415 PG),
enter 18.887 (−77.0303 Montgomery), leave 20.245, enter 28.160. All six wave-4 judgment calls
upheld with reasons (incl. WAY_ACCESS_KEYS correctly omitting bicycle:forward/backward — upstream
applies the directional keys after `bicycle`, graph_upstream.lua:1321,1339). Fixture is 18 rows.

**SHOULD-FIX.** SF-D1 a legality row that resolves against nothing is silent: only the sidepath
resolver reports `unmatched`; 14 of 18 rows (all sidepath_only:false, incl. Theodore Roosevelt
whose note says the no-trail variant depends entirely on rm:bridge_bicycle) can never reach the
log the README says covers them (executed). SF-D2 resolvers match `name` only, never
`bridge:name`, OSM's conventional home for a structure's name on a road way (likely shape for
Sousa, Benning, Whitney Young, 11th local) — medium-high, unverifiable here. SF-D3
MIN_URBAN_FRACTION pinned equal to MIN_JURISDICTION_FRACTION (0.10) but they answer opposite
questions: jurisdiction is inclusive (over-report is safe), urban is a binary switch to the
LOWER-stress default (30 vs 50 mph), so 10% inside Leesburg's polygon grades a Loudoun way urban
end to end and out of is_top_tier; should be a majority, decoupled, asymmetry written down.
SF-D4 `cycleway_values` dropping cycleway:left/right survives (1833 passed) — the dominant DC
tagging for a one-way street; a 25 mph oneway with cycleway:left=track goes LTS1 → LTS3 under
the mutation; only the values were enumerated in round 5, not the keys.

**NIT.** README never states the scope of the crossing set (Anacostia rail crossings absent).
revisits takes cos at the mean latitude (≤0.3% narrow at the extremes; unreachable on the
fixtures). conflate rank has no final way_id term (three-way tie → input order). has_shoulder
returns True for shoulder=no + shoulder:width (documented; say it is deliberate).
