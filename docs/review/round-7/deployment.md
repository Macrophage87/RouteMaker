# Round 7 — Deployability — REVISE (1 blocking)

Reviewed at `21a44b2` (the wave-5 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-6 disposition of every item is in `../../../handoff.md` §3.


All five round-6 blockers and seven should-fixes closed, each with the exact check (rendered
compose; migrate from empty; gunicorn on config.wsgi under the rendered env incl. the login
redirect, Secure cookie, foreign-Host 400; real Caddy 2.8.4 validate+run for both postures;
prepare_data_root.sh against a temp tree with both refusals; collectstatic; run_rebuild_now ×2;
check_operations; rollback dry run in the right container; perform_backup end-to-end; bootstrap
admin + operations page over the test client; all 8 pins with cp311+cp312 wheels; registry
manifests for the four external images; upstream valhalla Dockerfile at 3.5.1 confirming the
runner is ubuntu:24.04 with libluajit/spatialite/unzip/curl and no ENTRYPOINT/CMD/USER;
valhalla_service on an empty `current` warns and serves "no data" (graphreader.cc LOG_WARN)).

**B-1. Photon 2.4.0 on a fresh host.** ORCHESTRATOR CONFIRMED (compose:240 mounts
/photon/photon_data; src/utils/config.py at 2.4.0: DATA_DIR=/photon/data, INITIAL_DOWNLOAD
default True). The bind mount is inert (1.x path); entrypoint downloads the ~61 GB planet index
(REGION unset) onto the writable layer of the "small root volume" DEPLOYMENT.md specifies, needing
~104 GB free, else sys.exit(75) → restart: unless-stopped crash loop from the first `up`. §7 and
DEPLOYMENT.md say the opposite ("answers queries about nothing"). Nothing in phase 1 calls
Photon → `profiles: ["unbuilt"]` like bot/renderer.

**SHOULD-FIX.** S-1 DEVELOPMENT.md:229-231 still prints the osmium commands without -f pbf. S-2
"four lines" vs the five-line local block (the fifth is DJANGO_DEBUG=1, the one whose omission
reproduces round-6 B-5). S-3 OPERATIONS.md step 4 sets the bootstrap id after `up -d` and never
says `restart` does not re-read .env (DEVELOPMENT.md says "before the first start"). S-4
DEPLOYMENT.md:63 calls a TAG rollback "a restart" — restart re-reads neither .env nor the tag;
`up -d`. S-5 the reference-data command passes bare relative names that resolve under /app in the
image; should be /data/…. S-6 DEVELOPMENT.md:277 still states the pre-wave-5 intersection rule
for urban areas. S-7 check_operations exits 1 with five stale tasks from the first minute of a
fresh deployment (weekly_rebuild's window is 8 days); the documented cron pages continuously.
S-8 the first-host procedure installs VDOT only; the module says a single agency leaves precedence
nothing to arbitrate.

**NIT.** N-1 no DJANGO_ADMIN_PATH line in .env.example (ships on the public default). N-2 Caddy
header_up warning (by design). N-3 serving configs name /data/valhalla/* (harmless). N-4 nothing
says what `down -v` destroys (nothing durable: all bind mounts). N-5 no guidance on generating
DJANGO_SECRET_KEY/PGPASSWORD; `$` in a value is compose-interpolated; empty POSTGRES_PASSWORD
refuses initdb. N-6 handoff says the STATIC_ROOT comment was "removed"; it was rewritten.
Reasoned: the promotion symlink is relative and the daemon re-resolves the bind at container
start, so `docker compose restart` of a router picks up a promotion (unobserved).
