# Baltimore: the city's bike facilities and trails against OSM

Sources, all open-licensed by Baltimore City Code Art. 1 §9-1(h) (OWNER-DECISIONS 159), credit "City of Baltimore, Open Baltimore": DOT BMC Bike Facilities (item dbef46a0caf948debba8516f0d95fe4c; 184 mi of existing facilities, `STATUS1` 4) and Multiuse Trails (item 34260bfb3df74d3994e0c73fde47630b; proposed trails, `mainSpur` of Future Alignment, were excluded at the query). Retrieved 2026-10-01.

## Facilities the city records on roads, and what OSM has on the matched way

| city facility type | city miles | OSM way already tagged | candidates (miles) |
| --- | --- | --- | --- |
| Path or Sidepath | 47.0 | (a separate way; checked below) | 0.0 |
| Bike Lane | 37.9 | 35.3 mi | 4.6 |
| Shared Lane Markings | 34.4 | 12.9 mi | 21.4 |
| Signed Bike Route | 21.3 | 20.5 mi | 0.0 |
| Separated Bike Lane | 19.3 | 10.3 mi | 11.5 |
| Shared Bus-Bike Lane | 11.3 | 10.2 mi | 2.0 |
| Buffered Bike Lane | 5.9 | 5.2 mi | 1.3 |
| Bike Boulevard | 5.6 | 5.4 mi | 0.0 |
| Contraflow Bike Lane | 0.8 | 0.8 mi | 0.0 |

A *candidate* is an OSM road way lying along a city facility whose own tags carry no cycleway of the kind the city records (a lane for a bike lane, buffered lane or contraflow lane; a track or a `cycleway=separate` for a separated lane). `Signed Bike Route` and `Bike Boulevard` are routes, which OSM carries on relations and the classifier does not credit, so they are not candidates. `Path or Sidepath` is a separate way and is checked below.

### Roads whose bike lane or track OSM lacks (top 60 by miles)

| street | city facility | OSM class | OSM cycleway | miles | our tier | tier with the facility | ways |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HARFORD RD | Separated Bike Lane | primary | none | 1.60 | LTS 3 | LTS 1 | 178254354, 178254356, 178254358 |
| DRUID PARK LAKE DR | Separated Bike Lane | secondary | none | 1.15 | LTS 3 | LTS 1 | 6000701, 423400502, 423400503 |
| W MOUNT ROYAL AVE | Separated Bike Lane | secondary | none | 0.89 | LTS 3 | LTS 1 | 6004710, 48001165, 48001167 |
| ST LO DR | Separated Bike Lane | unclassified | none | 0.63 | LTS 3 | LTS 3 | 6007365, 380458640, 380458641 |
| GREENSPRING AVE | Separated Bike Lane | secondary | lane | 0.60 | LTS 3 | LTS 1 | 6019126, 213559205, 544896745 |
| ANNAPOLIS RD | Separated Bike Lane | secondary | none | 0.58 | LTS 3 | LTS 1 | 47999125, 422243516, 425107400 |
| CHESAPEAKE AVE | Buffered Bike Lane | unclassified | none | 0.55 | LTS 2 | LTS 2 | 6009864 |
| GREENSPRING AVE | Bike Lane | secondary | separate | 0.55 | LTS 2 | LTS 2 | 188164049, 947541482, 1558383598 |
| W NORTH AVE | Separated Bike Lane | primary | none | 0.47 | LTS 3 | LTS 1 | 11946018, 69531096, 113296957 |
| N CHARLES ST | Buffered Bike Lane | residential | none | 0.46 | LTS 2 | LTS 2 | 132381956, 532516429, 1062922431 |
| HARFORD RD | Separated Bike Lane | primary | none | 0.44 | LTS 3 | LTS 3 | 178254357, 178254361, 178254376 |
| E 39TH ST | Separated Bike Lane | secondary | lane | 0.39 | LTS 2 | LTS 1 | 110351411, 817738138, 852324512 |
| SAINT PAUL ST | Bike Lane | residential | none | 0.37 | LTS 2 | LTS 2 | 455277309, 455277310, 522343538 |
| WABASH AVE | Bike Lane | primary | none | 0.35 | LTS 3 | LTS 2 | 237887546, 425003410, 425184573 |
| W CENTRE ST | Separated Bike Lane | secondary | none | 0.32 | LTS 3 | LTS 1 | 6010257, 98117561, 98117562 |
| WALTHER AVE | Bike Lane | secondary | shared_lane | 0.31 | LTS 3 | LTS 3 | 424990152, 424993025, 424993026 |
| E CROMWELL ST | Separated Bike Lane | tertiary | none | 0.31 | LTS 3 | LTS 1 | 103285172, 548444091, 1052925414 |
| W UNIVERSITY PKWY | Separated Bike Lane | primary | lane | 0.27 | LTS 3 | LTS 1 | 107295920, 107295924, 107295928 |
| ARGONNE DR | Separated Bike Lane | secondary | lane | 0.25 | LTS 3 | LTS 1 | 51535573, 302003633, 948676226 |
| LIBERTY HEIGHTS AVE | Separated Bike Lane | tertiary | none | 0.24 | LTS 3 | LTS 1 | 10426297, 89385453, 425185517 |
| E CENTRE ST | Separated Bike Lane | secondary | none | 0.23 | LTS 3 | LTS 1 | 6010027, 98289479, 132521360 |
| WASHINGTON BLVD | Bike Lane | residential | none | 0.22 | LTS 2 | LTS 2 | 98289504, 127068499, 332701004 |
| COVINGTON ST | Separated Bike Lane | residential | none | 0.22 | LTS 2 | LTS 1 | 275828165, 452789362 |
| E 20TH ST | Separated Bike Lane | residential | -1,lane,shared_lane | 0.20 | LTS 2 | LTS 2 | 6019053, 225157507, 1156356326 |
| SAINT PAUL ST | Bike Lane | primary | shared_lane | 0.20 | LTS 3 | LTS 3 | 11961372, 69531013, 69531020 |
| N PACA ST | Separated Bike Lane | primary | lane | 0.17 | LTS 4 | LTS 1 | 115240292, 125568092, 1088485663 |
| W OSTEND ST | Bike Lane | residential | none | 0.16 | LTS 2 | LTS 2 | 26953224, 132521551, 606165664 |
| DUNDALK AVE | Bike Lane | primary_link | none | 0.15 | LTS 4 | LTS 3 | 75091528, 244059642 |
| FREDERICK AVE | Bike Lane | unclassified | none | 0.15 | LTS 3 | LTS 3 | 1070086186 |
| GREENSPRING AVE | Bike Lane | secondary | shared_lane | 0.14 | LTS 3 | LTS 3 | 87914008, 424992206, 605726735 |
| S PRESIDENT ST | Separated Bike Lane | primary | none | 0.13 | LTS 4 | LTS 1 | 113296956, 424997835 |
| W MCCOMAS ST | Separated Bike Lane | unclassified | none | 0.13 | LTS 3 | LTS 1 | 1163650052, 1163650059 |
| DRUID PARK LAKE DR | Separated Bike Lane | tertiary | none | 0.13 | LTS 2 | LTS 2 | 500547204, 581464220, 966518030 |
| GUILFORD AVE | Bike Lane | secondary | none | 0.12 | LTS 3 | LTS 3 | 132521405 |
| E MOUNT ROYAL AVE | Separated Bike Lane | secondary | none | 0.12 | LTS 3 | LTS 1 | 6007428, 399096870, 930214277 |
| CAROLINE ST | Separated Bike Lane | tertiary | none | 0.11 | LTS 2 | LTS 1 | 586050815 |
| W CHASE ST | Separated Bike Lane | secondary | none | 0.11 | LTS 3 | LTS 1 | 6005658, 98144290, 548197600 |
| W NORTH AVE | Separated Bike Lane | primary | share_busway | 0.11 | LTS 3 | LTS 1 | 69531102, 431328173, 542295864 |
| OLD FREDERICK ROAD | Bike Lane | residential | shared_lane | 0.11 | LTS 2 | LTS 2 | 1047732641, 1047732649, 1047732650 |
| BOSTON ST | Bike Lane | primary | shared_lane | 0.10 | LTS 3 | LTS 3 | 202365906, 450298544, 500861987 |
| GREENSPRING AVE | Bike Lane | secondary | separate | 0.10 | LTS 3 | LTS 3 | 424995896, 1088161175 |
| E CROMWELL ST | Separated Bike Lane | tertiary | none | 0.10 | LTS 2 | LTS 2 | 1132328634 |
| ARGONNE DR | Separated Bike Lane | secondary | none | 0.10 | LTS 3 | LTS 1 | 605724255 |
| LAWRENCE ST | Separated Bike Lane | tertiary | none | 0.10 | LTS 3 | LTS 3 | 188969422 |
| BOSTON ST | Bike Lane | secondary | shared_lane | 0.10 | LTS 4 | LTS 3 | 312657347 |
| E 33RD ST | Bike Lane | primary_link | none | 0.10 | LTS 3 | LTS 3 | 5998782 |
| N CHARLES | Buffered Bike Lane | primary | none | 0.09 | LTS 3 | LTS 2 | 132609915, 179973403, 543918805 |
| WALTHER AVE | Bike Lane | residential | none | 0.09 | LTS 2 | LTS 2 | 5997814 |
| GUILFORD AVE | Bike Lane | primary | none | 0.08 | LTS 3 | LTS 3 | 424999451, 424999454 |
| GUILFORD AVE | Separated Bike Lane | tertiary | shared_lane | 0.08 | LTS 2 | LTS 2 | 69530905, 833243489, 949066303 |
| N CHARLES ST | Bike Lane | residential | none | 0.08 | LTS 2 | LTS 2 | 532516431 |
| N CHARLES ST | Buffered Bike Lane | primary | none | 0.08 | LTS 3 | LTS 2 | 132381955, 818850643, 818850670 |
| E CENTRE ST | Separated Bike Lane | primary | none | 0.08 | LTS 3 | LTS 1 | 132521361, 424999427 |
| WYMAN PARK DR | Bike Lane | unclassified | none | 0.08 | LTS 2 | LTS 2 | 83704673, 914896169 |
| W 29TH ST | Bike Lane | primary | none | 0.07 | LTS 3 | LTS 3 | 6017357, 187473030, 424994496 |
| EDMONDSON AVE | Bike Lane | secondary | none | 0.07 | LTS 3 | LTS 3 | 10249138, 606136781 |
| N CHARLES ST | Bike Lane | primary | asphalt | 0.07 | LTS 3 | LTS 2 | 970453181 |
| W UNIVERSITY PKWY | Separated Bike Lane | primary | lane,yes | 0.07 | LTS 3 | LTS 1 | 197950029, 1083034963, 1083034964 |
| S CENTRAL AVE | Separated Bike Lane | secondary | lane | 0.07 | LTS 3 | LTS 3 | 113065023, 765165381, 1122032024 |
| DRUID PARK LAKE DR | Separated Bike Lane | secondary_link | none | 0.07 | LTS 3 | LTS 1 | 6005536, 1069502089 |

### Shared-lane markings and bus-bike lanes OSM lacks (no tier effect; top 30 by miles)

| street | city facility | OSM class | OSM cycleway | miles | our tier | tier with the facility | ways |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BOSTON ST | Shared Lane Markings | primary | none | 1.65 | LTS 3 | - | 6003340, 186672432, 192574246 |
| FRANKFORD AVE | Shared Lane Markings | tertiary | none | 1.21 | LTS 3 | - | 164024528, 198707921, 548202883 |
| HOLLINS ST | Shared Lane Markings | residential | none | 1.12 | LTS 2 | - | 75359769, 75359775, 75359777 |
| S BROADWAY | Shared Lane Markings | secondary | none | 1.11 | LTS 3 | - | 6013349, 6023144, 49639167 |
| N ROGERS AVE | Shared Lane Markings | tertiary | none | 0.99 | LTS 2 | - | 203683644, 501225952, 950055538 |
| W COLD SPRING LANE | Shared Lane Markings | primary | none | 0.95 | LTS 3 | - | 10426301, 130715033, 425001832 |
| N BROADWAY | Shared Lane Markings | secondary | none | 0.95 | LTS 3 | - | 55878858, 75923298, 75923300 |
| ECHODALE AVE | Shared Lane Markings | secondary | none | 0.84 | LTS 3 | - | 383087781, 522334866, 548174724 |
| PARK HEIGHTS AVE | Shared Lane Markings | secondary | none | 0.82 | LTS 3 | - | 451498929, 542341654, 542341655 |
| WASHINGTON BLVD | Shared Lane Markings | secondary | none | 0.75 | LTS 3 | - | 70497530, 207525387, 451772882 |
| LOCH RAVEN BLVD | Shared Lane Markings | secondary | none | 0.75 | LTS 3 | - | 111058351, 191923167, 425003366 |
| BELAIR ROAD | Shared Lane Markings | primary | none | 0.72 | LTS 3 | - | 51535569, 424990143, 424991226 |
| GARRISON BLVD | Shared Lane Markings | secondary | none | 0.67 | LTS 3 | - | 208502671, 424991337, 424991338 |
| W LEXINGTON ST | Shared Lane Markings | tertiary | none | 0.67 | LTS 2 | - | 73920725, 111075869 |
| W ROGERS AVE | Shared Lane Markings | tertiary | none | 0.66 | LTS 2 | - | 206189487, 336415568, 948148272 |
| DOLFIELD AVE | Shared Lane Markings | tertiary | none | 0.60 | LTS 2 | - | 6016914, 451775066 |
| W OSTEND ST | Shared Lane Markings | residential | none | 0.58 | LTS 2 | - | 132521548, 861256358, 952026781 |
| N CHARLES ST | Shared Bus-Bike Lane | secondary | none | 0.55 | LTS 3 | - | 98289564, 107263471, 195640776 |
| E 33RD ST | Shared Lane Markings | primary | none | 0.53 | LTS 3 | - | 132609849, 375012288, 399093877 |
| FALLSWAY | Shared Lane Markings | secondary | none | 0.44 | LTS 3 | - | 49667899, 188783421, 207747774 |
| N STRICKER ST | Shared Lane Markings | residential | none | 0.41 | LTS 2 | - | 6022636, 6022643, 73920717 |
| CHERRYLAND ROAD | Shared Lane Markings | tertiary | none | 0.41 | LTS 2 | - | 6017866, 198924878 |
| WABASH AVE | Shared Lane Markings | residential | none | 0.36 | LTS 2 | - | 5991827 |
| SAINT PAUL PL | Shared Bus-Bike Lane | primary | none | 0.36 | LTS 3 | - | 130599664, 279670985, 977370311 |
| W NORTH AVE | Shared Bus-Bike Lane | primary | none | 0.36 | LTS 3 | - | 6011495, 98144328, 138869951 |
| GREENSPRING AVE | Shared Lane Markings | secondary | none | 0.36 | LTS 3 | - | 188164057, 188165134, 425193724 |
| E MOUNT ROYAL AVE | Shared Lane Markings | secondary | none | 0.28 | LTS 3 | - | 6004711, 69546294, 69546295 |
| MCMECHEN ST | Shared Lane Markings | tertiary | none | 0.27 | LTS 2 | - | 160184314, 548242343, 548242345 |
| GUILFORD AVE | Shared Lane Markings | secondary | none | 0.25 | LTS 3 | - | 11202273, 69546296, 98289441 |
| MADISON AVE | Shared Lane Markings | residential | none | 0.23 | LTS 2 | - | 949167915 |

765 OSM ways (40.9 mi) in all. Of them, **410 ways (17.4 mi) lack the bike lane or track** the city records (bike lane, buffered, separated or contraflow lane), and 355 ways (23.5 mi) lack only a shared-lane marking or a shared bus-bike lane, which is neither a lane nor a track and which the classifier does not credit. 256 of the lane and track ways (10.7 mi) would be rated lower with the facility tagged and are among the rows the owner approved; they are the stress rows of `fixtures/overrides/2026-10-01-owner-baltimore-facilities.json` (OWNER-DECISIONS 182; the differences from the approved set are listed below). The tiers are this branch's, with the city's centerline conflated (its speed only where OSM has none, OWNER-DECISIONS 184).

### Against the rows the owner approved (OWNER-DECISIONS 182)

The file keeps within the 264 stress rows the owner approved (reports/data-comparison/owner-approved-override-ways.json, as proposed at commit 318708b).

Approved rows no longer valid, left out for the owner: 8.

| way | street | approved tier | why |
| --- | --- | --- | --- |
| 5998782 | E 33RD ST | LTS 3 | the facility no longer lowers its tier (LTS 3 with or without it) |
| 6021467 | Park Avenue | LTS 2 | no longer lies along the city's facility line |
| 10870563 | West 29th Street | LTS 1 | no longer lies along the city's facility line |
| 108842191 | O'Donnell Street Cutoff | LTS 3 | no longer lies along the city's facility line |
| 312657346 | Boston Street | LTS 3 | no longer lies along the city's facility line |
| 424993940 | Dolphin Street | LTS 2 | no longer lies along the city's facility line |
| 606136777 | Baltimore National Pike | LTS 3 | no longer lies along the city's facility line |
| 949168595 | West 29th Street | LTS 1 | no longer lies along the city's facility line |

Approved rows whose tier with the facility moved, kept at the re-derived tier: 1.

| way | street | approved tier | tier now with the facility | tier without |
| --- | --- | --- | --- | --- |
| 970453181 | N CHARLES ST | LTS 3 | LTS 2 | LTS 3 |

Ways the re-derivation finds that the owner was not shown, held back: 5.

| way | street | OSM class | city facility | tier | tier with the facility |
| --- | --- | --- | --- | --- | --- |
| 32829714 | W CHASE ST | tertiary | Separated Bike Lane | LTS 2 | LTS 1 |
| 51731746 | DRUID PARK LAKE DR | service | Separated Bike Lane | LTS 3 | LTS 1 |
| 178254360 | HARFORD RD | primary | Separated Bike Lane | LTS 3 | LTS 1 |
| 189310755 | W CHASE ST | tertiary | Separated Bike Lane | LTS 2 | LTS 1 |
| 1067446518 | HILLEN RD | primary | Separated Bike Lane | LTS 3 | LTS 1 |

## Paths, sidepaths and multiuse trails

City path and trail lines with no OSM way along at least half of them (candidate missing paths): 39 lines, 3.3 mi.

| layer | street or trail | miles |
| --- | --- | --- |
| Path or Sidepath | MOUNTAIN PASS | 0.38 |
| Multiuse trail | Gelston Heights Spur | 0.36 |
| Path or Sidepath | GWYNNS FALLS TRAIL | 0.25 |
| Multiuse trail | Jones Falls Trail - Lakeside Loop Spur | 0.24 |
| Path or Sidepath | MOUNTAIN PASS | 0.19 |
| Multiuse trail | Jones Falls Trail - Lakeside Loop Spur | 0.18 |
| Multiuse trail | Mountain Pass Spur | 0.16 |
| Multiuse trail | Poplar Drive Spur | 0.14 |
| Path or Sidepath | PATTERSON PARK 2 | 0.13 |
| Multiuse trail | Mountain Pass Spur | 0.13 |
| Multiuse trail | Gelston Heights Spur | 0.12 |
| Multiuse trail | Gelston Heights Spur | 0.11 |
| Multiuse trail | Woodstock Trail | 0.10 |
| Multiuse trail | Middle Branch Trail | 0.08 |
| Multiuse trail | Hillway Spur | 0.08 |
| Multiuse trail | Jones Falls Trail - Lakeside Loop Spur | 0.07 |
| Multiuse trail | Jones Falls Trail - Lakeside Loop Spur | 0.06 |
| Multiuse trail | Briarclift Spur | 0.05 |
| Multiuse trail | Wetland Spur | 0.05 |
| Multiuse trail | Old Wagon Road Spur | 0.04 |
| Multiuse trail | Mountain Pass Spur | 0.04 |
| Multiuse trail | Buckeye Trail | 0.04 |
| Multiuse trail | Mountain Pass Spur | 0.03 |
| Multiuse trail | Crossland Spur | 0.03 |
| Multiuse trail | Buckeye Trail | 0.03 |
| Multiuse trail | Red Road Spur | 0.02 |
| Multiuse trail | Jones Falls Trail | 0.02 |
| Multiuse trail | Mountain Pass Spur | 0.02 |
| Multiuse trail | Mountain Pass Spur | 0.02 |
| Multiuse trail | Briarclift Spur | 0.02 |
| Multiuse trail | Briarclift Spur | 0.02 |
| Path or Sidepath | GWYNNS FALLS TRAIL | 0.02 |
| Multiuse trail | Gwynns Falls Trail | 0.02 |
| Multiuse trail | Forest Drive | 0.02 |
| Multiuse trail | Clara's Trail | 0.02 |
| Multiuse trail | Jastrow Levin Spur | 0.01 |
| Multiuse trail | Mountain Pass Spur | 0.01 |
| Multiuse trail | Connector | 0.01 |
| Multiuse trail | Norman Reeves Nature Loop Spur | 0.00 |

OSM footways and paths that lie along a city path or trail and carry no bicycle permission (`bicycle` is not yes, designated or permissive, and not a mapper's `no` or `dismount`), lying along the city line for at least 80% of their length and at least 50 ft [15 m] long: 180 ways, 11.9 mi. The Veirs Mill case (OWNER-DECISIONS 115) was this: a paved sidepath mapped as a sidewalk. They are the `bicycle=designated` access rows of `fixtures/overrides/2026-10-01-owner-baltimore-facilities.json`.

| street or trail | city layer | OSM class | OSM bicycle | miles | way |
| --- | --- | --- | --- | --- | --- |
| Stony Run Walking Trail | Multiuse trail | path | (no tag) | 0.54 | 453490139 |
| Stony Run Walking Trail | Multiuse trail | path | (no tag) | 0.53 | 107263476 |
| Windsor Hill Conservation Spur | Multiuse trail | path | (no tag) | 0.45 | 328749665 |
| Stony Run Walking Trail | Multiuse trail | path | (no tag) | 0.39 | 293717317 |
| Old Franklintown Loop Spur | Multiuse trail | path | (no tag) | 0.37 | 368800728 |
| Wetland Spur | Multiuse trail | path | (no tag) | 0.31 | 328668901 |
| Windsor Hill Conservation Spur | Multiuse trail | path | (no tag) | 0.30 | 370053028 |
| Old Monticello Road Spur | Multiuse trail | path | (no tag) | 0.23 | 803429468 |
| Stony Run Walking Trail | Multiuse trail | path | (no tag) | 0.23 | 293717322 |
| Stony Run Walking Trail | Multiuse trail | path | (no tag) | 0.22 | 302535131 |
| Stony Run Walking Trail | Multiuse trail | path | (no tag) | 0.19 | 293714857 |
| Lazear Spur | Multiuse trail | path | (no tag) | 0.19 | 443655992 |
| Stony Run Walking Trail | Multiuse trail | path | (no tag) | 0.19 | 237171455 |
| Gwynns Falls Trail | Multiuse trail | footway (sidewalk) | (no tag) | 0.16 | 1504765060 |
| Old Spring Spur | Multiuse trail | path | (no tag) | 0.15 | 904379784 |
| Border Trail | Multiuse trail | path | (no tag) | 0.15 | 1189390273 |
| Stony Run Walking Trail | Multiuse trail | path | (no tag) | 0.14 | 727358458 |
| Windsor Hill Conservation Spur | Multiuse trail | path | (no tag) | 0.14 | 328749664 |
| Gwynns Falls Trail | Multiuse trail | footway (sidewalk) | (no tag) | 0.14 | 1365057863 |
| Stony Run Walking Trail | Multiuse trail | path | (no tag) | 0.13 | 293714861 |
| Stony Run Walking Trail | Multiuse trail | path | (no tag) | 0.12 | 293714868 |
| Old Spring Spur | Multiuse trail | path | (no tag) | 0.11 | 902123715 |
| 33rd St Trail | Multiuse trail | footway (sidewalk) | (no tag) | 0.11 | 833562798 |
| Herring Run Trail | Multiuse trail | footway | (no tag) | 0.11 | 51965427 |
| Prior Trail | Multiuse trail | path | (no tag) | 0.10 | 506584536 |
| Jones Falls Trail | Multiuse trail | footway (sidewalk) | (no tag) | 0.10 | 1005997722 |
| Stony Run Walking Trail | Multiuse trail | path | (no tag) | 0.09 | 293714850 |
| Jones Falls Trail | Multiuse trail | footway (sidewalk) | (no tag) | 0.09 | 587071809 |
| Old Hunting Ridge Spur | Multiuse trail | path | (no tag) | 0.09 | 917543524 |
| Old Fort Spur | Multiuse trail | path | (no tag) | 0.09 | 8039449 |
| Norman Reeves Nature Loop Spur | Multiuse trail | path | (no tag) | 0.09 | 904801429 |
| Gwynns Falls Trail | Multiuse trail | footway (sidewalk) | (no tag) | 0.09 | 1504765045 |
| Jones Falls Trail | Multiuse trail | footway (sidewalk) | (no tag) | 0.09 | 441683977 |
| Jones Falls Trail | Multiuse trail | footway (sidewalk) | (no tag) | 0.09 | 1030556442 |
| Jastrow Levin Spur | Multiuse trail | path | (no tag) | 0.08 | 803429476 |
| PATTERSON PARK 2 | Path or Sidepath | footway | (no tag) | 0.08 | 133689206 |
| Jones Falls Trail | Multiuse trail | footway (sidewalk) | (no tag) | 0.08 | 1030509307 |
| Hillway Spur | Multiuse trail | path | (no tag) | 0.08 | 982270874 |
| Gwynns Falls Trail | Multiuse trail | footway (sidewalk) | (no tag) | 0.08 | 554587380 |
| Gwynns Falls Trail | Multiuse trail | footway (sidewalk) | (no tag) | 0.08 | 452909523 |
