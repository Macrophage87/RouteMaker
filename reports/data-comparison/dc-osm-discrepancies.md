# DC Roadway Block against OSM: where they disagree

For the owner's review (OWNER-DECISIONS 191: "DC roads and especially bike infrastructure changes quite frequently, so it's likely OSM data is stale. However, report the discrepancies when you see them."). Every District road way a Roadway Block was matched to, where the block's record and the way's OSM tags say different things. The District's value is what the classifier reads (OWNER-DECISIONS 190) except where a block, which describes the whole road, cannot speak for one of its ways; those are listed as **not applied**, with the reason. Regenerated from `dcbal.tsv` (`scripts/analysis/data_before_after.py`) with the before-after report after each rebuild; every row is in `dc-osm-discrepancies.csv`.

Nothing here is for importing into OSM: the Roadway Block is CC BY 4.0, and copying its values into OSM (ODbL) would need a licence waiver from the District.

13,409 matched District ways (1,233 mi). A way can appear under several types. Tiers are the way's tier with OSM's tags alone and with the District's record applied (all of it, not only this attribute). Where OSM has no value (no `maxspeed`, no `lanes`) the District's fills it, and that is not counted here.

| type | ways | miles | applied: ways | applied: miles | not applied: ways | not applied: miles | applied, tier changed: ways |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Bike facility present or absent | 567 | 30.7 | 233 | 11.4 | 334 | 19.3 | 146 |
| Facility kind (painted, buffered, protected) | 135 | 5.8 | 98 | 4.3 | 37 | 1.5 | 43 |
| Contraflow lane | 53 | 4.2 | 21 | 2.4 | 32 | 1.9 | 7 |
| One-way | 3,125 | 183.1 | 358 | 25.1 | 2,767 | 158.0 | 43 |
| Through lanes per direction | 3,033 | 180.5 | 2,667 | 155.0 | 366 | 25.5 | 573 |
| Posted speed | 1,585 | 132.9 | 1,585 | 132.9 | 0 | 0.0 | 620 |

## Not applied (OWNER-DECISIONS 190 exceptions)

| type | reason | ways | miles |
| --- | --- | --- | --- |
| One-way | divided carriageway | 1,717 | 101.5 |
| One-way | carriageway pair | 697 | 36.6 |
| Through lanes per direction | slip road: its own lanes | 357 | 24.8 |
| One-way | slip road or freeway | 250 | 15.6 |
| Bike facility present or absent | separate: OSM maps a facility as its own way beside the road; DC records none | 193 | 12.1 |
| Bike facility present or absent | separate: OSM maps the facility as its own way beside the road or its other carriageway | 69 | 2.7 |
| One-way | junction stub | 64 | 0.7 |
| Bike facility present or absent | DC's blocks differ along the way (a lane on some) | 37 | 1.7 |
| Bike facility present or absent | carriageway: the other direction's lane, or no contraflow flag | 34 | 2.8 |
| Contraflow lane | separate: OSM maps the facility as its own way beside the road or its other carriageway | 26 | 1.4 |
| Facility kind (painted, buffered, protected) | separate: OSM maps the facility as its own way beside the road or its other carriageway | 25 | 0.7 |
| One-way | direction unknown | 12 | 0.7 |
| One-way | one-way blocks along it | 11 | 1.9 |
| One-way | unnamed | 10 | 0.4 |
| Through lanes per direction | DC records one direction of a two-way way | 9 | 0.7 |
| Contraflow lane | carriageway: the other direction's lane, or no contraflow flag | 6 | 0.5 |
| Facility kind (painted, buffered, protected) | carriageway: the other direction's lane, or no contraflow flag | 6 | 0.5 |
| Facility kind (painted, buffered, protected) | DC's blocks differ along the way (a lane on some) | 5 | 0.3 |
| One-way | roundabout | 4 | 0.1 |
| One-way | reversible lanes | 2 | 0.5 |
| Bike facility present or absent | OSM says bicycle=no, use_sidepath or cycleway=no | 1 | 0.0 |
| Facility kind (painted, buffered, protected) | OSM says bicycle=no, use_sidepath or cycleway=no | 1 | 0.0 |

## Bike facility present or absent: applied, the 25 longest of 233

| street | OSM way | DC block | length | OSM | DC | tier | applied |
| --- | --- | --- | --- | --- | --- | --- | --- |
| I Street Northeast | [131240406](https://www.openstreetmap.org/way/131240406) | dc-4639194-0 (+5) | 0.68 mi [1,097 m] | cycleway:right=shared_lane | painted lane (IB) | LTS 1 (no change) | yes |
| Tennessee Avenue Northeast | [50519360](https://www.openstreetmap.org/way/50519360) | dc-4637460-0 (+5) | 0.37 mi [603 m] | cycleway=lane | none recorded | LTS 2 to 1 | yes |
| Park Road Northwest | [6061744](https://www.openstreetmap.org/way/6061744) | dc-4637075-0 (+1) | 0.28 mi [447 m] | cycleway:left=lane, cycleway:left:oneway=-1, cycleway:right=shared_lane | none recorded | LTS 2 (no change) | yes |
| Florida Avenue Northwest | [29235002](https://www.openstreetmap.org/way/29235002) | dc-4625984-0 (+1) | 0.27 mi [439 m] | no cycleway tag | painted lane (OB) | LTS 3 (no change) | yes |
| Harry Thomas Way Northeast | [6051803](https://www.openstreetmap.org/way/6051803) | dc-4638094-0 (+1) | 0.27 mi [430 m] | no cycleway tag | painted lane (IB), painted lane (OB) | LTS 2 (no change) | yes |
| T Street Northeast | [6056792](https://www.openstreetmap.org/way/6056792) | dc-4637928-0 (+1) | 0.22 mi [361 m] | cycleway:left=lane, cycleway:right=shared_lane | none recorded | LTS 2 to 1 | yes |
| 4th Street Northwest | [6054064](https://www.openstreetmap.org/way/6054064) | dc-4631119-0 (+2) | 0.22 mi [348 m] | no cycleway tag | buffered lane (OB) | LTS 2 (no change) | yes |
| Kentucky Avenue Southeast | [6257737](https://www.openstreetmap.org/way/6257737) | dc-4642274-0 (+1) | 856 ft [261 m] | cycleway:left=lane, cycleway:left:oneway=-1, cycleway:right=lane | none recorded | LTS 2 to 1 | yes |
| Wyoming Avenue Northwest | [1239811171](https://www.openstreetmap.org/way/1239811171) | dc-4634962-0 | 853 ft [260 m] | no cycleway tag | painted lane (OB) | LTS 1 (no change) | yes |
| C Street Northeast | [50795351](https://www.openstreetmap.org/way/50795351) | dc-4637006-0 (+1) | 833 ft [254 m] | no cycleway tag | painted lane (OB) | LTS 1 (no change) | yes |
| K Street Northeast | [589905456](https://www.openstreetmap.org/way/589905456) | dc-4639242-0 (+1) | 827 ft [252 m] | cycleway=lane | none recorded | LTS 2 to 3 | yes |
| M Street Northeast | [50753197](https://www.openstreetmap.org/way/50753197) | dc-4637286-0 | 804 ft [245 m] | no cycleway tag | protected lane (IB), protected lane (OB) | LTS 3 to 1 | yes |
| 13th Street Southeast | [565479543](https://www.openstreetmap.org/way/565479543) | dc-4640238-0 | 781 ft [238 m] | cycleway:both=lane | none recorded | LTS 2 to 1 | yes |
| Adams Mill Road Northwest | [446063908](https://www.openstreetmap.org/way/446063908) | dc-4630690-0 | 741 ft [226 m] | no cycleway tag | painted lane (IB) | LTS 2 to 3 | yes |
| N Street Northwest | [321476518](https://www.openstreetmap.org/way/321476518) | dc-4626014-0 | 738 ft [225 m] | cycleway:left=opposite_lane, cycleway:right=shared_lane | none recorded | LTS 2 (no change) | yes |
| Florida Avenue Northwest | [508226098](https://www.openstreetmap.org/way/508226098) | dc-4630829-0 (+2) | 715 ft [218 m] | no cycleway tag | painted lane (OB) | LTS 3 (no change) | yes |
| 13th Street Southeast | [1474140031](https://www.openstreetmap.org/way/1474140031) | dc-4640474-0 (+1) | 715 ft [218 m] | cycleway:both=lane | none recorded | LTS 2 to 1 | yes |
| New Jersey Avenue Northwest | [6060793](https://www.openstreetmap.org/way/6060793) | dc-4630212-0 (+2) | 709 ft [216 m] | no cycleway tag | painted lane (IB), painted lane (OB) | LTS 3 to 2 | yes |
| M Street Northeast | [131052414](https://www.openstreetmap.org/way/131052414) | dc-4636000-0 (+1) | 676 ft [206 m] | cycleway:right=shared_lane | painted lane (IB) | LTS 3 (no change) | yes |
| Park Road Northwest | [29211232](https://www.openstreetmap.org/way/29211232) | dc-4636640-0 | 623 ft [190 m] | cycleway:left=lane, cycleway:right=shared_lane | none recorded | LTS 2 (no change) | yes |
| Maine Avenue Southwest | [379782120](https://www.openstreetmap.org/way/379782120) | dc-4641410-0 (+1) | 594 ft [181 m] | no cycleway tag | protected lane (IB), protected lane (OB) | LTS 3 to 1 | yes |
| Dahlia Street Northwest | [1335180342](https://www.openstreetmap.org/way/1335180342) | dc-4630390-0 (+1) | 594 ft [181 m] | cycleway=lane | none recorded | LTS 2 to 1 | yes |
| Vermont Avenue Northwest | [6051788](https://www.openstreetmap.org/way/6051788) | dc-4635030-0 (+1) | 574 ft [175 m] | cycleway:right=lane | none recorded | LTS 2 to 3 | yes |
| Vermont Avenue Northwest | [1409177342](https://www.openstreetmap.org/way/1409177342) | dc-4637175-0 (+2) | 571 ft [174 m] | cycleway:right=lane | none recorded | LTS 2 to 3 | yes |
| V Street Northwest | [6061988](https://www.openstreetmap.org/way/6061988) | dc-4634677-0 (+1) | 564 ft [172 m] | cycleway=lane | none recorded | LTS 2 to 1 | yes |

## Bike facility present or absent: not applied, the 25 longest of 334

| street | OSM way | DC block | length | OSM | DC | tier | applied |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Ohio Drive Southwest | [130908180](https://www.openstreetmap.org/way/130908180) | dc-4640995-0 (+1) | 2.52 mi [4,062 m] | cycleway:right=separate | none recorded | LTS 3 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| John McCormack Road | [132577607](https://www.openstreetmap.org/way/132577607) | dc-4638258-0 (+1) | 0.43 mi [698 m] | cycleway:right=separate | none recorded | LTS 2 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| Rock Creek and Potomac Parkway Northwest | [435101942](https://www.openstreetmap.org/way/435101942) | dc-4636825-0 | 0.43 mi [693 m] | cycleway:left=separate, cycleway:right=no | none recorded | LTS 4 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| Kentucky Avenue Southeast | [229700999](https://www.openstreetmap.org/way/229700999) | dc-4640326-0 (+4) | 0.41 mi [661 m] | cycleway:both=lane, cycleway:both:lane=advisory | none recorded | LTS 2 (not applied) | no: DC's blocks differ along the way (a lane on some) |
| South Capitol Street Southwest | [50464870](https://www.openstreetmap.org/way/50464870) | dc-4640235-0 | 0.30 mi [490 m] | cycleway:right=separate | none recorded | LTS 4 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| South Capitol Street Southeast | [910656490](https://www.openstreetmap.org/way/910656490) | dc-4641219-0 | 0.28 mi [454 m] | cycleway=separate | none recorded | LTS 4 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| South Capitol Street Southwest | [910656491](https://www.openstreetmap.org/way/910656491) | dc-4642085-0 | 0.28 mi [454 m] | cycleway=separate | none recorded | LTS 4 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| 3rd Street Northeast | [6062650](https://www.openstreetmap.org/way/6062650) | dc-4636895-0 (+3) | 0.25 mi [408 m] | cycleway:right=shared_lane | a lane on some of the way's blocks only | LTS 1 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| Franklin Street Northeast | [590581627](https://www.openstreetmap.org/way/590581627) | dc-4637156-0 (+1) | 0.25 mi [402 m] | no cycleway tag | a lane on some of the way's blocks only | LTS 2 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| (unnamed) | [50429940](https://www.openstreetmap.org/way/50429940) | dc-4640637-0 (+1) | 0.24 mi [385 m] | no cycleway tag | a lane on some of the way's blocks only | LTS 4 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| W Street Northwest | [170157722](https://www.openstreetmap.org/way/170157722) | dc-4636405-0 (+3) | 0.22 mi [360 m] | no cycleway tag | a lane on some of the way's blocks only | LTS 1 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| 8th Street Northeast | [132577766](https://www.openstreetmap.org/way/132577766) | dc-4638077-0 (+2) | 0.21 mi [330 m] | cycleway:left=separate | none recorded | LTS 1 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| Massachusetts Avenue Southeast | [130927038](https://www.openstreetmap.org/way/130927038) | dc-4640830-0 (+2) | 0.20 mi [316 m] | no cycleway tag | a lane on some of the way's blocks only | LTS 2 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| 8th Street Northeast | [1502134924](https://www.openstreetmap.org/way/1502134924) | dc-4635142-0 (+1) | 0.19 mi [305 m] | cycleway:left=separate | none recorded | LTS 1 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| Pomeroy Road Southeast | [6051305](https://www.openstreetmap.org/way/6051305) | dc-4641158-0 (+3) | 919 ft [280 m] | no cycleway tag | a lane on some of the way's blocks only | LTS 2 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| Connecticut Avenue Northwest | [130908011](https://www.openstreetmap.org/way/130908011) | dc-4634209-0 (+2) | 896 ft [273 m] | cycleway:both=separate | none recorded | LTS 4 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| Virginia Avenue Southeast | [367147288](https://www.openstreetmap.org/way/367147288) | dc-4641363-0 (+1) | 886 ft [270 m] | cycleway:right=separate | none recorded | LTS 1 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| Bates Road Northeast | [6055618](https://www.openstreetmap.org/way/6055618) | dc-4637288-0 | 876 ft [267 m] | cycleway:right=separate | none recorded | LTS 2 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| Virginia Avenue Northwest Service Road | [50431280](https://www.openstreetmap.org/way/50431280) | dc-4636685-0 | 850 ft [259 m] | no cycleway tag | protected lane (IB), protected lane (OB) | LTS 3 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| (unnamed) | [397296948](https://www.openstreetmap.org/way/397296948) | dc-4631768-0 | 781 ft [238 m] | no cycleway tag | protected lane (IB), protected lane (OB) | LTS 4 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| Anacostia Drive Southeast | [902939868](https://www.openstreetmap.org/way/902939868) | dc-4641644-0 | 748 ft [228 m] | cycleway:right=separate | none recorded | LTS 1 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| Virginia Avenue Southeast | [468488472](https://www.openstreetmap.org/way/468488472) | dc-4641285-0 | 725 ft [221 m] | cycleway:right=separate | none recorded | LTS 3 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| M Street Northeast | [294891243](https://www.openstreetmap.org/way/294891243) | dc-4639108-0 (+2) | 709 ft [216 m] | cycleway=separate | none recorded | LTS 2 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| Tunlaw Road Northwest | [589905667](https://www.openstreetmap.org/way/589905667) | dc-4637052-0 (+1) | 682 ft [208 m] | cycleway=separate | none recorded | LTS 2 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |
| West Basin Drive Southwest | [130927048](https://www.openstreetmap.org/way/130927048) | dc-4642798-0 | 659 ft [201 m] | cycleway:right=separate | none recorded | LTS 1 (not applied) | no: separate: OSM maps a facility as its own way beside the road; DC records none |

## Facility kind (painted, buffered, protected): applied, the 25 longest of 98

| street | OSM way | DC block | length | OSM | DC | tier | applied |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Arizona Avenue Northwest | [116837896](https://www.openstreetmap.org/way/116837896) | dc-4632381-0 (+5) | 0.44 mi [711 m] | painted lane (cycleway:both=lane) | protected lane (IB), protected lane (OB) | LTS 2 to 1 | yes |
| Klingle Road Northwest | [286345290](https://www.openstreetmap.org/way/286345290) | dc-4625906-0 | 869 ft [265 m] | painted lane (cycleway:right=lane) | protected lane (IB), protected lane (OB) | LTS 2 to 1 | yes |
| Tilden Street Northwest | [1424825838](https://www.openstreetmap.org/way/1424825838) | dc-4635687-0 | 814 ft [248 m] | painted lane (cycleway:right=lane) | buffered lane (IB), buffered lane (OB) | LTS 2 (no change) | yes |
| Tilden Street Northwest | [1424825839](https://www.openstreetmap.org/way/1424825839) | dc-4635687-0 | 784 ft [239 m] | painted lane (cycleway:right=lane) | buffered lane (IB), buffered lane (OB) | LTS 2 (no change) | yes |
| Klingle Road Northwest | [6054731](https://www.openstreetmap.org/way/6054731) | dc-4625906-0 | 682 ft [208 m] | painted lane (cycleway:right=lane) | protected lane (IB), protected lane (OB) | LTS 2 to 1 | yes |
| West Virginia Avenue Northeast | [130908264](https://www.openstreetmap.org/way/130908264) | dc-4640252-0 (+1) | 666 ft [203 m] | protected lane (cycleway:left=track, cycleway:right=lane) | painted lane (IB), buffered lane (OB) | LTS 2 (no change) | yes |
| Kansas Avenue Northwest | [554910711](https://www.openstreetmap.org/way/554910711) | dc-4631915-0 | 627 ft [191 m] | buffered lane (cycleway:right=lane) | painted lane (IB), painted lane (OB) | LTS 2 (no change) | yes |
| Kansas Avenue Northwest | [1365012385](https://www.openstreetmap.org/way/1365012385) | dc-4631915-0 | 620 ft [189 m] | buffered lane (cycleway:right=lane) | painted lane (IB), painted lane (OB) | LTS 2 (no change) | yes |
| Franklin Street Northeast | [6062955](https://www.openstreetmap.org/way/6062955) | dc-4638319-0 | 568 ft [173 m] | painted lane (cycleway:both=lane) | buffered lane (IB), buffered lane (OB) | LTS 2 (no change) | yes |
| North Carolina Avenue Southeast | [50507957](https://www.openstreetmap.org/way/50507957) | dc-4641184-0 | 440 ft [134 m] | painted lane (cycleway=lane, cycleway:lane=advisory) | buffered lane (IB), painted lane (OB) | LTS 2 (no change) | yes |
| West Virginia Avenue Northeast | [1111556758](https://www.openstreetmap.org/way/1111556758) | dc-4640398-0 | 430 ft [131 m] | protected lane (cycleway:both=track) | painted lane (IB), buffered lane (OB) | LTS 1 to 2 | yes |
| New Hampshire Avenue Northwest | [589533512](https://www.openstreetmap.org/way/589533512) | dc-4630051-0 (+1) | 427 ft [130 m] | painted lane (cycleway:both=lane) | painted lane (IB), buffered lane (OB) | LTS 2 (no change) | yes |
| Van Ness Street Northwest | [397275296](https://www.openstreetmap.org/way/397275296) | dc-4636969-0 | 384 ft [117 m] | buffered lane (cycleway:right=lane) | painted lane (IB) | LTS 2 (no change) | yes |
| Klingle Road Northwest | [38132836](https://www.openstreetmap.org/way/38132836) | dc-4625906-0 | 367 ft [112 m] | painted lane (cycleway:right=lane) | protected lane (IB), protected lane (OB) | LTS 2 to 1 | yes |
| E Street Northwest | [397318412](https://www.openstreetmap.org/way/397318412) | dc-4632548-0 | 354 ft [108 m] | painted lane (cycleway=lane, cycleway:both=lane) | buffered lane (IB), painted lane (OB) | LTS 2 (no change) | yes |
| Klingle Road Northwest | [365932703](https://www.openstreetmap.org/way/365932703) | dc-4625906-0 | 335 ft [102 m] | painted lane (cycleway:right=lane) | protected lane (IB), protected lane (OB) | LTS 2 to 1 | yes |
| West Virginia Avenue Northeast | [589905576](https://www.openstreetmap.org/way/589905576) | dc-4640404-0 | 331 ft [101 m] | protected lane (cycleway:left=lane, cycleway:right=track) | painted lane (IB), buffered lane (OB) | LTS 2 (no change) | yes |
| West Virginia Avenue Northeast | [589905569](https://www.openstreetmap.org/way/589905569) | dc-4642205-0 | 325 ft [99 m] | protected lane (cycleway:both=track) | buffered lane (IB), buffered lane (OB) | LTS 1 to 2 | yes |
| C Street Southeast | [1042038044](https://www.openstreetmap.org/way/1042038044) | dc-4641669-0 | 322 ft [98 m] | protected lane (cycleway:both=track) | painted lane (IB), painted lane (OB) | LTS 1 (no change) | yes |
| 7th Street Southwest | [379782126](https://www.openstreetmap.org/way/379782126) | dc-4639981-0 | 318 ft [97 m] | painted lane (cycleway:right=lane) | buffered lane (IB), buffered lane (OB) | LTS 2 (no change) | yes |
| West Virginia Avenue Northeast | [589905624](https://www.openstreetmap.org/way/589905624) | dc-4640411-0 | 276 ft [84 m] | protected lane (cycleway:both=track) | buffered lane (IB), buffered lane (OB) | LTS 1 to 2 | yes |
| 6th Street Northwest | [275355554](https://www.openstreetmap.org/way/275355554) | dc-4630301-0 | 272 ft [83 m] | buffered lane (cycleway:left=opposite_lane, cycleway:right=shared_lane) | painted lane (IB) | LTS 2 (no change) | yes |
| West Virginia Avenue Northeast | [1111556759](https://www.openstreetmap.org/way/1111556759) | dc-4640398-0 | 262 ft [80 m] | protected lane (cycleway:left=track, cycleway:right=lane) | painted lane (IB), buffered lane (OB) | LTS 2 (no change) | yes |
| Arizona Avenue Northwest | [1468055281](https://www.openstreetmap.org/way/1468055281) | dc-4625874-0 | 262 ft [80 m] | painted lane (cycleway:both=lane) | protected lane (IB), protected lane (OB) | LTS 2 to 1 | yes |
| 4th Street Northwest | [1111103088](https://www.openstreetmap.org/way/1111103088) | dc-4632040-0 | 233 ft [71 m] | painted lane (cycleway:left=shared_lane, cycleway:right=lane) | buffered lane (OB) | LTS 2 to 3 | yes |

## Facility kind (painted, buffered, protected): not applied, the 25 longest of 37

| street | OSM way | DC block | length | OSM | DC | tier | applied |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Fort Lincoln Drive Northeast | [132639295](https://www.openstreetmap.org/way/132639295) | dc-4638296-0 (+3) | 0.36 mi [586 m] | painted lane (cycleway:right=lane) | buffered lane (IB), painted lane (OB) | LTS 2 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| Van Ness Street Northwest | [203172528](https://www.openstreetmap.org/way/203172528) | dc-4638091-0 | 476 ft [145 m] | painted lane (cycleway:right=lane) | buffered lane (IB) | LTS 2 (not applied) | no: DC's blocks differ along the way (a lane on some) |
| Piney Branch Road Northwest | [1061530069](https://www.openstreetmap.org/way/1061530069) | dc-4639196-0 (+2) | 397 ft [121 m] | painted lane (cycleway:left=separate, cycleway:right=lane) | buffered lane (IB), painted lane (OB) | LTS 4 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| Piney Branch Road Northwest | [29234992](https://www.openstreetmap.org/way/29234992) | dc-4637321-0 (+1) | 390 ft [119 m] | painted lane (cycleway:left=separate, cycleway:right=lane) | buffered lane (IB), painted lane (OB) | LTS 4 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| Van Ness Street Northwest | [681462620](https://www.openstreetmap.org/way/681462620) | dc-4638091-0 | 325 ft [99 m] | painted lane (cycleway:right=lane) | buffered lane (IB) | LTS 2 (not applied) | no: DC's blocks differ along the way (a lane on some) |
| Van Ness Street Northwest | [700136469](https://www.openstreetmap.org/way/700136469) | dc-4638187-0 | 285 ft [87 m] | painted lane (cycleway:right=lane) | protected lane (IB) | LTS 2 (not applied) | no: DC's blocks differ along the way (a lane on some) |
| Nannie Helen Burroughs Avenue Northeast | [935719730](https://www.openstreetmap.org/way/935719730) | dc-4635146-0 | 272 ft [83 m] | painted lane (cycleway:right=lane) | buffered lane (IB) | LTS 3 (not applied) | no: DC's blocks differ along the way (a lane on some) |
| Kentucky Avenue Southeast | [130808359](https://www.openstreetmap.org/way/130808359) | dc-4641983-0 | 253 ft [77 m] | painted lane (cycleway:left=separate, cycleway:right=lane) | painted lane (IB), buffered lane (OB) | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| Maryland Avenue Northeast | [1208534009](https://www.openstreetmap.org/way/1208534009) | dc-4638455-0 | 226 ft [69 m] | painted lane (cycleway:right=lane) | painted lane (IB), protected lane (OB) | LTS 2 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| West Virginia Avenue Northeast | [1208534029](https://www.openstreetmap.org/way/1208534029) | dc-4640475-0 | 226 ft [69 m] | protected lane (cycleway:right=track) | buffered lane (IB), buffered lane (OB) | LTS 1 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| West Virginia Avenue Northeast | [1208534030](https://www.openstreetmap.org/way/1208534030) | dc-4640475-0 | 226 ft [69 m] | protected lane (cycleway:right=track) | buffered lane (IB), buffered lane (OB) | LTS 1 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| North Carolina Avenue Southeast | [6051497](https://www.openstreetmap.org/way/6051497) | dc-4641184-0 | 220 ft [67 m] | painted lane (cycleway:left=no, cycleway:right=lane) | buffered lane (IB), painted lane (OB) | LTS 2 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| Illinois Avenue Northwest | [806297678](https://www.openstreetmap.org/way/806297678) | dc-4633270-0 | 203 ft [62 m] | painted lane (cycleway:left=separate, cycleway:right=lane) | buffered lane (IB), painted lane (OB) | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| L Street Northwest | [1232726756](https://www.openstreetmap.org/way/1232726756) | dc-4631259-0 | 177 ft [54 m] | painted lane (cycleway:left=no, cycleway:right=lane, cycleway:right:oneway=yes) | buffered lane (OB) | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| (unnamed) | [1052908774](https://www.openstreetmap.org/way/1052908774) | dc-4634476-0 | 161 ft [49 m] | painted lane (cycleway:left=lane) | buffered lane (OB) | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| L Street Northwest | [1234650776](https://www.openstreetmap.org/way/1234650776) | dc-4630146-0 | 161 ft [49 m] | painted lane (cycleway:left=no, cycleway:right=lane, cycleway:right:oneway=yes) | buffered lane (OB) | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| (unnamed) | [1051205228](https://www.openstreetmap.org/way/1051205228) | dc-4631373-0 | 157 ft [48 m] | painted lane (cycleway:left=lane, cycleway:right=no) | buffered lane (OB) | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| Florida Avenue Northwest | [1097435632](https://www.openstreetmap.org/way/1097435632) | dc-4633242-0 | 157 ft [48 m] | protected lane (cycleway=separate, cycleway:both=track) | painted lane (IB), painted lane (OB) | LTS 1 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| L Street Northwest | [1215423873](https://www.openstreetmap.org/way/1215423873) | dc-4630533-0 | 144 ft [44 m] | painted lane (cycleway:left=no, cycleway:right=lane, cycleway:right:oneway=yes) | buffered lane (OB) | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| 14th Street Northwest | [590581588](https://www.openstreetmap.org/way/590581588) | dc-4632066-0 | 141 ft [43 m] | painted lane (cycleway:left=separate, cycleway:right=lane) | painted lane (IB), buffered lane (OB) | LTS 3 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| North Carolina Avenue Southeast | [50507956](https://www.openstreetmap.org/way/50507956) | dc-4641184-0 | 138 ft [42 m] | painted lane (cycleway:left=no, cycleway:left:lane=advisory, cycleway:left:oneway=-1, cycleway:right=lane) | buffered lane (IB), painted lane (OB) | LTS 2 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| New York Avenue Northwest | [354079209](https://www.openstreetmap.org/way/354079209) | dc-4634228-0 | 135 ft [41 m] | painted lane (cycleway:right=lane, cycleway:right:oneway=yes) | protected lane (IB), painted lane (OB) | LTS 2 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| Florida Avenue Northwest | [589539500](https://www.openstreetmap.org/way/589539500) | dc-4633242-0 | 135 ft [41 m] | protected lane (cycleway=separate, cycleway:both=track) | painted lane (IB), painted lane (OB) | LTS 1 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| Sherman Avenue Northwest | [87484440](https://www.openstreetmap.org/way/87484440) | dc-4635728-0 | 128 ft [39 m] | protected lane (cycleway=separate, cycleway:both=track) | painted lane (IB), painted lane (OB) | LTS 1 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| M Street Northwest | [988487225](https://www.openstreetmap.org/way/988487225) | dc-4631373-0 | 108 ft [33 m] | painted lane (cycleway:right=lane) | buffered lane (OB) | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |

## Contraflow lane: applied, the 21 longest of 21

| street | OSM way | DC block | length | OSM | DC | tier | applied |
| --- | --- | --- | --- | --- | --- | --- | --- |
| I Street Northeast | [131240406](https://www.openstreetmap.org/way/131240406) | dc-4639194-0 (+5) | 0.68 mi [1,097 m] | cycleway:right=shared_lane | contraflow lane flagged | LTS 1 (no change) | yes |
| 11th Street Northwest | [29235004](https://www.openstreetmap.org/way/29235004) | dc-4631233-0 (+1) | 0.22 mi [353 m] | cycleway:left=lane, cycleway:left:oneway=-1, cycleway:right=shared_lane, cycleway:right:lane=pictogram | contraflow lane flagged | LTS 2 to 1 | yes |
| G Street Northeast | [641693265](https://www.openstreetmap.org/way/641693265) | dc-4637188-0 (+2) | 863 ft [263 m] | cycleway:left=lane, cycleway:left:lane=exclusive, cycleway:left:oneway=-1, cycleway:right=shared_lane, cycleway:right:lane=pictogram | contraflow lane flagged | LTS 2 to 1 | yes |
| Wyoming Avenue Northwest | [1239811171](https://www.openstreetmap.org/way/1239811171) | dc-4634962-0 | 853 ft [260 m] | no cycleway tag | contraflow lane flagged | LTS 1 (no change) | yes |
| C Street Northeast | [50795351](https://www.openstreetmap.org/way/50795351) | dc-4637006-0 (+1) | 833 ft [254 m] | no cycleway tag | contraflow lane flagged | LTS 1 (no change) | yes |
| M Street Northeast | [131052414](https://www.openstreetmap.org/way/131052414) | dc-4636000-0 (+1) | 676 ft [206 m] | cycleway:right=shared_lane | contraflow lane flagged | LTS 3 (no change) | yes |
| G Street Northeast | [1205507344](https://www.openstreetmap.org/way/1205507344) | dc-4637702-0 (+2) | 604 ft [184 m] | cycleway:left=lane, cycleway:left:lane=exclusive, cycleway:left:oneway=-1, cycleway:right=shared_lane, cycleway:right:lane=pictogram | contraflow lane flagged | LTS 2 to 1 | yes |
| Massachusetts Avenue Northeast | [422204107](https://www.openstreetmap.org/way/422204107) | dc-4638852-0 | 591 ft [180 m] | cycleway:both=lane | contraflow lane flagged | LTS 2 (no change) | yes |
| 17th Street Northwest | [6055550](https://www.openstreetmap.org/way/6055550) | dc-4630610-0 (+2) | 554 ft [169 m] | cycleway:right=shared_lane | contraflow lane flagged | LTS 2 (no change) | yes |
| New Hampshire Avenue Northwest | [440942565](https://www.openstreetmap.org/way/440942565) | dc-4631266-0 | 449 ft [137 m] | cycleway:right=shared_lane | contraflow lane flagged | LTS 3 (no change) | yes |
| Ontario Road Northwest | [109663677](https://www.openstreetmap.org/way/109663677) | dc-4634511-0 | 407 ft [124 m] | no cycleway tag | contraflow lane flagged | LTS 1 (no change) | yes |
| Ontario Road Northwest | [1364378490](https://www.openstreetmap.org/way/1364378490) | dc-4631122-0 | 400 ft [122 m] | no cycleway tag | contraflow lane flagged | LTS 1 (no change) | yes |
| E Street Southeast | [50473187](https://www.openstreetmap.org/way/50473187) | dc-4640031-0 | 384 ft [117 m] | cycleway:both=lane, cycleway:both:lane=exclusive | contraflow lane flagged | LTS 2 to 3 | yes |
| M Street Northeast | [1257758384](https://www.openstreetmap.org/way/1257758384) | dc-4636275-0 | 302 ft [92 m] | cycleway:right=shared_lane | contraflow lane flagged | LTS 3 (no change) | yes |
| Massachusetts Avenue Northeast | [229105895](https://www.openstreetmap.org/way/229105895) | dc-4638852-0 | 148 ft [45 m] | cycleway:right=lane | contraflow lane flagged | LTS 2 (no change) | yes |
| (unnamed) | [331912753](https://www.openstreetmap.org/way/331912753) | dc-4636276-0 | 144 ft [44 m] | no cycleway tag | contraflow lane flagged | LTS 2 to 1 | yes |
| 10th Street Northeast | [928153007](https://www.openstreetmap.org/way/928153007) | dc-4639225-0 | 135 ft [41 m] | cycleway:left=lane, cycleway:left:oneway=-1, cycleway:right=shared_lane, cycleway:right:lane=pictogram | contraflow lane flagged | LTS 2 to 1 | yes |
| Massachusetts Avenue Northeast | [6057312](https://www.openstreetmap.org/way/6057312) | dc-4638852-0 | 131 ft [40 m] | cycleway:right=lane | contraflow lane flagged | LTS 2 (no change) | yes |
| 17th Street Northwest | [1111546581](https://www.openstreetmap.org/way/1111546581) | dc-4630717-0 | 79 ft [24 m] | cycleway:right=lane | contraflow lane flagged | LTS 2 (no change) | yes |
| New Hampshire Avenue Northwest | [1111550082](https://www.openstreetmap.org/way/1111550082) | dc-4634202-0 | 79 ft [24 m] | cycleway:right=shared_lane | contraflow lane flagged | LTS 3 (no change) | yes |
| E Street Southeast | [50507958](https://www.openstreetmap.org/way/50507958) | dc-4640031-0 | 75 ft [23 m] | cycleway:right=lane, cycleway:right:lane=exclusive | contraflow lane flagged | LTS 2 to 3 | yes |

## Contraflow lane: not applied, the 25 longest of 32

| street | OSM way | DC block | length | OSM | DC | tier | applied |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 17th Street Northwest | [130444170](https://www.openstreetmap.org/way/130444170) | dc-4633881-0 (+3) | 0.19 mi [307 m] | cycleway:left=separate, cycleway:right=shared_lane | contraflow lane flagged | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| Pomeroy Road Southeast | [6051305](https://www.openstreetmap.org/way/6051305) | dc-4641158-0 (+3) | 919 ft [280 m] | no cycleway tag | contraflow lane flagged | LTS 2 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| 17th Street Northwest | [1111546584](https://www.openstreetmap.org/way/1111546584) | dc-4626180-0 (+2) | 853 ft [260 m] | cycleway=separate | contraflow lane flagged | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| North Carolina Avenue Northeast | [50515734](https://www.openstreetmap.org/way/50515734) | dc-4637749-0 (+1) | 794 ft [242 m] | cycleway:left=no, cycleway:right=separate | contraflow lane flagged | LTS 1 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| 6th Street Northeast | [807874680](https://www.openstreetmap.org/way/807874680) | dc-4635217-0 (+1) | 568 ft [173 m] | cycleway=separate | contraflow lane flagged | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| 6th Street Northeast | [1024231035](https://www.openstreetmap.org/way/1024231035) | dc-4635708-0 (+2) | 548 ft [167 m] | cycleway=separate | contraflow lane flagged | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| 8th Street Northwest | [1340682789](https://www.openstreetmap.org/way/1340682789) | dc-4633771-0 | 505 ft [154 m] | cycleway=shared_lane | contraflow lane flagged | LTS 2 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| I Street Southeast | [265733214](https://www.openstreetmap.org/way/265733214) | dc-4642636-0 | 459 ft [140 m] | cycleway=separate | contraflow lane flagged | LTS 1 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| 8th Street Northwest | [1223411289](https://www.openstreetmap.org/way/1223411289) | dc-4630450-0 | 420 ft [128 m] | cycleway=shared_lane | contraflow lane flagged | LTS 2 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| 17th Street Northwest | [1111546582](https://www.openstreetmap.org/way/1111546582) | dc-4634088-0 (+1) | 404 ft [123 m] | cycleway:right=shared_lane | contraflow lane flagged | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| McDonald Place Northeast | [6061239](https://www.openstreetmap.org/way/6061239) | dc-4637108-0 | 397 ft [121 m] | cycleway:left=lane, cycleway:right=shared_lane | contraflow lane flagged | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| Champlain Street Northwest | [6060358](https://www.openstreetmap.org/way/6060358) | dc-4630583-0 (+1) | 374 ft [114 m] | cycleway:right=shared_lane | contraflow lane flagged | LTS 2 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| 4th Street Northwest | [50842701](https://www.openstreetmap.org/way/50842701) | dc-4626142-0 | 354 ft [108 m] | cycleway:left=separate, cycleway:right=shared_lane | contraflow lane flagged | LTS 1 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| Kentucky Avenue Southeast | [130808359](https://www.openstreetmap.org/way/130808359) | dc-4641983-0 | 253 ft [77 m] | cycleway:left=separate, cycleway:right=lane | contraflow lane flagged | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| 17th Street Northwest | [1111546583](https://www.openstreetmap.org/way/1111546583) | dc-4633907-0 | 233 ft [71 m] | cycleway=separate | contraflow lane flagged | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| Illinois Avenue Northwest | [806297678](https://www.openstreetmap.org/way/806297678) | dc-4633270-0 | 203 ft [62 m] | cycleway:left=separate, cycleway:right=lane | contraflow lane flagged | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| O Street Northwest | [6063021](https://www.openstreetmap.org/way/6063021) | dc-4631011-0 | 187 ft [57 m] | cycleway:right=lane | contraflow lane flagged | LTS 2 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| Woodley Place Northwest | [1042798288](https://www.openstreetmap.org/way/1042798288) | dc-4636165-0 | 177 ft [54 m] | cycleway:left=separate, cycleway:left:lane=exclusive, cycleway:left:oneway=-1, cycleway:right=shared_lane, cycleway:right:lane=pictogram | contraflow lane flagged | LTS 1 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| 9th Street Northwest | [397321706](https://www.openstreetmap.org/way/397321706) | dc-4632294-0 | 154 ft [47 m] | cycleway:left=separate, cycleway:right=no | contraflow lane flagged | LTS 3 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| 9th Street Northwest | [409551583](https://www.openstreetmap.org/way/409551583) | dc-4632294-0 | 148 ft [45 m] | cycleway:left=separate, cycleway:right=no | contraflow lane flagged | LTS 3 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| New Jersey Avenue Southeast | [1128059084](https://www.openstreetmap.org/way/1128059084) | dc-4641040-0 | 148 ft [45 m] | cycleway=separate | contraflow lane flagged | LTS 1 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| Champlain Street Northwest | [49301283](https://www.openstreetmap.org/way/49301283) | dc-4633223-0 | 138 ft [42 m] | cycleway:right=shared_lane | contraflow lane flagged | LTS 2 (not applied) | no: carriageway: the other direction's lane, or no contraflow flag |
| McDonald Place Northeast | [1443801106](https://www.openstreetmap.org/way/1443801106) | dc-4637108-0 | 118 ft [36 m] | cycleway:left=separate, cycleway:right=shared_lane | contraflow lane flagged | LTS 1 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| North Carolina Avenue Northeast | [6056826](https://www.openstreetmap.org/way/6056826) | dc-4636222-0 | 105 ft [32 m] | cycleway:left=no, cycleway:right=separate | contraflow lane flagged | LTS 1 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |
| 17th Street Northwest | [1204314682](https://www.openstreetmap.org/way/1204314682) | dc-4633734-0 | 72 ft [22 m] | cycleway=separate | contraflow lane flagged | LTS 2 (not applied) | no: separate: OSM maps the facility as its own way beside the road or its other carriageway |

## One-way: applied, the 25 longest of 358

| street | OSM way | DC block | length | OSM | DC | tier | applied |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Ellipse Road Northwest | [50792782](https://www.openstreetmap.org/way/50792782) | dc-4629956-0 (+1) | 0.61 mi [979 m] | oneway=yes | two-way | LTS 1 (no change) | yes |
| Ohio Drive Southwest | [130927049](https://www.openstreetmap.org/way/130927049) | dc-4641948-0 | 0.39 mi [630 m] | not tagged (two-way) | one-way | LTS 2 (no change) | yes |
| Crittenden Street Northeast | [6053624](https://www.openstreetmap.org/way/6053624) | dc-4638223-0 (+2) | 0.37 mi [589 m] | not tagged (two-way) | one-way | LTS 1 (no change) | yes |
| Springhouse Road | [120907202](https://www.openstreetmap.org/way/120907202) | dc-4634766-0 | 0.32 mi [511 m] | oneway=yes | two-way | LTS 1 (no change) | yes |
| 4th Avenue | [6060495](https://www.openstreetmap.org/way/6060495) | dc-4643378-0 | 0.29 mi [462 m] | not tagged (two-way) | one-way | LTS 1 (no change) | yes |
| South Capitol Street Southwest | [910656491](https://www.openstreetmap.org/way/910656491) | dc-4642085-0 | 0.28 mi [454 m] | oneway=yes | two-way | LTS 4 (no change) | yes |
| Park Road Northwest | [6061744](https://www.openstreetmap.org/way/6061744) | dc-4637075-0 (+1) | 0.28 mi [447 m] | oneway=yes | two-way | LTS 2 (no change) | yes |
| Boundary Road Southwest | [6053009](https://www.openstreetmap.org/way/6053009) | dc-4641145-0 | 0.26 mi [412 m] | oneway=yes | two-way | LTS 1 (no change) | yes |
| Buchanan Street Northeast | [77449775](https://www.openstreetmap.org/way/77449775) | dc-4635597-0 (+2) | 0.24 mi [381 m] | not tagged (two-way) | one-way | LTS 2 (no change) | yes |
| T Street Northeast | [6056792](https://www.openstreetmap.org/way/6056792) | dc-4637928-0 (+1) | 0.22 mi [361 m] | oneway=yes | two-way | LTS 2 to 1 | yes |
| 8th Street Northeast | [132577766](https://www.openstreetmap.org/way/132577766) | dc-4638077-0 (+2) | 0.21 mi [330 m] | oneway=yes | two-way | LTS 1 (no change) | yes |
| Buchanan Street Northeast | [1515745140](https://www.openstreetmap.org/way/1515745140) | dc-4636944-0 (+1) | 0.20 mi [325 m] | not tagged (two-way) | one-way | LTS 1 (no change) | yes |
| Emerson Street Northwest | [553575491](https://www.openstreetmap.org/way/553575491) | dc-4634295-0 | 0.19 mi [307 m] | oneway=yes | two-way | LTS 1 (no change) | yes |
| 8th Street Northeast | [1502134924](https://www.openstreetmap.org/way/1502134924) | dc-4635142-0 (+1) | 0.19 mi [305 m] | oneway=yes | two-way | LTS 1 (no change) | yes |
| 4th Avenue | [340368804](https://www.openstreetmap.org/way/340368804) | dc-4642738-0 (+1) | 951 ft [290 m] | not tagged (two-way) | one-way | LTS 1 (no change) | yes |
| Hawthorne Street Northwest | [6054279](https://www.openstreetmap.org/way/6054279) | dc-4633969-0 | 945 ft [288 m] | oneway=yes | two-way | LTS 1 (no change) | yes |
| Reno Road Northwest | [112319055](https://www.openstreetmap.org/way/112319055) | dc-4634813-0 (+1) | 938 ft [286 m] | not tagged (two-way) | one-way | LTS 3 (no change) | yes |
| 7th Street Northeast | [403681734](https://www.openstreetmap.org/way/403681734) | dc-4636560-0 (+1) | 932 ft [284 m] | not tagged (two-way) | one-way | LTS 1 (no change) | yes |
| Allison Street Northeast | [6055061](https://www.openstreetmap.org/way/6055061) | dc-4635733-0 (+2) | 922 ft [281 m] | not tagged (two-way) | one-way | LTS 1 (no change) | yes |
| Pomeroy Road Southeast | [6051305](https://www.openstreetmap.org/way/6051305) | dc-4641158-0 (+3) | 919 ft [280 m] | not tagged (two-way) | one-way | LTS 2 (no change) | yes |
| Texas Avenue Southeast | [6054286](https://www.openstreetmap.org/way/6054286) | dc-4640806-0 (+2) | 909 ft [277 m] | not tagged (two-way) | one-way | LTS 1 (no change) | yes |
| Brookley Avenue Southwest | [131118564](https://www.openstreetmap.org/way/131118564) | dc-4643155-0 | 906 ft [276 m] | oneway=yes | two-way | LTS 1 (no change) | yes |
| 6th Street Northwest | [275400465](https://www.openstreetmap.org/way/275400465) | dc-4634490-0 | 906 ft [276 m] | oneway=yes | two-way | LTS 1 (no change) | yes |
| Channing Street Northwest | [6057631](https://www.openstreetmap.org/way/6057631) | dc-4631708-0 | 899 ft [274 m] | oneway=yes | two-way | LTS 1 (no change) | yes |
| C Street Southeast | [581831508](https://www.openstreetmap.org/way/581831508) | dc-4642969-0 | 892 ft [272 m] | oneway=yes | two-way | LTS 1 (no change) | yes |

## One-way: not applied, the 25 longest of 2,767

| street | OSM way | DC block | length | OSM | DC | tier | applied |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Suitland Parkway Southeast | [252973249](https://www.openstreetmap.org/way/252973249) | dc-4640033-0 | 1.06 mi [1,705 m] | oneway=yes | two-way | LTS 4 (not applied) | no: divided carriageway |
| Bladensburg Road Northeast | [964927478](https://www.openstreetmap.org/way/964927478) | dc-4639116-0 (+4) | 0.72 mi [1,151 m] | oneway=yes | two-way | LTS 4 (not applied) | no: divided carriageway |
| North Capitol Street Northeast | [50752704](https://www.openstreetmap.org/way/50752704) | dc-4640081-0 | 0.71 mi [1,144 m] | oneway=yes | two-way | LTS 4 (not applied) | no: carriageway pair |
| Suitland Parkway Southeast | [379685261](https://www.openstreetmap.org/way/379685261) | dc-4640033-0 | 0.71 mi [1,140 m] | oneway=yes | two-way | LTS 4 (not applied) | no: divided carriageway |
| Dalecarlia Parkway Northwest | [124688166](https://www.openstreetmap.org/way/124688166) | dc-4630144-0 (+1) | 0.70 mi [1,121 m] | oneway=yes | two-way | LTS 4 (not applied) | no: divided carriageway |
| Dalecarlia Parkway Northwest | [130788122](https://www.openstreetmap.org/way/130788122) | dc-4630144-0 (+1) | 0.69 mi [1,113 m] | oneway=yes | two-way | LTS 4 (not applied) | no: divided carriageway |
| Suitland Parkway Southeast | [362668009](https://www.openstreetmap.org/way/362668009) | dc-4641412-0 (+2) | 0.69 mi [1,105 m] | oneway=yes | two-way | LTS 4 (not applied) | no: divided carriageway |
| South Capitol Street Southeast | [590525514](https://www.openstreetmap.org/way/590525514) | dc-4640239-0 | 0.64 mi [1,035 m] | oneway=yes | two-way | LTS 4 (not applied) | no: carriageway pair |
| South Capitol Street Southwest | [50477492](https://www.openstreetmap.org/way/50477492) | dc-4640239-0 | 0.59 mi [957 m] | oneway=yes | two-way | LTS 4 (not applied) | no: carriageway pair |
| G Street Northeast | [708853143](https://www.openstreetmap.org/way/708853143) | dc-4636440-0 (+5) | 0.58 mi [939 m] | oneway=yes | two-way | LTS 2 (not applied) | no: one-way blocks along it |
| MacArthur Boulevard Northwest | [6053797](https://www.openstreetmap.org/way/6053797) | dc-4631483-0 (+5) | 0.54 mi [876 m] | oneway=yes | two-way | LTS 3 (not applied) | no: divided carriageway |
| MacArthur Boulevard Northwest | [285960691](https://www.openstreetmap.org/way/285960691) | dc-4631483-0 (+5) | 0.54 mi [874 m] | oneway=yes | two-way | LTS 3 (not applied) | no: divided carriageway |
| North Capitol Street Northwest | [130772884](https://www.openstreetmap.org/way/130772884) | dc-4640081-0 | 0.54 mi [870 m] | oneway=yes | two-way | LTS 4 (not applied) | no: carriageway pair |
| Whitehurst Freeway | [24260117](https://www.openstreetmap.org/way/24260117) | dc-4636053-0 | 0.53 mi [852 m] | oneway=yes | two-way | LTS 4 (not applied) | no: slip road or freeway |
| Military Road Northwest | [355228838](https://www.openstreetmap.org/way/355228838) | dc-4631804-0 | 0.50 mi [804 m] | oneway=yes | two-way | LTS 4 (not applied) | no: divided carriageway |
| Military Road Northwest | [24976161](https://www.openstreetmap.org/way/24976161) | dc-4631804-0 | 0.47 mi [762 m] | oneway=yes | two-way | LTS 4 (not applied) | no: divided carriageway |
| Clara Barton Parkway Northwest | [5976883](https://www.openstreetmap.org/way/5976883) | dc-4632096-0 | 0.47 mi [753 m] | lanes counted each way | one-way | LTS 4 (not applied) | no: reversible lanes |
| New York Avenue Northeast | [131446920](https://www.openstreetmap.org/way/131446920) | dc-4635574-0 | 0.45 mi [727 m] | oneway=yes | two-way | LTS 4 (not applied) | no: slip road or freeway |
| Suitland Parkway Southeast | [362668008](https://www.openstreetmap.org/way/362668008) | dc-4640606-0 (+1) | 0.45 mi [724 m] | oneway=yes | two-way | LTS 4 (not applied) | no: divided carriageway |
| New York Avenue Northeast | [871089760](https://www.openstreetmap.org/way/871089760) | dc-4635734-0 | 0.44 mi [712 m] | oneway=yes | two-way | LTS 4 (not applied) | no: slip road or freeway |
| Cleveland Avenue Northwest | [203671710](https://www.openstreetmap.org/way/203671710) | dc-4632052-0 (+3) | 0.42 mi [676 m] | oneway=yes | two-way | LTS 3 (not applied) | no: divided carriageway |
| Pennsylvania Avenue Southeast | [130285141](https://www.openstreetmap.org/way/130285141) | dc-4639908-0 (+4) | 0.40 mi [650 m] | oneway=yes | two-way | LTS 4 (not applied) | no: divided carriageway |
| Pennsylvania Avenue Southeast | [203022895](https://www.openstreetmap.org/way/203022895) | dc-4639908-0 (+4) | 0.40 mi [650 m] | oneway=yes | two-way | LTS 4 (not applied) | no: divided carriageway |
| 16th Street Northwest | [105743118](https://www.openstreetmap.org/way/105743118) | dc-4632713-0 (+3) | 0.40 mi [643 m] | oneway=yes | two-way | LTS 4 (not applied) | no: divided carriageway |
| Bladensburg Road Northeast | [789803121](https://www.openstreetmap.org/way/789803121) | dc-4639116-0 | 0.40 mi [641 m] | oneway=yes | two-way | LTS 4 (not applied) | no: divided carriageway |

## Through lanes per direction: applied, the 25 longest of 2,667

| street | OSM way | DC block | length | OSM | DC | tier | applied |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Ohio Drive Southwest | [130908180](https://www.openstreetmap.org/way/130908180) | dc-4640995-0 (+1) | 2.52 mi [4,062 m] | 1 a direction | 2 a direction | LTS 1 to 3 | yes |
| Canal Road Northwest | [535538534](https://www.openstreetmap.org/way/535538534) | dc-4630274-0 (+1) | 1.69 mi [2,719 m] | 1 a direction | 2 a direction | LTS 4 (no change) | yes |
| Brookley Avenue Southwest | [6061628](https://www.openstreetmap.org/way/6061628) | dc-4639739-0 (+4) | 1.01 mi [1,633 m] | 1 a direction | 2 a direction | LTS 1 to 3 | yes |
| 18th Street Northeast | [130908285](https://www.openstreetmap.org/way/130908285) | dc-4637823-0 (+5) | 0.70 mi [1,120 m] | 1 a direction | 2 a direction | LTS 3 (no change) | yes |
| Georgia Avenue Northwest | [346681296](https://www.openstreetmap.org/way/346681296) | dc-4630444-0 (+5) | 0.67 mi [1,078 m] | 2 a direction | 3 a direction | LTS 3 to 4 | yes |
| Overlook Avenue Southwest | [355230038](https://www.openstreetmap.org/way/355230038) | dc-4640390-0 | 0.61 mi [979 m] | 1 a direction | 2 a direction | LTS 3 (no change) | yes |
| South Capitol Street Southwest | [50477492](https://www.openstreetmap.org/way/50477492) | dc-4640239-0 | 0.59 mi [957 m] | 2 a direction | 4 a direction | LTS 4 (no change) | yes |
| Anacostia Freeway | [50477475](https://www.openstreetmap.org/way/50477475) | dc-4640519-0 | 0.57 mi [915 m] | 3 a direction | 2 a direction | LTS 4 (no change) | yes |
| Georgia Avenue Northwest | [1321779006](https://www.openstreetmap.org/way/1321779006) | dc-4625882-0 (+5) | 0.55 mi [879 m] | 2 a direction | 3 a direction | LTS 3 to 4 | yes |
| South Dakota Avenue Northeast | [583945349](https://www.openstreetmap.org/way/583945349) | dc-4639555-0 (+5) | 0.48 mi [769 m] | 2 a direction | 4 a direction | LTS 3 (no change) | yes |
| Park Place Northwest | [29234999](https://www.openstreetmap.org/way/29234999) | dc-4637031-0 (+5) | 0.47 mi [762 m] | 1 a direction | 2 a direction | LTS 2 (no change) | yes |
| 5th Street Northwest | [6059235](https://www.openstreetmap.org/way/6059235) | dc-4630031-0 (+5) | 0.46 mi [739 m] | 1 a direction | 2 a direction | LTS 1 to 3 | yes |
| Martin Luther King Junior Avenue Southeast | [1063372431](https://www.openstreetmap.org/way/1063372431) | dc-4642742-0 (+4) | 0.44 mi [704 m] | 1 a direction | 2 a direction | LTS 3 to 4 | yes |
| Canal Road Northwest | [50773204](https://www.openstreetmap.org/way/50773204) | dc-4634031-0 | 0.44 mi [702 m] | 1 a direction | 2 a direction | LTS 4 (no change) | yes |
| Cleveland Avenue Northwest | [203671710](https://www.openstreetmap.org/way/203671710) | dc-4632052-0 (+3) | 0.42 mi [676 m] | 2 a direction | 1 a direction | LTS 3 (no change) | yes |
| Anacostia Drive Southeast | [1528336424](https://www.openstreetmap.org/way/1528336424) | dc-4641429-0 (+1) | 0.42 mi [675 m] | 1 a direction | 2 a direction | LTS 1 to 3 | yes |
| Anacostia Freeway | [50331772](https://www.openstreetmap.org/way/50331772) | dc-4642178-0 | 0.41 mi [659 m] | 2 a direction | 3 a direction | LTS 4 (no change) | yes |
| South Capitol Street | [535462113](https://www.openstreetmap.org/way/535462113) | dc-4640885-0 (+4) | 0.41 mi [657 m] | 2 a direction | 3 a direction | LTS 3 (no change) | yes |
| Reservoir Road Northwest | [130889729](https://www.openstreetmap.org/way/130889729) | dc-4638309-0 (+3) | 0.40 mi [638 m] | 1 a direction | 3 a direction | LTS 3 (no change) | yes |
| 22nd Street Northwest | [50524890](https://www.openstreetmap.org/way/50524890) | dc-4633296-0 (+5) | 0.40 mi [636 m] | 3 a direction | 1 a direction | LTS 3 (no change) | yes |
| Ohio Drive Southwest | [130927049](https://www.openstreetmap.org/way/130927049) | dc-4641948-0 | 0.39 mi [630 m] | 1 a direction | 2 a direction | LTS 2 (no change) | yes |
| Martin Luther King Junior Avenue Southeast | [1410025391](https://www.openstreetmap.org/way/1410025391) | dc-4641442-0 (+2) | 0.38 mi [619 m] | 2 a direction | 3 a direction | LTS 3 to 4 | yes |
| Anacostia Freeway | [50331774](https://www.openstreetmap.org/way/50331774) | dc-4642178-0 | 0.38 mi [604 m] | 2 a direction | 3 a direction | LTS 4 (no change) | yes |
| Rhode Island Avenue Northeast | [125568095](https://www.openstreetmap.org/way/125568095) | dc-4636283-0 (+3) | 0.36 mi [580 m] | 3 a direction | 2 a direction | LTS 3 (no change) | yes |
| 12th Street Northwest | [130788207](https://www.openstreetmap.org/way/130788207) | dc-4630911-0 (+4) | 0.36 mi [576 m] | 1 a direction | 2 a direction | LTS 2 (no change) | yes |

## Through lanes per direction: not applied, the 25 longest of 366

| street | OSM way | DC block | length | OSM | DC | tier | applied |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Clara Barton Parkway Northwest | [5976883](https://www.openstreetmap.org/way/5976883) | dc-4632096-0 | 0.47 mi [753 m] | 1 a direction | 2 a direction | LTS 4 (not applied) | no: DC records one direction of a two-way way |
| (unnamed) | [546095941](https://www.openstreetmap.org/way/546095941) | dc-4642178-0 | 0.33 mi [536 m] | 2 a direction | 3 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [6051912](https://www.openstreetmap.org/way/6051912) | dc-4643038-0 (+2) | 0.32 mi [507 m] | 2 a direction | 3 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| 395 Express Lane | [49077542](https://www.openstreetmap.org/way/49077542) | dc-4641301-0 (+1) | 0.28 mi [453 m] | 1 a direction | 4 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [1181165211](https://www.openstreetmap.org/way/1181165211) | dc-4640519-0 | 0.27 mi [437 m] | 1 a direction | 2 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [6052463](https://www.openstreetmap.org/way/6052463) | dc-4636810-0 (+1) | 0.27 mi [427 m] | 1 a direction | 4 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [296788578](https://www.openstreetmap.org/way/296788578) | dc-4642838-0 | 0.25 mi [396 m] | 1 a direction | 4 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [980693845](https://www.openstreetmap.org/way/980693845) | dc-4640519-0 | 0.24 mi [388 m] | 1 a direction | 2 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [50429940](https://www.openstreetmap.org/way/50429940) | dc-4640637-0 (+1) | 0.24 mi [385 m] | 1 a direction | 4 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [50427051](https://www.openstreetmap.org/way/50427051) | dc-4634271-0 (+1) | 0.22 mi [360 m] | 2 a direction | 3 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [24223005](https://www.openstreetmap.org/way/24223005) | dc-4642727-0 (+1) | 0.22 mi [359 m] | 2 a direction | 3 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [6053255](https://www.openstreetmap.org/way/6053255) | dc-4640135-0 | 0.21 mi [332 m] | 1 a direction | 2 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [50524895](https://www.openstreetmap.org/way/50524895) | dc-4639011-0 | 0.20 mi [327 m] | 1 a direction | 2 a direction | LTS 3 (not applied) | no: slip road: its own lanes |
| (unnamed) | [6053509](https://www.openstreetmap.org/way/6053509) | dc-4640390-0 (+1) | 0.20 mi [324 m] | 1 a direction | 2 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [296127984](https://www.openstreetmap.org/way/296127984) | dc-4640519-0 | 0.20 mi [320 m] | 1 a direction | 2 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [121980319](https://www.openstreetmap.org/way/121980319) | dc-4642972-0 (+1) | 0.20 mi [318 m] | 1 a direction | 3 a direction | LTS 3 (not applied) | no: slip road: its own lanes |
| (unnamed) | [50427962](https://www.openstreetmap.org/way/50427962) | dc-4632142-0 (+1) | 0.19 mi [308 m] | 1 a direction | 4 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [6051765](https://www.openstreetmap.org/way/6051765) | dc-4642727-0 | 0.19 mi [305 m] | 1 a direction | 3 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| 395 Express Lane | [374376244](https://www.openstreetmap.org/way/374376244) | dc-4642265-0 (+1) | 0.19 mi [305 m] | 1 a direction | 3 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [50505139](https://www.openstreetmap.org/way/50505139) | dc-4642997-0 | 984 ft [300 m] | 2 a direction | 4 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [1011922213](https://www.openstreetmap.org/way/1011922213) | dc-4640135-0 | 971 ft [296 m] | 1 a direction | 2 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [50502442](https://www.openstreetmap.org/way/50502442) | dc-4642997-0 | 968 ft [295 m] | 1 a direction | 4 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [50503609](https://www.openstreetmap.org/way/50503609) | dc-4640700-0 (+1) | 935 ft [285 m] | 1 a direction | 3 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [6051500](https://www.openstreetmap.org/way/6051500) | dc-4640700-0 | 896 ft [273 m] | 1 a direction | 3 a direction | LTS 4 (not applied) | no: slip road: its own lanes |
| (unnamed) | [50477493](https://www.openstreetmap.org/way/50477493) | dc-4640239-0 | 889 ft [271 m] | 2 a direction | 4 a direction | LTS 4 (not applied) | no: slip road: its own lanes |

## Posted speed: applied, the 25 longest of 1,585

| street | OSM way | DC block | length | OSM | DC | tier | applied |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Canal Road Northwest | [535538534](https://www.openstreetmap.org/way/535538534) | dc-4630274-0 (+1) | 1.69 mi [2,719 m] | 40 mph | 35 mph | LTS 4 (no change) | yes |
| Chappie James Boulevard Southwest | [135843310](https://www.openstreetmap.org/way/135843310) | dc-4641579-0 (+5) | 1.05 mi [1,689 m] | 30 mph | 20 mph | LTS 3 (no change) | yes |
| Duncan Avenue Southwest | [6054359](https://www.openstreetmap.org/way/6054359) | dc-4641705-0 (+5) | 1.04 mi [1,679 m] | 25 mph | 20 mph | LTS 2 to 1 | yes |
| Allison Street Northwest | [808403215](https://www.openstreetmap.org/way/808403215) | dc-4631135-0 (+5) | 0.75 mi [1,209 m] | 15 mph | 20 mph | LTS 1 (no change) | yes |
| Broad Branch Road Northwest | [83423475](https://www.openstreetmap.org/way/83423475) | dc-4625998-0 (+1) | 0.70 mi [1,123 m] | 25 mph | 20 mph | LTS 3 (no change) | yes |
| Anacostia Freeway | [50331773](https://www.openstreetmap.org/way/50331773) | dc-4643116-0 | 0.68 mi [1,102 m] | 40 mph | 20 mph | LTS 4 (no change) | yes |
| Ross Drive Northwest | [24963155](https://www.openstreetmap.org/way/24963155) | dc-4635643-0 | 0.66 mi [1,057 m] | 20 mph | 25 mph | LTS 1 to 2 | yes |
| Arnold Avenue Southwest | [131118538](https://www.openstreetmap.org/way/131118538) | dc-4640508-0 (+5) | 0.63 mi [1,020 m] | 25 mph | 20 mph | LTS 2 to 1 | yes |
| Ellipse Road Northwest | [50792782](https://www.openstreetmap.org/way/50792782) | dc-4629956-0 (+1) | 0.61 mi [979 m] | 15 mph | 20 mph | LTS 1 (no change) | yes |
| Albemarle Street Northwest | [1116377394](https://www.openstreetmap.org/way/1116377394) | dc-4632051-0 (+4) | 0.59 mi [946 m] | 25 mph | 20 mph | LTS 2 (no change) | yes |
| 29th Street Northwest | [45532017](https://www.openstreetmap.org/way/45532017) | dc-4633708-0 (+5) | 0.59 mi [943 m] | 25 mph | 20 mph | LTS 2 to 1 | yes |
| N Street Northwest | [6061868](https://www.openstreetmap.org/way/6061868) | dc-4631965-0 (+5) | 0.58 mi [932 m] | 25 mph | 20 mph | LTS 2 to 1 | yes |
| A Street Northeast | [6059017](https://www.openstreetmap.org/way/6059017) | dc-4638428-0 (+5) | 0.56 mi [908 m] | 25 mph | 20 mph | LTS 2 to 1 | yes |
| Whitehurst Freeway | [24260117](https://www.openstreetmap.org/way/24260117) | dc-4636053-0 | 0.53 mi [852 m] | 35 mph | 20 mph | LTS 4 (no change) | yes |
| Broad Branch Road Northwest | [130907973](https://www.openstreetmap.org/way/130907973) | dc-4631262-0 (+5) | 0.52 mi [830 m] | 20 mph | 25 mph | LTS 1 to 2 | yes |
| Connecticut Avenue Northwest | [344674243](https://www.openstreetmap.org/way/344674243) | dc-4630071-0 (+5) | 0.50 mi [807 m] | 25 mph | 30 mph | LTS 3 to 4 | yes |
| O Street Northwest | [6063018](https://www.openstreetmap.org/way/6063018) | dc-4633994-0 (+5) | 0.49 mi [784 m] | 25 mph | 20 mph | LTS 2 to 1 | yes |
| A Street Southeast | [6061639](https://www.openstreetmap.org/way/6061639) | dc-4641562-0 (+5) | 0.48 mi [770 m] | 25 mph | 20 mph | LTS 2 to 1 | yes |
| George Washington Memorial Parkway | [397351808](https://www.openstreetmap.org/way/397351808) | dc-4642648-0 (+1) | 0.48 mi [767 m] | 40 mph | 20 mph | LTS 4 (no change) | yes |
| 7th Street Northwest | [131520280](https://www.openstreetmap.org/way/131520280) | dc-4631778-0 (+5) | 0.46 mi [739 m] | 20 mph | 25 mph | LTS 2 (no change) | yes |
| New York Avenue Northeast | [131446920](https://www.openstreetmap.org/way/131446920) | dc-4635574-0 | 0.45 mi [727 m] | 40 mph | 45 mph | LTS 4 (no change) | yes |
| New York Avenue Northeast | [871089760](https://www.openstreetmap.org/way/871089760) | dc-4635734-0 | 0.44 mi [712 m] | 40 mph | 45 mph | LTS 4 (no change) | yes |
| Martin Luther King Junior Avenue Southeast | [1063372431](https://www.openstreetmap.org/way/1063372431) | dc-4642742-0 (+4) | 0.44 mi [704 m] | 25 mph | 30 mph | LTS 3 to 4 | yes |
| Canal Road Northwest | [50773204](https://www.openstreetmap.org/way/50773204) | dc-4634031-0 | 0.44 mi [702 m] | 40 mph | 35 mph | LTS 4 (no change) | yes |
| Northampton Street Northwest | [6056404](https://www.openstreetmap.org/way/6056404) | dc-4633414-0 (+3) | 0.43 mi [700 m] | 25 mph | 20 mph | LTS 2 to 1 | yes |
