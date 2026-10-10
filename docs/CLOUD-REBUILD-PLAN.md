# Cloud rebuild: plan

The backlog item FOLLOWUP-CLOUD-REBUILD. This plan collects what the owner has decided, splits
the work into what the code needs and what is infrastructure the owner provisions, and lists
every open question with a recommended default. Owner decision numbers refer to the owner
decisions record (OWNER-DECISIONS-2026-09-26b.md, outside the repository; PLAN.md "Owner
amendments" carries the ones already built). The checkpoint design is in the owner's report
folder (`rmdata/demo/reports/REBUILD-CHECKPOINTS-design.md`, not in this repository); what
version 1 does is docs/OPERATIONS.md, "Rebuild checkpoints", whose "Not done" list is the
starting point here.

## What the owner has decided

- **Checkpoints first** (459, built as version 1). A retried rebuild resumes from the last
  good checkpoint, reusing one only when every input it depends on is unchanged.
- **The cloud box is on the backlog, after checkpoints and Valhalla 3.6** (459a, 459b (2)).
  459a as recorded: an ephemeral cloud build box; the owner creates and owns the AWS account;
  no keys in the repository; artifacts are shipped the way `ship-data.sh` ships them. Valhalla
  is pinned at 3.9.1 now, so the second condition is met; the first is met for one machine.
- **One instance per rebuild, on-demand or spot** (459c). "This will be mainly on an AWS cloud
  instance anyway, so making an on demand or spot instance would work well." For spot,
  checkpoints live on durable storage (an EBS volume or S3), and a reclaimed instance resumes
  on a new one, so resuming across instances and jobs (the design's version 2) is required,
  with the same input fingerprints.
- **The time budget is per attempt** (459a, 459b (1)): `REBUILD_TIMEOUT_S`, 8 hours by default,
  at most 23 hours; a pre-swap timeout that made progress is retried, at most twice. A spot
  reclaim is not a timeout and needs its own rule (question 6).

## What is built (this branch)

`pipeline.checkpoint_store`, the mechanism of version 2, with tests
(`tests/test_checkpoint_store.py`). It needs no new owner decision and no cloud access, and it
is **not wired into the rebuild**: nothing in `pipeline.run` calls it yet, so production
behaviour is version 1's.

- **A run key.** A short name (`rebuild-20261013-8408`: lowercase letters, digits, hyphens, at
  most 64 characters) that the launcher gives one rebuild and hands to every instance that
  works on it. Version 1 keys on the Procrastinate job id, which a new job or a database on a
  lost instance does not keep. `run_key_for_job(job_id, day)` is the suggested default.
- **A durable store.** `CheckpointStore`, six methods (put and get a file, put and get a JSON
  manifest, delete, list), with the contract written in its docstring: atomic per key, nothing
  atomic across keys, read after write. `LocalDirectoryStore` implements it on a directory (an
  EBS volume moved to the replacement instance, or the local disk). An S3 store implements the
  same six methods later; no AWS SDK is a dependency.
- **Publish and restore.** `publish_checkpoint` deletes the old manifest, uploads every output,
  then the manifest, last (version 1's "written last", as an order). `restore_checkpoint`
  reads the manifest first, keeps a local file that already hashes right, downloads the rest
  beside their destinations, hashes each and renames it into place only if it matches; a
  damaged or missing file means no checkpoint, and nothing unverified is left behind.
- **Portable validation.** `portable_problem` refuses a checkpoint of another format, another
  run, a build id that is not one or is `current`/`previous` here, a build other than the run's,
  one older than a limit or dated in the future, or one whose fingerprint differs **by
  content** from what is measured on this machine. `content_only` drops `mtime_ns` (a restore
  rewrites every mtime, so version 1 would reuse nothing), and
  `portable_graph_fingerprint` measures the elevation tiles by sha256 instead of version 1's
  names, sizes and mtimes. As in version 1, a classification's `validation` entry only re-runs
  the staging checks.

## What the code still needs

In order; each its own branch and review. Slices 1 and 2 wait on questions 1 to 4.

1. **Wire the store into the rebuild.** A setting naming the store (unset means version 1
   exactly), a run key given to the rebuild, and in `pipeline.run`: publish the source,
   merged and variant extracts and the classification manifest after VALIDATE_SEGMENTS, and each graph after its
   manifest; at the start of an attempt with a run key, restore and check with
   `portable_problem` before version 1's own checks. The settings it adds go into
   `checkpoint.CHECKPOINT_SETTINGS` as `ignored` (where a checkpoint lives does not change the
   map). The timeout-retry count moves into the store under the run key, so the cap of two
   holds across instances.
2. **The staging schema off the instance**, if the database is on the instance (question 2):
   a `pg_dump --schema=<staging> -Fc` file published as one more output of the classification
   checkpoint and restored with `pg_restore` before the token and row-count check. If the
   database is not on the instance, nothing is needed: version 1's token check already works.
3. **Resume across jobs by hand.** `run_rebuild_now --resume <run key>` (the design's version 2
   command) and `--fresh` deleting the run from the store (`discard_run`, manifests first).
   A new job never resumes another run unless named, as in version 1.
4. **The spot interruption handler.** Poll the instance metadata for the two-minute notice;
   on it, stop between graphs (never inside VALIDATE_TILES or the swap), let the last publish
   finish, and exit with a distinct status the launcher reads as "reclaimed, resume".
5. **Shipping the result**, per 459a "like `ship-data.sh`": the promoted graphs and the
   staging rows go to the serving host, which swaps. Depends on question 1.
6. **The launcher.** Whatever starts the instance with the run key and the image, restarts a
   reclaimed run on a new instance, and stops the instance at the end. Mostly infrastructure
   (below); the repository holds its script or template, with no account ids, hostnames or
   bucket names in it.

## What the owner provisions

None of this is in the repository, and no credentials ever are (459a).

- The AWS account, a region, and the instance type(s) (questions 3 and 4).
- An instance role that can read and write the checkpoint store and nothing else, plus
  whatever the launcher needs to start and stop instances.
- The durable store: an S3 bucket with a lifecycle rule, or an EBS volume (question 5).
- The image registry the instance pulls the pipeline image from, and the route by which the
  result reaches the serving host (question 1).
- A budget alarm (question 8).

## Questions for the owner

Each has the default this plan would use if the owner says "go with the defaults".

1. **Where does the swap happen?** The rebuild box builds and checks the graphs; does it also
   promote into the production database, or ship to the serving host, which swaps?
   *Default: the box ships, the serving host swaps* (459a's "like `ship-data.sh`"; the box
   never holds production write credentials, and a bad box cannot damage `live`).
2. **Where does the rebuild's database live?** A PostGIS on the box (the classification writes
   millions of rows; local is fastest) or the production database over the network.
   *Default: on the box*, with the staging dump in the checkpoint (code slice 2).
3. **On-demand or spot?** *Default: spot with on-demand fallback*: spot first, and after two
   reclaims of one run the launcher starts an on-demand instance for the rest. Spot cuts cost;
   the fallback bounds the delay to one extra start.
4. **Region and instance type.** *Default: the region closest to the serving host; a
   memory-optimised type with at least 32 GB and 8 vCPUs* (the classification and a
   4-thread tile build; `REBUILD_TILE_CONCURRENCY=4`, as OPERATIONS.md suggests once 3.9.1
   rebuilds are clean). To be measured on the first run, not assumed.
5. **The durable store: S3 or EBS?** *Default: S3* for the checkpoints (survives any instance
   and zone; the S3 store implements the interface already defined), with the box's working
   disk a fresh volume per instance. Lifecycle: delete a run's objects after 14 days.
6. **What does a reclaim cost the budget?** *Default: a reclaim is not an attempt*: the new
   instance starts with a whole `REBUILD_TIMEOUT_S`, at most 3 reclaims per run, after which
   the run is abandoned and alerts. Timeouts keep 459a's rule (at most two retried).
7. **How old may a checkpoint be to resume?** *Default: 48 hours* (`portable_problem`'s
   `max_age_s`). Older means the map would be built from an extract that has since moved on;
   a fresh run is cheaper than explaining a stale one.
8. **A cost ceiling.** *Default: a monthly AWS budget alarm the owner sets*, and the launcher
   refuses to start a second instance for a run that already has one running.
9. **Does the serving host keep a rebuild path?** *Default: yes*, `REBUILD_CHECKPOINTS` and the
   local rebuild stay as they are, as the fallback when the cloud path is down, until the cloud
   rebuild has promoted three weekly maps cleanly.
10. **Where do the extracts come from on a fresh box?** *Default: the box downloads them from
    Geofabrik for a fresh run, and a resumed run restores the run's own copies from the store*
    (so a resumed run never mixes two days' extracts).
