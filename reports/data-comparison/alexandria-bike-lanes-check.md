# Alexandria Bike Lane Routes against OSM's bike lanes

City of Alexandria, VA GIS, "Bike Lane Routes" (ArcGIS item 74341781de91444a8f03620efc5c0514), licence cc0, retrieved 2026-10-01. Record types: Route Off Street 150, Route Shared Lane 150, Route Recommend Connection 147, Route Bike Lanes 70, Route Walking Path 53, Route Climbing Lanes 23.

OSM road ways that lie along a city lane, shared-lane or climbing-lane route and already carry a `cycleway` lane, track or shared-lane tag: 34.9 mi. Those that carry none:

* **Candidates for a missed bike lane** (`Route Bike Lanes`, `Route Climbing Lanes`): 17 street/type groups, 48 ways, 2.2 mi.
* **Sharrows** (`Route Shared Lane`): 33 street/type groups, 113 ways, 10.7 mi. A shared-lane marking is neither a lane nor a track, and the classifier does not credit one (the owner: "Sharrows don't count as anything"), so these change no tier; they are listed for OSM completeness only.

### Missed bike lanes

| street | city record | miles | ways | example ways |
| --- | --- | --- | --- | --- |
| Mill Road | Route Bike Lanes | 0.68 | 12 | 8825030, 50596440, 232402111, 232402118 |
| Stevenson Avenue | Route Climbing Lanes | 0.35 | 3 | 8821888, 590898846, 1192353108 |
| Eisenhower Avenue | Route Bike Lanes | 0.25 | 4 | 8823811, 327010883, 468896917, 506952362 |
| Quantrell Avenue | Route Bike Lanes | 0.22 | 5 | 50656465, 590669463, 755323710, 755985447 |
| Daingerfield Road | Route Bike Lanes | 0.17 | 3 | 8823257, 507244572, 798186800 |
| Stultz Road | Route Bike Lanes | 0.16 | 2 | 8824376, 636835339 |
| King Street | Route Bike Lanes | 0.08 | 6 | 326971673, 475543212, 545745925, 1057860521 |
| Kenwood Avenue | Route Climbing Lanes | 0.05 | 2 | 1395831653, 1395831654 |
| South Pickett Street | Route Bike Lanes | 0.05 | 2 | 663609123, 930493628 |
| South Royal Street | Route Bike Lanes | 0.04 | 1 | 666736033 |
| Seminary Road | Route Bike Lanes | 0.03 | 1 | 468778514 |
| Commonwealth Avenue | Route Bike Lanes | 0.03 | 1 | 179909902 |
| North Hampton Drive | Route Bike Lanes | 0.01 | 2 | 590669455, 732354009 |
| Slaters Lane | Route Bike Lanes | 0.01 | 1 | 397270231 |
| Prince Street | Route Bike Lanes | 0.01 | 1 | 506874555 |
| Wheeler Avenue | Route Bike Lanes | 0.01 | 1 | 1148978737 |
| Roundhouse Lane | Route Bike Lanes | 0.01 | 1 | 734595946 |

### Sharrows OSM does not tag

| street | city record | miles | ways | example ways |
| --- | --- | --- | --- | --- |
| North Beauregard Street | Route Shared Lane | 1.85 | 24 | 281468459, 281468466, 281471289, 281471299 |
| North Royal Street | Route Shared Lane | 0.93 | 12 | 8821830, 69073347, 762916064, 1034973415 |
| West Braddock Road | Route Shared Lane | 0.89 | 6 | 8822041, 507299554, 575072521, 575102059 |
| North Fayette Street | Route Shared Lane | 0.82 | 4 | 8823870, 849732803, 1485442511, 1485442512 |
| Mount Vernon Avenue | Route Shared Lane | 0.50 | 4 | 160819608, 443808520, 607707634, 1282469625 |
| Duke Street | Route Shared Lane | 0.46 | 7 | 468548410, 468548411, 468551723, 468551726 |
| Allison Street | Route Shared Lane | 0.43 | 2 | 8823636, 8823637 |
| Tennessee Avenue | Route Shared Lane | 0.42 | 1 | 8824706 |
| South Royal Street | Route Shared Lane | 0.40 | 5 | 8824016, 317261314, 535582118, 762089434 |
| Four Mile Road | Route Shared Lane | 0.34 | 5 | 8823964, 8823966, 443990117, 670407271 |
| University Drive | Route Shared Lane | 0.33 | 1 | 963639775 |
| Colvin Street | Route Shared Lane | 0.33 | 1 | 8824539 |
| North Gordon Street | Route Shared Lane | 0.33 | 1 | 8825091 |
| Sanger Avenue | Route Shared Lane | 0.31 | 3 | 8823242, 1418956383, 1460425056 |
| South Gordon Street | Route Shared Lane | 0.30 | 2 | 8821972, 444474720 |
| Powhatan Street | Route Shared Lane | 0.30 | 3 | 199133435, 199133802, 1463063827 |
| Martha Custis Drive | Route Shared Lane | 0.29 | 1 | 590898790 |
| Stewart Avenue | Route Shared Lane | 0.25 | 1 | 8824263 |
| South Quaker Lane | Route Shared Lane | 0.18 | 1 | 8824242 |
| Dulany Street | Route Shared Lane | 0.17 | 5 | 8823755, 232402122, 565572146, 881902296 |
| South West Street | Route Shared Lane | 0.16 | 6 | 50603444, 520320420, 574944241, 574944242 |
| Valley Drive | Route Shared Lane | 0.15 | 4 | 24776355, 507009663, 507009664, 583703147 |
| Radford Street | Route Shared Lane | 0.15 | 1 | 273510067 |
| Osage Street | Route Shared Lane | 0.14 | 1 | 8823704 |
| South Fayette Street | Route Shared Lane | 0.08 | 2 | 422410211, 1486345652 |
| Old Dominion Boulevard | Route Shared Lane | 0.06 | 1 | 8824463 |
| Gunston Road | Route Shared Lane | 0.05 | 2 | 590831830, 762953964 |
| Roth Street | Route Shared Lane | 0.04 | 1 | 8824989 |
| Henry G. Shirley Memorial Highway | Route Shared Lane | 0.03 | 2 | 50658204, 50658209 |
| Pendleton Street | Route Shared Lane | 0.02 | 1 | 45836991 |
| (unnamed) | Route Shared Lane | 0.01 | 1 | 50658211 |
| Preston Road | Route Shared Lane | 0.01 | 1 | 507096231 |
| North Morgan Street | Route Shared Lane | 0.01 | 1 | 590669468 |
