# Round 5 review — phase 1

Five independent reviewers on `9601c34`, the wave-3 merge. **All five returned REVISE**, and all
five verified every round-4 finding in their area closed by reversion (the test-quality reviewer
re-ran all 26 round-4 survivors as literal edits: 26 killed; and 29 sampled wave-3 claims: 26
killed, 3 equivalent or blocking-as-recorded). The round-5 blockers are new ground.

| Reviewer | Verdict | Blocking | Lead finding |
|---|---|---|---|
| [Routing and tile pipeline](routing.md) | REVISE | 1 | nothing produces the source extract; `FETCH_EXTRACT` only checks |
| [Database, scheduler, operations](database-pipeline.md) | REVISE | 3 | worker lacks `DATA_ROOT`; failed dumps kept under the ordinary name; prune runs only after success |
| [Cycling / DC-region domain](domain.md) | REVISE | 2 | `cycleway=separate` rates the roadway LTS1; shoulder credit beside declared parking |
| [Access control, sign-in, privacy](security.md) | REVISE | 1 | compose delivers none of the settings the sign-in path reads |
| [Test quality by mutation](test-quality.md) | REVISE | 7 | argued rules one layer down: the Lua tier gate, the cycleway value sets, the operations-page gate, half the disk gate, three of four rollback preconditions |

Kill rate 86.5% (157 mutants) against round 4's 85.6%; coverage 97%. Two masked schema leaks found
by per-test instrumentation.

Found outside the panel, by the wave-4 agents while fixing panel findings, and assigned in the same
wave: the repository had no Dockerfile for any of the four `routemaker/*` images `compose.yaml`
names; `config.wsgi` did not exist though `WSGI_APPLICATION` and the api entrypoint name it; no
`STATIC_ROOT`, so `collectstatic` could not run; no `Caddyfile`, though compose bind-mounts one
(Docker would create a directory in its place). Five review rounds read the code for correctness
and none asked whether the stack could start; the round-6 panel gets a deployment reviewer.

The round-4 mutant catalogue was never committed, so two "equivalent" acceptances (A7, E3) could not
be re-derived this round. From round 5 on, the exact edit is recorded beside every verdict; the
tables in these reports are that record.
