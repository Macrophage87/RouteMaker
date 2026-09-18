# Phase 1 review retrospective — rounds 3 to 10

Written after round 10 at the owner's request, to answer three questions: what has been blocking,
what is genuinely blocking the phase now, and why the loop is not converging. The proposal at the
end is a recommendation, not a decision; the decisions it needs are the owner's.

## 1. The numbers

| Round | Reviewers | Blockers | Areas accepted | Regressions from the previous wave |
|---|---|---|---|---|
| 3 | 5 | 19 | 0 | — |
| 4 | 5 | 10 | 0 | 0 |
| 5 | 5 | 14 | 0 | 0 |
| 6 | 6 | 9 | 1 (domain) | 0 |
| 7 | 6 | 5 | 2 (domain, routing) | 0 |
| 8 | 6 | 6 (5 distinct) | 1 (domain) | 0 |
| 9 | 6 | 8 | 0 | 2 (rows 65, 72) |
| 10 | 6 | 5 | 1 (access control) | **4 of 5** (the fifth is a test-only guard, kind E) |

284 commits, 3293 tests, 72 numbered findings closed, 49 recorded gaps, seven review directories.
Every finding from rounds 3 to 9 is closed on the tree with a reversion confirmed to fail.

The blocker count fell from 19 to 5 over rounds 3 to 7 and has not fallen since. The composition
changed underneath: rounds 3 to 5 were mostly things that did not exist (no elevation stage, no
source extract, no Dockerfiles, no `wsgi`, no `Caddyfile`); rounds 6 to 8 were pre-existing defects
reached by reviewers told to look where earlier rounds had not; rounds 9 and 10 are mostly defects
**introduced by the wave that closed the previous round**.

## 2. Every blocker, classified

Five kinds. The row numbers are `handoff.md` §3's.

**A. Build gaps** — a plan-named thing was absent or could not run. Rows 6, 7, 8, 9, 11, 12, 28,
31, 32, 42, 43, 44, 45, 49, 50, 54. Sixteen. Concentrated in rounds 3 to 6; none since round 7.
These were the reviews doing what the missing execution environment could not: nothing in this
repository has ever been built or started, so "does it run" has only ever been answered by reading.

**B. Pre-existing defects found by fresh reach** — real, reachable, in code no wave had touched.
Rows 1, 2, 3, 4, 5, 10, 13, 14, 16, 19, 20, 21, 22, 24, 25, 29, 30, 33, 34, 46, 47, 48, 51, 52,
55, 56, 57, 60, 61, 62, 63 (record half), 66, 67, 68, 69, 70, 71 (the sourcing half). Thirty-seven.
The largest class, and the one the loop is designed to find. Their consequence ranges from "a
deployment never rebuilds again" (62) to "a healthcheck flag" (56).

**C. Regressions from a fix wave** — introduced or left incomplete by the wave that closed the
previous round. Rows 18 (round 3, the orchestrator's own), 65 (wave 7: overrides reaching the
extract collided with the fixture), 72 (wave 7: a claimed kill satisfied by a comment), and four of
round 10's five: the compose pull policy that builds unconditionally (wave 8), the side rule not
applied within a side (wave 8), the api tiles mount making a documented refusal false and a
half-swapped state reachable (wave 8), and the directional override withholding the fixture's grant
wholesale (wave 8). Seven, **six of them in the last two rounds.**

**D. Record gaps** — a plan-named behaviour absent and not written in §7. Rows 63 (the guild admin's
mapping action), 68 (in part), and the "not in §7" clause that turned several B-class findings from
should-fix into blocking. The blocking definition every brief carried — "…or a plan-named behaviour
absent and not recorded in `handoff.md` §7" — makes a missing paragraph a phase blocker.

**E. Test-only** — a value or guard replaceable with the suite green, no wrong behaviour on the
tree. Rows 15, 17, 26, 27, 35, 36, 37, 38, 39, 40, 41, 53, 58, 64, and round 10's sentinel guard
(row 72 sits in both C and E). Sixteen. The test-quality
reviewer's blocking definition ("a value the router or the authorization path weighs can be
replaced by a constant with the suite green") counts a hole in the suite as a blocker on the phase.

So of 77 blockers over eight rounds: 16 build gaps (all closed), 37 defects (all closed), 7
regressions (4 open), 16 test holes (1 open), and a handful of record gaps. **What is open on the
tree today is four small regressions from wave 8 and one missing test.**

## 3. Why it is circling

Six mechanisms, in order of weight.

1. **The exit condition cannot be met by a loop whose brief mandates fresh reach.** Acceptance
   needs six independent reviewers to each report zero blockers in the same round, and every
   round's brief tells each reviewer to "reach for what N rounds have not". A reviewer who
   reaches will find something; a reviewer who finds something files it; and the blocking
   definition (§2, kinds D and E) lets a documentation row or an unpinned constant carry the
   verdict. The domain was accepted three rounds running and lost it in round 9 to two findings in
   code no wave had touched. Under this rule the residual defect rate has to reach exactly zero
   across six areas simultaneously. It will not.

2. **Fixes ship without the adversarial pass the reviewers apply.** Each wave's agent proves its
   fix with a mutation that fails and a suite that passes, then hands back. The next round's
   reviewer then does what the agent did not: runs the fix's *claim* rather than its test, on the
   merged tree, against the neighbouring key form or the neighbouring container. Round 9 found two
   of wave 7's; round 10 found four of wave 8's. The wave's proof standard ("the exact mutation
   that now fails") proves the test catches the change; it does not prove the change is right.

3. **Three areas are being patched piecewise where they need one design.**
   - *LTS side and width semantics* (`routemaker/tags.py`, `stress.py`): rows 13, 23, 29, 30, 36,
     37, 67, and round 10's B1 — seven rounds of patches to how the four cycleway and shoulder key
     forms combine, each fixing the case in front of it and leaving the next key form untested.
   - *What wins in the extract* (`pipeline/run.py` `inject_tags`, `overrides.py`, the crossings
     fixture, the variant rules): rows 4, 24, 59, 65 and round 10's B-1 — the precedence among
     source tags, the fixture's legality opinion, an approved override and the e-bike variant has
     never been written down as one table, so each fix changes one edge of it.
   - *Rollback, containers and mounts* (`pipeline/promotion.py`, `compose.yaml`, both runbooks):
     rows 22, 41, 47, 61, 62, 66 and round 10's B10-1 — which container may run which command,
     what it can see, and in what order the rollback touches tiles and schemas has been settled
     five times and unsettled by the next mount change.

4. **Documentation is pinned by prose tests, which then defend the stale sentence.** Rows 46, 72
   and round 10's SF10-1 are a test asserting a sentence rather than a property; when the code
   moves, the test holds the guide to the old state and a correction fails the suite.

5. **Every deployability finding is derived, not observed.** There is no Docker daemon, no
   Valhalla, no osmium, no Geofabrik in this environment. Rounds 6 to 10 walked the deployment by
   rendering compose, reading library source and running the pieces that will run here. That has
   found real things — but round 9's `$$` finding was a misreading of `docker compose config`'s
   output, and round 10's pull-policy finding rests on reading Compose's source. The reviews are
   standing in for a `docker compose up` that has never happened, and they cannot finish that job.

6. **The record is now large enough to be a cost.** `handoff.md` is over 800 lines; §7 has 49 rows;
   the review directories hold 45 reports. Wave agents are told to read the relevant reports and
   rows before fixing, and reviewers to read the previous round's; both are spending a rising share
   of their budget reading the record rather than the code.

## 4. What is genuinely blocking phase 1 today

Two things, and they are different in kind.

**The stack has never run.** Not the compose build, not `up -d`, not a rebuild against Valhalla,
not the reference-route smoke check, not a sign-in through a browser, not a backup and restore on
the real containers. §6's caveat has said this since round 3. No number of review rounds changes
it, and the remaining derived findings (Debian package names, Valhalla's config keys at startup,
rebuild memory) are exactly the ones a first run answers in an hour.

**Four small wave-8 regressions, open on the tree**, plus one should-fix that behaves like a
blocker:

| Area | Open item | Fix size |
|---|---|---|
| Deployability | `pull_policy: build` builds unconditionally; the documented rollback rebuilds the current tree under the old tag | one word (`never`) + three doc passages |
| Domain | the worst-side rule is not applied within a side: `cycleway=track` + `cycleway:right=no` still rates LTS1 on a 35 mph arterial; widths still side-blind | one function each in `tags.py` + a grid test |
| Database | `rollback_rebuild` in `api` (now that it mounts the tiles read-only) swaps schemas, fails on the mount, and can lose the re-swap lock; guides and a test say the opposite | re-order the rollback (tiles before schemas, or a write probe) + the docs + the test |
| Routing | a directional-only override withholds the fixture's bidirectional grant wholesale | scope the withholding to the keys the row wrote |
| Test quality | the sentinel read's "one and the same way" guard has no test that fails for that reason alone | one assertion |
| Access control (should-fix) | a pending instance-admin removal survives the target's stand-down and later strips a re-appointment | clear the pending row on re-appointment |
| Domain (should-fix, from test quality) | `is_oneway` accepts any `oneway` value, so `oneway=no` would read as one-way and the side rule fall back to the union | one line + a test |

Everything else open — 49 §7 rows, the round-10 should-fixes and nits, the test-quality survivors
— is backlog: recorded, not blocking anything an organizer or an operator would meet in phase 1's
first month.

## 5. A route out

The recommendation, in order. Steps 1 and 2 are independent of each other.

**Step 0 — change the exit condition, once, on the record.** Replace "six ACCEPTs in one round"
with an acceptance checklist that can be executed:

1. `docker compose build` and `docker compose up -d` on a host with a Docker daemon, from
   `.env.example` filled in;
2. a first weekly rebuild that completes, validates and promotes, against the real Valhalla
   3.5.1 image and a real Geofabrik extract;
3. the reference-route smoke check passing on all three variants;
4. sign-in, bootstrap, a guild admin's own-guild edit and a refused cross-guild write, through a
   browser;
5. `perform_backup`, then the restore runbook onto a fresh data directory, then a second rebuild;
6. `rollback_rebuild` after that second rebuild, and the routers restarted.

The panel then answers a narrower question: *does the wave's diff regress anything, and does the
checklist pass?* Blocking means a checklist failure, a regression, or a grant of standing the plan
does not make. A fresh-reach finding that is none of those goes to the backlog with a §7 row and
does not withhold acceptance. This is the decision the header of `handoff.md` has been asking for
since round 8.

**Step 1 — one consolidation wave, scoped, with a design note per hot spot.** Not another
round-driven fix list. Six items:

- the four open regressions and the removal/re-appointment should-fix from §4, each with the
  reviewer's own probe turned into the test;
- *LTS side model*: build one per-side facility record (value and width) from the four key forms
  with explicit precedence — side-specific over `both` over general, a `no` side is an absent
  side — then classify the worst side; replace the case pins with a property test over a
  generated grid of every key-form combination (presence × side × width × oneway), asserting
  monotonicity (adding a facility on either side never raises the tier; a narrower width never
  lowers it);
- *extract precedence*: write the table — source tags, then the fixture's legality opinion, then
  an approved override, per key and per direction, with the e-bike variant rule applied last —
  and implement `inject_tags` from it; make the override report reach the run detail;
- *rollback and containers*: demote the tiles before the schema swap so a read-only mount fails
  before any rename, add a write probe to `rollback_rebuild`'s pre-flight, and name one container
  (`rebuild`) as the only home for every data-volume command in both guides;
- replace every doc test that asserts a sentence with one that asserts the property (the rendered
  configuration, the presence of a section, a command's argv), and delete the ones that cannot be
  rephrased;
- trim the record: fold `handoff.md` §3's closed rows into the review directories, keep §1, §2,
  §5, §6, §7 and a one-page §3 of what is open.

Before merging, a single diff-scoped adversarial pass by one reviewer (not a six-area panel): run
each fix's claim on the merged tree against the neighbouring case. That is the check waves 7 and 8
lacked, and it costs a tenth of a panel.

**Step 2 — run the checklist on a real host.** A small VM or the owner's machine with Docker and
the network allowances `handoff.md` §2 lists (the Valhalla image registry, Geofabrik, 3DEP). Expect
the first `docker compose build` and the first rebuild to fail on things no review could see —
package names, a Valhalla config key, memory — and treat those failures as the next wave's only
list. This is the step that has been missing since round 3, and it is the one that actually ends
the phase.

**Step 3 — one final panel under the new rule, then accept.** Diff-scoped, checklist-gated, with
the narrowed blocking definition. If it returns zero regressions and the checklist holds, phase 1
is accepted on the record with §7 as its known-gaps list. If it returns a regression, one more
scoped wave, not a new round of reach.

**What to keep from the loop.** The mutation-after-test rule, the exact-edit record beside every
verdict, the reviewer probes becoming tests, the one-worktree-per-agent discipline, and the §7
convention of recording rather than silently deferring. Those are what turned 19 blockers into a
tree with 3293 tests; they are not what is holding the phase open.

**What it costs.** The consolidation wave is one day of agent time in the shape of the last two.
The checklist on a host is half a day if the images build, longer if Valhalla needs iteration —
and that iteration is the real remaining work of phase 1, which no amount of review here can do.
