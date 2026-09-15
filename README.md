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

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e . pytest defusedxml ruff
.venv/bin/pytest -q
```

The reference-route tests are the quality bar rather than a smoke test: they
assert that measurements reproduce the recorded tables in
`fixtures/reference-routes/README.md`, which is what stops a tuning change from
quietly redefining what a mass ride is.

## Licence

MIT, across the repository. Route data derived from OpenStreetMap is a separate
matter, governed by ODbL; see the Licensing section of the plan.
