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

Routing needs data that the first rebuild makes (hours, and three reference
files you supply): until then the map loads but routes do not. The script says
so and prints the next step, `docs/PLAYBOOK.md` section 7. Once a build is
promoted, the same command starts the routers too, through
`scripts/boot/start-stack.sh`, which also checks that place search answers, so
import a Photon index first (`docs/DEPLOYMENT.md`, "Photon"). After pulling new
code, run `scripts/local-up.sh -- --force-recreate-all` to put the new images
into service (it stops a rebuild that is running).

It needs the internet on a first run: Docker Hub, ghcr.io, pypi.org,
deb.debian.org, registry.npmjs.org and build.protomaps.com, plus
download.geofabrik.de for the rebuild. Claude's cloud sessions block several of
these, so this runs on a real computer, not in one of them. On Windows, run it
inside WSL2 (`handoff-local.md` section 3).

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
