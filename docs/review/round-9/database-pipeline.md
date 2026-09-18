# Round 9 — Database / scheduler / rebuild operations — REVISE (1 blocking)

Reviewed at `17a912b`. Nineteen of twenty wave-7 items closed by reversion; `STALLED_WORKER_TIMEOUT_S`
30 → 30000 survives (N9-1). Weighed and upheld, each against the pinned library source or by
execution: the epoch as the earlier of the two (per-task "watched from" would reintroduce B8-1;
`max` fails five tests); `JobAborted` lands `aborted`, confirmed by running the shipped worker
command against a real duplicate; the 30 s threshold is Procrastinate's own and a wrong verdict is
bounded on one slot because `finish_job` consumes the requeue; `retry_job_by_id` always requeues
and costs a retry budget slot; `_abort_job` writes in memory only, so a stop mid-build ends at
SIGKILL with the row `doing`, exactly as §7 says.

**What would change my verdict:** the operations page's free-space block measuring the tiles
volume, or saying that it cannot.

## BLOCKING
**B9-1.** The page is served from `api`, which mounts no data volume: `TILES_DIR=/app/data/tiles`
→ nearest existing ancestor `/` → `headroom None` → "The tiles volume has room for the next
rebuild." A positive claim about a filesystem the process cannot see, on the surface PLAN.md:290
names, rendered whenever nothing is wrong. Surviving mutations: `_nearest_existing(TILES_DIR)` →
`("/")` (64 passed); the sentence → anything (42 passed). §7's row read as settled and offered
`worker` as an honest home, which binds backups only.

## SHOULD-FIX
- **S9-1.** `docs/OPERATIONS.md:69-71` still states B8-1's rule as current.
- **S9-2.** The `--project-directory … exec -T api` alternative, fourteen lines under the paragraph
  explaining it must not be `api`.
- **S9-3.** `promotion.py`'s `add_note` never reaches the run row (`str()` drops `__notes__`), and a
  swap whose undo failed stays retryable.
- **S9-4.** The cron check now spawns a Django process inside the rebuild's 8 GB cgroup every ten
  minutes, including during a build.

## NIT
N9-1 the threshold asserted against itself; N9-2 §7 wrong about `worker`; N9-3 a test docstring
naming `api`.

**Wave 8:** B9-1 closed on two branches — `disk_headroom()` returns ok/short/unmeasured with the
path, `unmeasured` is an alert line and exit 1 and the page never reassures (both wave-7 survivors
now fail), while `api` and `worker` gain a read-only tiles bind and the cron entry moves back to
`worker`, which also closes S9-4. S9-3: `record()` writes `failure_detail()` with every note down
the cause chain, and `SwapUndoIncomplete` is terminal. S9-1 and S9-2 corrected in the guides.
`unwedge_job`'s next-steps text is task-aware. N9-1 reads Procrastinate's own default; N9-3 fixed.
