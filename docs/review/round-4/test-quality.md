# Round 4 — Test quality by mutation — REVISE (1 blocking cluster)

Reviewed at `66ccb03` (the wave-2 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-3 disposition of every item is in `../../../handoff.md` §3.


187 mutants, 160 killed, 27 survived (85.6%; round 3: 71%). Coverage 96%. 0 skipped. No APPLY_FAIL.
Round-3's 50 survivors reconstructed as 54 mutants: 46 killed, 8 survive (A7 and E3 equivalent —
accept; D9/D10/D11 swap defaults; E2 sweep_priority tautology; F2 is_staff; F8 gdalwarp). Every
sampled fix-agent kill (≥3 per cluster) reproduced.

**BLOCKING cluster.** L5 `derived["stress_tier"] = 1` in inject_tags → 945 passed: the e2e test
asserts presence only (`tags[100].get("rm:stress_tier")`), the segment-table tier is asserted on a
different path. AD7 drop `motorway_link` from ALWAYS_TOP_TIER_HIGHWAY → 945 (on-ramp admissible to
Beginner). AD6 drop `steps` from TRAIL_CLASS_HIGHWAY → 945 (staircase scored as a road).

**SHOULD-FIX.** 3.1 sweep_sessions clauses I5/I6 mask each other (= security S-8). 3.2
test_degraded_sweep_prioritises_active_sessions: the session row is also the stalest → E2 survives;
swap the timestamps. 3.3 stale_tasks staleness comparison deletable (945); STALE_AFTER nightly_backup
26h→260h and membership_sweep 12h→120h survive; only weekly_rebuild pinned. 3.4 swap defaults
(3_000, 5, 2.0) unexercised; perform_swap calls swap_schemas() bare so DEFAULT_ATTEMPTS=1 ships no
retry (PLAN:290). 3.5 F2 is_staff ban conjunct; Q2 has_perm `_admin_guild_ids` guard; N3 middleware
user= conjunct — all masked by a second guard. 3.6 Y9 roadway `width` ahead of cycleway width chain;
P3 parking absent set dropping no_parking/no_stopping/no_standing; Z3 has_shoulder → True — all 945.
3.7 R2 reconcile drift join without `o.ordinal = n.ordinal` survives (one segment per way in fixture);
I1 gateway_has_ever_reported filtered to succeeded=True survives.

**NIT.** P5 token_urlsafe(32)→(24) (`>= 32` where == 43 available); `>=` shapes at
test_admin_scoping:220, test_valhalla_config:93 max_alternates. L1 handlers assert redundant. U3
extract.derived_tags `if value is None: continue` deletable. AD1 MIN_MEANINGFUL_LENGTH_M 25→2500
survives. F8 bilinear. test_schema_swap:293 users-survive assertion with no user created.
cards.py still has no caller (phase 4).

Answers: test_plan_constants typed in, all ten killed; shoulder property constrains (G2 83 fails, G3
34) with two blind spots; cold-worker test kills H1/H2; promotion 7/7; audit HTTP tests discriminate;
is_forgotten 4/4; heartbeat gate killed.
