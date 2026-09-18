# Round 7 review — phase 1

Six independent reviewers on `21a44b2`, the wave-5 merge. **Two ACCEPTs** (routing and tile
pipeline; the cycling / DC-region domain for the second round running) **and four REVISE**, each
with one blocker except the database area with two. Every reviewer verified every round-6 item
in their area closed by reversion, with the exact edit recorded beside each verdict. The container
running the session restarted once mid-panel; all six reviews were relaunched from the same
commit and nothing in the repository or its records was lost.

| Reviewer | Verdict | Blocking | Lead finding |
|---|---|---|---|
| [Routing and tile pipeline](routing.md) | **ACCEPT** | 0 | every subprocess's stderr was captured and discarded (should-fix, closed in wave 6) |
| [Database, scheduler, operations](database-pipeline.md) | REVISE | 2 | the hand-fired rebuild refuses a queued duplicate but not a running one, and the extra job breaks the running one's retry; the postgis healthcheck probes the socket the init server listens on |
| [Cycling / DC-region domain](domain.md) | **ACCEPT** | 0 | lane-direction asymmetry decides the top-tier line (should-fix, closed in wave 6) |
| [Access control, sign-in, privacy](security.md) | REVISE | 1 | the jurisdiction admin's map widget loaded OpenLayers from a CDN and tiles from the public OpenStreetMap servers the plan rules out |
| [Test quality by mutation](test-quality.md) | REVISE | 1 | the conflation ranking's overlap term can be a constant with the suite green |
| [Deployability](deployment.md) | REVISE | 1 | Photon 2.4.0 would download the planet index onto the root volume on first boot |

Kill rate this round 72.6% (117 mutants, 85 killed), a pass weighted to argued constants and
ranking terms; coverage 97%. Wave 6 closed every item on six branches, each fix with a
confirmed-failing mutation; disposition per item is in `handoff.md` §3.
