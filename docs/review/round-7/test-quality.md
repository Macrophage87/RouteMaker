# Round 7 — Test quality by mutation — REVISE (1 blocking)

Reviewed at `21a44b2` (the wave-5 merge). The wave-6 disposition of every item is in `../../../handoff.md` §3.


117 mutants, 117 verdicts, 85 killed, 32 survived, 0 discarded; every survivor re-run serially.
Coverage 97%. Round-6's 30 survivors as literal edits: 22 killed, 8 survived = the accepted
equivalents (FR27, FR45, FR99, F_ROLL_C, PRUNE_SYM1 confirmed by proof; FR18 now KILLED by wave
5's admin/timezone e2e test; FR10, FR32, F_AUD2 DISPUTED as equivalent — all three cheaply
pinnable). Sampled wave-5 claims: 24 claims / 28 checks, all reproduce. Reverse order 2731
passed; per-test instrumentation over 2730 boundaries carried nothing.

**BLOCKING N78.** conflation.rank `-overlap` → `0.0` survives 2731. Executed: an arterial on the
survey line for 98% at 12.2 m vs a frontage road at 71%/2.8 m — unmutated gives the 42,000 AADT to
the arterial, the mutant to the frontage road; the count feeds classify() → rm:stress → the
router's cost. N79 (mean_distance → 0.0) and N44 (-overlap → overlap, hands the count to the
worse candidate) survive too; every ranking test constructs equal precedence and equal overlap
and asserts only the tie-break wave 5 added (which IS pinned). Precedence is held (N80 killed).

**SHOULD-FIX (a).** N47 the logout method check `== "POST"` → `!= "GET"` survives: with it, HEAD
(CORS-safelisted, reachable with cookies from any page) returns 405 AND deletes the row; the real
tree survives HEAD; tests pin POST and GET only — parametrise over HEAD/PUT/DELETE/OPTIONS. N23
the SIDEPATH half of the unmatched union is deletable (wave 5 pinned the half it added;
test_reference_data_install.py:120 asserts non-empty only).
**SHOULD-FIX.** N60 graph.lua's `and next(changes) ~= nil` (the clause the new comment says carries
the guard) deletable; nothing tests nodes_proc. N15 variants.py "seen whether or not this way is
the one recorded" unpinned. N50 `of=("self",)` (→ pinned in wave 6 db). N42 feature_id term of the
tie-break free. N39 111,320 constant / N40 REVISIT_PROXIMITY_M / N41 GRADE_MIN_RUN_M unpinned (→ N39,
N41 pinned in wave 6 domain). N62 POSTGRES_DB literal survives because the example's PGDATABASE is
the default — render with an override. N73 chown uid 10002 survives (the list is derived, not the
uid). N75–N77 test_compose_render's own derivation constants (UNBUILT_SERVICES, DJANGO_SERVICES,
DEFAULT_PORTS) can each be narrowed — needs a canary like test_compose's. FR10/FR32/F_AUD2 pin.
**Equivalent, accept.** N46 (order with the method check present), N28, N11, N18, N37 (but the
SHOULDER_WIDTH_KEYS "same order" comment has outlived its code), N83 (with proof), N87.

Pattern for §4: wave 5 pinned what it added and left what it added it TO unpinned, three times
(conflate tie-break vs overlap; legality half vs sidepath half; graph.lua's comment vs the
emptiness clause). Write the mutation against the whole expression you edited, not the part added.
