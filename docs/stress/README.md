# The traffic-stress model

These pages describe how RouteMaker rates roads for traffic stress, how the rating
is drawn and how it changes the routes it plans. They describe the code as it is on
`main`. They do not propose changes. Owner decision 461 (2026-10-09) was: "Let's keep
what we have currently for now. Just turn that into a number for stress. Let's make
a set of documentation for all of this." Anything not yet built is marked
**planned**.

Riders read a plain-language version of this, linked from the legend and the road
panel, at `/about/stress.html` (`frontend/public/about/stress.html`; `/about/stress`
redirects to it).

## Overview

Each OSM way in the region gets one traffic-stress tier: LTS 1 to 4 on Furth's
Level of Traffic Stress scale, or 5, "Avoid", for a road a bicycle may legally ride
that nobody should be sent onto. Tiers are set once per data rebuild. The classifier
(`src/routemaker/stress.py`) reads the way's OSM tags, agency street and traffic-count
data, and the owner's curated files (speed limits, bike lanes, named corridors). The
owner's approved override rows are applied after that. The tier goes into the segment
table and the map tiles. It also goes into the Valhalla graph as tags, which price
LTS 3 and above per meter and charge a fixed cost for entering Avoid. RouteMaker's own
ranking reads the live tier again at route time, through its calm search, guards and
junction model. Whether a bicycle may use a way at all is a separate question,
answered by the access rules. A closed way has no stress price because it is not
routable. The **stress number** (461) is the tier as a number. Each preset maps that
number to a cost multiplier, read from the weights above. The rolling stress chart
(built, PR #34) adds junction costs to it and draws calm miles per mile along the
route, under the elevation.

## The pages

| Page | What it covers |
|---|---|
| [classification.md](classification.md) | How a way gets its tier: inputs, rule order, AADT smoothing, curated files, closures (access) against stress |
| [overrides.md](overrides.md) | Stress and access override rows, `at_least` floors, `retire` lists, the loader, the owner's sign-off rule, re-matching by fingerprint |
| [routing-costs.md](routing-costs.md) | Valhalla's graph tags and request knobs, the slider, each preset's values, RouteMaker's ranking (calm search, LTS 4 hold, strict order, worth rule), the junction model |
| [stress-number.md](stress-number.md) | The numeric stress value, each preset's cost multiplier per level, half steps as midpoints (planned), and the rolling stress chart as built |
| [drawing.md](drawing.md) | Map colors, dashes and widths by level in each palette, zoom rules, half-step drawing (planned), the Mass Ride map |
| [intersections.md](intersections.md) | The junction cost model as built (which roads count, crossing, left, merge and slip costs, caps, orange and red), and the planned revision (467, 468, 468a) |
| [literature.md](literature.md) | The research consulted, what RouteMaker took from each source, and where and why it differs |
| [layers.md](layers.md) | The z12-13 ride layer (calm roads, long paths), Mass Ride capacity, and how stress feeds them |

Source reports this set was checked against (not in the repository):
GEOMETRIC-LTS-model.md (its inventory, re-verified here at `main`; its geometric
proposal is **parked**, see [stress-number.md](stress-number.md)), HALF-STEP-EDITOR-plan.md
(half steps and the editor, **planned**), and LTS-literature-review-2.md (sources).
Owner decisions are cited by number (OWNER-DECISIONS, kept outside the repository).

## Glossary

| Term | Meaning |
|---|---|
| **LTS** | Level of Traffic Stress, Furth's four-level scale (Mekuria, Furth & Nixon, MTI Report 11-19, 2012; Furth, LTS criteria v2.0 2017 and v2.2 2022). 1 is for nearly everyone, 4 only for the "strong and fearless". |
| **Tier** | The integer stored for a way: `segment.stress_tier`, 1-5 (`src/pipeline/schema.py:482`), and `Stress` in `src/routemaker/stress.py:117-128`. |
| **Avoid** | Tier 5. Not a Furth level. The road is legal for a bicycle and best avoided: an expressway posted 50 mph or more (`legal_but_avoid`, `stress.py:670-681`), an owner override, or a named corridor. It stays routable and pays an entry charge. |
| **Closed** | Bicycles may not use the way (OSM access, military and secured areas, singletrack and similar rules). This is access, not stress. When it is unclear whether bikes are allowed, the rules err closed, and the owner reopens a way with evidence through an access override. |
| **Stress number** | The tier as a number, 1-5, with half steps once they exist (461). See [stress-number.md](stress-number.md). |
| **Half step** | 1.5, 2.5, 3.5 or 4.5: a level between two whole tiers (441i-441l). **Planned**, built with the half-step editor. 461a: its cost and rule effects are the arithmetic midpoint of its two levels' values. 4.5 is never Avoid (441k). |
| **Cost multiplier** | How many meters of quiet street one meter at a level costs under a preset's weights, counting the tier's added cost only (461). See [stress-number.md](stress-number.md). |
| **Floor** | An override row with `"at_least": true`. It raises a way to the row's tier and never lowers it (`src/pipeline/overrides.py:113-118`, `:438-444`). Also the classifier's own arterial and collector floors (`stress.py:1080-1098`). |
| **Retire list** | The `retire` entries of an override file. They are rows a later decision withdraws, and the loader deletes them before it writes the file's rows. |
| **Preset** | A ride type (`src/core/presets.py:472-629`): Default, Trailmaxxing, Group Ride, Mass Ride, Mountain Goat, Gravel, Fast, Cargo Bike, E-bike. Each sets a graph variant, costing options and where the sliders start. |
| **Slider** | The traffic-stress slider, 0-100. Up to 80 it sets Valhalla's `use_roads`. From 80 to 100 it sets RouteMaker's calm rate, and at 100 it switches to the strict stress order (`presets.py:198-258`). |
| **`use_roads`** | Valhalla's bicycle costing option, 0-1. The only stress weight a request carries. |
| **Calm rate** | Meters of detour accepted per meter of LTS 3 avoided, above 80 on the slider (`calm_rate_for`, `presets.py:252-258`). |
| **Exposure** | A route's weighted busy meters: LTS 3 x1, LTS 4 x2, Avoid x3, or 1/8/16 on the stress-averse rides (`presets.py:332-348`). |
| **LTS 4 hold** | On Trailmaxxing and Cargo with passengers, a candidate route may not have more LTS 4 and Avoid meters, plus red-junction cost, than the router's first route (`src/core/refine.py:817-870`). |
| **Strict order** | At the top of the slider (100), candidates are ranked by LTS 4 + Avoid + red junctions first, then LTS 3 + orange junctions, then distance (`refine.py:338-356`). |
| **Worth rule** | At the top of the slider, a longer route must save at least 1 m of LTS 3-equivalent stress for every 5 m it adds. With a target distance set, the rate past the target is 1 m for every 2.5 m (`refine.py:405-508`). |
| **Junction cost** | The junction model's cost of a crossing or turn, in feet of quiet riding (`src/routemaker/intersections.py`). From 600 ft it is orange (higher stress) and from 2,000 ft red (very high stress). |
| **Calm run** | A continuous run of named LTS 1-2 road, broken at every junction with a road at LTS 3 or above. Runs of 2 mi [3.2 km] or more are drawn at z12-13 (`src/pipeline/calm_roads.py`). |
| **Ride layer** | What the stress map draws at z12-13: long paths, calm runs and roads closed to cars at set times, and no road at LTS 3 or above (`src/core/stress_tiles.py:35-42`). |
| **Rolling stress score** | Built (460.12, 461b-461e; `src/routemaker/calm.py`). Calm miles per actual mile over the mile around each point of a route, junction costs and Avoid entries included, on the same scale as the cost multiplier (1 is a quiet street). Drawn under the elevation on every ride type but Mass Ride. Each stretch is priced by its tier for now, so it is labeled an estimate; pricing each segment by its own routing cost is **planned**. See [stress-number.md](stress-number.md), section 4. |

## Data sources credited

The model reads OpenStreetMap (© OpenStreetMap contributors, ODbL); DC Open Data
(DDOT 2024 Traffic Volume, DC Roadway Block; CC BY 4.0, adapted); VDOT traffic
volume (Virginia Roads); Montgomery County Planning Department (Bicycle Level of
Traffic Stress, its LTS 5 used as Avoid); Open Baltimore (City of Baltimore, bike
facilities); and the U.S. Census Bureau (TIGER/Line Shapefiles (2024), 2020 Urban
Areas, for default speeds). The Mass Ride map's riders a minute are the RouteMaker Mass Ride model, from
OpenStreetMap, DC Roadway Block and DC Bike Party counts. docs/SOURCES.md holds each
source's full record and credit line.
The method follows Furth's published tables, written from the tables and not copied
from another classifier (`stress.py:1-13`). The junction costs come from the
literature review's derived values (Broach, Dill & Gliebe's Portland route-choice
model; Eugene; the Oregon and Mineta crossing tables), as cited at
`intersections.py:51-177`.
