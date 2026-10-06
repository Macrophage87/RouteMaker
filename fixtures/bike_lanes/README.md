# Curated bike lanes

A painted bike lane the map is missing, read by the rebuild at classify time
(`routemaker.bike_lanes`, CLASSIFY_STRESS, beside the curated speeds of
`fixtures/speed/`); nothing here is loaded into the database. A row adds
`cycleway:<side>=lane` to the tags the classifier and the facility class read, never
to the graph's tags, and only while the way carries no `cycleway` key of its own: the
owner's OSM edit, once it is in the extract, wins, and the row is warned about as
unused.

A file is `{"version": 1, "rows": [...]}`; a row is `osm_way_id`, `side` (`right`,
the kerb side of a one-way carriageway; `left`; or `both`), and the owner's `reason`
and the map `evidence`, both required.

| File | Decision |
|---|---|
| `2026-10-05-owner-veirs-mill-lanes.json` | Veirs Mill Road (MD 586), Twinbrook Parkway east to about 77.088 W, both carriageways, 23 ways (decision 433: "Yes, it should be marked", "It's not an avoid"). The Montgomery Planning LTS 5 rows on the same ways are retired (`fixtures/overrides/2026-10-01-owner-moco-lts5-avoid.json`, `retire`). The owner maps the lane upstream (`cycleway:right=lane`, its width, `maxspeed`). |
