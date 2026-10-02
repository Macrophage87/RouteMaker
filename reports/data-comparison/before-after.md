# Before and after: DC Roadway Block and Baltimore street centerline conflated

Before: this branch's classifier on the 2026-09-25 extract without the agency layers, as the earlier calibration tables were made (classification only: the loaded stress and access rows, and the 2026-10-01 MoCo and Baltimore override files, are overrides applied at the rebuild and are in neither column). After: the same classifier with the agency layers conflated (`pipeline.conflation.road_facts_by_way`, `agency_roads.overlay`) and the Roadway Block's AADT filling where no count layer reached the way. Since review r1 the overlay never writes a bike facility OSM maps as its own way onto the road, gives each carriageway its own direction's lanes and bike lane, keeps a slip road's own lanes, does not make a way OSM tags two-way one-way, and takes Baltimore's speed only where OSM has none (OWNER-DECISIONS 184); a painted lane's reach beside parking is the lane plus the parking lane only where DC records the lane beside parking, against Furth's 15 ft [4.6 m]. Only DC's and Baltimore's ways can change; every other way is the baseline's. Road ways only (proposed, construction, platform and corridor ways and trail-class ways are not classified here). Miles.

The two runs agree on the baseline tier of all but 7 of the 82,357 DC and Baltimore ways (the baseline did not know a separately mapped bike facility the way the rebuild's own pairing does).

## Region-wide

| area | total mi | LTS 1 before -> after | LTS 2 before -> after | LTS 3 before -> after | LTS 4 before -> after | LTS 5 before -> after |
| --- | --- | --- | --- | --- | --- | --- |
| Region | 98,411 | 47,377.2 (48.1%) -> 47,297.9 (48.1%), -79.2 | 27,003.5 (27.4%) -> 27,061.4 (27.5%), +57.8 | 5,775.1 ( 5.9%) -> 5,775.1 ( 5.9%), -0.0 | 16,724.4 (17.0%) -> 16,745.8 (17.0%), +21.4 | 1,530.8 ( 1.6%) -> 1,530.8 ( 1.6%), +0.0 |
| DC | 2,189 | 1,560.5 (71.3%) -> 1,511.8 (69.1%), -48.7 | 222.9 (10.2%) -> 244.5 (11.2%), +21.6 | 266.9 (12.2%) -> 270.5 (12.4%), +3.6 | 138.3 ( 6.3%) -> 161.7 ( 7.4%), +23.4 | 0.0 ( 0.0%) -> 0.0 ( 0.0%), +0.0 |
| MD | 62,196 | 28,241.1 (45.4%) -> 28,210.5 (45.4%), -30.6 | 19,858.4 (31.9%) -> 19,894.6 (32.0%), +36.2 | 3,566.7 ( 5.7%) -> 3,563.1 ( 5.7%), -3.6 | 10,159.7 (16.3%) -> 10,157.7 (16.3%), -2.0 | 370.4 ( 0.6%) -> 370.4 ( 0.6%), +0.0 |
| VA | 33,765 | 17,500.6 (51.8%) -> 17,500.6 (51.8%), +0.0 | 6,836.1 (20.2%) -> 6,836.1 (20.2%), +0.0 | 1,938.9 ( 5.7%) -> 1,938.9 ( 5.7%), +0.0 | 6,329.3 (18.7%) -> 6,329.3 (18.7%), +0.0 | 1,160.0 ( 3.4%) -> 1,160.0 ( 3.4%), +0.0 |
| no state | 261 | 75.0 (28.7%) -> 75.0 (28.7%), +0.0 | 86.2 (33.0%) -> 86.2 (33.0%), +0.0 | 2.6 ( 1.0%) -> 2.6 ( 1.0%), +0.0 | 97.1 (37.2%) -> 97.1 (37.2%), +0.0 | 0.4 ( 0.1%) -> 0.4 ( 0.1%), +0.0 |
| DC ways a Roadway Block was matched to | 1,232 | 651.9 (52.9%) -> 603.2 (48.9%), -48.7 | 206.6 (16.8%) -> 228.3 (18.5%), +21.6 | 249.3 (20.2%) -> 253.0 (20.5%), +3.6 | 124.4 (10.1%) -> 147.9 (12.0%), +23.4 | 0.0 ( 0.0%) -> 0.0 ( 0.0%), +0.0 |
| Baltimore City (within about 500 ft [150 m] of its centerline) | 2,950 | 1,342.3 (45.5%) -> 1,311.7 (44.5%), -30.6 | 1,029.4 (34.9%) -> 1,065.6 (36.1%), +36.2 | 357.6 (12.1%) -> 353.9 (12.0%), -3.6 | 220.3 ( 7.5%) -> 218.3 ( 7.4%), -2.0 | 0.1 ( 0.0%) -> 0.1 ( 0.0%), +0.0 |

## What moved, by what the layer changed

Ways whose tier changed, by the inputs the layer changed on them (from the tags the classifier read before and after).

| area | the layer changed | ways | miles | higher stress | lower stress |
| --- | --- | --- | --- | --- | --- |
| dc | speed + parking | 675 | 85.3 | 52.9 | 32.4 |
| baltimore | speed | 449 | 37.0 | 28.8 | 8.2 |
| dc | speed + parking + count | 125 | 25.1 | 24.5 | 0.6 |
| dc | speed + lanes + parking | 367 | 22.8 | 15.8 | 7.0 |
| dc | parking + count | 94 | 17.3 | 16.8 | 0.5 |
| dc | speed + lanes + parking + count | 47 | 7.6 | 6.7 | 0.8 |
| dc | lanes + parking | 84 | 7.4 | 4.9 | 2.5 |
| dc | lanes + parking + count | 42 | 5.9 | 5.8 | 0.0 |
| dc | speed + bike facility | 54 | 4.8 | 1.5 | 3.3 |
| baltimore | speed + one-way | 39 | 3.3 | 2.6 | 0.8 |
| dc | speed + bike facility + parking | 85 | 2.8 | 0.6 | 2.2 |
| dc | bike facility + count | 6 | 1.8 | 1.8 | 0.0 |
| dc | bike facility + parking | 41 | 1.5 | 0.4 | 1.1 |
| dc | bike facility | 16 | 1.3 | 0.4 | 0.9 |
| dc | speed + lanes + bike facility + parking | 34 | 1.2 | 0.4 | 0.8 |
| dc | speed + lanes | 20 | 1.1 | 0.7 | 0.4 |
| dc | speed + bike facility + count | 5 | 1.0 | 1.0 | 0.0 |
| dc | speed + bike-lane width | 14 | 0.8 | 0.8 | 0.0 |
| dc | speed + lanes + bike facility | 12 | 0.7 | 0.6 | 0.1 |
| dc | lanes + bike facility + parking | 22 | 0.6 | 0.0 | 0.6 |
| dc | speed | 19 | 0.6 | 0.6 | 0.0 |
| dc | speed + count | 4 | 0.5 | 0.5 | 0.0 |
| dc | speed + bike-lane width + count | 2 | 0.5 | 0.4 | 0.1 |
| dc | speed + lanes + bike-lane width | 14 | 0.5 | 0.4 | 0.1 |

## The parking reach on its own (`classify(parking_width_m=)`)

The one change outside the data plumbing: where DC records a painted lane beside a parking lane (`BIKELANE_PARKINGLANE_ADJACENT`), the parking lane's width is added to the lane's for Furth's reach, adequate at 15 ft [4.6 m] (MTI 11-19, Table 2). It applies on 795 ways and changes the tier of 17 of them (0.6 mi), against the same "after" with the lane measured on its own. Every other change in this report is the layer's data. The criterion itself moved from 13.5 ft to Furth's 15 ft in the same change; no way in the extract carries a lane or shoulder width between the two [4.1 to 4.57 m], so no OSM-only way outside DC and Baltimore moves and the region baseline stands.

| without the reach | with it | miles |
| --- | --- | --- |
| LTS 2 | LTS 1 | 0.6 |

### DC: miles by tier movement

| from | to | miles |
| --- | --- | --- |
| LTS 1 | LTS 2 | 68.3 |
| LTS 2 | LTS 1 | 34.8 |
| LTS 3 | LTS 4 | 29.5 |
| LTS 1 | LTS 3 | 20.8 |
| LTS 2 | LTS 3 | 19.4 |
| LTS 3 | LTS 2 | 8.6 |
| LTS 4 | LTS 3 | 6.4 |
| LTS 3 | LTS 1 | 4.9 |
| LTS 2 | LTS 4 | 1.3 |
| LTS 4 | LTS 1 | 0.7 |
| LTS 4 | LTS 2 | 0.3 |
| LTS 1 | LTS 4 | 0.1 |

### Baltimore City: miles by tier movement

| from | to | miles |
| --- | --- | --- |
| LTS 1 | LTS 2 | 31.0 |
| LTS 3 | LTS 2 | 5.9 |
| LTS 4 | LTS 3 | 2.2 |
| LTS 2 | LTS 1 | 0.7 |
| LTS 1 | LTS 3 | 0.4 |
| LTS 3 | LTS 4 | 0.2 |
| LTS 3 | LTS 1 | 0.2 |

## The owner's example roads (DC)

16th Street NW and Connecticut Avenue NW stay at LTS 4 where the Roadway Block's lanes and counts put them there (OWNER-DECISIONS 179, "Keep LTS 4 (Recommended)"). Two readings behind that, recorded for the owner: DC's lane totals include bus lanes (`BUSLANE_*` on 16th Street), which are counted as travel lanes, the conservative reading; and Connecticut Avenue's reversible lanes are assumed to be operating, so they count as lanes in the peak direction (1 + 1 + 2 reversible is 3 a direction).

### 4th Street Northeast: 2.90 mi, 37 ways

before LTS 1 0.33, LTS 2 2.25, LTS 3 0.33 | after LTS 1 0.57, LTS 2 2.16, LTS 3 0.17

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.77 | 16 | LTS 2 (same) | bike lane, narrow at 25 mph or below | bike lane, narrow at 25 mph or below | `{"cycleway:left": "no", "cycleway:right": "lane", "cycleway:right:buffer": "no", "cycleway:right:oneway": "yes", "lanes": "1", "oneway": "yes", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"cycleway:right": "lane", "cycleway:right:width": "1.52", "lanes": "1", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 4054, "bike": {"ib": 1}, "bike_back": 0, "bike_ft": 5.0, "bike_fwd": 1, "lanes": {"ib": 1, "ob": 0}, "lanes_back": 1, "lanes_fwd": 1, "one_way": true, "parking": 2, "speed": {}}` |
| 0.30 | 3 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"maxspeed": "25 mph"}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "25 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": false, "parking": 2, "speed": {"ob": 25}}` |
| 0.29 | 4 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.28 | 4 | LTS 3 -> 1 | mixed traffic, 20 mph or below, urban multilane, two-way floor | separated track alongside | `{"cycleway:left": "track", "cycleway:left:oneway": "no", "lanes": "3", "lanes:backward": "2", "oneway:bicycle": "no"}` | `{"cycleway:both": "track", "lanes:backward": "2", "lanes:forward": "2", "maxspeed": "25 mph", "oneway:bicycle": "no", "parking:left": "no", "parking:right": "parallel"}` | `{"aadt": 10730, "bike": {"ib": 3, "ob": 3}, "bike_back": 3, "bike_ft": 4.5, "bike_fwd": 3, "lanes": {"ib": 2, "ob": 2}, "lanes_back": 2, "lanes_fwd": 2, "one_way": false, "parking": 1, "speed": {"ob": 25}}` |
| 0.06 | 1 | LTS 2 -> 3 | mixed traffic, 25 mph, single lane | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"cycleway:right": "separate", "lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"cycleway:right": "separate", "lanes:backward": "1", "lanes:forward": "2", "maxspeed": "20 mph", "oneway": "no", "parking:left": "no", "parking:right": "parallel"}` | `{"aadt": null, "bike": {"ib": 1}, "bike_back": 0, "bike_ft": 16.0, "bike_fwd": 1, "lanes": {"ib": 2, "ob": 1}, "lanes_back": 1, "lanes_fwd": 2, "one_way": false, "parking": 1, "speed": {"ob": 20}}` |
| 0.05 | 1 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "4", "lanes:backward": "2", "lanes:forward": "2"}` | `{"lanes:backward": "2", "lanes:forward": "1", "maxspeed": "25 mph", "parking:both": "no"}` | `{"aadt": 10730, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 2}, "lanes_back": 2, "lanes_fwd": 1, "one_way": false, "parking": 0, "speed": {"ob": 25}}` |

### 6th Street Northeast: 2.06 mi, 28 ways

before LTS 1 0.65, LTS 2 1.38, LTS 3 0.03 | after LTS 1 0.53, LTS 2 1.03, LTS 3 0.23, LTS 4 0.27

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.58 | 5 | LTS 2 (same) | bike lane, narrow at 25 mph or below | mixed traffic, 25 mph, single lane | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "cycleway:right:oneway": "yes", "lanes": "1", "oneway": "yes", "parking:both": "yes", "parking:both:orientation": "parallel"}` | `{"cycleway:left": "opposite_lane", "lanes": "1", "maxspeed": "25 mph", "oneway": "yes", "oneway:bicycle": "no", "parking:both": "parallel"}` | `{"aadt": 2965, "bike": {"ib": 1}, "bike_back": 1, "bike_ft": 5.0, "bike_fwd": 0, "lanes": {"ib": 0, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": true, "parking": 2, "speed": {"ob": 25}}` |
| 0.53 | 8 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.25 | 3 | LTS 2 (same) | mixed traffic, 20 mph or below, urban multilane, mid volume | mixed traffic, 25 mph, single lane | `{"cycleway": "separate", "lanes": "2", "oneway": "yes"}` | `{"cycleway": "separate", "lanes": "1", "maxspeed": "25 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 6523, "bike": {"ib": 2, "ob": 2}, "bike_back": 2, "bike_ft": 4.0, "bike_fwd": 2, "lanes": {"ib": 0, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": true, "parking": 2, "speed": {"ob": 25}}` |
| 0.24 | 1 | LTS 2 -> 4 | mixed traffic, 20 mph or below, single lane, high volume | mixed traffic, 30 mph, urban multilane, two-way busy | `{"cycleway": "separate", "lanes": "2"}` | `{"cycleway": "separate", "lanes:backward": "3", "lanes:forward": "1", "maxspeed": "30 mph", "parking:both": "parallel"}` | `{"aadt": 9867, "bike": {"ib": 2, "ob": 2}, "bike_back": 2, "bike_ft": 4.0, "bike_fwd": 2, "lanes": {"ib": 3, "ob": 1}, "lanes_back": 3, "lanes_fwd": 1, "one_way": false, "parking": 3, "speed": {"ob": 30}}` |
| 0.23 | 2 | LTS 2 -> 3 | bike lane, narrow at 25 mph or below | mixed traffic, 20 mph or below, single lane, mid volume, arterial floor | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "cycleway:right:oneway": "yes", "lanes": "1", "oneway": "yes", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"cycleway:left": "opposite_lane", "lanes": "1", "maxspeed": "20 mph", "oneway": "yes", "oneway:bicycle": "no", "parking:both": "parallel"}` | `{"aadt": 3014, "bike": {"ib": 1}, "bike_back": 1, "bike_ft": 5.0, "bike_fwd": 0, "lanes": {"ib": 0, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": true, "parking": 2, "speed": {"ob": 20}}` |
| 0.12 | 2 | LTS 1 -> 2 | mixed traffic, 20 mph or below, single lane | mixed traffic, 25 mph, single lane | `{}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "25 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": false, "parking": 2, "speed": {"ob": 25}}` |

### 22nd Street Northwest: 1.43 mi, 26 ways

before LTS 1 0.25, LTS 2 0.28, LTS 3 0.89 | after LTS 1 0.13, LTS 2 0.41, LTS 3 0.89

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.46 | 5 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, wide one-way floor | mixed traffic, 20 mph or below, single lane, mid volume, arterial floor | `{"lanes": "3", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 5630, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 0, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": true, "parking": 3, "speed": {"ob": 20}}` |
| 0.25 | 1 | LTS 1 -> 2 | mixed traffic, 20 mph or below, urban multilane | mixed traffic, 20 mph or below, single lane, mid volume | `{"lanes": "2", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 2742, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 0, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": true, "parking": 2, "speed": {"ob": 20}}` |
| 0.14 | 4 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, single lane, mid volume, arterial floor | `{"lanes": "3", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 6764, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 0, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": true, "parking": 3, "speed": {"ob": 20}}` |
| 0.12 | 2 | LTS 2 (same) | mixed traffic, 20 mph or below, single lane, mid volume | mixed traffic, 20 mph or below, single lane, mid volume | `{"lanes": "1", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 2742, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 0, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": true, "parking": 2, "speed": {"ob": 20}}` |
| 0.11 | 1 | LTS 2 -> 3 | mixed traffic, 25 mph, single lane | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"maxspeed": "25 mph"}` | `{"lanes:backward": "2", "lanes:forward": "2", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 2}, "lanes_back": 2, "lanes_fwd": 2, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.11 | 3 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "3", "oneway": "yes"}` | `{"lanes": "3", "oneway": "yes"}` | `not matched` |

### Connecticut Avenue Northwest: 6.18 mi, 96 ways

before LTS 2 0.04, LTS 3 6.14 | after LTS 2 0.12, LTS 3 2.82, LTS 4 3.24

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3.24 | 32 | LTS 3 -> 4 | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 30 mph, urban multilane, two-way busy | `{"cycleway:both": "no", "lanes": "6", "maxspeed": "25 mph", "parking:both": "no"}` | `{"cycleway:both": "no", "lanes:backward": "3", "lanes:forward": "3", "maxspeed": "30 mph", "parking:both": "parallel"}` | `{"aadt": 20831, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 1, "reversible": 2}, "lanes_back": 3, "lanes_fwd": 3, "one_way": false, "parking": 2, "speed": {"ob": 30}}` |
| 1.33 | 26 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "2", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": 21119, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 2}, "lanes_back": 2, "lanes_fwd": 2, "one_way": false, "parking": 0, "speed": {"ob": 25}}` |
| 0.90 | 16 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "3", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "25 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": 24213, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": 0, "speed": {}}` |
| 0.47 | 11 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"cycleway:right": "no", "lanes": "3", "oneway": "yes"}` | `{"cycleway:right": "no", "lanes": "2", "maxspeed": "20 mph", "oneway": "yes", "parking:left": "no", "parking:right": "parallel"}` | `{"aadt": 21119, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 3, "ob": 2}, "lanes_back": 3, "lanes_fwd": 2, "one_way": false, "parking": 1, "speed": {"ob": 20}}` |
| 0.09 | 5 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "3", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "25 mph", "oneway": "yes"}` | `not matched` |
| 0.08 | 2 | LTS 3 -> 2 | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, single lane, mid volume | `{"lanes": "4"}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": 2335, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |

### 16th Street Northwest: 10.53 mi, 230 ways

before LTS 1 0.21, LTS 2 0.18, LTS 3 6.30, LTS 4 3.84 | after LTS 1 0.07, LTS 2 0.32, LTS 3 2.96, LTS 4 7.18

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3.49 | 110 | LTS 4 (same) | mixed traffic, 30 mph, urban multilane, two-way busy | mixed traffic, 30 mph, urban multilane, two-way busy | `{"lanes": "5", "lanes:backward": "2", "lanes:forward": "3", "maxspeed": "30 mph"}` | `{"lanes:backward": "2", "lanes:forward": "2", "maxspeed": "30 mph", "parking:both": "no"}` | `{"aadt": 24429, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 2}, "lanes_back": 2, "lanes_fwd": 2, "one_way": false, "parking": 0, "speed": {"ob": 30}}` |
| 2.89 | 24 | LTS 3 -> 4 | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane, two-way busy | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": 24429, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 3, "ob": 2}, "lanes_back": 3, "lanes_fwd": 2, "one_way": false, "parking": 0, "speed": {"ob": 30}}` |
| 1.18 | 22 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 9540, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 3}, "lanes_back": 3, "lanes_fwd": 2, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.94 | 22 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "4", "maxspeed": "25 mph"}` | `{"lanes:backward": "3", "lanes:forward": "3", "maxspeed": "25 mph", "parking:both": "no"}` | `{"aadt": 26965, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 2, "reversible": 1}, "lanes_back": 3, "lanes_fwd": 3, "one_way": false, "parking": 0, "speed": {"ob": 25}}` |
| 0.48 | 13 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "6", "lanes:backward": "3", "lanes:forward": "3"}` | `{"lanes:backward": "3", "lanes:forward": "3", "maxspeed": "20 mph", "parking:both": "no"}` | `{"aadt": 9540, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 3, "ob": 3}, "lanes_back": 3, "lanes_fwd": 3, "one_way": false, "parking": 0, "speed": {"ob": 20}}` |
| 0.33 | 1 | LTS 3 -> 4 | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 30 mph, urban multilane, two-way busy | `{"cycleway:both": "share_busway", "lanes": "4", "lanes:psv:backward": "1", "lanes:psv:backward:conditional": "1 @ (Mo-Fr 07:00-09:30)", "lanes:psv:forward": "1", "lanes:psv:forward:conditional": "1 @ (Mo-Fr 15:30-19:00)", "maxspeed": "25 mph"}` | `{"cycleway:both": "share_busway", "lanes:backward": "3", "lanes:forward": "3", "lanes:psv:backward": "1", "lanes:psv:backward:conditional": "1 @ (Mo-Fr 07:00-09:30)", "lanes:psv:forward": "1", "lanes:psv:forward:conditional": "1 @ (Mo-Fr 15:30-19:00)", "maxspeed": "30 mph", "parking:both": "no"}` | `{"aadt": 26965, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 2, "reversible": 1}, "lanes_back": 3, "lanes_fwd": 3, "one_way": false, "parking": 0, "speed": {"ob": 30}}` |

### K Street Northwest: 6.02 mi, 162 ways

before LTS 1 1.18, LTS 2 0.68, LTS 3 4.16 | after LTS 1 0.38, LTS 2 0.30, LTS 3 5.34

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2.24 | 68 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 2}, "lanes_back": 2, "lanes_fwd": 2, "one_way": false, "parking": 0, "speed": {"ob": 20}}` |
| 1.10 | 20 | LTS 1 -> 3 | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "1", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 2}, "lanes_back": 2, "lanes_fwd": 2, "one_way": false, "parking": 0, "speed": {"ob": 20}}` |
| 0.75 | 27 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"cycleway:right": "no", "lanes": "2", "oneway": "yes"}` | `{"cycleway:right": "no", "lanes": "2", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 2}, "lanes_back": 2, "lanes_fwd": 2, "one_way": false, "parking": 0, "speed": {"ob": 20}}` |
| 0.35 | 3 | LTS 3 (same) | mixed traffic, 20 mph or below, single lane, arterial floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"cycleway:right": "no", "lanes": "1", "oneway": "yes"}` | `{"cycleway:right": "no", "lanes": "2", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 2}, "lanes_back": 2, "lanes_fwd": 2, "one_way": false, "parking": 0, "speed": {"ob": 20}}` |
| 0.20 | 5 | LTS 2 -> 3 | mixed traffic, 20 mph or below, single lane, high volume | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"cycleway": "separate", "lanes": "2", "parking:left": "no", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"cycleway": "separate", "lanes:backward": "2", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 2}, "lanes_back": 2, "lanes_fwd": 1, "one_way": false, "parking": 3, "speed": {"ob": 20}}` |
| 0.18 | 7 | LTS 3 -> 2 | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, single lane, high volume | `{"cycleway": "separate", "lanes": "4"}` | `{"cycleway": "separate", "lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "no"}` | `{"aadt": 13188, "bike": {"ib": 2, "ob": 2}, "bike_back": 2, "bike_ft": 6.0, "bike_fwd": 2, "lanes": {"ib": 1, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": false, "parking": 0, "speed": {"ob": 20}}` |

### Minnesota Avenue Southeast: 4.93 mi, 98 ways

before LTS 1 0.01, LTS 2 0.97, LTS 3 3.96 | after LTS 1 0.20, LTS 2 0.71, LTS 3 4.02

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.96 | 21 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "5", "lanes:backward": "2", "lanes:forward": "3"}` | `{"lanes:backward": "2", "lanes:forward": "3", "maxspeed": "25 mph", "parking:both": "no"}` | `{"aadt": 11729, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 3}, "lanes_back": 2, "lanes_fwd": 3, "one_way": false, "parking": 0, "speed": {"ob": 25}}` |
| 0.58 | 2 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "1", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 8336, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 2}, "lanes_back": 2, "lanes_fwd": 2, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.52 | 7 | LTS 2 (same) | mixed traffic, 20 mph or below, single lane, high volume | mixed traffic, 20 mph or below, single lane, high volume | `{"cycleway": "separate", "lanes": "2", "maxspeed": "20 mph"}` | `{"cycleway": "separate", "lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:left": "no", "parking:right": "parallel"}` | `{"aadt": 8336, "bike": {"ib": 3, "ob": 3}, "bike_back": 3, "bike_ft": 4.5, "bike_fwd": 3, "lanes": {"ib": 1, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": false, "parking": 1, "speed": {"ob": 20}}` |
| 0.51 | 2 | LTS 3 (same) | mixed traffic, 20 mph or below, single lane, arterial floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "2"}` | `{"lanes:backward": "2", "lanes:forward": "2", "maxspeed": "25 mph", "parking:both": "parallel"}` | `{"aadt": 8336, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 2}, "lanes_back": 2, "lanes_fwd": 2, "one_way": false, "parking": 2, "speed": {"ob": 25}}` |
| 0.32 | 4 | LTS 3 (same) | mixed traffic, 20 mph or below, single lane, high volume, arterial floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "2"}` | `{"lanes:backward": "2", "lanes:forward": "2", "maxspeed": "20 mph", "parking:left": "no", "parking:right": "parallel"}` | `{"aadt": 8336, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 2}, "lanes_back": 2, "lanes_fwd": 2, "one_way": false, "parking": 1, "speed": {"ob": 20}}` |
| 0.20 | 2 | LTS 2 -> 3 | mixed traffic, 20 mph or below, single lane, mid volume | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "2"}` | `{"lanes:backward": "2", "lanes:forward": "1", "maxspeed": "20 mph", "parking:left": "no", "parking:right": "parallel"}` | `{"aadt": 3255, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 1}, "lanes_back": 2, "lanes_fwd": 1, "one_way": false, "parking": 1, "speed": {"ob": 20}}` |

### MacArthur Boulevard Northwest: 5.04 mi, 51 ways

before LTS 1 0.10, LTS 3 4.63, LTS 4 0.31 | after LTS 1 0.10, LTS 3 4.53, LTS 4 0.42

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3.34 | 21 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 11011, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 2}, "lanes_back": 2, "lanes_fwd": 2, "one_way": false, "parking": 2, "speed": {"ob": 25}}` |
| 0.63 | 6 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, single lane, mid volume, arterial floor | `{"lanes": "4", "lanes:backward": "2", "lanes:forward": "2"}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": 6907, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.22 | 1 | LTS 3 -> 4 | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane, two-way busy | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 11011, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 2}, "lanes_back": 2, "lanes_fwd": 2, "one_way": false, "parking": 2, "speed": {"ob": 30}}` |
| 0.16 | 2 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 20 mph or below, single lane, mid volume, arterial floor | `{"lanes": "4", "lanes:backward": "2", "lanes:forward": "2", "maxspeed": "25 mph"}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": 6907, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.12 | 1 | LTS 4 -> 3 | mixed traffic, 30 mph, urban multilane, two-way busy | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 11011, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 2}, "lanes_back": 2, "lanes_fwd": 2, "one_way": false, "parking": 2, "speed": {"ob": 25}}` |
| 0.10 | 1 | LTS 4 (same) | mixed traffic, 30 mph, urban multilane, two-way busy | mixed traffic, 30 mph, single lane, high volume | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": 11011, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": false, "parking": 0, "speed": {"ob": 30}}` |

### Kenilworth Avenue Northeast: 2.51 mi, 30 ways

before LTS 1 0.27, LTS 3 2.24 | after LTS 1 0.27, LTS 3 2.24

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.50 | 3 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 20 mph or below, single lane, arterial floor | `{"lanes": "1", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 0, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": true, "parking": 0, "speed": {"ob": 20}}` |
| 0.40 | 4 | LTS 3 (same) | mixed traffic, 20 mph or below, single lane, arterial floor | mixed traffic, 20 mph or below, single lane, arterial floor | `{"lanes": "1", "maxspeed": "20 mph", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 0}, "lanes_back": 1, "lanes_fwd": 1, "one_way": true, "parking": 0, "speed": {}}` |
| 0.30 | 3 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "1", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "25 mph", "oneway": "yes", "parking:left": "no", "parking:right": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 0}, "lanes_back": 1, "lanes_fwd": 1, "one_way": true, "parking": 1, "speed": {}}` |
| 0.27 | 2 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{"lanes": "2"}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.26 | 2 | LTS 3 (same) | mixed traffic, 20 mph or below, single lane, arterial floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "1", "oneway": "yes"}` | `{"lanes": "2", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 0}, "lanes_back": 2, "lanes_fwd": 2, "one_way": true, "parking": 0, "speed": {}}` |
| 0.22 | 2 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, high volume, arterial floor | mixed traffic, 20 mph or below, urban multilane, high volume, arterial floor | `{"lanes": "2", "oneway": "yes"}` | `{"lanes": "2", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 2, "ob": 0}, "lanes_back": 2, "lanes_fwd": 2, "one_way": true, "parking": 0, "speed": {}}` |

### The US National Arboretum's internal roads

### Arboretum (roads and service ways in the grounds): 41.31 mi, 766 ways

before LTS 1 41.07, LTS 2 0.23 | after LTS 1 41.07, LTS 2 0.23

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 39.95 | 747 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{}` | `{}` | `not matched` |
| 1.13 | 8 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{"parking:both": "no"}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {"ib": 1, "ob": 1}, "lanes_back": 1, "lanes_fwd": 1, "one_way": false, "parking": 0, "speed": {"ob": 20}}` |
| 0.22 | 10 | LTS 2 (same) | mixed traffic, 20 mph or below, single lane, high volume | mixed traffic, 20 mph or below, single lane, high volume | `{}` | `{}` | `not matched` |
| 0.01 | 1 | LTS 2 (same) | mixed traffic, 20 mph or below, single lane, mid volume | mixed traffic, 20 mph or below, single lane, mid volume | `{}` | `{}` | `not matched` |

## Baltimore examples

### Charles Street: 8.42 mi, 123 ways

before LTS 2 2.50, LTS 3 5.85, LTS 4 0.07 | after LTS 2 2.50, LTS 3 5.92

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 4.13 | 54 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "4", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"lanes": "4", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 1.51 | 8 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.99 | 17 | LTS 2 (same) | bike lane, narrow at 25 mph or below | bike lane, narrow at 25 mph or below | `{"cycleway:right": "lane", "cycleway:right:buffer": "yes", "lanes": "1", "maxspeed": "25 mph", "oneway": "yes", "parking:left": "no", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "yes", "lanes": "1", "maxspeed": "25 mph", "oneway": "yes", "parking:left": "no", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.63 | 14 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "4", "lanes:backward": "2", "lanes:forward": "2", "maxspeed": "25 mph"}` | `{"lanes": "4", "lanes:backward": "2", "lanes:forward": "2", "maxspeed": "25 mph"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 30}}` |
| 0.61 | 15 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "2", "maxspeed": "25 mph"}` | `{"lanes": "2", "maxspeed": "25 mph"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.18 | 1 | LTS 3 (same) | bike lane, narrow or multilane at 30 mph | bike lane, narrow or multilane at 30 mph | `{"cycleway:right": "lane", "cycleway:right:buffer": "yes", "lanes": "3", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "yes", "lanes": "3", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |

### St Paul Street: 5.25 mi, 66 ways

before LTS 2 0.37, LTS 3 2.91, LTS 4 1.96 | after LTS 2 0.37, LTS 3 2.91, LTS 4 1.96

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.94 | 12 | LTS 4 (same) | mixed traffic, 35 mph or above | mixed traffic, 35 mph or above | `{"lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 35}}` |
| 1.54 | 17 | LTS 3 (same) | bike lane, narrow or multilane at 30 mph | bike lane, narrow or multilane at 30 mph | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "2", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "2", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 1.30 | 25 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "3", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.37 | 3 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"maxspeed": "25 mph", "oneway": "yes", "parking:both:fee": "yes", "parking:both:maxstay": "4 hours", "parking:left": "street_side", "parking:left:orientation": "parallel", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"maxspeed": "25 mph", "oneway": "yes", "parking:both:fee": "yes", "parking:both:maxstay": "4 hours", "parking:left": "street_side", "parking:left:orientation": "parallel", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.05 | 4 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"cycleway:right": "shared_lane", "lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"cycleway:right": "shared_lane", "lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `not matched` |
| 0.02 | 3 | LTS 4 (same) | mixed traffic, 35 mph or above | mixed traffic, 35 mph or above | `{"lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `not matched` |

### North Avenue: 7.66 mi, 171 ways

before LTS 2 0.30, LTS 3 7.37 | after LTS 2 0.30, LTS 3 7.37

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 6.67 | 140 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "3", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.30 | 2 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.23 | 7 | LTS 3 (same) | mixed traffic, 30 mph, single lane | mixed traffic, 30 mph, single lane | `{"maxspeed": "30 mph", "oneway": "yes"}` | `{"maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.22 | 14 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "4", "maxspeed": "30 mph"}` | `{"lanes": "4", "maxspeed": "30 mph"}` | `not matched` |
| 0.16 | 4 | LTS 3 (same) | bike lane, narrow or multilane at 30 mph | bike lane, narrow or multilane at 30 mph | `{"cycleway:both": "lane", "cycleway:both:buffer": "no", "lanes": "4", "maxspeed": "30 mph", "parking:both": "no"}` | `{"cycleway:both": "lane", "cycleway:both:buffer": "no", "lanes": "4", "maxspeed": "30 mph", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 30}}` |
| 0.07 | 3 | LTS 3 (same) | mixed traffic, 30 mph, single lane | mixed traffic, 30 mph, single lane | `{"lanes": "1", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "30 mph", "oneway": "yes"}` | `not matched` |

### Maryland Avenue: 1.48 mi, 19 ways

before LTS 2 0.98, LTS 3 0.50 | after LTS 2 0.98, LTS 3 0.50

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.92 | 13 | LTS 2 (same) | mixed traffic, 25 mph, urban multilane | mixed traffic, 25 mph, urban multilane | `{"cycleway:left": "separate", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"cycleway:left": "separate", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.47 | 3 | LTS 3 (same) | mixed traffic, 30 mph, single lane | mixed traffic, 30 mph, single lane | `{"cycleway:left": "separate", "lanes": "1", "maxspeed": "30 mph", "oneway": "yes"}` | `{"cycleway:left": "separate", "lanes": "1", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.06 | 2 | LTS 2 (same) | bike lane, narrow at 25 mph or below | bike lane, narrow at 25 mph or below | `{"cycleway:left": "lane", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"cycleway:left": "lane", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.03 | 1 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, wide one-way floor | mixed traffic, 25 mph, urban multilane, wide one-way floor | `{"lanes": "3", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "25 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |

### Fort Avenue: 2.26 mi, 27 ways

before LTS 1 0.37, LTS 2 1.74, LTS 3 0.15 | after LTS 1 0.37, LTS 2 1.74, LTS 3 0.15

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.09 | 15 | LTS 2 (same) | bike lane, narrow at 25 mph or below | bike lane, narrow at 25 mph or below | `{"cycleway:both": "lane", "cycleway:both:buffer": "no", "lanes": "2", "maxspeed": "25 mph", "parking:both": "no"}` | `{"cycleway:both": "lane", "cycleway:both:buffer": "no", "lanes": "2", "maxspeed": "25 mph", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.63 | 7 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.37 | 1 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{}` | `{}` | `not matched` |
| 0.14 | 2 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"cycleway": "shared_lane", "lanes": "3", "lanes:backward": "2", "lanes:forward": "1", "maxspeed": "25 mph", "oneway": "no"}` | `{"cycleway": "shared_lane", "lanes": "3", "lanes:backward": "2", "lanes:forward": "1", "maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.02 | 1 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"maxspeed": "25 mph", "oneway": "no"}` | `not matched` |
| 0.02 | 1 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"cycleway": "shared_lane", "lanes": "4", "maxspeed": "25 mph", "oneway": "no"}` | `{"cycleway": "shared_lane", "lanes": "4", "maxspeed": "25 mph", "oneway": "no"}` | `not matched` |

### Key Highway: 2.76 mi, 41 ways

before LTS 3 2.76 | after LTS 3 2.76

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2.71 | 33 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.05 | 8 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `not matched` |

### Pratt Street: 5.04 mi, 68 ways

before LTS 2 1.35, LTS 3 3.68 | after LTS 2 1.35, LTS 3 3.68

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2.58 | 38 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 1.35 | 11 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.58 | 9 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, wide one-way floor | mixed traffic, 25 mph, urban multilane, wide one-way floor | `{"lanes": "3", "maxspeed": "25 mph", "oneway": "yes", "parking:condition:left": "free", "parking:left": "yes", "parking:left:orientation": "parallel", "parking:right": "no", "parking:right:restriction": "no_stopping"}` | `{"lanes": "3", "maxspeed": "25 mph", "oneway": "yes", "parking:condition:left": "free", "parking:left": "yes", "parking:left:orientation": "parallel", "parking:right": "no", "parking:right:restriction": "no_stopping"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.48 | 7 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no", "parking:condition:both": "free", "parking:lane:both": "parallel"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no", "parking:condition:both": "free", "parking:lane:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.03 | 2 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "4", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "4", "maxspeed": "30 mph", "oneway": "yes"}` | `not matched` |
| 0.01 | 1 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, arterial floor | mixed traffic, 25 mph, urban multilane, arterial floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `not matched` |

### Eastern Avenue: 6.15 mi, 129 ways

before LTS 1 0.20, LTS 2 0.18, LTS 3 3.19, LTS 4 2.58 | after LTS 1 0.20, LTS 2 0.18, LTS 3 3.19, LTS 4 2.58

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2.28 | 60 | LTS 4 (same) | mixed traffic, 35 mph or above | mixed traffic, 35 mph or above | `{"lanes": "3", "maxspeed": "35 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "35 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 35}}` |
| 1.67 | 21 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.86 | 14 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "4", "maxspeed": "25 mph", "oneway": "no"}` | `{"lanes": "4", "maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.45 | 3 | LTS 3 (same) | mixed traffic, 20 mph or below, single lane, arterial floor | mixed traffic, 20 mph or below, single lane, arterial floor | `{"cycleway": "no", "lanes": "2", "maxspeed": "20 mph", "oneway": "no", "parking:both": "lane", "parking:both:orientation": "parallel", "parking:condition:both": "free"}` | `{"cycleway": "no", "lanes": "2", "maxspeed": "20 mph", "oneway": "no", "parking:both": "lane", "parking:both:orientation": "parallel", "parking:condition:both": "free"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.30 | 11 | LTS 4 (same) | mixed traffic, 35 mph or above | mixed traffic, 35 mph or above | `{"lanes": "3", "maxspeed": "35 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "35 mph", "oneway": "yes"}` | `not matched` |
| 0.20 | 4 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{"maxspeed": "20 mph", "oneway": "no"}` | `{"maxspeed": "20 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |

### Falls Road: 5.16 mi, 68 ways

before LTS 3 5.16 | after LTS 3 5.16

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.67 | 19 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "5", "lanes:backward": "3", "lanes:forward": "2", "maxspeed": "30 mph"}` | `{"lanes": "5", "lanes:backward": "3", "lanes:forward": "2", "maxspeed": "30 mph"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 30}}` |
| 1.22 | 14 | LTS 3 (same) | mixed traffic, 30 mph, single lane | mixed traffic, 30 mph, single lane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "no"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 30}}` |
| 0.95 | 11 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "4", "lanes:backward": "2", "lanes:forward": "2", "maxspeed": "25 mph"}` | `{"lanes": "4", "lanes:backward": "2", "lanes:forward": "2", "maxspeed": "25 mph"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.74 | 7 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.33 | 4 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, arterial floor | mixed traffic, 25 mph, urban multilane, arterial floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes", "parking:left": "no", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes", "parking:left": "no", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.07 | 2 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `not matched` |

### Roland Avenue: 5.32 mi, 86 ways

before LTS 2 4.30, LTS 3 1.02 | after LTS 2 4.30, LTS 3 1.02

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3.20 | 52 | LTS 2 (same) | bike lane, narrow at 25 mph or below | bike lane, narrow at 25 mph or below | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.99 | 11 | LTS 3 (same) | bike lane, 35 mph | bike lane, 35 mph | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 35}}` |
| 0.85 | 10 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"lanes": "2", "maxspeed": "25 mph", "parking:both": "no"}` | `{"lanes": "2", "maxspeed": "25 mph", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.14 | 1 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"lanes": "2", "oneway": "no"}` | `{"lanes": "2", "oneway": "no"}` | `not matched` |
| 0.10 | 10 | LTS 2 (same) | bike lane, narrow at 25 mph or below | bike lane, narrow at 25 mph or below | `{"cycleway:right": "lane", "cycleway:right:buffer": "yes", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "yes", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `not matched` |
| 0.03 | 1 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"cycleway": "shared_lane", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"cycleway": "shared_lane", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |

### Greenmount Avenue: 3.05 mi, 26 ways

before LTS 1 0.09, LTS 3 2.97 | after LTS 1 0.09, LTS 3 2.97

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.58 | 16 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "4", "maxspeed": "25 mph"}` | `{"lanes": "4", "maxspeed": "25 mph"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 1.34 | 6 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "2", "lanes:backward": "1", "lanes:forward": "1", "maxspeed": "25 mph", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"lanes": "2", "lanes:backward": "1", "lanes:forward": "1", "maxspeed": "25 mph", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.09 | 2 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{}` | `{}` | `not matched` |
| 0.05 | 2 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "4", "maxspeed": "25 mph", "oneway": "no"}` | `{"lanes": "4", "maxspeed": "25 mph", "oneway": "no"}` | `not matched` |

### Boston Street: 4.52 mi, 114 ways

before LTS 3 4.38, LTS 4 0.14 | after LTS 3 4.38, LTS 4 0.14

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2.58 | 77 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "3", "lanes:backward": "2", "lanes:forward": "1", "maxspeed": "30 mph", "parking:both": "yes", "parking:both:orientation": "parallel", "parking:condition:both": "free", "parking:condition:both:time_interval": "00:00-24:00; Mo-Fr 07:00-09:00 off"}` | `{"lanes": "3", "lanes:backward": "2", "lanes:forward": "1", "maxspeed": "30 mph", "parking:both": "yes", "parking:both:orientation": "parallel", "parking:condition:both": "free", "parking:condition:both:time_interval": "00:00-24:00; Mo-Fr 07:00-09:00 off"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 30}}` |
| 1.14 | 8 | LTS 3 (same) | bike lane, 35 mph | bike lane, 35 mph | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "1", "maxspeed": "35 mph", "oneway": "yes", "oneway:bicycle": "yes", "parking:right": "yes", "parking:right:orientation": "parallel"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "1", "maxspeed": "35 mph", "oneway": "yes", "oneway:bicycle": "yes", "parking:right": "yes", "parking:right:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 35}}` |
| 0.37 | 8 | LTS 3 (same) | mixed traffic, 30 mph, single lane | mixed traffic, 30 mph, single lane | `{"lanes": "1", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "no", "parking:both:restriction": "no_stopping"}` | `{"lanes": "1", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "no", "parking:both:restriction": "no_stopping"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.25 | 17 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"cycleway:right": "shared_lane", "lanes": "2", "maxspeed": "30 mph", "oneway": "yes", "parking:condition:right": "free", "parking:condition:right:time_interval": "00:00-24:00; Mo-Fr 07:00-09:00 off", "parking:left": "no", "parking:left:restriction": "no_stopping", "parking:right": "yes", "parking:right:orientation": "parallel"}` | `{"cycleway:right": "shared_lane", "lanes": "2", "maxspeed": "30 mph", "oneway": "yes", "parking:condition:right": "free", "parking:condition:right:time_interval": "00:00-24:00; Mo-Fr 07:00-09:00 off", "parking:left": "no", "parking:left:restriction": "no_stopping", "parking:right": "yes", "parking:right:orientation": "parallel"}` | `not matched` |
| 0.10 | 1 | LTS 4 (same) | mixed traffic, 35 mph or above | mixed traffic, 35 mph or above | `{"cycleway:right": "shared_lane", "lanes": "1", "maxspeed": "35 mph", "oneway": "yes", "oneway:bicycle": "yes"}` | `{"cycleway:right": "shared_lane", "lanes": "1", "maxspeed": "35 mph", "oneway": "yes", "oneway:bicycle": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 35}}` |
| 0.04 | 2 | LTS 4 (same) | mixed traffic, 35 mph or above | mixed traffic, 35 mph or above | `{"cycleway:right": "shared_lane", "lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `{"cycleway:right": "shared_lane", "lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `not matched` |

### Guilford Avenue: 2.92 mi, 50 ways

before LTS 1 0.01, LTS 2 1.70, LTS 3 1.21 | after LTS 2 1.70, LTS 3 1.22

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.70 | 22 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"lanes": "2", "maxspeed": "25 mph"}` | `{"lanes": "2", "maxspeed": "25 mph"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.67 | 14 | LTS 3 (same) | bike lane, narrow or multilane at 30 mph | bike lane, narrow or multilane at 30 mph | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "3", "maxspeed": "30 mph", "oneway": "yes"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "3", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.47 | 11 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.07 | 2 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `not matched` |
| 0.01 | 1 | LTS 1 -> 3 | mixed traffic, 20 mph or below, single lane | mixed traffic, 30 mph, single lane | `{"oneway": "yes"}` | `{"maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |

### Druid Park Lake Drive: 3.24 mi, 53 ways

before LTS 2 0.27, LTS 3 2.97 | after LTS 2 0.27, LTS 3 2.97

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.91 | 33 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.55 | 6 | LTS 3 (same) | mixed traffic, 30 mph, single lane | mixed traffic, 30 mph, single lane | `{"lanes": "1", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.41 | 3 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "2", "maxspeed": "25 mph"}` | `{"lanes": "2", "maxspeed": "25 mph"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.24 | 3 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"lanes": "1", "maxspeed": "25 mph"}` | `{"lanes": "1", "maxspeed": "25 mph"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.04 | 4 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `not matched` |
| 0.04 | 1 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_back": 0, "bike_ft": null, "bike_fwd": 0, "lanes": {}, "lanes_back": null, "lanes_fwd": null, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
