# Round 5 — Test quality by mutation — REVISE (7 blocking)

Reviewed at `9601c34` (the wave-3 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-4 disposition of every item is in `../../../handoff.md` §3.


157 mutants, 156 verdicts, 135 killed, 20 survived, 1 discarded (bad edit, re-run and killed).
Kill rate 86.5% (round 4: 85.6%); coverage 97%. All 26 round-4 survivors killed as literal edits.
Wave-3 sampled claims 29: 26 killed, 3 survived (a2′ `rows_before = {}` equivalent; prune-symlink-1
equivalent; a4 `_retired_holds_a_graph → True` BLOCKING). a1/a2 hold independently. A7/E3 cannot be
re-derived — the round-4 mutant catalogue was never committed; require mutation text with verdicts.

Fresh pass 101 mutants: 84 killed, 17 survived.

**BLOCKING.** F_LUA3 remap gate `stress_tier == 1` → `<= 2`: Lua tests cover tiers 1 and 4 only.
F_STR7 SEPARATED_CYCLEWAY drops opposite_track (appears nowhere in tests); SEPARATED/PAINTED sets not
enumerated like classes.py's. F_STR8 `if shoulder_tier < tier` → `<=`: on a tie shoulder_credited
flips → has_facility → volume-gate exemption; the 648-case sweep never lands on the tie. F_VAR3
resolve_sidepath_bridge_ids' `bridge in (None,"no"): continue` deletable → Key Bridge Road etc.
resolve sidepath-only (the identical guard in resolve_bridge_bicycle_legality IS caught). F_AOP2
admin_operations.changelist_view's PermissionDenied deletable → a guild admin gets the operations
page (admin_view raises 404 on has_permission = staff, which a guild admin is; the override never
calls super). F_TIL2 disk gate drops `usage.free < required`: fraction alone passes with 2 GB free
on 10 TB. C_PROMO_A4/F_PROM3/F_PROM4 rollback_target: three of four clauses individually deletable;
both refusal tests satisfied by the fourth and assert only `"previous" in str(...)`; (a) reopens
"live 5→0 segments".

**SHOULD-FIX.** F_RNS1 prune_run_rows newest-successful keep set deletable. F_RNS4
TERMINAL_JOB_STATUSES gains "doing" survives. F_PROM2 undo loop narrowed to outcome.promoted
survives (comment argues every variant). F_RUN3 zero-byte admin/timezone db passes. F_IRD5 feature
id drops the file stem survives (comment names the county-restart collision). F_ADM1
RouteMakerAdminSite.has_permission is_active conjunct (defence in depth, unasserted).

**Equivalent/accept.** F_VAR2 load_sidepath_bridge_ids has NO CALLER (dead code; delete). F_AUD2
detail[:2000]. F_RUN7 REPORTED_VIOLATIONS. prune-symlink-1.

**Order/state.** Reverse file order 1590 passed. Instrumented every test: TWO schema leaks —
test_pipeline_end_to_end.py::test_a_trail_alongside_a_road_cannot_take_the_roads_count[road-first]
and ::test_the_shared_use_path_on_a_bridge_is_not_barred_by_the_roadways_row take (tmp_path, states)
not segment_schemas and leave `staging` populated; masked because the next segment_schemas fixture
drops-then-creates. Migrations fingerprint constant (7570c97 genuinely closed). Settings/filesystem/
module globals clean.
