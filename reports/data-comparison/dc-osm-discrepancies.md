# DC Roadway Block against OSM: where they disagree

For the owner's review (OWNER-DECISIONS 191: "DC roads and especially bike infrastructure changes quite frequently, so it's likely OSM data is stale. However, report the discrepancies when you see them."). Every District road way a Roadway Block was matched to, where the block's record and the way's OSM tags say different things. The District's value is what the classifier reads (OWNER-DECISIONS 190) except where a block, which describes the whole road, cannot speak for one of its ways, or the owner has withheld it (an owner override, item 197); those are **not applied**, summarised below by reason. This copy is written from `dcbal.tsv` (`scripts/analysis/data_before_after.py`) with the before-after report; each rebuild writes its own to `<DATA_ROOT>/rebuild/reports/`. Every item, applied or not, is a row of `dc-osm-discrepancies.csv`.

Nothing here is for importing into OSM: the Roadway Block is CC BY 4.0, and copying its values into OSM (ODbL) would need a licence waiver from the District.

13,409 matched District ways (1,233 mi). A way can appear under several types. Tiers are the way's tier with OSM's tags alone and with the District's record applied (all of it, not only this attribute). Where OSM has no value (no `maxspeed`, no `lanes`) the District's fills it, and that is not counted here.

| type | ways | miles | applied: ways | applied: miles | not applied: ways | not applied: miles | applied, tier changed: ways |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Bike facility present or absent | 567 | 30.7 | 233 | 11.4 | 334 | 19.3 | 144 |
| Facility kind (painted, buffered, protected) | 135 | 5.8 | 98 | 4.3 | 37 | 1.5 | 43 |
| Contraflow lane | 53 | 4.2 | 25 | 2.6 | 28 | 1.6 | 7 |
| One-way | 3,125 | 183.1 | 356 | 25.0 | 2,769 | 158.1 | 41 |
| Through lanes per direction | 3,033 | 180.5 | 2,630 | 153.0 | 403 | 27.5 | 541 |
| Posted speed | 1,585 | 132.9 | 1,568 | 131.2 | 17 | 1.7 | 618 |

## Not applied, by reason

Most are the exceptions OWNER-DECISIONS 190 keeps for modelling: a block describes the whole road, so its two-way record says nothing about one carriageway of a divided road or one of a pair of one-way ways, and so on. They are summarised here rather than listed; the examples are the longest ways of each, and `dc-osm-discrepancies.csv` has every one.

| type | reason | ways | miles | longest |
| --- | --- | --- | --- | --- |
| One-way | divided carriageway | 1,717 | 101.5 | Suitland Parkway Southeast [252973249](https://www.openstreetmap.org/way/252973249), Bladensburg Road Northeast [964927478](https://www.openstreetmap.org/way/964927478), Suitland Parkway Southeast [379685261](https://www.openstreetmap.org/way/379685261) |
| One-way | carriageway pair | 697 | 36.6 | North Capitol Street Northeast [50752704](https://www.openstreetmap.org/way/50752704), South Capitol Street Southeast [590525514](https://www.openstreetmap.org/way/590525514), South Capitol Street Southwest [50477492](https://www.openstreetmap.org/way/50477492) |
| Through lanes per direction | slip road: its own lanes | 357 | 24.8 | (unnamed) [546095941](https://www.openstreetmap.org/way/546095941), (unnamed) [6051912](https://www.openstreetmap.org/way/6051912), 395 Express Lane [49077542](https://www.openstreetmap.org/way/49077542) |
| One-way | slip road or freeway | 250 | 15.6 | Whitehurst Freeway [24260117](https://www.openstreetmap.org/way/24260117), New York Avenue Northeast [131446920](https://www.openstreetmap.org/way/131446920), New York Avenue Northeast [871089760](https://www.openstreetmap.org/way/871089760) |
| Bike facility present or absent | separate: OSM maps a facility as its own way beside the road; DC records none | 193 | 12.1 | Ohio Drive Southwest [130908180](https://www.openstreetmap.org/way/130908180), John McCormack Road [132577607](https://www.openstreetmap.org/way/132577607), Rock Creek and Potomac Parkway Northwest [435101942](https://www.openstreetmap.org/way/435101942) |
| Bike facility present or absent | separate: OSM maps the facility as its own way beside the road or its other carriageway | 69 | 2.7 | Virginia Avenue Northwest Service Road [50431280](https://www.openstreetmap.org/way/50431280), (unnamed) [397296948](https://www.openstreetmap.org/way/397296948), Irving Street Northeast [830423226](https://www.openstreetmap.org/way/830423226) |
| One-way | junction stub | 64 | 0.7 | 47th Street Southeast [6056898](https://www.openstreetmap.org/way/6056898), New Jersey Avenue Northwest [1508260473](https://www.openstreetmap.org/way/1508260473), 28th Street Northeast [123534465](https://www.openstreetmap.org/way/123534465) |
| Bike facility present or absent | DC's blocks differ along the way (a lane on some) | 37 | 1.7 | Kentucky Avenue Southeast [229700999](https://www.openstreetmap.org/way/229700999), Kentucky Avenue Southeast [229701007](https://www.openstreetmap.org/way/229701007), Water Street Northwest [137952735](https://www.openstreetmap.org/way/137952735) |
| Through lanes per direction | side lane beside a two-way carriageway | 36 | 2.0 | K Street Northwest [321477125](https://www.openstreetmap.org/way/321477125), Lincoln Memorial Circle Southwest [1093448958](https://www.openstreetmap.org/way/1093448958), K Street Northwest [436136929](https://www.openstreetmap.org/way/436136929) |
| Bike facility present or absent | carriageway: the other direction's lane, or no contraflow flag | 34 | 2.8 | 3rd Street Northeast [6062650](https://www.openstreetmap.org/way/6062650), Franklin Street Northeast [590581627](https://www.openstreetmap.org/way/590581627), (unnamed) [50429940](https://www.openstreetmap.org/way/50429940) |
| Contraflow lane | separate: OSM maps the facility as its own way beside the road or its other carriageway | 26 | 1.4 | 17th Street Northwest [130444170](https://www.openstreetmap.org/way/130444170), 17th Street Northwest [1111546584](https://www.openstreetmap.org/way/1111546584), North Carolina Avenue Northeast [50515734](https://www.openstreetmap.org/way/50515734) |
| Facility kind (painted, buffered, protected) | separate: OSM maps the facility as its own way beside the road or its other carriageway | 25 | 0.7 | Piney Branch Road Northwest [1061530069](https://www.openstreetmap.org/way/1061530069), Piney Branch Road Northwest [29234992](https://www.openstreetmap.org/way/29234992), Kentucky Avenue Southeast [130808359](https://www.openstreetmap.org/way/130808359) |
| Posted speed | owner override | 17 | 1.7 | Whitehurst Freeway [24260117](https://www.openstreetmap.org/way/24260117), Whitehurst Freeway [50430008](https://www.openstreetmap.org/way/50430008), Whitehurst Freeway [397354071](https://www.openstreetmap.org/way/397354071) |
| One-way | direction unknown | 12 | 0.7 | Pierce Street Northeast [6054329](https://www.openstreetmap.org/way/6054329), 4th Street Northeast [807669477](https://www.openstreetmap.org/way/807669477), 4th Street Northeast [29961230](https://www.openstreetmap.org/way/29961230) |
| One-way | one-way blocks along it | 11 | 1.9 | G Street Northeast [708853143](https://www.openstreetmap.org/way/708853143), Dumbarton Street Northwest [131118545](https://www.openstreetmap.org/way/131118545), Madison Street Northwest [402266061](https://www.openstreetmap.org/way/402266061) |
| Through lanes per direction | DC records one direction of a two-way way | 10 | 0.7 | Clara Barton Parkway Northwest [5976883](https://www.openstreetmap.org/way/5976883), Clara Barton Parkway Northwest [889043769](https://www.openstreetmap.org/way/889043769), 1st Street Northeast [1425758436](https://www.openstreetmap.org/way/1425758436) |
| One-way | unnamed | 10 | 0.4 | (unnamed) [191382519](https://www.openstreetmap.org/way/191382519), (unnamed) [807980006](https://www.openstreetmap.org/way/807980006), (unnamed) [191382515](https://www.openstreetmap.org/way/191382515) |
| Facility kind (painted, buffered, protected) | carriageway: the other direction's lane, or no contraflow flag | 6 | 0.5 | Fort Lincoln Drive Northeast [132639295](https://www.openstreetmap.org/way/132639295), Maryland Avenue Northeast [1208534009](https://www.openstreetmap.org/way/1208534009), North Carolina Avenue Southeast [6051497](https://www.openstreetmap.org/way/6051497) |
| Facility kind (painted, buffered, protected) | DC's blocks differ along the way (a lane on some) | 5 | 0.3 | Van Ness Street Northwest [203172528](https://www.openstreetmap.org/way/203172528), Van Ness Street Northwest [681462620](https://www.openstreetmap.org/way/681462620), Van Ness Street Northwest [700136469](https://www.openstreetmap.org/way/700136469) |
| One-way | roundabout | 4 | 0.1 | (unnamed) [156702699](https://www.openstreetmap.org/way/156702699), (unnamed) [296795220](https://www.openstreetmap.org/way/296795220), Chevy Chase Circle [695757047](https://www.openstreetmap.org/way/695757047) |
| Contraflow lane | carriageway: the other direction's lane, or no contraflow flag | 2 | 0.2 | Pomeroy Road Southeast [6051305](https://www.openstreetmap.org/way/6051305), O Street Northwest [6063021](https://www.openstreetmap.org/way/6063021) |
| One-way | reversible lanes | 2 | 0.5 | Clara Barton Parkway Northwest [5976883](https://www.openstreetmap.org/way/5976883), Clara Barton Parkway Northwest [889043769](https://www.openstreetmap.org/way/889043769) |
| One-way | side lane beside a two-way carriageway | 2 | 0.1 | K Street Northwest [924793627](https://www.openstreetmap.org/way/924793627), Cedar Avenue [555136043](https://www.openstreetmap.org/way/555136043) |
| Facility kind (painted, buffered, protected) | OSM says bicycle=no, use_sidepath or cycleway=no | 1 | 0.0 | New Jersey Avenue Northwest [1508314440](https://www.openstreetmap.org/way/1508314440) |
| Bike facility present or absent | OSM says bicycle=no, use_sidepath or cycleway=no | 1 | 0.0 | Arizona Avenue Northwest [50773195](https://www.openstreetmap.org/way/50773195) |

## Owner overrides: every one, 17

The District's value withheld by the owner (OWNER-DECISIONS 197; `agency_blocks` in fixtures/overrides/), so OSM's stands. Listed in full, as the owner asked.

| street | OSM way | DC block | length | OSM | DC | tier | applied |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Canal Road Northwest | [397350557](https://www.openstreetmap.org/way/397350557) | dc-4633425-0 | 978 ft [298 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Canal Road Northwest | [397350552](https://www.openstreetmap.org/way/397350552) | dc-4633425-0 | 489 ft [149 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Canal Road Northwest | [397350555](https://www.openstreetmap.org/way/397350555) | dc-4633425-0 | 299 ft [91 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Canal Road Northwest | [397350554](https://www.openstreetmap.org/way/397350554) | dc-4633425-0 | 161 ft [49 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Canal Road Northwest | [397350549](https://www.openstreetmap.org/way/397350549) | dc-4633425-0 | 82 ft [25 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Whitehurst Freeway | [24260117](https://www.openstreetmap.org/way/24260117) | dc-4636053-0 | 0.53 mi [852 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Whitehurst Freeway | [50430008](https://www.openstreetmap.org/way/50430008) | dc-4636053-0 | 0.23 mi [368 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Whitehurst Freeway | [397354071](https://www.openstreetmap.org/way/397354071) | dc-4636053-0 (+1) | 0.19 mi [309 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Whitehurst Freeway | [235079846](https://www.openstreetmap.org/way/235079846) | dc-4636053-0 | 656 ft [200 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Whitehurst Freeway | [50430007](https://www.openstreetmap.org/way/50430007) | dc-4636053-0 | 472 ft [144 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Whitehurst Freeway | [235079848](https://www.openstreetmap.org/way/235079848) | dc-4636053-0 | 230 ft [70 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Whitehurst Freeway | [469146408](https://www.openstreetmap.org/way/469146408) | dc-4636053-0 | 118 ft [36 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Whitehurst Freeway | [1488503509](https://www.openstreetmap.org/way/1488503509) | dc-4636053-0 | 108 ft [33 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Whitehurst Freeway | [235079847](https://www.openstreetmap.org/way/235079847) | dc-4636053-0 | 95 ft [29 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Whitehurst Freeway | [235079849](https://www.openstreetmap.org/way/235079849) | dc-4636053-0 | 95 ft [29 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Whitehurst Freeway | [50430016](https://www.openstreetmap.org/way/50430016) | dc-4636053-0 | 62 ft [19 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |
| Whitehurst Freeway | [1176510909](https://www.openstreetmap.org/way/1176510909) | dc-4636053-0 | 49 ft [15 m] | 35 mph | 20 mph | LTS 4 (not applied) | no: owner override |

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

## Contraflow lane: applied, the 25 longest of 25

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
| 8th Street Northwest | [1340682789](https://www.openstreetmap.org/way/1340682789) | dc-4633771-0 | 505 ft [154 m] | cycleway=shared_lane | contraflow lane flagged | LTS 1 (no change) | yes |
| New Hampshire Avenue Northwest | [440942565](https://www.openstreetmap.org/way/440942565) | dc-4631266-0 | 449 ft [137 m] | cycleway:right=shared_lane | contraflow lane flagged | LTS 3 (no change) | yes |
| 8th Street Northwest | [1223411289](https://www.openstreetmap.org/way/1223411289) | dc-4630450-0 | 420 ft [128 m] | cycleway=shared_lane | contraflow lane flagged | LTS 1 (no change) | yes |
| Ontario Road Northwest | [109663677](https://www.openstreetmap.org/way/109663677) | dc-4634511-0 | 407 ft [124 m] | no cycleway tag | contraflow lane flagged | LTS 1 (no change) | yes |
| Ontario Road Northwest | [1364378490](https://www.openstreetmap.org/way/1364378490) | dc-4631122-0 | 400 ft [122 m] | no cycleway tag | contraflow lane flagged | LTS 1 (no change) | yes |
| E Street Southeast | [50473187](https://www.openstreetmap.org/way/50473187) | dc-4640031-0 | 384 ft [117 m] | cycleway:both=lane, cycleway:both:lane=exclusive | contraflow lane flagged | LTS 2 to 3 | yes |
| Champlain Street Northwest | [6060358](https://www.openstreetmap.org/way/6060358) | dc-4630583-0 (+1) | 374 ft [114 m] | cycleway:right=shared_lane | contraflow lane flagged | LTS 2 (no change) | yes |
| M Street Northeast | [1257758384](https://www.openstreetmap.org/way/1257758384) | dc-4636275-0 | 302 ft [92 m] | cycleway:right=shared_lane | contraflow lane flagged | LTS 3 (no change) | yes |
| Massachusetts Avenue Northeast | [229105895](https://www.openstreetmap.org/way/229105895) | dc-4638852-0 | 148 ft [45 m] | cycleway:right=lane | contraflow lane flagged | LTS 2 (no change) | yes |
| (unnamed) | [331912753](https://www.openstreetmap.org/way/331912753) | dc-4636276-0 | 144 ft [44 m] | no cycleway tag | contraflow lane flagged | LTS 2 to 1 | yes |
| Champlain Street Northwest | [49301283](https://www.openstreetmap.org/way/49301283) | dc-4633223-0 | 138 ft [42 m] | cycleway:right=shared_lane | contraflow lane flagged | LTS 2 (no change) | yes |
| 10th Street Northeast | [928153007](https://www.openstreetmap.org/way/928153007) | dc-4639225-0 | 135 ft [41 m] | cycleway:left=lane, cycleway:left:oneway=-1, cycleway:right=shared_lane, cycleway:right:lane=pictogram | contraflow lane flagged | LTS 2 to 1 | yes |
| Massachusetts Avenue Northeast | [6057312](https://www.openstreetmap.org/way/6057312) | dc-4638852-0 | 131 ft [40 m] | cycleway:right=lane | contraflow lane flagged | LTS 2 (no change) | yes |
| 17th Street Northwest | [1111546581](https://www.openstreetmap.org/way/1111546581) | dc-4630717-0 | 79 ft [24 m] | cycleway:right=lane | contraflow lane flagged | LTS 2 (no change) | yes |
| New Hampshire Avenue Northwest | [1111550082](https://www.openstreetmap.org/way/1111550082) | dc-4634202-0 | 79 ft [24 m] | cycleway:right=shared_lane | contraflow lane flagged | LTS 3 (no change) | yes |
| E Street Southeast | [50507958](https://www.openstreetmap.org/way/50507958) | dc-4640031-0 | 75 ft [23 m] | cycleway:right=lane, cycleway:right:lane=exclusive | contraflow lane flagged | LTS 2 to 3 | yes |

## One-way: applied, the 25 longest of 356

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

## Through lanes per direction: applied, the 25 longest of 2,630

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

## Posted speed: applied, the 25 longest of 1,568

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
| Ross Drive Northwest | [6062049](https://www.openstreetmap.org/way/6062049) | dc-4635643-0 | 0.43 mi [686 m] | 20 mph | 25 mph | LTS 1 to 2 | yes |
