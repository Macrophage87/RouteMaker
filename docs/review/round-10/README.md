# Round 10 review — phase 1

Six independent reviewers on `0d79759`, the wave-8 merge, under a tightened standard: every wave-8
item verified by reversion **and** by executing what the fix claims. **One ACCEPT** — access
control, sign-in and privacy, for the first time in ten rounds — **and five REVISE**, one blocker
each. **Four of the five blockers are wave 8's own**: a compose pull policy read as a fallback that
is unconditional; the side rule not applied within a side; a documented rollback refusal made
false by a new mount, with a half-swapped state reachable behind it; and a directional override
withholding the fixture's bidirectional grant. The fifth is a guard deletable with the suite green.
Every wave-8 item verified closed, and every one of 38 sampled wave-8 kills reproduced.

| Reviewer | Verdict | Blocking | Lead finding |
|---|---|---|---|
| [Routing and tile pipeline](routing.md) | REVISE | 1 | a directional-only approved override withholds the fixture's grant in the direction nobody overruled; the bridge is served barred both ways |
| [Database, scheduler, operations](database-pipeline.md) | REVISE | 1 | `rollback_rebuild` in `api`, which now mounts the tiles read-only, swaps the schemas, fails on the mount, and can lose the re-swap lock to the api's own readers — reproduced to a half-swapped state the next rebuild turns into data loss |
| [Cycling / DC-region domain](domain.md) | REVISE | 1 | the worst-side rule is not applied within a side: `cycleway=track` + `cycleway:right=no` still rates LTS1 on a 35 mph arterial |
| [Access control, sign-in, privacy](security.md) | **ACCEPT** | 0 | a pending instance-admin removal survives the target's stand-down and later strips a re-appointment (should-fix) |
| [Test quality by mutation](test-quality.md) | REVISE | 1 | the sentinel read's one-way guard is deletable with the suite green; the test that covers it fails for the other reason |
| [Deployability](deployment.md) | REVISE | 1 | `pull_policy: build` builds unconditionally, so the documented `TAG` rollback rebuilds the current tree under the old tag |

Kill rate this round 84.7% (170 mutants, 144 killed), the fresh pass at 79.6%; coverage 97%.
**No wave followed this round.** The owner asked for a hold and a retrospective over the whole
review history; it is at `docs/review/retrospective.md`.
