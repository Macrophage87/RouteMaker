# Round 6 review — phase 1

Six independent reviewers on `00ee400`, the wave-4 merge, with a deployability reviewer added
because five rounds had read the code for correctness and none had asked whether the stack could
start. **One ACCEPT** (the cycling / DC-region domain, the phase's first) **and five REVISE**,
every one of the five with a single blocker except deployability, whose walk-through found five.
All six verified every round-5 finding in their area closed by reversion, with the exact edit
recorded beside each verdict.

| Reviewer | Verdict | Blocking | Lead finding |
|---|---|---|---|
| [Routing and tile pipeline](routing.md) | REVISE | 1 | osmium cannot detect an output format from a `.part` name; both extract steps would throw |
| [Database, scheduler, operations](database-pipeline.md) | REVISE | 1 | the documented rollback runs in the one container that cannot see the tiles |
| [Cycling / DC-region domain](domain.md) | **ACCEPT** | 0 | a million-case re-run of the provision property at zero failures |
| [Access control, sign-in, privacy](security.md) | REVISE | 1 | `GET <admin>/logout/` signs the person out cross-site |
| [Test quality by mutation](test-quality.md) | REVISE | 1 | the instance-admin listing's allowed-lookup set is unpinned: a working oracle over admins' session epochs |
| [Deployability](deployment.md) | REVISE | 5 | `.env.example`'s `PGHOST=127.0.0.1` defeats compose; nothing reaches the database |

Kill rate this round 79.2% (144 mutants, 114 killed); the fresh pass deliberately targeted argued
constants and one-clause guards. Coverage 97%. The deployability reviewer executed what could be
executed without a daemon: rendered the compose configuration, ran migrate from an empty PostGIS,
booted gunicorn under the rendered api environment, ran collectstatic, and validated and served
the Caddyfile under a real Caddy 2.8.4 binary.

Wave 5 closed every item on six branches (one per reviewer), each fix with a confirmed-failing
mutation; disposition per item is in `handoff.md` §3.
