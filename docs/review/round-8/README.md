# Round 8 review — phase 1

Six independent reviewers on `60436a6`, the wave-6 merge. **One ACCEPT** (the cycling / DC-region
domain, for the third round running) **and five REVISE**, each with one blocker except the database
area with two. Every reviewer verified every round-7 item in their area closed by reversion, with
the exact edit recorded beside each verdict. None of this round's blockers is a regression from a
fix wave: each was in the tree before wave 1 and was reached by a reviewer told to look where earlier
rounds had not.

| Reviewer | Verdict | Blocking | Lead finding |
|---|---|---|---|
| [Routing and tile pipeline](routing.md) | REVISE | 1 | an approved `access` override is diffed away against the tags it rewrote and never reaches any variant extract |
| [Database, scheduler, operations](database-pipeline.md) | REVISE | 2 | a deployment whose worker never dequeued a job is "ok" for ever; `rollback_rebuild` drops the staging schema a running rebuild is writing |
| [Cycling / DC-region domain](domain.md) | **ACCEPT** | 0 | `graph.lua`'s bridge-legality sign has no test (should-fix, closed in wave 7) |
| [Access control, sign-in, privacy](security.md) | REVISE | 1 | PLAN:272's guild-admin audited mapping action is absent, unrecorded in §7, and the docstring misstates why the form is read-only |
| [Test quality by mutation](test-quality.md) | REVISE | 1 | the shipped no-basemap `base_layer` can be nulled with the suite green, at which point Django builds `ol.source.OSM` |
| [Deployability](deployment.md) | REVISE | 1 | a rebuild worker killed mid-run wedges every future rebuild and the repository holds no way out |

Kill rate this round 72.6% (164 mutants, 119 killed, 44 survived, 1 discarded), the fresh pass over
wave-6 code at 65.6% by selection; coverage 98%. Both reversal orders green; per-test state
instrumentation clean. Wave 7 closed every item on five branches — the test-quality survivors went to
the branch owning each file rather than to a sixth — each fix with a mutation confirmed to fail, and
the orchestrator re-ran one kill per branch before merging. The five merged without a conflict.
