# RouteMaker

Collaborative bicycle route planning for the Washington, DC metro area.

Two gaps in existing tools shape it: planning a ride *with other people*, and
planning for *differing cycling modalities* — a mass ride that takes the roadway
at parade pace has almost nothing in common with a rural gravel loop, yet most
tools offer one router and one set of assumptions.

**[PLAN.md](PLAN.md) is the build specification.** It is the authority on scope,
architecture, and every decision taken so far, including the ones that were
reconsidered and why.

## Status

Early. Phase 1 of 6; no application yet. What exists:

- `src/routemaker/geo.py` — spherical geometry, dependency-free
- `src/routemaker/measure.py` — the normative route measurements
- `src/routemaker/gpx.py` — GPX reading for the import path
- `fixtures/reference-routes/` — fifteen real routes with their measured
  properties, supplied by the project owner and used as ground truth

## Running it on this computer

With Docker running (Docker Desktop, or Docker Engine with the compose plugin),
from the checkout:

```sh
scripts/local-up.sh
```

That is the whole of it, the first time and every time after; the site is at
<http://localhost>. The first run writes a local `.env` with fresh secrets (an
existing one is never touched), prepares the data directory (`~/rmdata`, or
`--data-root DIR`), fetches the base map, builds the front end and the images,
and starts the stack. Later runs skip whatever is already done. `--help` lists
the options; `--dry-run` shows what a run would do.

It refuses to touch a stack that was started from another checkout or worktree
(run it from that one), and a `.env` for any stack but the local `routemaker`
one, such as the beta's. When the code under `frontend/` has changed, a run
republishes the front end straight away, so the running site serves it at
once. The map works signed out; signing in needs a Discord application, as the
note at the end of the generated `.env` explains.

Routing needs data that the first rebuild makes (hours, and three reference
files you supply). Until then the map loads but routes do not, and the script
prints the next step:
[PLAYBOOK section 7, "The first rebuild"](docs/PLAYBOOK.md#7-the-first-rebuild--a4).
Once a build is promoted, the same command starts the routers too.

It needs the internet on a first run: Docker Hub, ghcr.io, pypi.org,
deb.debian.org, registry.npmjs.org, build.protomaps.com and github.com, plus
download.geofabrik.de for the rebuild. Claude's cloud sessions block several of
these, so this runs on a real computer, not in one of them. On Windows, run it
inside WSL2 ([handoff-local.md section 3](handoff-local.md#3-setting-up-on-windows)).

## Development

The suite needs PostgreSQL 16 with PostGIS, LuaJIT and a Python 3.11 venv
carrying the images' exact pins; docs/DEVELOPMENT.md, "The native loop", has
the commands. In short, once those are installed:

```sh
uv venv --python 3.11 .venv
uv pip install -r docker/requirements.txt -r requirements-dev.txt
sudo sh scripts/devdb.sh
PGDATABASE=routemaker_dev .venv/bin/python -m pytest tests/ -q -p no:randomly
```

The reference-route tests are the quality bar rather than a smoke test: they
assert that measurements reproduce the recorded tables in
`fixtures/reference-routes/README.md`, which is what stops a tuning change from
quietly redefining what a mass ride is.

## Licence

MIT, across the repository. Route data derived from OpenStreetMap is a separate
matter, governed by ODbL; see the Licensing section of the plan.
