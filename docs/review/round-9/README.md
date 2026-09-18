# Round 9 review — phase 1

Six independent reviewers on `17a912b`, the wave-7 merge. **Six REVISE**, eight blockers: one each
in routing, the database, deployability and test quality, two each in the domain and access
control. The domain's three-round run of acceptances ended on two findings no round had reached
(an LTS inversion between one-sided and two-sided provisions; a count's agency and year dropped
before anything durable). One blocker was a direct consequence of wave 7's own fix — access
overrides reaching the extract now collided there with the crossings fixture — and one was a
wave-7 claimed kill that did not reproduce. Every reviewer verified every wave-7 item in their
area closed by reversion, with the exact edit recorded beside each verdict.

| Reviewer | Verdict | Blocking | Lead finding |
|---|---|---|---|
| [Routing and tile pipeline](routing.md) | REVISE | 1 | the crossings fixture outranked the audited override table on all eighteen crossing rows |
| [Database, scheduler, operations](database-pipeline.md) | REVISE | 1 | the operations page's free-space block reassured about a filesystem the api container cannot see |
| [Cycling / DC-region domain](domain.md) | REVISE | 2 | provisioning both sides of a road rated it worse than one; a count's agency and year were dropped, so a conditionally licensed source's influence could not be named |
| [Access control, sign-in, privacy](security.md) | REVISE | 2 | a padded URL turned every refused admin write into a 500 with no audit row; a duplicate `action` parameter walked past the action guard |
| [Test quality by mutation](test-quality.md) | REVISE | 1 | the entrypoint's cgroup quota read was pinned by its own comment, and wave 7's claimed kill did not reproduce |
| [Deployability](deployment.md) | REVISE | 1 | the guide sourced `.env` into the shell before `docker compose`, so two runs of the documented procedure produced two database passwords |

Kill rate this round 75.4% (134 mutants, 101 killed), the fresh pass at 70.7%; coverage 97%. One
reviewer claim was corrected by the wave that closed it: the `$$` escape in an env file was right,
and it was `docker compose config`'s re-escaped output that had been read as the container's
value. Wave 8 closed every item on five area branches plus a sixth for the test-quality survivors,
each fix with a mutation confirmed to fail; the five area branches merged without a conflict and
the orchestrator carried the two seams the domain branch could not reach.
