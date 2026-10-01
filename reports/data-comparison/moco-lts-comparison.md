# Our tier against Montgomery County Planning's Bicycle Level of Traffic Stress

Source: Montgomery County Planning Department, "Bicycle Level of Traffic Stress" (ArcGIS item fb903d1ffbc84b219bdb47629bd02b82), retrieved 2026-10-01; attribution: Montgomery County Planning Department. Our tier is the integration branch's classifier (33ff4da) on the 2026-09-25 extract, before the Roadway Block and Baltimore conflations (neither touches Montgomery County).

## Are LTS 3 and LTS 4 separate? (OWNER-DECISIONS 149)

Yes. The layer's existing-condition field `LTS_EXIST` takes the values below on its 59,148 records; 3 and 4 are separate levels, and so is 5 ("Very High"). It also has half levels: 0.5 ("None", not a road a bicycle is rated on) and 2.5 ("Moderate Low").

| LTS_EXIST | records |
| --- | --- |
| 0.5 | 2,027 |
| 1 | 35,647 |
| 2 | 8,202 |
| 2.5 | 2,083 |
| 3 | 5,075 |
| 4 | 4,953 |
| 5 | 1,161 |

Used: existing records of roads (47,112); left out: 5,915 sidepath or trail record, 5,544 parking lot or trail, 558 not existing, 19 no LTS (0.5 'None'). Sidepaths and trails are left out because they lie beside the road they follow and would take its probes; the road's own record is the one that rates the road.

## Match

16,982 OSM road ways in Maryland lie along a Montgomery record (3,039 mi). A way along several records takes the level of the one it lies along most (`mixed` ways are 16% of the miles).

* Same level: 28.3% of miles; within half a level (2.5 against 2 or 3): 30.6%; within one level: 96.3%.
* Ours higher than MoCo's: 60.5%; ours lower: 11.3%.

## Confusion matrix

| miles: our LTS (rows) / MoCo LTS (columns) | 1 | 2 | 2.5 | 3 | 4 | 5 | total |
| --- | --- | --- | --- | --- | --- | --- | --- |
| our LTS 1 | 35.9 | 9.0 | 1.6 | 1.6 | 1.4 | 0.0 | 49.5 |
| our LTS 2 | 1558.5 | 238.2 | 52.9 | 34.4 | 24.2 | 0.0 | 1908.1 |
| our LTS 3 | 14.9 | 103.5 | 18.3 | 196.8 | 123.3 | 3.6 | 460.4 |
| our LTS 4 | 27.1 | 35.3 | 2.5 | 74.6 | 367.7 | 90.4 | 597.7 |
| our LTS 5 | 0.0 | 0.0 | 0.0 | 0.0 | 2.8 | 20.6 | 23.4 |
| total | 1636.4 | 386.0 | 75.2 | 307.4 | 519.4 | 114.6 | 3039.1 |

## By OSM road class

| OSM class | miles | equal | ours higher than MoCo | ours lower than MoCo |
| --- | --- | --- | --- | --- |
| residential | 1904.1 | 13% | 82% | 5% |
| tertiary | 440.2 | 45% | 35% | 20% |
| primary | 310.7 | 64% | 6% | 31% |
| secondary | 263.2 | 67% | 21% | 12% |
| unclassified | 60.6 | 21% | 75% | 4% |
| trunk | 36.4 | 65% | 0% | 35% |
| service | 10.5 | 28% | 2% | 70% |
| primary_link | 8.0 | 41% | 31% | 28% |
| motorway_link | 1.8 | 14% | 26% | 60% |
| track | 1.1 | 92% | 0% | 8% |
| trunk_link | 1.1 | 26% | 30% | 45% |
| secondary_link | 0.7 | 54% | 39% | 7% |
| tertiary_link | 0.5 | 50% | 30% | 20% |
| living_street | 0.1 | 0% | 0% | 100% |

## Top 50 disagreements

Grouped by street and the pair of levels, ranked by miles times the gap. `our rule` is the classifier's reason for the most of the group's miles.

| # | street | OSM class | miles | ours | theirs | our rule | example ways |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Berryville Road | unclassified | 3.49 | LTS 4 | MoCo LTS 1 | mixed traffic, 35 mph or above | 5990773, 1519880224, 1519880225 |
| 2 | West Old Baltimore Road | tertiary | 3.43 | LTS 4 | MoCo LTS 1 | mixed traffic, 35 mph or above | 5978517, 943929253 |
| 3 | Davis Mill Road | tertiary | 3.35 | LTS 4 | MoCo LTS 1 | mixed traffic, 35 mph or above | 5970748, 166548489 |
| 4 | Martinsburg Road | unclassified | 4.70 | LTS 4 | MoCo LTS 2 | mixed traffic, 35 mph or above | 5973112, 369917211, 369917212 |
| 5 | Darnestown Road | primary | 9.23 | LTS 4 | MoCo LTS 5 | mixed traffic, 35 mph or above | 5970658, 92183771, 92183773 |
| 6 | Edwards Ferry Road | unclassified | 4.30 | LTS 4 | MoCo LTS 2 | mixed traffic, 35 mph or above | 5974809, 1520783390, 1520783391 |
| 7 | River Road | unclassified | 4.30 | LTS 3 | MoCo LTS 1 | mixed traffic, 30 mph, single lane | 5968812, 5968819, 435722560 |
| 8 | White Ground Road | tertiary | 2.81 | LTS 4 | MoCo LTS 1 | mixed traffic, 35 mph or above | 5971451, 552608220 |
| 9 | Georgia Avenue | primary | 8.32 | LTS 3 | MoCo LTS 4 | mixed traffic, 30 mph, urban multilane | 50832834, 69194540, 92148125 |
| 10 | Hughes Road | tertiary | 4.03 | LTS 4 | MoCo LTS 2 | mixed traffic, 35 mph or above | 369053095 |
| 11 | Georgia Avenue | primary | 7.56 | LTS 4 | MoCo LTS 5 | mixed traffic, 35 mph or above | 101252574, 101252589, 101252598 |
| 12 | Hawkins Creamery Road | residential | 3.49 | LTS 2 | MoCo LTS 4 | mixed traffic, 25 mph, single lane | 5976768, 1511731590, 1511731591 |
| 13 | Frederick Road | primary | 6.73 | LTS 4 | MoCo LTS 5 | mixed traffic, 35 mph or above | 27029596, 53335029, 130576281 |
| 14 | (unnamed) | residential | 6.54 | LTS 2 | MoCo LTS 1 | mixed traffic, 25 mph, single lane | 5964027, 5964047, 5964937 |
| 15 | Elmer School Road | residential | 3.19 | LTS 2 | MoCo LTS 4 | mixed traffic, 25 mph, single lane | 5968951 |
| 16 | Mouth of Monocacy Road | unclassified | 2.06 | LTS 4 | MoCo LTS 1 | mixed traffic, 35 mph or above | 5967878, 97908455, 97908480 |
| 17 | River Road | tertiary | 5.99 | LTS 4 | MoCo LTS 5 | mixed traffic, 35 mph or above | 131947862, 137131984, 137131993 |
| 18 | Howard Chapel Road | unclassified | 1.93 | LTS 4 | MoCo LTS 1 | mixed traffic, 35 mph or above | 5270050, 5972103, 92341636 |
| 19 | Wildcat Road | tertiary | 1.91 | LTS 4 | MoCo LTS 1 | mixed traffic, 35 mph or above | 5971359, 1076445873, 1076445874 |
| 20 | Ridge Road | trunk | 5.54 | LTS 3 | MoCo LTS 4 | bike lane, decent, 40 mph: a tier below mixed traffic | 50832482, 50832483, 130467971 |
| 21 | Sligo Creek Parkway | tertiary | 5.52 | LTS 2 | MoCo LTS 3 | mixed traffic, 25 mph, single lane | 5988543, 42564818, 50030477 |
| 22 | Wasche Road | residential | 2.70 | LTS 2 | MoCo LTS 4 | mixed traffic, 25 mph, single lane | 5975640 |
| 23 | Airpark Road | tertiary | 2.62 | LTS 3 | MoCo LTS 5 | mixed traffic, 30 mph, single lane | 5969483, 76699119, 76699122 |
| 24 | New Hampshire Avenue | primary | 5.02 | LTS 4 | MoCo LTS 5 | mixed traffic, 35 mph or above | 65251236, 130467951, 130467953 |
| 25 | Ridge Road | trunk | 4.88 | LTS 4 | MoCo LTS 5 | mixed traffic, 35 mph or above | 5977844, 5977852, 50832512 |
| 26 | Kings Valley Road | tertiary | 1.60 | LTS 4 | MoCo LTS 1 | mixed traffic, 35 mph or above | 5978711, 1160957537, 1549213927 |
| 27 | Schaeffer Road | tertiary | 2.35 | LTS 4 | MoCo LTS 2 | mixed traffic, 35 mph or above | 156554755, 456131685, 456131686 |
| 28 | (unnamed) | unclassified | 2.28 | LTS 4 | MoCo LTS 2 | mixed traffic, 35 mph or above | 97523046, 101370045, 102607550 |
| 29 | West Offutt Road | unclassified | 2.22 | LTS 4 | MoCo LTS 2 | mixed traffic, 35 mph or above | 5984122, 5984126 |
| 30 | Brighton Dam Road | secondary | 2.22 | LTS 4 | MoCo LTS 2 | mixed traffic, 35 mph or above | 5968279, 5968280, 405836481 |
| 31 | Lewisdale Road | tertiary | 2.21 | LTS 4 | MoCo LTS 2 | mixed traffic, 35 mph or above | 5985981 |
| 32 | East Village Avenue | tertiary | 4.36 | LTS 3 | MoCo LTS 4 | mixed traffic, 30 mph, single lane | 5978274, 76700238, 697338073 |
| 33 | Travilah Road | secondary | 4.31 | LTS 4 | MoCo LTS 3 | mixed traffic, 35 mph or above | 5981022, 5981025, 342660840 |
| 34 | River Road | unclassified | 1.42 | LTS 4 | MoCo LTS 1 | mixed traffic, 35 mph or above | 358267975, 358267976, 1137073602 |
| 35 | Norbeck Road | primary | 4.25 | LTS 4 | MoCo LTS 5 | mixed traffic, 35 mph or above | 10820989, 51459227, 92186746 |
| 36 | Blunt Road | tertiary | 1.42 | LTS 4 | MoCo LTS 1 | mixed traffic, 35 mph or above | 5967102, 997041276, 997041277 |
| 37 | West Harris Road | unclassified | 2.08 | LTS 3 | MoCo LTS 1 | mixed traffic, 30 mph, single lane | 349215249, 369738971, 369738972 |
| 38 | Glen Road | secondary | 4.15 | LTS 4 | MoCo LTS 3 | mixed traffic, 35 mph or above | 5990191, 5990192, 5990195 |
| 39 | Shiloh Church Road | residential | 2.02 | LTS 2 | MoCo LTS 4 | mixed traffic, 25 mph, single lane | 5989308 |
| 40 | Hipsley Mill Road | tertiary | 1.97 | LTS 4 | MoCo LTS 2 | mixed traffic, 35 mph or above | 5975659, 92341550 |
| 41 | Old Columbia Pike | secondary | 3.92 | LTS 4 | MoCo LTS 3 | mixed traffic, 35 mph or above | 5971978, 5971980, 73325072 |
| 42 | Burnt Hill Road | residential | 1.94 | LTS 2 | MoCo LTS 4 | mixed traffic, 25 mph, single lane | 121782823, 121782824, 121852644 |
| 43 | Bethesda Church Road | tertiary | 3.83 | LTS 4 | MoCo LTS 3 | mixed traffic, 35 mph or above | 5972865 |
| 44 | (unnamed) | primary_link | 3.75 | LTS 4 | MoCo LTS 5 | mixed traffic, 35 mph or above | 5964497, 5966063, 5973481 |
| 45 | West Willard Road | tertiary | 1.87 | LTS 4 | MoCo LTS 2 | mixed traffic, 35 mph or above | 896842109 |
| 46 | Seven Locks Road | secondary | 3.68 | LTS 4 | MoCo LTS 3 | mixed traffic, 35 mph or above | 5966452, 26662367, 26662371 |
| 47 | Veirs Mill Road | primary | 3.63 | LTS 4 | MoCo LTS 5 | mixed traffic, 35 mph or above | 128574906, 128574914, 128574915 |
| 48 | Howard Chapel Drive | residential | 1.74 | LTS 2 | MoCo LTS 4 | mixed traffic, 25 mph, single lane | 5990097 |
| 49 | Observation Drive | tertiary | 3.46 | LTS 3 | MoCo LTS 4 | mixed traffic, 30 mph, single lane | 99663691, 100102594, 334875148 |
| 50 | Piney Meetinghouse Road | secondary | 3.41 | LTS 4 | MoCo LTS 3 | mixed traffic, 35 mph or above | 5970502, 5970503, 368679965 |
