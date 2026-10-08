# Lane overrides

Corrections to DC Roadway Block lane counts, applied to the blocks when the rebuild loads the
layer, before conflation (`src/routemaker/lane_overrides.py`). A broken file stops the rebuild
(`LaneOverrideRefused`, terminal). Each entry cites the owner's decision that is its source.

| File | Decision |
| --- | --- |
| `2026-10-05-owner-connecticut-lanes.json` | Connecticut Avenue NW from Calvert St NW to Chevy Chase Circle (decisions 412, 419): three travel lanes each way for the classifier and crossings, in place of the layer's out-of-date 1 + 1 and 2 reversible; for the Mass Ride width the curb lane is part-time parking, so two lanes on the ride's own side (18 ft, 162 riders a minute). Double and triple parking is a known hazard, not modelled. Blocks south of Calvert St, including R St to Calvert St and the Dupont underpass, are untouched. |

The owner is the source (docs/SOURCES.md, DC Roadway Block). Maryland's Connecticut Ave (MD 185)
needs no override: OSM already maps it with three lanes each way (419).
