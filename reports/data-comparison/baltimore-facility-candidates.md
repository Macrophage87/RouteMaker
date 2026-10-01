# Baltimore: the city's bike facilities and trails against OSM

Sources, all open-licensed by Baltimore City Code Art. 1 s.9-1(h) (OWNER-DECISIONS 159), credit "City of Baltimore, Open Baltimore": DOT BMC Bike Facilities (item dbef46a0caf948debba8516f0d95fe4c; 184 mi of existing facilities, `STATUS1` 4) and Multiuse Trails (item 34260bfb3df74d3994e0c73fde47630b; proposed trails, `mainSpur` of Future Alignment, were excluded at the query). Retrieved 2026-10-01.

## Facilities the city records on roads, and what OSM has on the matched way

| city facility type | city miles | OSM way already tagged | candidates (miles) |
| --- | --- | --- | --- |
| Path or Sidepath | 47.0 | (a separate way; checked below) | 0.0 |
| Bike Lane | 37.9 | 35.5 mi | 5.2 |
| Shared Lane Markings | 34.4 | 12.9 mi | 21.5 |
| Signed Bike Route | 21.3 | 20.8 mi | 0.0 |
| Separated Bike Lane | 19.3 | 10.3 mi | 11.7 |
| Shared Bus-Bike Lane | 11.3 | 10.2 mi | 2.0 |
| Buffered Bike Lane | 5.9 | 5.2 mi | 1.3 |
| Bike Boulevard | 5.6 | 5.4 mi | 0.0 |
| Contraflow Bike Lane | 0.8 | 0.8 mi | 0.0 |

A *candidate* is an OSM road way lying along a city facility whose own tags carry no cycleway of the kind the city records (a lane for a bike lane, buffered lane or contraflow lane; a track or a `cycleway=separate` for a separated lane). `Signed Bike Route` and `Bike Boulevard` are routes, which OSM carries on relations and the classifier does not credit, so they are not candidates. `Path or Sidepath` is a separate way and is checked below.

### Roads whose bike lane or track OSM lacks (top 60 by miles)

| street | city facility | OSM class | OSM cycleway | miles | our tier | tier with the facility | ways |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BOSTON ST | Shared Lane Markings | primary | none | 1.65 | LTS 3 | - | 6003340, 186672432, 192574246 |
| HARFORD RD | Separated Bike Lane | primary | none | 1.57 | LTS 3 | LTS 1 | 178254354, 178254356, 178254358 |
| DRUID PARK LAKE DR | Separated Bike Lane | secondary | none | 1.34 | LTS 3 | LTS 1 | 6000701, 10870563, 423400502 |
| FRANKFORD AVE | Shared Lane Markings | tertiary | none | 1.21 | LTS 3 | - | 164024528, 198707921, 548202883 |
| HOLLINS ST | Shared Lane Markings | residential | none | 1.12 | LTS 2 | - | 75359769, 75359775, 75359777 |
| S BROADWAY | Shared Lane Markings | secondary | none | 1.11 | LTS 3 | - | 6013349, 6023144, 49639167 |
| N ROGERS AVE | Shared Lane Markings | tertiary | none | 0.99 | LTS 2 | - | 203683644, 501225952, 950055538 |
| W COLD SPRING LANE | Shared Lane Markings | primary | none | 0.95 | LTS 3 | - | 10426301, 130715033, 425001832 |
| N BROADWAY | Shared Lane Markings | secondary | none | 0.95 | LTS 3 | - | 55878858, 75923298, 75923300 |
| W MOUNT ROYAL AVE | Separated Bike Lane | secondary | none | 0.89 | LTS 3 | LTS 1 | 6004710, 48001165, 48001167 |
| ECHODALE AVE | Shared Lane Markings | secondary | none | 0.84 | LTS 3 | - | 383087781, 522334866, 548174724 |
| PARK HEIGHTS AVE | Shared Lane Markings | secondary | none | 0.82 | LTS 3 | - | 451498929, 542341654, 542341655 |
| WASHINGTON BLVD | Shared Lane Markings | secondary | none | 0.75 | LTS 3 | - | 70497530, 207525387, 451772882 |
| LOCH RAVEN BLVD | Shared Lane Markings | secondary | none | 0.75 | LTS 3 | - | 111058351, 191923167, 425003366 |
| BELAIR ROAD | Shared Lane Markings | primary | none | 0.72 | LTS 3 | - | 51535569, 424990143, 424991226 |
| GARRISON BLVD | Shared Lane Markings | secondary | none | 0.67 | LTS 3 | - | 208502671, 424991337, 424991338 |
| W LEXINGTON ST | Shared Lane Markings | tertiary | none | 0.67 | LTS 2 | - | 73920725, 111075869 |
| W ROGERS AVE | Shared Lane Markings | tertiary | none | 0.66 | LTS 2 | - | 206189487, 336415568, 948148272 |
| ST LO DR | Separated Bike Lane | unclassified | none | 0.63 | LTS 3 | LTS 3 | 6007365, 380458640, 380458641 |
| GREENSPRING AVE | Separated Bike Lane | secondary | lane | 0.60 | LTS 3 | LTS 1 | 6019126, 213559205, 544896745 |
| DOLFIELD AVE | Shared Lane Markings | tertiary | none | 0.60 | LTS 2 | - | 6016914, 451775066 |
| W OSTEND ST | Shared Lane Markings | residential | none | 0.58 | LTS 2 | - | 132521548, 861256358, 952026781 |
| ANNAPOLIS RD | Separated Bike Lane | secondary | none | 0.58 | LTS 3 | LTS 1 | 47999125, 422243516, 425107400 |
| CHESAPEAKE AVE | Buffered Bike Lane | unclassified | none | 0.55 | LTS 2 | LTS 2 | 6009864 |
| GREENSPRING AVE | Bike Lane | secondary | separate | 0.55 | LTS 2 | LTS 2 | 188164049, 947541482, 1558383598 |
| N CHARLES ST | Shared Bus-Bike Lane | secondary | none | 0.55 | LTS 3 | - | 98289564, 107263471, 195640776 |
| E 33RD ST | Shared Lane Markings | primary | none | 0.53 | LTS 3 | - | 132609849, 375012288, 399093877 |
| W NORTH AVE | Separated Bike Lane | primary | none | 0.47 | LTS 3 | LTS 1 | 11946018, 69531096, 113296957 |
| HARFORD RD | Separated Bike Lane | primary | none | 0.47 | LTS 3 | LTS 3 | 178254357, 178254360, 178254361 |
| N CHARLES ST | Buffered Bike Lane | residential | none | 0.46 | LTS 2 | LTS 2 | 132381956, 532516429, 1062922431 |
| FALLSWAY | Shared Lane Markings | secondary | none | 0.44 | LTS 3 | - | 49667899, 188783421, 207747774 |
| N STRICKER ST | Shared Lane Markings | residential | none | 0.41 | LTS 2 | - | 6022636, 6022643, 73920717 |
| CHERRYLAND ROAD | Shared Lane Markings | tertiary | none | 0.41 | LTS 2 | - | 6017866, 198924878 |
| E 39TH ST | Separated Bike Lane | secondary | lane | 0.39 | LTS 2 | LTS 1 | 110351411, 817738138, 852324512 |
| SAINT PAUL ST | Bike Lane | residential | none | 0.37 | LTS 2 | LTS 2 | 455277309, 455277310, 522343538 |
| WABASH AVE | Shared Lane Markings | residential | none | 0.36 | LTS 2 | - | 5991827 |
| SAINT PAUL PL | Shared Bus-Bike Lane | primary | none | 0.36 | LTS 3 | - | 130599664, 279670985, 977370311 |
| W NORTH AVE | Shared Bus-Bike Lane | primary | none | 0.36 | LTS 3 | - | 6011495, 98144328, 138869951 |
| GREENSPRING AVE | Shared Lane Markings | secondary | none | 0.36 | LTS 3 | - | 188164057, 188165134, 425193724 |
| WABASH AVE | Bike Lane | primary | none | 0.35 | LTS 3 | LTS 2 | 237887546, 425003410, 425184573 |
| W CENTRE ST | Separated Bike Lane | secondary | none | 0.32 | LTS 3 | LTS 1 | 6010257, 98117561, 98117562 |
| AUCHENTOROLY TERR | Bike Lane | secondary | none | 0.31 | LTS 3 | LTS 3 | 130536463, 130536510, 130536511 |
| WALTHER AVE | Bike Lane | secondary | shared_lane | 0.31 | LTS 3 | LTS 3 | 424990152, 424993025, 424993026 |
| E CROMWELL ST | Separated Bike Lane | tertiary | none | 0.31 | LTS 3 | LTS 1 | 103285172, 548444091, 1052925414 |
| E MOUNT ROYAL AVE | Shared Lane Markings | secondary | none | 0.28 | LTS 3 | - | 6004711, 69546294, 69546295 |
| MCMECHEN ST | Shared Lane Markings | tertiary | none | 0.27 | LTS 2 | - | 160184314, 548242343, 548242345 |
| W UNIVERSITY PKWY | Separated Bike Lane | primary | lane | 0.27 | LTS 3 | LTS 1 | 107295920, 107295924, 107295928 |
| GUILFORD AVE | Shared Lane Markings | secondary | none | 0.27 | LTS 3 | - | 11202273, 24709969, 69546296 |
| ARGONNE DR | Separated Bike Lane | secondary | lane | 0.25 | LTS 3 | LTS 1 | 51535573, 302003633, 948676226 |
| LIBERTY HEIGHTS AVE | Separated Bike Lane | tertiary | none | 0.24 | LTS 3 | LTS 1 | 10426297, 89385453, 425185517 |
| MADISON AVE | Shared Lane Markings | residential | none | 0.23 | LTS 2 | - | 949167915 |
| E CENTRE ST | Separated Bike Lane | secondary | none | 0.23 | LTS 3 | LTS 1 | 6010027, 98289479, 132521360 |
| SEQUOIA AVE | Shared Lane Markings | residential | none | 0.23 | LTS 2 | - | 423405856, 623582878 |
| WASHINGTON BLVD | Bike Lane | residential | none | 0.22 | LTS 2 | LTS 2 | 98289504, 127068499, 332701004 |
| COVINGTON ST | Separated Bike Lane | residential | none | 0.22 | LTS 2 | LTS 1 | 275828165, 452789362 |
| W BELVEDERE AVE | Shared Lane Markings | secondary | none | 0.21 | LTS 3 | - | 198873398, 198873399, 425002799 |
| E 20TH ST | Separated Bike Lane | residential | -1,lane,shared_lane | 0.20 | LTS 2 | LTS 2 | 6019053, 225157507, 1156356326 |
| W HENRIETTA ST | Shared Lane Markings | residential | none | 0.20 | LTS 2 | - | 6012660, 952662000 |
| SAINT PAUL ST | Bike Lane | primary | shared_lane | 0.20 | LTS 3 | LTS 3 | 11961372, 69531013, 69531020 |
| S STRICKER ST | Shared Lane Markings | residential | none | 0.19 | LTS 2 | - | 1289127443, 1555360231, 1555360232 |

785 OSM ways (41.7 mi) in all; 264 of them (11.2 mi) would be rated lower with the facility tagged, and are in the proposed override file.

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

OSM footways and paths that lie along a city path or trail and carry no bicycle permission (`bicycle` is not yes, designated or permissive, and not a mapper's `no` or `dismount`), lying along the city line for at least 80% of their length and at least 15 m long: 180 ways, 11.9 mi. The Veirs Mill case (OWNER-DECISIONS 115) was this: a paved sidepath mapped as a sidewalk. They are in the proposed file as `bicycle=designated` access rows.

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
