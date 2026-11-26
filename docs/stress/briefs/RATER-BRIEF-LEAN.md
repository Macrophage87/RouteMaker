# Rating roads for traffic stress (lean brief)

You rate how stressful a road is to ride a bike on, for an open-source bike route planner. Each
group you get is one road stretch, or stretches sharing the same facts. Make a reasoned call from the
evidence and use your best judgment. Everything below is a starting point with its reason, not a
limit: depart from it whenever this road's own evidence says so, and say why.

## The scale

1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5 (Avoid), or "closed" where bikes are barred or access is unclear.

Levels 1 to 4 are Peter Furth's Level of Traffic Stress definitions, quoted without the rider-type labels:

- **1:** Strong separation from all except low speed, low volume traffic. Simple crossings. Suitable for children.
- **2:** Except in low speed, low volume traffic, cyclists have their own place to ride that keeps them from having to interact with traffic except at formal crossings. Physical separation from higher speed and multilane traffic. Crossings that are easy for an adult to negotiate. Corresponds to design criteria for Dutch bicycle route facilities. A level of traffic stress that most adults can tolerate.
- **3:** Interaction with moderate speed or multilane traffic, or close proximity to higher speed traffic.
- **4:** Interaction with higher speed traffic, or close proximity to high speed traffic.

Two levels are added above Furth's 4 for roads that are legal but worse than an ordinary 4:
- **4.5:** very high stress, sometimes the only way through (a rural expressway, a multilane 55 mph road).
- **5 (Avoid):** legal, but not a real option (a city expressway open to bikes).

Half steps (1.5, 2.5, 3.5) are the halfway points between these definitions. Ask which definition
the road fits, and use a half step when it sits between two.

## What matters

Travel speed, traffic volume, through lanes each way, bike facility, shoulder, and town or country.
Prefer what was measured on this road, then dated project records, agency data fields, map tags, the
legal default speed, and last inference from class, surroundings and a web check of what the road
serves. Posted and statutory speeds are legal limits, not how fast traffic moves.

## What counts as a miss

Half a level off is fine. A big miss is not. The worst is calling a truly stressful road calm. The
other is rating quiet country roads so high that nobody is sent down the roads people go to the
country to ride. Lean higher on real signs of speed or traffic (class, through role, lanes), never
on missing data alone.

## Starting points

**Town, one lane each way, 25 mph or less, no bike facility** (cars a day): under 1,500: 1.
1,500 to 3,000: 2. 3,000 to 8,000: 2.5. 8,000 to 12,000: 3. 12,000 to 20,000: 3.5. Over 20,000: 4.
About half a level more at 30 mph, a level more at 35 to 40.

**Town, two lanes each way:** about 3 with light traffic, 3.5 at 8,000 to 20,000, 4 over 20,000 or
from 40 mph, 4.5 when highway-like. A one-way street is rated as
a divided two-way street with the same lanes each way (Furth): one-way with 2 lanes equals 2+2.

**Bike facilities:** see the next section.

**Country, two lanes, no 4 ft shoulder** (cars a day): under 400: 2. 400 to 1,500: 2.5.
1,500 to 3,000: 3. 3,000 to 18,000: 4. Above that: 4.5. About a level lower with a real shoulder.
Country traffic is fast when it comes, so country roads start at 2.

**No count:** judge the traffic from what the road does. As a start: residential 1 in town and 2 in
the country; minor road 2; collector (tertiary) 2.5; secondary 3 in town and 3.5 in the country;
primary 3.5 to 4; trunk 4. Narrow, winding, unpaved, dead-end or access-only roads are usually
quiet. A road linking towns, highways, schools or employers usually is not.

**Highways:** multilane posted 55 or more, or a rural expressway: 4.5. A town expressway: 5.
**Alleys, driveways, parking aisles and other service roads:** about 1 to 1.5: few cars at low
speed, with backing cars, delivery trucks and blind exits. More where the way is really a street:
a busy shopping-centre or campus road, a truck or loading route, a cut-through. A farm or forest
track is about 1 for traffic; say its surface in `why`.

## Bike lanes, protected lanes and side paths

A lane painted on the road is part of that road's rating. A protected lane, side path or trail
mapped as its own way is rated as its own stretch, with the facts of the road beside it and of what
it crosses. Ask what the rider there actually has to deal with.

**Between crossings.** Physical separation (a kerb, parked cars, a verge) takes the rider out of
the traffic beside them, so a protected lane, side path or trail starts at 1 whatever the road
carries (Furth). About 1.5 to 2 where only posts or a narrow kerb stand between the rider and
traffic at 40 mph or more, or where the separation has gaps. A painted lane leaves the rider beside
traffic: about 1.5 to 2 on a calm street and never above the same road with no lane, 2.5 on a busy
25 mph street or with two lanes each way, 3 at 35 to 40 mph or three lanes, 3.5 to 4 above that. A
buffer or a wide lane helps by about half a level; a narrow lane in the door zone of parked cars,
or one that is often blocked, costs about half a level. A bus-bike lane or a contraflow lane is
rated as a painted lane. A shared-lane marking or a signed route is no facility: rate the road. A
sidewalk open to bikes is about 2 (walkers, driveways, kerb ramps), not a protected lane; a wide,
railed bridge sidewalk about 1.5.

**Road crossings are not part of this level.** Each road crossing is rated separately as a
junction, with its own stress and delay, and the planner charges it once, where it is. So a signal,
a multilane crossing, a slip lane or a highway ramp must not raise the level of the lane, side path
or trail that crosses it; counting it here as well would charge it twice, and for every mile of the
way (the owner, 2026-11-15, on a test of both methods). What still counts is what the rider meets
between crossings: a run of busy driveways (shops, fuel stations, car parks), cars turning across
the lane at driveways and minor entrances, a place where the path drops the rider into the road. A
few: about 1.5. Many: 2 to 2.5. On a two-way path on one side of the road, drivers turning out do
not look for riders coming the "wrong" way: about half a level more where driveways are frequent.
Name the hard road crossings in `why` so a reader knows they are there, without rating them.

Take the worse of separation and driveways, and half a level more when both are poor.

**Compare with the road.** A facility is there to be calmer than the roadway beside it, and it
almost always is. If your level for a lane or side path comes out above the road's own, or at 3 or
more, look again at what you counted. Some paths really are that bad; when you hold such a level,
name the driveways or gaps that make it so and set `second_look` true.

**Trails in their own corridor** (rail trails, park paths): 1. Their road crossings are rated as
junctions, not here. Unpaved or narrow is a surface fact to say in `why`, not stress.

## Reading the facts you are given

- Rate the roadway itself. A protected lane or side path mapped as its own way is its own group,
  rated from the section above; never copy the road's level onto it.
- A lane figure in agency data is usually per direction and a map `lanes` tag is usually the total.
  A count is the whole road, both directions, including on a divided road.
- With no speed given, do not assume the legal maximum in the country. Judge from the road's shape
  and role.
- The town or country flag can be wrong. Go with what is on the ground when speed, homes and
  surroundings clearly disagree with it.
- A shoulder with no width given is worth about half a level, not a whole one.
- Ramps and short links take the level of the calmer road they join, and no less than 3 at a
  highway interchange.
- A freeway-type road with no sign that bikes are allowed is "closed" with access unclear.

## Things that have fooled raters before

- A count may belong to another road: one overhead, a frontage road, or a station past a busy
  junction. A count that is implausible for the road probably is.
- Repeated round counts across unrelated roads are placeholders.
- Turn lanes have been counted as through lanes, which over-rates the road. Count only through
  lanes: one lane each way with turn lanes at junctions is a one-lane street. Check whether a lane
  figure is per direction or a total.
- On commuter arteries traffic often runs well above the posted limit.
- Country collectors with no count have been over-rated from a default 55 mph; residential-tagged
  country roads with a real count of several hundred a day have been under-rated as town streets.
- Jobs nearby say little about a residential street. Few homes nearby say little about a road that
  links places.

## Rules that are not judgment

Rate blind: never look up an agency's bike stress or comfort rating, or another map's rating, for
these roads. No Street View. Describe the road, never the people or neighbourhood around it. Say
what you did not know.

## Output

A JSON array, one object per group id:

```json
{"id": "T0000", "level": 2.5, "confidence": "medium", "range": [2.5, 3],
 "why": "Two-lane collector, posted 25 mph, about 6,200 cars a day (state count), no bike lane: steady traffic.",
 "evidence": ["count 6,200 (measured)", "posted 25 (map tag)", "web: links two main roads, school on it"],
 "missing": ["measured speed"],
 "departed_from_starting_point": "",
 "second_look": false}
```

`why` is one or two plain sentences a rider can read. Fill `departed_from_starting_point` with the
reason when you departed by a level or more. Set `second_look` true when you are torn by 1.5 levels
or more, or when you rate a busy or main road calm.

## Law by region

## Statutory speeds and sidewalk riding (law)

| Jurisdiction | Town (residence or business district) | Open country | Other | Bikes on sidewalks | Citation |
|---|---|---|---|---|---|
| District of Columbia | 20 mph on every street unless posted | (none) | Alleys 15 mph | Allowed outside the central business district | 18 DCMR 2200.6, 1201.9 |
| Maryland | 30 undivided, 35 divided | 50 undivided, 55 divided | | Only where a local law allows it | Transportation Article 21-801.1, 21-1103 |
| Virginia | 25 | 55 | 35 on unpaved roads | Allowed unless a local law or sign bars it | Code of Virginia 46.2-870 to 46.2-878, 46.2-904 |
| West Virginia | 25 | 55 | | Not checked | W. Va. Code 17C-6-1 |
| Florida | 30 | 55 | A county or city may post 20 or 25 after a study | Allowed, with a pedestrian's rights and duties, unless a local law bars it | Fla. Stat. 316.183(2), 316.189, 316.2065(9)-(10) |

The sidewalk column says whether a rider may be there, not what riding there is like: rate that
from the sidewalk's own facts (width, driveways, walkers), as the bike-facility section says.

DC also has a stop-as-yield law for bikes (a junction matter, not a road level).
