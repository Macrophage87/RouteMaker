# Conflation of DC's Roadway Block and Baltimore's street centerline onto OSM ways

Match statistics on the source extract of 2026-09-25, from `scripts/analysis/data_before_after.py` (the rebuild's own conflation, `pipeline.conflation.road_facts_by_way`). A block is matched when it lies along a matched OSM way, by geometry (within 66 ft [20 m], heading agreeing locally) and street name; a way is matched when its blocks cover half of it. A block naming a different street vetoes every way but a freeway's (motorway and trunk and their links), and a service or track way needs an agreeing name.

## DC: Roadway Block (DDOT, CC BY 4.0)

**Agency side.** 13,833 blocks, 1,179.5 mi. 13,463 lie along a matched OSM way (97.3% of blocks); **24.4 mi in 370 blocks are unmatched** (2.1% of the miles): FOXHALL CRES NW (18), KEMBLE PL NW (12), FOLEY AVE SW (8), KEEL RD SW (6), CEDAR DR SE (6), 1ST ST NE (5), EASTERN AVE NE (5), WHARF ST SW (5), REDWOOD DR SE (5), VAN KUREN AVE SW (5), PERIMETER SOUTH RD SW (5), WESTOVER PL NW (4).

**OSM side.** 32,694 road ways (2,188 mi) in the area; 13,409 matched (1,233 mi, 56.3%). Public street classes only (residential through primary, trunk, links, motorway): 13,228 of 15,022 ways, 1,216 of 1,284 mi, **94.7%**. The rest is mostly `service` ways (parking aisles, driveways, alleys), which a street layer does not describe and which match only where a block's name agrees.

| OSM class | miles | matched | rate |
| --- | --- | --- | --- |
| service | 899.1 | 16.7 | 1.9% |
| residential | 647.9 | 627.8 | 96.9% |
| tertiary | 175.3 | 170.5 | 97.3% |
| primary | 156.0 | 150.5 | 96.5% |
| secondary | 130.2 | 126.8 | 97.3% |
| motorway | 46.1 | 44.4 | 96.3% |
| unclassified | 43.1 | 32.3 | 75.0% |
| motorway_link | 32.5 | 22.1 | 68.2% |
| trunk | 31.0 | 30.5 | 98.6% |
| primary_link | 13.7 | 6.7 | 49.0% |
| track | 3.4 | 0.0 | 0.0% |
| living_street | 2.4 | 1.4 | 60.2% |

Street names: of the matched ways, 12,593 agree with their block's name, 241 disagree (geometry only), 575 have no name to compare (93.9% agree).

Blocks per matched way: 1 10,302, 2-3 2,463, 4-10 631, more than 10 13. A way along several blocks takes the most stressful of their values (one tier is stored per way).

### Posted speed: agency against OSM `maxspeed` (matched ways)

|  | ways | miles | share |
| --- | --- | --- | --- |
| agency posts it, OSM unposted | 7,026 | 672.0 | 52.4% |
| same speed | 2,448 | 229.6 | 18.3% |
| agency has no speed | 2,350 | 198.2 | 17.5% |
| OSM differs | 1,585 | 132.9 | 11.8% |

Where OSM's posted speed and the agency's differ (the agency's is used, OWNER-DECISIONS 151), the most common pairs:

| OSM maxspeed | agency | miles |
| --- | --- | --- |
| 25 mph | 20 mph | 71.9 |
| 25 mph | 30 mph | 12.5 |
| 20 mph | 25 mph | 11.4 |
| 30 mph | 20 mph | 7.2 |
| 15 mph | 20 mph | 5.8 |
| 10 mph | 20 mph | 4.3 |
| 35 mph | 20 mph | 3.8 |
| 30 mph | 25 mph | 3.7 |

### Lanes per direction: agency against OSM

|  | ways | miles | share |
| --- | --- | --- | --- |
| same | 5,295 | 460.6 | 41.4% |
| agency has lanes, OSM none | 4,341 | 525.0 | 33.9% |
| agency more | 1,852 | 125.8 | 14.5% |
| agency fewer | 1,312 | 64.5 | 10.2% |

### One-way streets

DC's record takes priority over OSM's (OWNER-DECISIONS 190): a DC one-way is applied where OSM tags the way two-way in so many words, except on a reversible-lane block, a junction stub under 30 m [100 ft] or where the direction is not known; a DC two-way is applied over an OSM one-way except on a carriageway of a divided road or of a pair sharing the block, a slip road, a freeway or trunk road, a roundabout, a stub or an unnamed way. What is kept is counted as a disagreement (before-after.md has the table).

|  | ways | miles | share |
| --- | --- | --- | --- |
| agree two-way | 7,419 | 806.4 | 56.2% |
| agency two-way, OSM one-way | 2,949 | 172.2 | 22.3% |
| agree one-way | 2,656 | 225.4 | 20.1% |
| agency one-way, OSM not | 176 | 10.9 | 1.3% |

### Bike lane or track: agency against OSM

Where OSM maps the way's bike facility as a way of its own (`cycleway*=separate`, or a separately mapped facility beside it), on the way itself or on another way matched to one of its blocks (review r2), the agency's facility is that way and is never written onto the road: 763 matched ways (39.6 mi), counted as agreement. Nor is a protected lane written where OSM says `bicycle=no`, `use_sidepath` or `cycleway*=no`. A lane is a contraflow lane only where DC flags it (`BIKELANE_CONTRAFLOW`), and where DC records no facility on any block of a way, OSM's painted lane is removed (OWNER-DECISIONS 190).

|  | ways | miles | share |
| --- | --- | --- | --- |
| neither | 11,551 | 1,111.8 | 86.1% |
| agency only | 995 | 52.0 | 7.4% |
| both | 758 | 61.8 | 5.7% |
| OSM only | 105 | 7.0 | 0.8% |

### Parking: agency against OSM

|  | ways | miles | share |
| --- | --- | --- | --- |
| OSM silent | 12,328 | 1,136.8 | 91.9% |
| agree | 987 | 92.7 | 7.4% |
| disagree | 94 | 3.1 | 0.7% |

Tier effect: 1,798 of the 13,409 matched ways (190.9 of 1,232.6 mi) change tier.

## Baltimore: street centerline (Open Baltimore)

**Agency side.** 35,363 blocks, 1,712.7 mi. 33,356 lie along a matched OSM way (94.3% of blocks); **100.6 mi in 2,007 blocks are unmatched** (5.9% of the miles): STODDARD ALY (16), O'DONNELL ST CUT OFF (16), LELAND AVE (15), S CHAPELGATE LN (15), N BETHEL ST (14), W LEXINGTON ST (12), CAMDEN YARDS SPORTS COMPLEX 1 (12), S BOULDIN ST (12), ELLICOTT DWY (11), SMALL ST (11), LEMMON ST (11), E MCCOMAS ST (11).

**OSM side.** 37,283 road ways (2,950 mi) in the area; 15,023 matched (1,597 mi, 54.1%). Public street classes only (residential through primary, trunk, links, motorway): 14,206 of 16,274 ways, 1,522 of 1,625 mi, **93.6%**. The rest is mostly `service` ways (parking aisles, driveways, alleys), which a street layer does not describe and which match only where a block's name agrees.

| OSM class | miles | matched | rate |
| --- | --- | --- | --- |
| service | 1,299.5 | 74.1 | 5.7% |
| residential | 885.9 | 825.0 | 93.1% |
| primary | 240.6 | 230.2 | 95.7% |
| tertiary | 156.3 | 150.5 | 96.3% |
| secondary | 145.3 | 139.5 | 96.0% |
| motorway | 78.6 | 74.4 | 94.7% |
| unclassified | 59.2 | 45.5 | 76.8% |
| motorway_link | 46.7 | 45.5 | 97.3% |
| track | 22.5 | 0.3 | 1.5% |
| primary_link | 9.8 | 9.0 | 91.8% |
| secondary_link | 1.9 | 1.7 | 86.8% |
| services | 0.8 | 0.0 | 0.0% |

Street names: of the matched ways, 13,893 agree with their block's name, 333 disagree (geometry only), 797 have no name to compare (92.5% agree).

Blocks per matched way: 1 8,670, 2-3 4,387, 4-10 1,881, more than 10 85. A way along several blocks takes the most stressful of their values (one tier is stored per way).

### Posted speed: agency against OSM `maxspeed` (matched ways)

|  | ways | miles | share |
| --- | --- | --- | --- |
| same speed | 12,669 | 1,385.6 | 84.3% |
| agency posts it, OSM unposted | 1,235 | 117.2 | 8.2% |
| OSM differs | 1,035 | 90.1 | 6.9% |
| agency has no speed | 84 | 3.5 | 0.6% |

Where OSM's posted speed and the agency's differ (OSM's posted speed is kept and the city's fills only where OSM has none, OWNER-DECISIONS 184), the most common pairs:

| OSM maxspeed | agency | miles |
| --- | --- | --- |
| 25 mph | 30 mph | 24.0 |
| 30 mph | 25 mph | 16.5 |
| 55 mph | 50 mph | 8.0 |
| 25 mph | 15 mph | 4.9 |
| 30 mph | 35 mph | 4.4 |
| 30 mph | 40 mph | 4.0 |
| 15 mph | 25 mph | 3.7 |
| 50 mph | 40 mph | 3.1 |

### Lanes per direction: agency against OSM

Baltimore's `lane_count` is filled on only 5 of the 35,363 centerline blocks installed, so this table covers 3 ways and its shares say nothing about the city's streets at large.

|  | ways | miles | share |
| --- | --- | --- | --- |
| same | 2 | 0.6 | 66.7% |
| agency has lanes, OSM none | 1 | 0.0 | 33.3% |

### One-way streets

The centerline marks one-way streets only (`oneway` FT or TF) and says nothing of a two-way street (13,657 one-way blocks, 0 marked two-way), so the shares below are of the ways along a one-way record, not of all matched ways. Where OSM tags a way two-way in so many words (`oneway=no`, or lanes counted each way) the city's one-way is not applied and is counted as a disagreement.

|  | ways | miles | share |
| --- | --- | --- | --- |
| agree one-way | 6,884 | 673.8 | 94.8% |
| agency one-way, OSM not | 378 | 31.9 | 5.2% |

Tier effect: 491 of the 15,023 matched ways (40.6 of 1,596.5 mi) change tier.

## AADT

Roadway Block AADT (2020) is on 4,879 blocks. A matched way takes the busiest of its blocks' counts where no count layer reached it, and never on a slip road: 1,187 ways do. DDOT's own 2024 counts (the volume layer) are the newer survey and are never replaced. `segment.attr_sources` names the count the classifier read.
