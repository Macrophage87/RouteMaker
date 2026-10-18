# DC's circle parks

The circle-park rule (`src/routemaker/circleparks.py`; the owner, 2026-10-17:
"People still need to get into the circle. It's a common riding destination.",
"Same with logan circle"): the walkways inside these parks are open to bicycles,
and a trip point inside one is never matched to the road tunnel beneath it.

| File | What | Source | Licence |
| --- | --- | --- | --- |
| `circle-parks.geojson` | 16 polygons, the National Park Service parks named "... Circle": Chevy Chase, Dupont, Grant, Logan, Randle, Scott, Sheridan, Sherman, Tenley, Thomas, Ward, Washington and Westmoreland Circles (Tenley, Ward and Randle in several pieces) | DC GIS, National Parks (NPS Map A), as `scripts/build_federal_land.py` simplified it into `frontend/src/federal-data/federal-land.json` (sha256 `773f230f…ce4af`); the source layer's record is in `fixtures/datasets/README.md`, "Federal land" | CC BY 4.0, "DC GIS"; credited in routing's "DC Open Data (CC BY 4.0, adapted)" line |

Copied from the overlay with only the name kept: every `kind=nps` feature whose
name ends " Circle", except Fort Circle Park (the Civil War forts, not a traffic
circle). To refresh after the overlay is rebuilt, re-run the same selection.

Who runs them, for reference: Dupont, Logan and Sheridan Circles appear in
National Mall and Memorial Parks' compendium
(<https://home.nps.gov/nama/learn/management/superintendent-s-compendium.htm>);
Chevy Chase, Grant, Sherman and Tenley Circles in Rock Creek Park's
(<https://www.nps.gov/rocr/learn/management/rock-creek-park-superintendent-compendium.htm>).
The opening is the owner's decision as stated.
