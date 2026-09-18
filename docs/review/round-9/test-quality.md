# Round 9 — Test quality by mutation — REVISE (1 blocking)

Reviewed at `17a912b`. 134 mutants applied, 134 verdicts: 101 killed, 33 survived, no APPLY_FAIL,
collection error, timeout or discard; every survivor re-run serially and reproduced. Coverage 97%
over `src/`.

**Round-8 survivors as literal edits:** 35 mutants, 32 killed — the blocking F66 and all 27
should-fix survivors are closed — and the three accepted equivalents (F12, F30a, F74) re-proved,
F30's sibling on the enclave sort being killed, which is what identifies it.

**Sampled wave-7 claims:** 48 across five branches; 47 reproduce, one does not (the deployability
branch's "cgroup quota read before `nproc`").

**Fresh pass over the wave-7 code:** 99 mutants, 70 killed, 29 survived (70.7%), the tests' own
helpers included this round.

**What would change my verdict:** one test that executes the entrypoint's cgroup branch, or pins the
call rather than the string.

## BLOCKING
**B9-1.** `docker/api-entrypoint.sh`'s cgroup cpu-quota read is pinned by a comment. The test
asserts that `/sys/fs/cgroup/cpu.max` appears before `$(nproc)` in the raw file text, and the
comment block above the function satisfies it: replacing the whole `if cores=$(cgroup_cpus) … else
cores=$(nproc)` block with `cores=$(nproc)` leaves 2988 green, and deleting the function too leaves
the 139 deploy tests green. The two tests that execute the script take the `nproc` fallback in both
the mutant and the original, because this box has no `cpu.max`. Reverted, a hand-run container
falls back to `nproc·2+1` = 17 workers in a 2 GB cgroup — wave 7's own SF-5. Blocking twice over:
a plan-named guard deletable with the suite green, and a claimed kill that does not reproduce. Two
siblings inside the unreached branch: the ceiling division and the floor of one.

## Should-fix survivors (27)
`extract.py`: the `source_tags` snapshot can be emptied (the alias is pinned, the content is not);
`compare=False`. `run.py`: `_jurisdictions` `setdefault` → `__setitem__`; the merge order of the
override diff and the `rm:` tags. `retention.py`: four on `_prune_dump_parts` — the `kept` slice,
the `<` boundary (the equal instant is the live write), the `is_file()` guard, `kept[-1]`.
`runs.py`: `MAX(applied)` → `MIN`; both free-space comparators at their boundaries; the zero-total
fallback direction; the free-space half of the alert deleted; `fraction * 100`. `unwedge_job.py`:
the threshold to 300 s; `.exclude(id=job_id)`; the read-back replaced by the constant `"todo"`.
`rollback_rebuild.py`: `in_flight[0]` → `[-1]`. `tags.py`: the one-way lane floor. `measure.py`:
the cell margin's upper side; the cosine floor. `jurisdiction.py`: the shared-boundary tolerance
tenfold. The entrypoint's two arithmetic siblings; `.env.example`'s commented `WEB_CONCURRENCY`.
And two of the tests' own helpers: `make_a_plain_member_of` can be emptied with its test still
passing for the wrong reason, and the doc collector's `.strip()` can be dropped so indented osmium
lines are never read.

## Equivalent — accepted
The U+2028/U+2029 escape rows under `ensure_ascii=True`, already recorded in the source.

## Order and state
Reverse file order and full item reversal both green; the per-test hookwrapper over schemas,
settings, the data directories, ten modules' globals and `os.environ` recorded only pytest-django's
own two boundaries.

**Wave 8:** a sixth branch on top of the merged tree pins the survivors; see the wave-8 table in
`handoff.md` §3 for what closed and what was recorded as equivalent on the merged tree.
