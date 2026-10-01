# Before and after: DC Roadway Block and Baltimore street centerline conflated

Before: the integration branch (33ff4da) classifier on the 2026-09-25 extract, as the earlier calibration tables were made (classification only: the 886 loaded stress rows and 52 access rows are overrides applied at the rebuild and are in neither column). After: the same classifier with the agency layers conflated (`pipeline.conflation.conflate_blocks`, `agency_roads.overlay`) and the Roadway Block's AADT filling where no count layer reached the way. Only DC's and Baltimore's ways can change; every other way is the baseline's. Road ways only (proposed, construction, platform and corridor ways and trail-class ways are not classified here). Miles.

The two runs agree on the baseline tier of all but 7 of the 82,357 DC and Baltimore ways (the baseline did not know a separately mapped bike facility the way the rebuild's own pairing does).

## Region-wide

| area | total mi | LTS 1 before -> after | LTS 2 before -> after | LTS 3 before -> after | LTS 4 before -> after | LTS 5 before -> after |
| --- | --- | --- | --- | --- | --- | --- |
| Region | 98,411 | 47,377.2 (48.1%) -> 47,318.3 (48.1%), -58.9 | 27,003.5 (27.4%) -> 27,059.6 (27.5%), +56.1 | 5,775.1 ( 5.9%) -> 5,749.2 ( 5.8%), -25.9 | 16,724.4 (17.0%) -> 16,753.1 (17.0%), +28.7 | 1,530.8 ( 1.6%) -> 1,530.8 ( 1.6%), +0.0 |
| DC | 2,189 | 1,560.5 (71.3%) -> 1,532.4 (70.0%), -28.1 | 222.9 (10.2%) -> 243.7 (11.1%), +20.9 | 266.9 (12.2%) -> 252.3 (11.5%), -14.6 | 138.3 ( 6.3%) -> 160.0 ( 7.3%), +21.8 | 0.0 ( 0.0%) -> 0.0 ( 0.0%), +0.0 |
| MD | 62,196 | 28,241.1 (45.4%) -> 28,210.2 (45.4%), -30.9 | 19,858.4 (31.9%) -> 19,893.7 (32.0%), +35.3 | 3,566.7 ( 5.7%) -> 3,555.4 ( 5.7%), -11.3 | 10,159.7 (16.3%) -> 10,166.7 (16.3%), +6.9 | 370.4 ( 0.6%) -> 370.4 ( 0.6%), +0.0 |
| VA | 33,765 | 17,500.6 (51.8%) -> 17,500.6 (51.8%), +0.0 | 6,836.1 (20.2%) -> 6,836.1 (20.2%), +0.0 | 1,938.9 ( 5.7%) -> 1,938.9 ( 5.7%), +0.0 | 6,329.3 (18.7%) -> 6,329.3 (18.7%), +0.0 | 1,160.0 ( 3.4%) -> 1,160.0 ( 3.4%), +0.0 |
| no state | 261 | 75.0 (28.7%) -> 75.0 (28.7%), +0.0 | 86.2 (33.0%) -> 86.2 (33.0%), +0.0 | 2.6 ( 1.0%) -> 2.6 ( 1.0%), +0.0 | 97.1 (37.2%) -> 97.1 (37.2%), +0.0 | 0.4 ( 0.1%) -> 0.4 ( 0.1%), +0.0 |
| DC ways a Roadway Block was matched to | 1,238 | 652.6 (52.7%) -> 624.5 (50.5%), -28.1 | 207.0 (16.7%) -> 227.9 (18.4%), +20.9 | 251.8 (20.3%) -> 237.2 (19.2%), -14.6 | 126.3 (10.2%) -> 148.0 (12.0%), +21.8 | 0.0 ( 0.0%) -> 0.0 ( 0.0%), +0.0 |
| Baltimore City (within about 150 m of its centerline) | 2,950 | 1,342.3 (45.5%) -> 1,311.5 (44.5%), -30.8 | 1,029.4 (34.9%) -> 1,064.7 (36.1%), +35.2 | 357.6 (12.1%) -> 346.2 (11.7%), -11.3 | 220.3 ( 7.5%) -> 227.2 ( 7.7%), +6.9 | 0.1 ( 0.0%) -> 0.1 ( 0.0%), +0.0 |

## What moved, by what the layer changed

Ways whose tier changed, by the inputs the layer changed on them (from the tags the classifier read before and after).

| area | the layer changed | ways | miles | higher stress | lower stress |
| --- | --- | --- | --- | --- | --- |
| dc | speed + parking | 637 | 82.4 | 51.5 | 30.9 |
| baltimore | speed | 907 | 78.4 | 54.9 | 23.5 |
| dc | speed + parking + count | 119 | 24.7 | 24.4 | 0.3 |
| dc | speed + lanes + parking | 323 | 21.3 | 15.3 | 6.0 |
| dc | parking + count | 81 | 14.7 | 14.2 | 0.5 |
| dc | speed + bike facility + parking | 228 | 9.0 | 0.8 | 8.2 |
| dc | speed + lanes + parking + count | 60 | 8.2 | 7.7 | 0.6 |
| dc | lanes + parking + count | 49 | 7.5 | 7.4 | 0.0 |
| dc | lanes + parking | 61 | 7.4 | 6.2 | 1.1 |
| dc | bike facility + parking | 115 | 5.3 | 0.3 | 5.0 |
| dc | speed + lanes + bike facility + parking | 131 | 4.8 | 1.0 | 3.7 |
| baltimore | speed + one-way | 45 | 4.2 | 3.4 | 0.8 |
| dc | lanes + bike facility + parking | 101 | 4.1 | 0.0 | 4.1 |
| dc | speed + bike facility | 60 | 3.9 | 2.0 | 1.9 |
| dc | bike facility + parking + count | 22 | 2.9 | 0.2 | 2.7 |
| dc | speed + bike-lane width | 34 | 2.3 | 0.2 | 2.1 |
| dc | bike facility | 37 | 2.1 | 0.7 | 1.4 |
| dc | speed + bike facility + parking + count | 28 | 1.9 | 0.1 | 1.8 |
| dc | bike-lane width | 28 | 1.6 | 0.0 | 1.6 |
| dc | speed + bike-lane width + count | 8 | 1.6 | 0.1 | 1.6 |
| dc | speed + lanes + bike facility | 26 | 1.5 | 0.6 | 0.9 |
| baltimore | speed + lanes + one-way | 7 | 1.4 | 0.4 | 1.0 |
| dc | speed + lanes + bike facility + parking + count | 14 | 1.1 | 0.2 | 1.0 |
| dc | speed + bike facility + count | 5 | 1.1 | 0.9 | 0.2 |

### DC: miles by tier movement

| from | to | miles |
| --- | --- | --- |
| LTS 1 | LTS 2 | 69.9 |
| LTS 2 | LTS 1 | 43.9 |
| LTS 3 | LTS 4 | 28.9 |
| LTS 1 | LTS 3 | 22.3 |
| LTS 3 | LTS 1 | 18.3 |
| LTS 2 | LTS 3 | 14.9 |
| LTS 3 | LTS 2 | 10.5 |
| LTS 4 | LTS 3 | 5.8 |
| LTS 4 | LTS 1 | 2.0 |
| LTS 2 | LTS 4 | 0.9 |
| LTS 4 | LTS 2 | 0.3 |
| LTS 1 | LTS 4 | 0.0 |

### Baltimore City: miles by tier movement

| from | to | miles |
| --- | --- | --- |
| LTS 1 | LTS 2 | 37.3 |
| LTS 3 | LTS 2 | 14.3 |
| LTS 3 | LTS 4 | 11.1 |
| LTS 2 | LTS 3 | 9.7 |
| LTS 2 | LTS 1 | 6.7 |
| LTS 4 | LTS 3 | 4.0 |
| LTS 1 | LTS 3 | 0.4 |
| LTS 4 | LTS 2 | 0.3 |
| LTS 2 | LTS 4 | 0.2 |
| LTS 3 | LTS 1 | 0.2 |

## The owner's example roads (DC)

### 4th Street Northeast: 2.90 mi, 37 ways

before LTS 1 0.33, LTS 2 2.25, LTS 3 0.33 | after LTS 1 1.22, LTS 2 1.51, LTS 3 0.17

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.12 | 14 | LTS 2 (same) | bike lane, narrow at 25 mph or below | bike lane, narrow at 25 mph or below | `{"cycleway:both": "lane", "cycleway:both:buffer": "no", "lanes": "2", "parking:both": "yes", "parking:both:orientation": "parallel"}` | `{"cycleway:both": "lane", "cycleway:both:width": "1.52", "lanes:backward": "1", "lanes:forward": "1", "maxspeed": "25 mph", "parking:both": "parallel"}` | `{"aadt": 10730, "bike": {"ib": 1, "ob": 1}, "bike_ft": 5.0, "lanes": {"ib": 1, "ob": 1}, "one_way": false, "parking": 2, "speed": {"ob": 25}}` |
| 0.65 | 2 | LTS 2 -> 1 | bike lane, narrow at 25 mph or below | bike lane, adequate width at 25 mph or below | `{"cycleway:left": "no", "cycleway:right": "lane", "cycleway:right:buffer": "no", "cycleway:right:oneway": "yes", "lanes": "1", "oneway": "yes", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"cycleway:right": "lane", "cycleway:right:width": "1.52", "lanes": "1", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 4054, "bike": {"ib": 1}, "bike_ft": 5.0, "lanes": {"ib": 1, "ob": 0}, "one_way": true, "parking": 2, "speed": {}}` |
| 0.29 | 4 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 1}, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.28 | 4 | LTS 3 -> 1 | mixed traffic, 20 mph or below, urban multilane, two-way floor | separated track alongside | `{"cycleway:left": "track", "cycleway:left:oneway": "no", "lanes": "3", "lanes:backward": "2", "oneway:bicycle": "no"}` | `{"cycleway:both": "track", "lanes:backward": "2", "lanes:forward": "2", "maxspeed": "25 mph", "oneway:bicycle": "no", "parking:left": "no", "parking:right": "parallel"}` | `{"aadt": 10730, "bike": {"ib": 3, "ob": 3}, "bike_ft": 4.5, "lanes": {"ib": 2, "ob": 2}, "one_way": false, "parking": 1, "speed": {"ob": 25}}` |
| 0.19 | 2 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"maxspeed": "25 mph"}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "25 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 1}, "one_way": false, "parking": 2, "speed": {"ob": 25}}` |
| 0.11 | 1 | LTS 2 (same) | mixed traffic, 25 mph, single lane | bike lane, narrow at 25 mph or below | `{"cycleway:right": "separate", "lanes": "1", "maxspeed": "25 mph", "oneway": "yes"}` | `{"cycleway:both": "lane", "cycleway:both:buffer": "yes", "cycleway:both:width": "1.52", "lanes": "1", "maxspeed": "25 mph", "oneway": "yes", "parking:left": "no", "parking:right": "parallel"}` | `{"aadt": 2679, "bike": {"ib": 2, "ob": 2}, "bike_ft": 5.0, "lanes": {"ib": 1, "ob": 0}, "one_way": true, "parking": 1, "speed": {}}` |

### 6th Street Northeast: 2.06 mi, 28 ways

before LTS 1 0.65, LTS 2 1.38, LTS 3 0.03 | after LTS 1 0.56, LTS 2 1.23, LTS 3 0.27

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.83 | 8 | LTS 2 (same) | bike lane, narrow at 25 mph or below | bike lane, narrow at 25 mph or below | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "cycleway:right:oneway": "yes", "lanes": "1", "oneway": "yes", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"cycleway:right": "lane", "cycleway:right:width": "1.52", "lanes": "1", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 3014, "bike": {"ib": 1}, "bike_ft": 5.0, "lanes": {"ib": 0, "ob": 1}, "one_way": true, "parking": 2, "speed": {"ob": 20}}` |
| 0.53 | 8 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 1}, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.25 | 3 | LTS 2 (same) | mixed traffic, 20 mph or below, urban multilane, mid volume | bike lane, narrow at 25 mph or below | `{"cycleway": "separate", "lanes": "2", "oneway": "yes"}` | `{"cycleway:both": "lane", "cycleway:both:buffer": "yes", "cycleway:both:width": "1.22", "lanes": "1", "maxspeed": "25 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 6523, "bike": {"ib": 2, "ob": 2}, "bike_ft": 4.0, "lanes": {"ib": 0, "ob": 1}, "one_way": true, "parking": 2, "speed": {"ob": 25}}` |
| 0.24 | 1 | LTS 2 -> 3 | mixed traffic, 20 mph or below, single lane, high volume | bike lane, narrow or multilane at 30 mph | `{"cycleway": "separate", "lanes": "2"}` | `{"cycleway:both": "lane", "cycleway:both:buffer": "yes", "cycleway:both:width": "1.22", "lanes:backward": "3", "lanes:forward": "3", "maxspeed": "30 mph", "parking:both": "parallel"}` | `{"aadt": 9867, "bike": {"ib": 2, "ob": 2}, "bike_ft": 4.0, "lanes": {"ib": 3, "ob": 1}, "one_way": false, "parking": 3, "speed": {"ob": 30}}` |
| 0.12 | 2 | LTS 1 -> 2 | mixed traffic, 20 mph or below, single lane | mixed traffic, 25 mph, single lane | `{}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "25 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 1}, "one_way": false, "parking": 2, "speed": {"ob": 25}}` |
| 0.03 | 1 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | bike lane, narrow or multilane at 30 mph | `{"cycleway": "separate", "lanes": "4", "lanes:backward": "3", "lanes:forward": "1"}` | `{"cycleway:both": "lane", "cycleway:both:buffer": "yes", "cycleway:both:width": "1.52", "lanes:backward": "3", "lanes:forward": "3", "maxspeed": "30 mph", "parking:both": "no"}` | `{"aadt": 9867, "bike": {"ib": 2, "ob": 2}, "bike_ft": 5.0, "lanes": {"ib": 3, "ob": 1}, "one_way": false, "parking": 0, "speed": {"ob": 30}}` |

### 22nd Street Northwest: 1.43 mi, 26 ways

before LTS 1 0.25, LTS 2 0.28, LTS 3 0.89 | after LTS 1 0.13, LTS 2 0.41, LTS 3 0.89

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.46 | 5 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, wide one-way floor | mixed traffic, 20 mph or below, single lane, mid volume, arterial floor | `{"lanes": "3", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 5630, "bike": {}, "bike_ft": null, "lanes": {"ib": 0, "ob": 1}, "one_way": true, "parking": 3, "speed": {"ob": 20}}` |
| 0.25 | 1 | LTS 1 -> 2 | mixed traffic, 20 mph or below, urban multilane | mixed traffic, 20 mph or below, single lane, mid volume | `{"lanes": "2", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 2742, "bike": {}, "bike_ft": null, "lanes": {"ib": 0, "ob": 1}, "one_way": true, "parking": 2, "speed": {"ob": 20}}` |
| 0.14 | 4 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, single lane, mid volume, arterial floor | `{"lanes": "3", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 6764, "bike": {}, "bike_ft": null, "lanes": {"ib": 0, "ob": 1}, "one_way": true, "parking": 3, "speed": {"ob": 20}}` |
| 0.12 | 2 | LTS 2 (same) | mixed traffic, 20 mph or below, single lane, mid volume | mixed traffic, 20 mph or below, single lane, mid volume | `{"lanes": "1", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 2742, "bike": {}, "bike_ft": null, "lanes": {"ib": 0, "ob": 1}, "one_way": true, "parking": 2, "speed": {"ob": 20}}` |
| 0.11 | 1 | LTS 2 -> 3 | mixed traffic, 25 mph, single lane | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"maxspeed": "25 mph"}` | `{"lanes:backward": "2", "lanes:forward": "2", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 2}, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.09 | 2 | LTS 3 -> 1 | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, single lane | `{"lanes": "4"}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 1}, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |

### Connecticut Avenue Northwest: 6.18 mi, 96 ways

before LTS 2 0.04, LTS 3 6.14 | after LTS 2 0.12, LTS 3 2.82, LTS 4 3.24

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3.24 | 32 | LTS 3 -> 4 | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 30 mph, urban multilane, two-way busy | `{"cycleway:both": "no", "lanes": "6", "maxspeed": "25 mph", "parking:both": "no"}` | `{"cycleway:both": "no", "lanes:backward": "3", "lanes:forward": "3", "maxspeed": "30 mph", "parking:both": "parallel"}` | `{"aadt": 20831, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 1, "reversible": 2}, "one_way": false, "parking": 2, "speed": {"ob": 30}}` |
| 1.33 | 26 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "2", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": 21119, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 2}, "one_way": false, "parking": 0, "speed": {"ob": 25}}` |
| 0.96 | 17 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "3", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "25 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": 24213, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": 0, "speed": {}}` |
| 0.47 | 11 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"cycleway:right": "no", "lanes": "3", "oneway": "yes"}` | `{"cycleway:right": "no", "lanes": "3", "maxspeed": "20 mph", "oneway": "yes", "parking:left": "no", "parking:right": "parallel"}` | `{"aadt": 21119, "bike": {}, "bike_ft": null, "lanes": {"ib": 3, "ob": 2}, "one_way": false, "parking": 1, "speed": {"ob": 20}}` |
| 0.08 | 2 | LTS 3 -> 2 | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, single lane, mid volume | `{"lanes": "4"}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": 2335, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 1}, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.04 | 4 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "4", "maxspeed": "25 mph"}` | `{"lanes": "4", "maxspeed": "25 mph"}` | `not matched` |

### 16th Street Northwest: 10.53 mi, 230 ways

before LTS 1 0.21, LTS 2 0.18, LTS 3 6.30, LTS 4 3.84 | after LTS 1 0.07, LTS 2 0.32, LTS 3 2.96, LTS 4 7.18

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3.49 | 110 | LTS 4 (same) | mixed traffic, 30 mph, urban multilane, two-way busy | mixed traffic, 30 mph, urban multilane, two-way busy | `{"lanes": "5", "lanes:backward": "2", "lanes:forward": "3", "maxspeed": "30 mph"}` | `{"lanes:backward": "2", "lanes:forward": "2", "maxspeed": "30 mph", "parking:both": "no"}` | `{"aadt": 24429, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 2}, "one_way": false, "parking": 0, "speed": {"ob": 30}}` |
| 2.89 | 24 | LTS 3 -> 4 | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane, two-way busy | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": 24429, "bike": {}, "bike_ft": null, "lanes": {"ib": 3, "ob": 2}, "one_way": false, "parking": 0, "speed": {"ob": 30}}` |
| 1.21 | 23 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 9540, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 3}, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.94 | 22 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "4", "maxspeed": "25 mph"}` | `{"lanes:backward": "3", "lanes:forward": "3", "maxspeed": "25 mph", "parking:both": "no"}` | `{"aadt": 26965, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 2, "reversible": 1}, "one_way": false, "parking": 0, "speed": {"ob": 25}}` |
| 0.48 | 13 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "6", "lanes:backward": "3", "lanes:forward": "3"}` | `{"lanes:backward": "3", "lanes:forward": "3", "maxspeed": "20 mph", "parking:both": "no"}` | `{"aadt": 9540, "bike": {}, "bike_ft": null, "lanes": {"ib": 3, "ob": 3}, "one_way": false, "parking": 0, "speed": {"ob": 20}}` |
| 0.33 | 1 | LTS 3 -> 4 | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 30 mph, urban multilane, two-way busy | `{"cycleway:both": "share_busway", "lanes": "4", "lanes:psv:backward": "1", "lanes:psv:backward:conditional": "1 @ (Mo-Fr 07:00-09:30)", "lanes:psv:forward": "1", "lanes:psv:forward:conditional": "1 @ (Mo-Fr 15:30-19:00)", "maxspeed": "25 mph"}` | `{"cycleway:both": "share_busway", "lanes:backward": "3", "lanes:forward": "3", "lanes:psv:backward": "1", "lanes:psv:backward:conditional": "1 @ (Mo-Fr 07:00-09:30)", "lanes:psv:forward": "1", "lanes:psv:forward:conditional": "1 @ (Mo-Fr 15:30-19:00)", "maxspeed": "30 mph", "parking:both": "no"}` | `{"aadt": 26965, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 2, "reversible": 1}, "one_way": false, "parking": 0, "speed": {"ob": 30}}` |

### K Street Northwest: 6.02 mi, 162 ways

before LTS 1 1.18, LTS 2 0.68, LTS 3 4.16 | after LTS 1 0.55, LTS 2 0.08, LTS 3 5.38

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2.24 | 68 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 2}, "one_way": false, "parking": 0, "speed": {"ob": 20}}` |
| 1.10 | 20 | LTS 1 -> 3 | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "1", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 2}, "one_way": false, "parking": 0, "speed": {"ob": 20}}` |
| 0.69 | 25 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "2", "oneway": "yes"}` | `{"lanes": "4", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": 12484, "bike": {}, "bike_ft": null, "lanes": {"ib": 0, "ob": 4}, "one_way": true, "parking": 0, "speed": {"ob": 20}}` |
| 0.35 | 3 | LTS 3 (same) | mixed traffic, 20 mph or below, single lane, arterial floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"cycleway:right": "no", "lanes": "1", "oneway": "yes"}` | `{"cycleway:right": "no", "lanes": "2", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 2}, "one_way": false, "parking": 0, "speed": {"ob": 20}}` |
| 0.20 | 5 | LTS 2 -> 3 | mixed traffic, 20 mph or below, single lane, high volume | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"cycleway": "separate", "lanes": "2", "parking:left": "no", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"cycleway": "separate", "lanes:backward": "2", "lanes:forward": "2", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 2}, "one_way": false, "parking": 3, "speed": {"ob": 20}}` |
| 0.19 | 2 | LTS 2 -> 3 | mixed traffic, 25 mph, single lane | mixed traffic, 20 mph or below, urban multilane, wide one-way floor | `{"maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 3}, "one_way": false, "parking": 0, "speed": {"ob": 20}}` |

### Minnesota Avenue Southeast: 4.93 mi, 98 ways

before LTS 1 0.01, LTS 2 0.97, LTS 3 3.96 | after LTS 1 0.75, LTS 2 0.19, LTS 3 3.99

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.96 | 21 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "5", "lanes:backward": "2", "lanes:forward": "3"}` | `{"lanes:backward": "3", "lanes:forward": "3", "maxspeed": "25 mph", "parking:both": "no"}` | `{"aadt": 11729, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 3}, "one_way": false, "parking": 0, "speed": {"ob": 25}}` |
| 0.58 | 2 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "1", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 8336, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 2}, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.52 | 7 | LTS 2 -> 1 | mixed traffic, 20 mph or below, single lane, high volume | separated track alongside | `{"cycleway": "separate", "lanes": "2", "maxspeed": "20 mph"}` | `{"cycleway:both": "track", "lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:left": "no", "parking:right": "parallel"}` | `{"aadt": 8336, "bike": {"ib": 3, "ob": 3}, "bike_ft": 4.5, "lanes": {"ib": 1, "ob": 1}, "one_way": false, "parking": 1, "speed": {"ob": 20}}` |
| 0.51 | 2 | LTS 3 (same) | mixed traffic, 20 mph or below, single lane, arterial floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "2"}` | `{"lanes:backward": "2", "lanes:forward": "2", "maxspeed": "25 mph", "parking:both": "parallel"}` | `{"aadt": 8336, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 2}, "one_way": false, "parking": 2, "speed": {"ob": 25}}` |
| 0.32 | 4 | LTS 3 (same) | mixed traffic, 20 mph or below, single lane, high volume, arterial floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "2"}` | `{"lanes:backward": "2", "lanes:forward": "2", "maxspeed": "20 mph", "parking:left": "no", "parking:right": "parallel"}` | `{"aadt": 8336, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 2}, "one_way": false, "parking": 1, "speed": {"ob": 20}}` |
| 0.20 | 2 | LTS 2 -> 3 | mixed traffic, 20 mph or below, single lane, mid volume | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "2"}` | `{"lanes:backward": "2", "lanes:forward": "2", "maxspeed": "20 mph", "parking:left": "no", "parking:right": "parallel"}` | `{"aadt": 3255, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 1}, "one_way": false, "parking": 1, "speed": {"ob": 20}}` |

### MacArthur Boulevard Northwest: 5.04 mi, 51 ways

before LTS 1 0.10, LTS 3 4.63, LTS 4 0.31 | after LTS 1 0.10, LTS 3 4.53, LTS 4 0.42

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3.34 | 21 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 11011, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 2}, "one_way": false, "parking": 2, "speed": {"ob": 25}}` |
| 0.63 | 6 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, two-way floor | mixed traffic, 20 mph or below, single lane, mid volume, arterial floor | `{"lanes": "4", "lanes:backward": "2", "lanes:forward": "2"}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": 6907, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 1}, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.22 | 1 | LTS 3 -> 4 | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane, two-way busy | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 11011, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 2}, "one_way": false, "parking": 2, "speed": {"ob": 30}}` |
| 0.16 | 2 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 20 mph or below, single lane, mid volume, arterial floor | `{"lanes": "4", "lanes:backward": "2", "lanes:forward": "2", "maxspeed": "25 mph"}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": 6907, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 1}, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.12 | 1 | LTS 4 -> 3 | mixed traffic, 30 mph, urban multilane, two-way busy | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes", "parking:both": "parallel"}` | `{"aadt": 11011, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 2}, "one_way": false, "parking": 2, "speed": {"ob": 25}}` |
| 0.10 | 1 | LTS 4 (same) | mixed traffic, 30 mph, urban multilane, two-way busy | mixed traffic, 30 mph, single lane, high volume | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": 11011, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 1}, "one_way": false, "parking": 0, "speed": {"ob": 30}}` |

### Kenilworth Avenue Northeast: 2.51 mi, 30 ways

before LTS 1 0.27, LTS 3 2.24 | after LTS 1 0.27, LTS 3 2.24

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.50 | 3 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 20 mph or below, single lane, arterial floor | `{"lanes": "1", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 0, "ob": 1}, "one_way": true, "parking": 0, "speed": {"ob": 20}}` |
| 0.40 | 4 | LTS 3 (same) | mixed traffic, 20 mph or below, single lane, arterial floor | mixed traffic, 20 mph or below, single lane, arterial floor | `{"lanes": "1", "maxspeed": "20 mph", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "20 mph", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 0}, "one_way": true, "parking": 0, "speed": {}}` |
| 0.30 | 3 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "1", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "25 mph", "oneway": "yes", "parking:left": "no", "parking:right": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 0}, "one_way": true, "parking": 1, "speed": {}}` |
| 0.27 | 2 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{"lanes": "2"}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 1}, "one_way": false, "parking": 2, "speed": {"ob": 20}}` |
| 0.26 | 2 | LTS 3 (same) | mixed traffic, 20 mph or below, single lane, arterial floor | mixed traffic, 20 mph or below, urban multilane, two-way floor | `{"lanes": "1", "oneway": "yes"}` | `{"lanes": "2", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 0}, "one_way": true, "parking": 0, "speed": {}}` |
| 0.22 | 2 | LTS 3 (same) | mixed traffic, 20 mph or below, urban multilane, high volume, arterial floor | mixed traffic, 20 mph or below, urban multilane, high volume, arterial floor | `{"lanes": "2", "oneway": "yes"}` | `{"lanes": "2", "oneway": "yes", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 2, "ob": 0}, "one_way": true, "parking": 0, "speed": {}}` |

### The US National Arboretum's internal roads

### Arboretum (roads and service ways in the grounds): 41.31 mi, 766 ways

before LTS 1 41.07, LTS 2 0.23 | after LTS 1 41.07, LTS 2 0.23

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 39.95 | 747 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{}` | `{}` | `not matched` |
| 1.13 | 8 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{"parking:both": "no"}` | `{"lanes:backward": "1", "lanes:forward": "1", "maxspeed": "20 mph", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {"ib": 1, "ob": 1}, "one_way": false, "parking": 0, "speed": {"ob": 20}}` |
| 0.22 | 10 | LTS 2 (same) | mixed traffic, 20 mph or below, single lane, high volume | mixed traffic, 20 mph or below, single lane, high volume | `{}` | `{}` | `not matched` |
| 0.01 | 1 | LTS 2 (same) | mixed traffic, 20 mph or below, single lane, mid volume | mixed traffic, 20 mph or below, single lane, mid volume | `{}` | `{}` | `not matched` |

## Baltimore examples

### Charles Street: 8.42 mi, 123 ways

before LTS 2 2.50, LTS 3 5.85, LTS 4 0.07 | after LTS 2 2.26, LTS 3 6.16

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 4.00 | 51 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "4", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"lanes": "4", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 1.36 | 6 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.90 | 16 | LTS 2 (same) | bike lane, narrow at 25 mph or below | bike lane, narrow at 25 mph or below | `{"cycleway:right": "lane", "cycleway:right:buffer": "yes", "lanes": "1", "maxspeed": "25 mph", "oneway": "yes", "parking:left": "no", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "yes", "lanes": "1", "maxspeed": "25 mph", "oneway": "yes", "parking:left": "no", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.61 | 15 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "2", "maxspeed": "25 mph"}` | `{"lanes": "2", "maxspeed": "25 mph"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.44 | 5 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 30 mph, urban multilane | `{"lanes": "4", "lanes:backward": "2", "lanes:forward": "2", "maxspeed": "25 mph"}` | `{"lanes": "4", "lanes:backward": "2", "lanes:forward": "2", "maxspeed": "30 mph"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 30}}` |
| 0.18 | 8 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"cycleway:right": "shared_lane", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"cycleway:right": "shared_lane", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |

### St Paul Street: 5.25 mi, 66 ways

before LTS 2 0.37, LTS 3 2.91, LTS 4 1.96 | after LTS 2 0.37, LTS 3 2.91, LTS 4 1.97

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.94 | 12 | LTS 4 (same) | mixed traffic, 35 mph or above | mixed traffic, 35 mph or above | `{"lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 35}}` |
| 1.54 | 17 | LTS 3 (same) | bike lane, narrow or multilane at 30 mph | bike lane, narrow or multilane at 30 mph | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "2", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "2", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 1.30 | 24 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "3", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.37 | 3 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"maxspeed": "25 mph", "oneway": "yes", "parking:both:fee": "yes", "parking:both:maxstay": "4 hours", "parking:left": "street_side", "parking:left:orientation": "parallel", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"maxspeed": "25 mph", "oneway": "yes", "parking:both:fee": "yes", "parking:both:maxstay": "4 hours", "parking:left": "street_side", "parking:left:orientation": "parallel", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.05 | 4 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"cycleway:right": "shared_lane", "lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"cycleway:right": "shared_lane", "lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `not matched` |
| 0.02 | 3 | LTS 4 (same) | mixed traffic, 35 mph or above | mixed traffic, 35 mph or above | `{"lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `not matched` |

### North Avenue: 7.66 mi, 171 ways

before LTS 2 0.30, LTS 3 7.37 | after LTS 2 0.30, LTS 3 7.37

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 6.67 | 140 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "3", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.30 | 2 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.23 | 7 | LTS 3 (same) | mixed traffic, 30 mph, single lane | mixed traffic, 30 mph, single lane | `{"maxspeed": "30 mph", "oneway": "yes"}` | `{"maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.22 | 14 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "4", "maxspeed": "30 mph"}` | `{"lanes": "4", "maxspeed": "30 mph"}` | `not matched` |
| 0.16 | 4 | LTS 3 (same) | bike lane, narrow or multilane at 30 mph | bike lane, narrow or multilane at 30 mph | `{"cycleway:both": "lane", "cycleway:both:buffer": "no", "lanes": "4", "maxspeed": "30 mph", "parking:both": "no"}` | `{"cycleway:both": "lane", "cycleway:both:buffer": "no", "lanes": "4", "maxspeed": "30 mph", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 30}}` |
| 0.07 | 3 | LTS 3 (same) | mixed traffic, 30 mph, single lane | mixed traffic, 30 mph, single lane | `{"lanes": "1", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "30 mph", "oneway": "yes"}` | `not matched` |

### Maryland Avenue: 1.48 mi, 19 ways

before LTS 2 0.98, LTS 3 0.50 | after LTS 2 1.45, LTS 3 0.03

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.92 | 13 | LTS 2 (same) | mixed traffic, 25 mph, urban multilane | mixed traffic, 25 mph, urban multilane | `{"cycleway:left": "separate", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"cycleway:left": "separate", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.47 | 3 | LTS 3 -> 2 | mixed traffic, 30 mph, single lane | mixed traffic, 25 mph, single lane | `{"cycleway:left": "separate", "lanes": "1", "maxspeed": "30 mph", "oneway": "yes"}` | `{"cycleway:left": "separate", "lanes": "1", "maxspeed": "25 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.06 | 2 | LTS 2 (same) | bike lane, narrow at 25 mph or below | bike lane, narrow at 25 mph or below | `{"cycleway:left": "lane", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"cycleway:left": "lane", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.03 | 1 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, wide one-way floor | mixed traffic, 25 mph, urban multilane, wide one-way floor | `{"lanes": "3", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "25 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |

### Fort Avenue: 2.26 mi, 27 ways

before LTS 1 0.37, LTS 2 1.74, LTS 3 0.15 | after LTS 1 0.37, LTS 2 1.74, LTS 3 0.15

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.09 | 15 | LTS 2 (same) | bike lane, narrow at 25 mph or below | bike lane, narrow at 25 mph or below | `{"cycleway:both": "lane", "cycleway:both:buffer": "no", "lanes": "2", "maxspeed": "25 mph", "parking:both": "no"}` | `{"cycleway:both": "lane", "cycleway:both:buffer": "no", "lanes": "2", "maxspeed": "25 mph", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.63 | 7 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.37 | 1 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{}` | `{}` | `not matched` |
| 0.14 | 2 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"cycleway": "shared_lane", "lanes": "3", "lanes:backward": "2", "lanes:forward": "1", "maxspeed": "25 mph", "oneway": "no"}` | `{"cycleway": "shared_lane", "lanes": "3", "lanes:backward": "2", "lanes:forward": "1", "maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.02 | 1 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"maxspeed": "25 mph", "oneway": "no"}` | `not matched` |
| 0.02 | 1 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"cycleway": "shared_lane", "lanes": "4", "maxspeed": "25 mph", "oneway": "no"}` | `{"cycleway": "shared_lane", "lanes": "4", "maxspeed": "25 mph", "oneway": "no"}` | `not matched` |

### Key Highway: 2.76 mi, 41 ways

before LTS 3 2.76 | after LTS 3 2.76

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2.71 | 33 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.05 | 8 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `not matched` |

### Pratt Street: 5.04 mi, 68 ways

before LTS 2 1.35, LTS 3 3.68 | after LTS 1 0.20, LTS 2 1.15, LTS 3 3.68

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2.58 | 38 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 1.15 | 10 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.58 | 9 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, wide one-way floor | mixed traffic, 25 mph, urban multilane, wide one-way floor | `{"lanes": "3", "maxspeed": "25 mph", "oneway": "yes", "parking:condition:left": "free", "parking:left": "yes", "parking:left:orientation": "parallel", "parking:right": "no", "parking:right:restriction": "no_stopping"}` | `{"lanes": "3", "maxspeed": "25 mph", "oneway": "yes", "parking:condition:left": "free", "parking:left": "yes", "parking:left:orientation": "parallel", "parking:right": "no", "parking:right:restriction": "no_stopping"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.48 | 7 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no", "parking:condition:both": "free", "parking:lane:both": "parallel"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no", "parking:condition:both": "free", "parking:lane:both": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.20 | 1 | LTS 2 -> 1 | mixed traffic, 25 mph, single lane | mixed traffic, 20 mph or below, single lane | `{"lanes": "1", "maxspeed": "25 mph", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "15 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 15}}` |
| 0.03 | 2 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "4", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "4", "maxspeed": "30 mph", "oneway": "yes"}` | `not matched` |

### Eastern Avenue: 6.15 mi, 129 ways

before LTS 1 0.20, LTS 2 0.18, LTS 3 3.19, LTS 4 2.58 | after LTS 2 0.38, LTS 3 3.04, LTS 4 2.72

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2.28 | 60 | LTS 4 (same) | mixed traffic, 35 mph or above | mixed traffic, 35 mph or above | `{"lanes": "3", "maxspeed": "35 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "35 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 35}}` |
| 1.67 | 21 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.71 | 11 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "4", "maxspeed": "25 mph", "oneway": "no"}` | `{"lanes": "4", "maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.45 | 3 | LTS 3 (same) | mixed traffic, 20 mph or below, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"cycleway": "no", "lanes": "2", "maxspeed": "20 mph", "oneway": "no", "parking:both": "lane", "parking:both:orientation": "parallel", "parking:condition:both": "free"}` | `{"cycleway": "no", "lanes": "2", "maxspeed": "25 mph", "oneway": "no", "parking:both": "lane", "parking:both:orientation": "parallel", "parking:condition:both": "free"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.30 | 11 | LTS 4 (same) | mixed traffic, 35 mph or above | mixed traffic, 35 mph or above | `{"lanes": "3", "maxspeed": "35 mph", "oneway": "yes"}` | `{"lanes": "3", "maxspeed": "35 mph", "oneway": "yes"}` | `not matched` |
| 0.20 | 4 | LTS 1 -> 2 | mixed traffic, 20 mph or below, single lane | mixed traffic, 25 mph, single lane | `{"maxspeed": "20 mph", "oneway": "no"}` | `{"maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |

### Falls Road: 5.16 mi, 68 ways

before LTS 3 5.16 | after LTS 3 5.16

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.50 | 15 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "5", "lanes:backward": "3", "lanes:forward": "2", "maxspeed": "30 mph"}` | `{"lanes": "5", "lanes:backward": "3", "lanes:forward": "2", "maxspeed": "30 mph"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 30}}` |
| 1.22 | 14 | LTS 3 (same) | mixed traffic, 30 mph, single lane | mixed traffic, 30 mph, single lane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "no"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 30}}` |
| 0.95 | 11 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "4", "lanes:backward": "2", "lanes:forward": "2", "maxspeed": "25 mph"}` | `{"lanes": "4", "lanes:backward": "2", "lanes:forward": "2", "maxspeed": "25 mph"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.74 | 7 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.33 | 4 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, arterial floor | mixed traffic, 25 mph, urban multilane, arterial floor | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes", "parking:left": "no", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes", "parking:left": "no", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.17 | 4 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "3", "lanes:backward": "1", "lanes:forward": "2", "maxspeed": "30 mph", "oneway": "no"}` | `{"lanes": "3", "lanes:backward": "1", "lanes:forward": "2", "maxspeed": "25 mph", "oneway": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |

### Roland Avenue: 5.32 mi, 86 ways

before LTS 2 4.30, LTS 3 1.02 | after LTS 2 1.81, LTS 3 3.51

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2.48 | 47 | LTS 2 -> 3 | bike lane, narrow at 25 mph or below | bike lane, narrow or multilane at 30 mph | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.99 | 11 | LTS 3 (same) | bike lane, 35 mph | bike lane, 35 mph | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 35}}` |
| 0.85 | 10 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"lanes": "2", "maxspeed": "25 mph", "parking:both": "no"}` | `{"lanes": "2", "maxspeed": "25 mph", "parking:both": "no"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.72 | 4 | LTS 2 (same) | bike lane, narrow at 25 mph or below | bike lane, narrow at 25 mph or below | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.14 | 1 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"lanes": "2", "oneway": "no"}` | `{"lanes": "2", "oneway": "no"}` | `not matched` |
| 0.10 | 10 | LTS 2 (same) | bike lane, narrow at 25 mph or below | bike lane, narrow at 25 mph or below | `{"cycleway:right": "lane", "cycleway:right:buffer": "yes", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "yes", "lanes": "2", "maxspeed": "25 mph", "oneway": "yes", "parking:right": "lane", "parking:right:orientation": "parallel"}` | `not matched` |

### Greenmount Avenue: 3.05 mi, 26 ways

before LTS 1 0.09, LTS 3 2.97 | after LTS 1 0.09, LTS 3 2.97

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.58 | 16 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "4", "maxspeed": "25 mph"}` | `{"lanes": "4", "maxspeed": "25 mph"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 1.34 | 6 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "2", "lanes:backward": "1", "lanes:forward": "1", "maxspeed": "25 mph", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"lanes": "2", "lanes:backward": "1", "lanes:forward": "1", "maxspeed": "25 mph", "parking:both": "lane", "parking:both:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.09 | 2 | LTS 1 (same) | mixed traffic, 20 mph or below, single lane | mixed traffic, 20 mph or below, single lane | `{}` | `{}` | `not matched` |
| 0.05 | 2 | LTS 3 (same) | mixed traffic, 25 mph, urban multilane, two-way floor | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "4", "maxspeed": "25 mph", "oneway": "no"}` | `{"lanes": "4", "maxspeed": "25 mph", "oneway": "no"}` | `not matched` |

### Boston Street: 4.52 mi, 114 ways

before LTS 3 4.38, LTS 4 0.14 | after LTS 3 4.38, LTS 4 0.14

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2.58 | 77 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "3", "lanes:backward": "2", "lanes:forward": "1", "maxspeed": "30 mph", "parking:both": "yes", "parking:both:orientation": "parallel", "parking:condition:both": "free", "parking:condition:both:time_interval": "00:00-24:00; Mo-Fr 07:00-09:00 off"}` | `{"lanes": "3", "lanes:backward": "2", "lanes:forward": "1", "maxspeed": "30 mph", "parking:both": "yes", "parking:both:orientation": "parallel", "parking:condition:both": "free", "parking:condition:both:time_interval": "00:00-24:00; Mo-Fr 07:00-09:00 off"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 30}}` |
| 1.17 | 9 | LTS 3 (same) | bike lane, 35 mph | bike lane, 35 mph | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "1", "maxspeed": "35 mph", "oneway": "yes", "oneway:bicycle": "yes", "parking:right": "yes", "parking:right:orientation": "parallel"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "1", "maxspeed": "35 mph", "oneway": "yes", "oneway:bicycle": "yes", "parking:right": "yes", "parking:right:orientation": "parallel"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 35}}` |
| 0.37 | 8 | LTS 3 (same) | mixed traffic, 30 mph, single lane | mixed traffic, 30 mph, single lane | `{"lanes": "1", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "no", "parking:both:restriction": "no_stopping"}` | `{"lanes": "1", "maxspeed": "30 mph", "oneway": "yes", "parking:both": "no", "parking:both:restriction": "no_stopping"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.24 | 16 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"cycleway:right": "shared_lane", "lanes": "2", "maxspeed": "30 mph", "oneway": "yes", "parking:condition:right": "free", "parking:condition:right:time_interval": "00:00-24:00; Mo-Fr 07:00-09:00 off", "parking:left": "no", "parking:left:restriction": "no_stopping", "parking:right": "yes", "parking:right:orientation": "parallel"}` | `{"cycleway:right": "shared_lane", "lanes": "2", "maxspeed": "30 mph", "oneway": "yes", "parking:condition:right": "free", "parking:condition:right:time_interval": "00:00-24:00; Mo-Fr 07:00-09:00 off", "parking:left": "no", "parking:left:restriction": "no_stopping", "parking:right": "yes", "parking:right:orientation": "parallel"}` | `not matched` |
| 0.13 | 2 | LTS 4 (same) | mixed traffic, 35 mph or above | mixed traffic, 35 mph or above | `{"cycleway:right": "shared_lane", "lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `{"cycleway:right": "shared_lane", "lanes": "2", "maxspeed": "35 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 35}}` |
| 0.01 | 1 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "3", "lanes:backward": "1", "lanes:forward": "2", "maxspeed": "30 mph", "maxspeed:lanes:backward": "30 mph", "maxspeed:lanes:forward": "30 mph|30 mph"}` | `{"lanes": "3", "lanes:backward": "1", "lanes:forward": "2", "maxspeed": "25 mph", "maxspeed:lanes:backward": "30 mph", "maxspeed:lanes:forward": "30 mph|30 mph"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |

### Guilford Avenue: 2.92 mi, 50 ways

before LTS 1 0.01, LTS 2 1.70, LTS 3 1.21 | after LTS 2 1.70, LTS 3 1.22

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.70 | 22 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"lanes": "2", "maxspeed": "25 mph"}` | `{"lanes": "2", "maxspeed": "25 mph"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.67 | 14 | LTS 3 (same) | bike lane, narrow or multilane at 30 mph | bike lane, narrow or multilane at 30 mph | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "3", "maxspeed": "30 mph", "oneway": "yes"}` | `{"cycleway:right": "lane", "cycleway:right:buffer": "no", "lanes": "3", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.47 | 11 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.07 | 2 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `not matched` |
| 0.01 | 1 | LTS 1 -> 3 | mixed traffic, 20 mph or below, single lane | mixed traffic, 30 mph, single lane | `{"oneway": "yes"}` | `{"maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |

### Druid Park Lake Drive: 3.24 mi, 53 ways

before LTS 2 0.27, LTS 3 2.97 | after LTS 2 0.25, LTS 3 2.99

| miles | ways | tier | rule before | rule after | tags before | tags after | agency facts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.15 | 29 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.76 | 4 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 25 mph, urban multilane, two-way floor | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "25 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 25}}` |
| 0.55 | 6 | LTS 3 (same) | mixed traffic, 30 mph, single lane | mixed traffic, 30 mph, single lane | `{"lanes": "1", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "1", "maxspeed": "30 mph", "oneway": "yes"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": true, "parking": null, "speed": {"centerline": 30}}` |
| 0.41 | 3 | LTS 3 (same) | mixed traffic, 25 mph, single lane, arterial floor | mixed traffic, 25 mph, single lane, arterial floor | `{"lanes": "2", "maxspeed": "25 mph"}` | `{"lanes": "2", "maxspeed": "25 mph"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.24 | 3 | LTS 2 (same) | mixed traffic, 25 mph, single lane | mixed traffic, 25 mph, single lane | `{"lanes": "1", "maxspeed": "25 mph"}` | `{"lanes": "1", "maxspeed": "25 mph"}` | `{"aadt": null, "bike": {}, "bike_ft": null, "lanes": {}, "one_way": null, "parking": null, "speed": {"centerline": 25}}` |
| 0.04 | 4 | LTS 3 (same) | mixed traffic, 30 mph, urban multilane | mixed traffic, 30 mph, urban multilane | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `{"lanes": "2", "maxspeed": "30 mph", "oneway": "yes"}` | `not matched` |
