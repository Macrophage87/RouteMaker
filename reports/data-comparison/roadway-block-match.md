# Conflation of DC's Roadway Block and Baltimore's street centerline onto OSM ways

Match statistics on the source extract of 2026-09-25, from `scripts/analysis/data_before_after.py` (the rebuild's own conflation, `pipeline.conflation.conflate_blocks`). A block is matched when it lies along a matched OSM way, by geometry (within 20 m, heading agreeing locally) and street name; a way is matched when its blocks cover half of it.

## DC: Roadway Block (DDOT, CC BY 4.0)

**Agency side.** 13,833 blocks, 1,179.5 mi. 13,473 lie along a matched OSM way (97.4% of blocks); **23.7 mi in 360 blocks are unmatched** (2.0% of the miles): FOXHALL CRES NW (18), KEMBLE PL NW (12), FOLEY AVE SW (8), KEEL RD SW (6), CEDAR DR SE (6), 1ST ST NE (5), EASTERN AVE NE (5), WHARF ST SW (5), REDWOOD DR SE (5), VAN KUREN AVE SW (5), WESTOVER PL NW (4), SMITH ST SW (4).

**OSM side.** 32,694 road ways (2,188 mi) in the area; 13,502 matched (1,238 mi, 56.6%). Public street classes only (residential through primary, trunk, links, motorway): 13,335 of 15,022 ways, 1,221 of 1,284 mi, **95.0%**. The rest is mostly `service` ways (parking aisles, driveways, alleys), which a street layer does not describe and which match only where a block's name agrees.

| OSM class | miles | matched | rate |
| --- | --- | --- | --- |
| service | 899.1 | 17.1 | 1.9% |
| residential | 647.9 | 627.6 | 96.9% |
| tertiary | 175.3 | 170.6 | 97.3% |
| primary | 156.0 | 153.2 | 98.2% |
| secondary | 130.2 | 128.0 | 98.3% |
| motorway | 46.1 | 45.0 | 97.6% |
| unclassified | 43.1 | 32.4 | 75.1% |
| motorway_link | 32.5 | 22.1 | 68.2% |
| trunk | 31.0 | 30.6 | 98.8% |
| primary_link | 13.7 | 6.7 | 49.0% |
| track | 3.4 | 0.0 | 0.0% |
| living_street | 2.4 | 1.4 | 60.2% |

Street names: of the matched ways, 12,299 agree with their block's name, 300 disagree (geometry only), 903 have no name to compare (91.1% agree).

Blocks per matched way: 1 10,335, 2-3 2,522, 4-10 632, more than 10 13. A way along several blocks takes the most stressful of their values (one tier is stored per way).

### Posted speed: agency against OSM `maxspeed` (matched ways)

|  | ways | miles | share |
| --- | --- | --- | --- |
| agency posts it, OSM unposted | 7,081 | 673.9 | 52.4% |
| same speed | 2,458 | 229.9 | 18.2% |
| agency has no speed | 2,359 | 200.1 | 17.5% |
| OSM differs | 1,604 | 133.7 | 11.9% |

Where OSM's posted speed and the agency's differ (the agency's is used), the most common pairs:

| OSM maxspeed | agency | miles |
| --- | --- | --- |
| 25 mph | 20 mph | 72.6 |
| 25 mph | 30 mph | 12.7 |
| 20 mph | 25 mph | 11.4 |
| 30 mph | 20 mph | 7.3 |
| 15 mph | 20 mph | 5.3 |
| 10 mph | 20 mph | 4.3 |
| 35 mph | 20 mph | 3.8 |
| 30 mph | 25 mph | 3.7 |

### Lanes per direction: agency against OSM

|  | ways | miles | share |
| --- | --- | --- | --- |
| same | 5,345 | 462.5 | 41.4% |
| agency has lanes, OSM none | 4,339 | 526.0 | 33.6% |
| agency more | 1,903 | 128.6 | 14.8% |
| agency fewer | 1,311 | 64.2 | 10.2% |

### One-way streets

|  | ways | miles | share |
| --- | --- | --- | --- |
| agree two-way | 7,427 | 808.1 | 55.9% |
| agency two-way, OSM one-way | 2,991 | 174.5 | 22.5% |
| agree one-way | 2,703 | 226.9 | 20.3% |
| agency one-way, OSM not | 177 | 10.9 | 1.3% |

### Bike lane or track: agency against OSM

|  | ways | miles | share |
| --- | --- | --- | --- |
| neither | 11,633 | 1,116.3 | 86.2% |
| agency only | 1,000 | 52.2 | 7.4% |
| both | 761 | 61.9 | 5.6% |
| OSM only | 108 | 7.2 | 0.8% |

### Parking: agency against OSM

|  | ways | miles | share |
| --- | --- | --- | --- |
| OSM silent | 12,416 | 1,141.6 | 92.0% |
| agree | 992 | 92.9 | 7.3% |
| disagree | 94 | 3.1 | 0.7% |

Tier effect: 2,333 of the 13,502 matched ways (217.9 of 1,237.6 mi) change tier.

## Baltimore: street centerline (Open Baltimore)

**Agency side.** 35,363 blocks, 1,712.7 mi. 33,359 lie along a matched OSM way (94.3% of blocks); **100.8 mi in 2,004 blocks are unmatched** (5.9% of the miles): STODDARD ALY (16), LELAND AVE (15), S CHAPELGATE LN (15), N BETHEL ST (14), W LEXINGTON ST (12), CAMDEN YARDS SPORTS COMPLEX 1 (12), S BOULDIN ST (12), ELLICOTT DWY (11), SMALL ST (11), LEMMON ST (11), E MCCOMAS ST (11), FAIT AVE (10).

**OSM side.** 37,283 road ways (2,950 mi) in the area; 15,049 matched (1,598 mi, 54.2%). Public street classes only (residential through primary, trunk, links, motorway): 14,236 of 16,274 ways, 1,524 of 1,625 mi, **93.8%**. The rest is mostly `service` ways (parking aisles, driveways, alleys), which a street layer does not describe and which match only where a block's name agrees.

| OSM class | miles | matched | rate |
| --- | --- | --- | --- |
| service | 1,299.5 | 73.2 | 5.6% |
| residential | 885.9 | 824.1 | 93.0% |
| primary | 240.6 | 231.1 | 96.1% |
| tertiary | 156.3 | 150.5 | 96.3% |
| secondary | 145.3 | 140.5 | 96.7% |
| motorway | 78.6 | 75.3 | 95.8% |
| unclassified | 59.2 | 45.5 | 76.8% |
| motorway_link | 46.7 | 45.5 | 97.4% |
| track | 22.5 | 0.3 | 1.5% |
| primary_link | 9.8 | 9.0 | 91.8% |
| secondary_link | 1.9 | 1.7 | 86.8% |
| services | 0.8 | 0.0 | 0.0% |

Street names: of the matched ways, 13,677 agree with their block's name, 386 disagree (geometry only), 986 have no name to compare (90.9% agree).

Blocks per matched way: 1 8,682, 2-3 4,399, 4-10 1,883, more than 10 85. A way along several blocks takes the most stressful of their values (one tier is stored per way).

### Posted speed: agency against OSM `maxspeed` (matched ways)

|  | ways | miles | share |
| --- | --- | --- | --- |
| same speed | 12,692 | 1,387.9 | 84.3% |
| agency posts it, OSM unposted | 1,231 | 116.4 | 8.2% |
| OSM differs | 1,042 | 89.8 | 6.9% |
| agency has no speed | 84 | 3.5 | 0.6% |

Where OSM's posted speed and the agency's differ (the agency's is used), the most common pairs:

| OSM maxspeed | agency | miles |
| --- | --- | --- |
| 25 mph | 30 mph | 24.3 |
| 30 mph | 25 mph | 16.6 |
| 55 mph | 50 mph | 7.5 |
| 25 mph | 15 mph | 4.6 |
| 30 mph | 35 mph | 4.5 |
| 30 mph | 40 mph | 4.0 |
| 15 mph | 25 mph | 3.7 |
| 50 mph | 40 mph | 3.1 |

### Lanes per direction: agency against OSM

|  | ways | miles | share |
| --- | --- | --- | --- |
| same | 2 | 0.6 | 66.7% |
| agency has lanes, OSM none | 1 | 0.0 | 33.3% |

### One-way streets

|  | ways | miles | share |
| --- | --- | --- | --- |
| agree one-way | 6,910 | 676.2 | 94.8% |
| agency one-way, OSM not | 377 | 31.9 | 5.2% |

Tier effect: 963 of the 15,049 matched ways (84.1 of 1,597.6 mi) change tier.

## AADT

Roadway Block AADT (2020) is on 4,879 blocks. A matched way takes the busiest of its blocks' counts where no count layer reached it: 1,373 ways do. DDOT's own 2024 counts (the volume layer) are the newer survey and are never replaced.
