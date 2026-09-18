# Round 6 — Deployability — REVISE (5 blocking)

Reviewed at `00ee400` (the wave-4 merge). Findings marked ORCHESTRATOR CONFIRMED were reproduced independently before a fix was assigned. The wave-5 disposition of every item is in `../../../handoff.md` §3.


Executed here: `docker compose config` with .env.example copied to .env; migrate from empty PostGIS
(core + 41 procrastinate migrations, no `schema --apply` needed); gunicorn config.wsgi under the
rendered api env (boots, 400 on foreign Host); collectstatic 135 files; REAL Caddy 2.8.4 validate +
run against the Caddyfile for `:80` and a hostname (static served with prefix stripped, rest
proxied); rollback_rebuild with/without DATA_ROOT; check_operations; check_compose_limits 27.0G/
25.0G rc 0; all 8 pip pins current with cp311+cp312 wheels; 12 noble packages exist.
Cannot verify: image builds; Debian bookworm names + PGDG line (403); valhalla_service first boot
against an empty `current` directory; Photon first run.

**B-1. `.env.example:20 PGHOST=127.0.0.1` defeats compose's `${PGHOST:-postgis}`.** ORCHESTRATOR
CONFIRMED by rendering: all four Django services get 127.0.0.1 = the container itself; migrate
fails, nothing starts. test_compose asserts the compose LITERAL, never the rendered value or the
env example's values — the round-3 defect reintroduced one file away.
**B-2. OPERATIONS.md:316-319 runs rollback_rebuild in `api`**, which has no DATA_ROOT and no data
mount → refuses on all three tile links (executed); the rebuild container succeeds.
**B-3. ${DATA_ROOT} subdirectories end up root-owned.** The chown runs before the first `up`;
Docker auto-creates missing bind sources (tiles/<variant>/current, elevation, backups, static,
photon) as root; both images run as 10001 → the first rebuild's mkdir, the symlink replace, the
dump and collectstatic all EACCES. Documented-order dependent.
**B-4. bot and renderer in the default profile** with no source/build/profiles → the documented
`docker compose up -d` cannot resolve two images; no doc says so or offers the remedy.
**B-5. On the shipped .env.example nobody can sign in:** CADDY_SITE_ADDRESS=:80 with DEBUG unset →
SESSION/CSRF cookies Secure (executed); DISCORD_REDIRECT_URI names port 8000 which nothing
publishes (test_compose forbids that default in compose while the env example ships it);
CSRF_TRUSTED_ORIGINS=https://localhost against http.

**SHOULD-FIX.** No healthchecks; migrate races initdb (restart "no", depends_on service_started).
No way to fire the first rebuild by hand (OPERATIONS refers to "a hand-fired rebuild" three times;
only the Tuesday tick). Reference data has no deployment procedure and a chicken-and-egg with the
extract (LOAD_REFERENCE_DATA after FETCH_EXTRACT; the installer wants the extract only a rebuild
produces). Photon unpinned (`latest`, PLAN:64 "all images pinned"), index population (PLAN:60)
unbuilt, nothing in src/ references Photon; not in §7. DEPLOYMENT.md states no host requirements
(check_compose_limits hardcodes 32 GB; PLAN:293 8 vCPU/32 GB/200 GB). `$DATA_ROOT` in snippets is
never exported (chown -R "" targets /). api.Dockerfile:133-135 stale "no STATIC_ROOT" comment.
DEPLOYMENT.md:204 cross-references the wrong blocker (api's missing DATA_ROOT never listed).
test_compose parses the literal YAML and settings source, never the rendered config or env values.

**NIT.** "Debian's osmium-tool" (image is noble). Caddy warns header_up X-Forwarded-Proto is
unnecessary. Serving configs name /data/valhalla/* paths no serving mount provides. `/` is 404 and
no doc names /auth/login. Header commit count accurate.
