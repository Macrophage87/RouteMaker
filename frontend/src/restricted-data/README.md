# Closed sites on the map

`restricted-sites.json`: the military areas and secured federal compounds whose roads the
rebuild closes to bicycles, plus closed areas drawn by hand (`fixtures/restricted-sites/`), with
each site's gates and the open ways inside it. Built by `scripts/build_restricted_sites.py` from
the project's OSM extract (on the PC: `python3 scripts/build_restricted_sites.py --pbf
<DATA_ROOT>/extracts/source.osm.pbf`). The map shades and names the sites
(`src/lib/restrictedSites.ts`); the API moves a trip point inside one to its nearest gate
(`src/routemaker/restricted_sites.py`), so the API image copies this file too.

| Source | Licence | Credit on the map |
| --- | --- | --- |
| OpenStreetMap, via the project's own extract; hand-drawn areas from OSM geometry, each with its `source` page | **ODbL 1.0** (a produced work of the extract) | the map's existing "© OpenStreetMap contributors (ODbL)" |
| U.S. Fish and Wildlife Service, Patuxent Research Refuge North Tract map, 2026-06: evidence for the Patuxent closed area's outline | Public domain (a U.S. federal government work) | none needed; credited in the About page's Acknowledgements |

Until the script is run, the file is an empty FeatureCollection: no shading, and routing is as
before.
