# Round 8 — Test quality by mutation — REVISE (1 blocking)

Reviewed at `60436a6`. 164 mutants applied, 163 verdicts: 119 killed, 44 survived, 1 discarded (a
collection abort, not counted), no APPLY_FAIL, no timeouts; every survivor re-run serially and
reproduced. Coverage 98% (`src/` 96.8%).

**Round-7 survivors as literal edits:** 31 mutants, 19 killed, 12 survived — all seventeen of round
7's blocking and should-fix items are closed (N78/N79/N44/N42 the rank terms, N47, N23, N60, N15,
N40, N62, N73, N75–N77, FR10, FR32, F_AUD2, N50, N41), and the twelve survivors are exactly the set
accepted as equivalent in rounds 6 and 7, each proof re-derived (N46, N28, N11, N18, N83, N87, FR27,
FR45, FR99, F_ROLL_C, PRUNE_SYM1, N37).

**Sampled wave-6 claims:** 43 mutants, at least four per branch; every claimed kill reproduces. One
discarded (`DEGREE_OF_LATITUDE_M`, a module-level assert aborts collection; re-run at the use site
and killed) and one off-target of the reviewer's own, re-run correctly and killed.

**Fresh pass over the wave-6 code:** 90 mutants, 59 killed, 31 survived (65.6%, by selection).

**What would change my verdict:** one positive assertion in the no-basemap widget test.

## BLOCKING
**F66.** `routemaker_openlayers.html`'s shipped branch `var base_layer = new ol.layer.Vector(…)` →
`null` survives. Django's `OLMapWidget.js` does `if (!options.base_layer) { … new ol.source.OSM() }`,
so every add and change page for `Jurisdiction` and `BorderCrossing` would fetch
`tile.openstreetmap.org` in an instance admin's session — the one thing PLAN.md:15 rules out, and
the guard the template's own comment names. The test asserts only absences, which a falsy layer
satisfies. Round 7's pattern verbatim: wave 6 pinned everything it added and not the branch it added
it to. (Filed independently by the access-control reviewer as SF8-1.)

## Equivalent — accepted with proof
F30 (`ORDER BY` reorder; the consumer re-sorts stably), F12 (`not expected` → `is None`), F74 (the
stageless `RebuildTimedOut` arm is unreachable).

## Should-fix survivors (27), by owner
Routing: F14, F08, F01/F02/F03, F05, F17. Database: F73, F58, F50, F57, F54, F74's docstring.
Deployability: F80, F85, F89/F90, F87. Access control: F60, F63, F61, F62/F71, F70. Domain: F37, F47,
F33, F34, C-DM13, C-DM6. Each recorded with its exact edit in the report and the proof files.

## Order and state
Reverse file order and full item reversal both green; a `pytest_runtest_protocol` hookwrapper over
schemas, settings, the data directories, module globals and `os.environ` recorded four boundaries,
none a suite leak.

**Wave 7:** F66 pinned on the access-control branch; every should-fix survivor pinned on the branch
owning its file (F74 by docstring, as accepted). Each branch's proof file records the exact edit and
the failing test; the orchestrator re-ran one kill per branch before merging.
