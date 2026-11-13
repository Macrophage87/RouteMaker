# The literature RouteMaker draws on, and where it differs

[Index](README.md). This page summarizes, in our own words, the research consulted for
the stress model. It draws on the project's two literature reviews
(`LTS-literature-review.md` and `LTS-literature-review-2.md`, kept with the project's
reports, not in this repository). For each source it says what the source found, what
RouteMaker took from it, and where RouteMaker **deliberately differs**, and why. Figures
are US first, with metric in brackets; a cost in calm miles has kilometers in brackets
(decision 467). Where a figure is a judgment, or comes from a small sample, this page
says so. What is not built is marked **planned**, and what the owner has not yet
confirmed is marked **proposed**. The junction model (option C, decisions 467 and 468),
its statutory default speeds (469 and 469a) and its time of day (468a, 469c to 469e)
are built. Related pages: [intersections.md](intersections.md),
[classification.md](classification.md), [routing-costs.md](routing-costs.md) and
[stress-number.md](stress-number.md). Riders see a short version of this page, with the
main sources listed, under "Why our ratings differ from the studies" and "Sources" at
`/about/stress.html`.

## Level of Traffic Stress

### Mekuria, Furth and Nixon (2012), Mineta Transportation Institute Report 11-19
[Low-Stress Bicycling and Network Connectivity](https://transweb.sjsu.edu/sites/default/files/1005-low-stress-bicycling-network-connectivity.pdf).
This report defines Level of Traffic Stress, LTS 1 to 4, from lookup tables on speed,
lanes, traffic volume and bike facility, with the worst factor deciding the level. It
also scores crossings with no signal by the crossed road's lanes and speed (read
2026-11-13). Table 7, with no median refuge: up to 3 lanes LTS 1 / 1 / 2 / 3 at up to
25 / 30 / 35 / 40 mph or more; 4 to 5 lanes 2 / 2 / 3 / 4; 6 lanes or more 4 at any
speed. Table 8, with a median refuge at least six feet wide: up to 3 lanes the same;
4 to 5 lanes 1 / 2 / 3 / 4; 6 or more 2 / 3 / 4 / 4. So a refuge is worth nothing on up
to 3 lanes or at 35 mph and above on 4 to 5 lanes, one level on 4 to 5 lanes at 25 mph,
and two levels on 6 lanes at 25 mph. Signalized crossings "do not usually present a
barrier".
- **Taken:** the four levels, the rule that the worst factor decides, the tables
  ([classification.md](classification.md)), and, cell for cell, the two crossing tables
  (`routemaker.intersections.CROSSING_LTS`, `REFUGE_LTS`), which give a junction's
  crossing level from the road's lanes and speed; and no stress price at a signal
  ([intersections.md](intersections.md)).
- **Differs:** RouteMaker adds a fifth tier, **Avoid**, for a road a bicycle may legally
  use but nobody should be sent onto; the tables never produce it. It also has **half
  steps** (in use since 2026-10: 1.5 for service roads, 4.5 for the worst highways, and
  others set by override rows), each costed at the midpoint of its two levels, which the
  published scale does not define. Since 2026-11-13 the classifier's own tables produce
  whole levels only. The published levels are ordered categories, not
  amounts, so a route's cost does not add up level numbers. It adds up each stretch's
  length times that ride type's **cost multiplier** for the level.

### Furth, Level of Traffic Stress criteria, versions 2.0 (2017) and 2.2 (2022)
[Furth's Level of Traffic Stress pages](https://peterfurth.sites.northeastern.edu/level-of-traffic-stress/)
and [the version 2.2 tables](https://bpb-us-e1.wpmucdn.com/sites.northeastern.edu/dist/e/618/files/2014/05/LTS-Tables-v2.2.pdf).
These versions refine the tables: lanes per direction, volume bands, speed bands,
bike-lane width including its buffer, the 15 ft [4.6 m] reach beside parked cars, and
one-way streets.
Full reference: Furth, P. G. (May 2022). *Level of Traffic Stress Criteria for Road
Segments, version 2.2.* Northeastern University. Fetched and read 2026-11-13.
- **Taken (2026-11-13):** version 2.2's "Bikes in mixed traffic" table and both bike-lane
  tables, cell for cell, and note 4 under the lane tables ("Use mixed traffic criteria if
  it would result in lower LTS"). Until then the code said "Furth 2017" but used the 2012
  bands with local count steps on top ([classification.md](classification.md)).
- **Differs:** the road class stands in for the centerline, which OSM seldom records; the
  posted or statutory limit stands in for prevailing speed; a narrow one-way is read as
  wide; notes 1 to 3 under the lane tables are not modelled. The owner's data corrections
  (speed limits, bike lanes, curated corridors) and approved overrides are applied after
  the tables.
- **For the record:** version 2.0 (2017) at 45 mph on an unlaned street is LTS 3 up to
  1,500 a day and 4 above; "750" is the break of its 50 mph and over column. An earlier
  version of this page had that wrong.
- **A gap, not a choice:** Furth keeps LTS 1 and LTS 2 as different levels, but today
  RouteMaker's routing cost does not separate them by level. The level adds nothing at
  LTS 1 or LTS 2; only the kind of facility changes the cost there (a traffic-free path
  or a protected bike lane counts for less than a quiet street,
  [stress-number.md](stress-number.md) section 2). This is not a deliberate difference.
  Owner decision 240 plans to close it: a small LTS 2 weight in the calm search for Cargo
  with passengers and Trailmaxxing, and a "Riding with kids" ride type (**planned**).

### Oregon DOT Analysis Procedures Manual, version 2, chapter 14
[Analysis Procedures Manual, chapter 14](https://www.oregon.gov/odot/Planning/Documents/APMv2_Ch14.pdf).
Oregon gives tables for unsignalized crossings by speed, lanes and volume. A median
refuge lowers the level (a 10 ft [3 m] refuge is needed for LTS 1). Left turns made in
traffic are scored by the lanes crossed, and any such left at 35 mph [56 km/h] or more is
LTS 4. It also covers right-turn lanes, slip lanes and roundabouts. Its rural "R" tables
rate a stop-controlled crossing of a road at 45 mph [72 km/h] or more above the lowest
level even at low volume, because rural drivers do not expect bicycles.
- **Taken:** the shape of the crossing costs; the values for a left across oncoming
  traffic (LTS 3 for one lane, LTS 4 for more); the idea of a credit for a median refuge;
  the slip lane rule; and charging for the lane changes before a left. (The rural
  crossing factor of 1.25 that came from Oregon's rural idea was removed on 2026-11-13:
  the crossed road's own speed now sets its level, in town or out of it.)
- **Differs:** Oregon lowers a crossing with a refuge by a whole level. RouteMaker now
  follows Furth's Table 8 (above), where the credit depends on the lanes and the speed;
  until 2026-11-13 it multiplied the cost by 0.75 (decision 196, a card pick). Oregon
  scores a two-stage left as two crossings; RouteMaker caps a
  left at a signal at the price of a two-stage box turn. Oregon's roundabout guidance is not
  followed: RouteMaker prices a ride round a busy ring as a crossing of the ring's traffic
  scaled by the arms passed, a proposal of its own (`ROUNDABOUT_FACTOR_ONTO`, 2026-11-08).
- **An open question:** our cost for a left off an LTS 3 road, 0.11 calm mi [0.18 km], is
  below the range for crossing an LTS 3 road from a stop. The reasoning is that the rider
  already holds a lane and crosses one oncoming lane, but the code marks this value as a
  question for the owner (`intersections.py:139-141`), not a settled choice.


#### Oregon's rural segment table (used as published since 2026-11-13)
Full reference: Oregon Department of Transportation (last updated 07/2025). *Analysis
Procedures Manual, version 2, chapter 14: Multimodal Analysis*, section 14.4.8, Exhibit
14-17, "BLTS Rural Segment Criteria with posted speeds 45 mph or greater". Fetched and read
2026-11-13. It rates rural roads at 45 mph [72 km/h] or more by daily traffic and paved
shoulder, not by the speed limit:

| Vehicles a day | Shoulder under 4 ft [1.2 m] | 4 to under 6 ft [1.2-1.8 m] | 6 ft [1.8 m] or more |
|---|---|---|---|
| Under 400 | R2 | R2 | R2 |
| 400-1,500 | R3 | R2 | R2 |
| 1,500-7,000 | R4 | R3 | R2 |
| Over 7,000 | R4 | R4 | R3 |

Under 45 mph Oregon uses its ordinary mixed-traffic tables (Exhibits 14-6 and 14-7), which
also pair each count band with a functional class "if ADT is not available". FHWA's rural
bikeway framework (FHWA-FLH-19-004, 2019) finds lanes shared under about 1,200 a day "may
be suitable" even at 45+ mph.

- **Taken:** the exhibit cell for cell, for rural two-lane roads at 45 mph or more, posted
  or by statute; R2 as the lowest rural level; the class-for-count pairing for roads nobody
  counted ([classification.md](classification.md), "Rural roads" and "Traffic counts").
- **Differs:** a rural road under 45 mph takes the lower of the ordinary table and this
  one, so a lower limit never raises the level. A shoulder nobody mapped is read on the
  narrow column and reported as unknown. Oregon's notes that an R level is not the urban
  level of the same number, and that sharp curves raise stress, are not modelled.
- **What it replaced:** from 2026-11-09 to 2026-11-13 the map used a reading with half
  steps (2 under 400 a day, 2.5 to 1,500, 3 to 3,000, 4 above; one level lower with a 4 ft
  shoulder), applied through override rows. It was half a level calmer than Oregon at 400
  to 1,500 a day and a whole level calmer in three cells (1,500 to 3,000 with no shoulder;
  with a 4 ft shoulder at 1,500 to 3,000 and over 7,000), and a level harsher at 3,000 to
  7,000 with a 6 ft shoulder. No source supported the differences, so the published cells
  are used. The owner's reason for a calmer reading still stands as a statement of purpose
  (2026-11-09: agencies rate roads "to see which roads need additional bike
  infrastructure, ours is to choose roads more suitable for biking without undue traffic
  stress"); it is a reason to look for better rural evidence (shoulders, measured speeds),
  not for unsourced cells.

### Montgomery County Planning, Bicycle Master Plan, Appendix D (LTS 0 to 5)
[Montgomery County Bicycle Master Plan, Appendix D](https://montgomeryplanning.org/wp-content/uploads/2017/11/Appendix-D.pdf).
A county version of the scale that runs from 0 to 5: LTS 0 for traffic-free paths, an
LTS 2.5 for the gap between 2 and 3, stricter ratings for sidepaths with driveways, and
LTS 5 for roads to avoid.
- **Taken:** the county's layer, as calibration data and as a source of Avoid rows. Its
  2.5 inspired the half steps, and its LTS 0 supports a separate category for
  traffic-free paths.
- **Differs:** our planned half steps are 1.5, 2.5, 3.5 and 4.5, not only 2.5. The
  county's rows are an input, and the owner's approved overrides can change them (the
  Veirs Mill Road decision, for example).

### Maryland DOT statewide LTS (2022)
[MDOT methodology](https://www.mdot.maryland.gov/OPCP/MDOT_LTS_Metadata_Methodology_Full.pdf).
A statewide layer from 0 to 5, whose LTS 5 means "Bicycle Access Prohibited". It fills in
missing speeds from the road's class, and it does not consider intersections or
blockages.
- **Taken:** a statewide comparison, and the idea of filling in a missing speed.
- **Differs:** RouteMaker's Avoid means legal but best avoided, not prohibited. Whether
  bicycles may use a way is decided separately and **errs closed**: where it is unclear
  whether bicycles are allowed, the way is closed, and it is reopened only by an override
  with evidence.

### Arlington County Bicycle Comfort Index (2024)
[Arlington's Bicycle Comfort Index methodology](https://www.bikearlington.com/wp-content/uploads/2024/12/bikearlington-bicycle-comfort-level-map-methodolgy-2024.pdf).
A score from 0 to 150 built from published point values, including ones for the control
at a junction: a signal 0, an all-way stop -1, a two-way stop -2, and no control -5.
- **Taken:** Arlington's ordering of controls guides our control costs.
- **Differs:** Arlington's index adds points, so a good feature can make up for a bad
  one. RouteMaker keeps the rule that the worst factor decides the level, and adds up
  only costs.

## Route choice and junction costs

### Broach, Dill and Gliebe (2012), Portland
["Where do cyclists ride? A route choice model developed with revealed preference GPS data"](https://ppms.trec.pdx.edu/media/1307553839HIVYEAW.pdf),
Transportation Research Part A 46(10), 1730-1740 (the preprint at the link was read on
2026-11-13). A GPS study of how riders trade distance against traffic. Its Table 3 gives
what each thing is worth as a share of a mile of riding. The junction rows, in full
(non-commute trips, then commute trips):

| Table 3 row | Non-commute | Commute |
|---|---|---|
| A turn | 7.4% (391 ft) | 4.2% (222 ft) |
| A traffic signal, except on a right turn | 3.6% (190 ft) | 2.1% (111 ft) |
| A stop sign | 0.9% (48 ft) | 0.5% (26 ft) |
| Left turn with no signal off a road of 10,000-20,000 a day | 16.2% (855 ft) | 9.1% (480 ft) |
| Left turn with no signal off a road of 20,000 or more a day | 43.1% (2,276 ft) | 23.1% (1,220 ft) |
| Right turn with no signal onto a road of 10,000 or more a day | 6.7% (354 ft) | 3.8% (201 ft) |
| Crossing or left onto, no signal, a road of 5,000-10,000 a day | 7.2% (380 ft) | 4.1% (216 ft) |
| The same, 10,000-20,000 a day | 10.4% (549 ft) | 5.9% (312 ft) |
| The same, 20,000 or more a day | 61.7% (3,258 ft) | 32.2% (1,700 ft) |

Nothing was measurable below 5,000 vehicles a day. Bike lanes made up for traffic but
added little on their own, and paths made a route feel 16-26% shorter. Half of the trips
were less than 10% longer than the shortest route.
- **Taken:** the junction model's prices for a crossing, a left onto, a left off and a
  right onto a busy road with no signal are the non-commute column above (380, 550, 3,260,
  855, 2,276 and 354 ft; `routemaker.intersections.STOPPED_CROSSING_FT`,
  `LEFT_ACROSS_ONCOMING_FT`, `RIGHT_ONTO_MAX_FT`), with straight lines between the count
  bins so no count is a cliff (`COUNT_LEVELS`). Also the idea that a stretch of path counts
  for less than the same length of quiet street.
- **Differs:** the top. The most one junction can cost is 2 calm miles [3.2 km; 10,560 ft]
  (the owner's choice, decision 467: "There's definitely intersections that I'd detour
  2 miles to avoid, though rare."), above Broach's 0.62 mi. Only a crossing where the wait
  for a gap runs to minutes reaches it (Fitzpatrick et al. 2006, below).
- **Differs:** until 2026-11-13 the model priced a crossing of a road of 5,000-20,000 a
  day at 1,088 to 3,900 ft, 3 to 11 times the table (decision 468, "option C"). The audit
  of that day found no published source for those figures.
- **Differs:** Broach's figures describe the average choices of the Portland riders
  studied. **RouteMaker is stress-averse by default** (owner decision 14: most people
  should be sent on trails rather than faster LTS 3 and LTS 4 roads, and traffic-free
  paths get a category of their own). So its LTS 3 and LTS 4 road costs are well above
  Broach's (at Default, 2.9-5.8 and 12.9-15.8 calm miles per mile). Its path discount is
  also deeper than Broach's. Broach found a path made a route feel 16-26% shorter, so a
  meter of path counted as about 0.74 to 0.84 of a meter of quiet street. In RouteMaker a
  meter of path counts as about 0.55. The 0.55 is RouteMaker's own figure, not Broach's.

### Fitzpatrick and colleagues (2006), NCHRP Report 562
Fitzpatrick, Turner, Brewer, Carlson, Ullman, Trout, Park, Whitacre, Lalani and Lord,
["Improving Pedestrian Safety at Unsignalized Crossings"](https://nacto.org/wp-content/uploads/2010/08/NCHRP-562-Improving-Pedestrian-Safety-at-Unsignalized-Crossings.pdf),
TCRP Report 112 / NCHRP Report 562, Transportation Research Board. (Opened by the audit of
2026-11-13, areas/14; the formula as printed in its Appendix A worksheets.) The wait for
a gap at a crossing with no signal, from the Highway Capacity Manual 2000: critical gap
tc = L / S + ts (crossing length over speed, plus a start-up time), average delay
d = (e^(v tc) - v tc - 1) / v with v the conflicting flow in vehicles a second; with a
median refuge each half is crossed against one direction's flow. Its table of delay
against risk-taking: over 30 s the likelihood is "high", over 45 s "very high". Drivers
yielding to someone waiting: over 94% at red-signal or beacon devices, 61% at 25 mph and
17% at 35 mph at high-visibility signs and markings, 34% at median refuge islands.
- **Taken:** the formula, with the report's 12 ft lanes and 3 s start-up, is the junction
  model's wait for a gap (`routemaker.intersections.gap_delay_s`), which prices a crossing
  at twice the wait where that is more than Broach's price. The 30 s and 45 s lines are
  the orange and red marks (`ORANGE_MIN_FT`, `RED_MIN_FT`). The yielding shares at 25 and
  35 mph price a marked trail crossing (`MARKED_YIELD_SHARE`).
- **Differs:** the crossing speed is a rider's 11.2 mph [18 km/h], not a walker's
  3.5 ft/s. The formula takes random arrivals and no yielding, so it overstates on roads
  where signals upstream make gaps. The share of a day's traffic in an hour (8% at rush
  hour, 5.5% off-peak, 5% at the weekend, 1.5% at night) is our default, unmeasured.

### Zimmermann, Mai and Frejinger (2017), Eugene
["Bike route choice modeling using GPS data without choice sets of paths"](https://doi.org/10.1016/j.trc.2016.12.009),
Transportation Research Part C 75, 183-196 (working paper
[CIRRELT-2016-49](https://www.cirrelt.ca/DocumentsTravail/CIRRELT-2016-49.pdf)). A route
choice model for Eugene, Oregon. A left with no signal through HEAVY traffic (over 20,000
vehicles a day) was worth about 818 ft [249 m] of riding; through medium traffic
(8,000-20,000 a day) about 124 ft [38 m]. Its 716 ft [218 m] is a constant for every
link of the network, quiet ones included, not a cost per intersection. Lefts and rights
were otherwise much alike.
- **Taken:** nothing as a number. It agrees with Broach in direction: heavy cross traffic
  is where a junction with no signal costs, and a left is not otherwise dearer than a
  right.
- **Corrected 2026-11-13:** this page used to say the range for crossing an LTS 3 road
  "starts at Eugene's 818 ft" and that each intersection was worth 716 ft. The 818 ft is
  the over-20,000-a-day case; the matching medium-traffic figure is 124 ft; and the 716 ft
  is the per-link constant. The model's old 1,600 ft for an LTS 3 crossing rested on that
  misreading and is gone.

### Skov-Petersen, Barkow, Lundhede and Jacobsen (2018), Copenhagen
["How do cyclists make their way? A GPS-based revealed preference study in Copenhagen"](https://repository.up.ac.za/bitstream/handle/2263/65159/SkovPetersen_How_2018.pdf?sequence=1),
International Journal of Geographical Information Science. A left turn cost riders about
154 ft [47 m] of riding, and a right turn 62 ft [19 m]. Real detours averaged 28%,
against 40% in a survey.
- **Taken:** that a left costs more than a right (about 2.5 times as much in
  Copenhagen).
- **Differs:** Copenhagen's costs are small because its network is already calm. Since
  2026-11-13 a left onto a busy road costs what the crossing costs (Broach has one
  variable for both), no longer 1.5 times it; a right costs at most Broach's 354 ft.

### Ton and colleagues (2017), Amsterdam
[Ton and colleagues](https://swov.nl/en/publicatie/how-do-people-cycle-amsterdam-netherlands)
(we read the abstract only). In a network already full of bike routes, riders cared more
about crossing fewer intersections than about having separate paths.
- **Taken:** support for charging for junctions as well as for distance.
- **Differs:** this is a dense Dutch grid. For a mixed American region we rank the road's
  own stress first.

### Caviedes and Figliozzi (2018), Portland wearable sensors
["Modeling the impact of traffic conditions and bicycle facilities on cyclists' on-road stress levels"](https://doi.org/10.1016/j.trf.2018.06.032),
Transportation Research Part F. A small study that measured riders' stress with sensors.
Stress at peak hours was reported at about 1.75 times off-peak, in a sample said to be
five riders (we have not confirmed the sample size from the full text).
- **Taken:** the direction only: junctions are harder at peak hours.
- **Differs:** the model no longer has time-of-day factors (they were x1.25 at rush hour,
  x0.85 at the weekend, x0.5 or x0.85 at night; decisions 468a, 469c-469e). Since
  2026-11-13 the hour reaches a junction through its traffic: the wait for a gap at that
  hour (Fitzpatrick et al. 2006, above), and at the weekend and at night the count read
  in proportion to the hour's traffic.

## Other design guides and studies

- **NACTO (2017)**, *Designing for All Ages & Abilities: Contextual Guidance for
  High-Comfort Bicycle Facilities*
  ([page](https://nacto.org/publication/urban-bikeway-design-guide/designing-ages-abilities-new)):
  on a street of 25 mph or less with one lane each way, sharing suits up to 1,500 vehicles a
  day, a bicycle boulevard or lane 1,500 to 3,000, a buffered or protected lane 3,000 to
  6,000, and a protected lane above. *Taken:* a cross-check on Furth's 1,500 break.
  *Differs:* a design guide, not a rating table; its 3,000 and 6,000 lines are not steps
  here.
- **FHWA (Schultheiss and colleagues, 2019)**, *Bikeway Selection Guide*, FHWA-SA-18-077
  ([PDF](https://highways.dot.gov/sites/fhwa.dot.gov/files/2022-07/fhwasa18077.pdf)): "as
  motorized traffic volumes increase above 6,000 vehicles/day, it becomes increasingly
  difficult for motorists and bicyclists to share roadway space". *Taken:* a cross-check.
  *Differs:* as NACTO.
- **Jones (2004)**, *Development of Rural Bicycle Compatibility Index*, Nebraska Department
  of Roads, SPR-PL-1(038) P533
  ([report](https://dot.nebraska.gov/media/thff4qex/final-report-p533.pdf)): in video
  ratings of rural Nebraska highways, paved shoulder width and heavy vehicles an hour
  explained comfort; speed and total volume dropped out. Small sample. *Taken:* nothing
  yet. *Differs:* our rural table reads volume and shoulder and has no truck input.
- **Beck and colleagues (2019)**, "How much space do drivers provide when passing
  cyclists?", *Accident Analysis & Prevention* 128
  ([doi:10.1016/j.aap.2019.03.007](https://doi.org/10.1016/j.aap.2019.03.007)): drivers
  passed closer where a painted bike lane existed (abstract read, not the full paper). *Taken:* nothing; noted as a limit of
  the lane table.
- **Caltrans DRISI (2026)**, Preliminary Investigation PI-0420, *Statewide Bicycle Level
  of Traffic Stress Map*
  ([PDF](https://dot.ca.gov/-/media/dot-media/programs/research-innovation-system-information/documents/preliminary-investigations/pi-0420-statewide-bicycle-level-of-traffic-stress-map-jan-2026-a11y.pdf)):
  a survey of state methods; every statewide map it found starts from the Mineta tables
  with local changes, and agencies split on posted against prevailing speed. *Taken:* the
  second-hand report of Colorado's truck rule, in the gaps section below.
- **District of Columbia Municipal Regulations, 18 DCMR 2200.6** (as amended by DDOT's
  rulemaking adopted 2020-06-01;
  [notice](https://ddot.dc.gov/sites/default/files/dc/sites/ddot/publication/attachments/NEPRM%2020MPH.pdf)):
  the District's default speed limit is 20 mph. Law, read as a posted sign is.

- **CROW (Netherlands) and the UK's LTN 1/20**
  ([LTN 1/20](https://assets.publishing.service.gov.uk/media/5ffa1f96d3bf7f65d9e35825/cycle-infrastructure-design-ltn-1-20.pdf)):
  riding with cars is acceptable below about 2,000-2,500 vehicles a day at 20 mph [32
  km/h]. *Taken:* a cross-check on LTS 1 and 2. *Differs:* we use the US tables and
  volumes.
- **Transport for London and Germany's ERA 2010**
  ([a summary by Peters](https://verkehrslexikon.de/PDF/Peters_ERA_2010.pdf)): signals
  above about 800-1,000 vehicles in the peak hour; a direct left limited to one lane
  change; sidepaths discouraged where junctions and driveways are frequent. *Taken:* that
  changing lanes before a left is stressful, and that frequent junctions matter.
  *Differs:* we charge for them as costs rather than treat them as design rules.
- **Transport for NSW**
  ([Cycleway Design Toolbox](https://www.transport.nsw.gov.au/system/files/media/documents/2023/Cycleway-Design-Toolbox-Web.pdf)):
  riding with cars only on quiet streets of 19 mph [30 km/h] or less, and painted lanes
  unsuitable on main bike routes. *Taken:* support for a strict line for comfort.
  *Differs:* a cross-check only.
- **Harris and colleagues (2013)**, injuries in Vancouver and Toronto
  ([PMC3786647](https://pmc.ncbi.nlm.nih.gov/articles/PMC3786647)): where two minor
  streets met, the odds of injury were far lower than where two major streets met.
  *Taken:* support for charging only junctions that involve a busy road. *Differs:* the
  risk of injury is not the same as comfort, and we price comfort.
- **Harvey, Fang and Rodriguez**, Mineta Transportation Institute Report 19-20
  ([report](https://transweb.sjsu.edu/sites/default/files/1711-Fang-Bicycle-Level-of-Stress-Crowdsourced-Route-Satisfaction.pdf)):
  LTS levels are ordered categories, so averaging them assumes equal spacing they were
  not designed for. *Taken:* we average each ride type's costs, not the levels.
  *Differs:* their riders' ratings matched LTS only weakly (rank correlation 0.13-0.26),
  so we do not claim that fine steps between levels are proven.

## Data and software

- **OpenStreetMap** contributors (ODbL): the map data. *Differs:* **we err closed** on
  whether bicycles may use a way, as above.
- **DC Open Data** (DDOT Traffic Volume and DC Roadway Block; CC BY 4.0, adapted) and
  **VDOT** traffic volumes (Virginia Roads): traffic counts and street records, credited
  on the rider page. *Differs:* agency data is an input to the rules, not the answer, and
  the owner's curated files take precedence.
- **U.S. Census Bureau, TIGER/Line Shapefiles (2024), 2020 Urban Areas**
  (`tl_2024_us_uac20`; U.S. public domain; full record in
  [docs/SOURCES.md](../SOURCES.md)): which places are urban, for the default speed
  limits.
- **Valhalla** 3.9.1 ([bicyclecost.cc](https://github.com/valhalla/valhalla/blob/master/src/sif/bicyclecost.cc)):
  the router. It cannot see which road is crossed at a junction, which is why the
  junction model works on the traced route ([intersections.md](intersections.md),
  section 1).

### Statutory default speed limits (decisions 469 and 469a)

Decision 469 replaced the junction model's assumed 45 mph [72 km/h] for a road with no
mapped speed with each jurisdiction's statutory default. The junction cost reads it
(`stress.statutory_default_mph`; [intersections.md](intersections.md), section 3). A
business or residence district is read as inside a Census urban area, and a divided road
as a carriageway of a divided road. Where the state is not known, the classifier's own
assumed speed is used. The default is used for the cost only and is never said to a
rider. The sources, as the owner gave them:

- **District of Columbia**: a 20 mph [32 km/h] default where no other limit is posted,
  since 2020-06-01. DDOT,
  [20 MPH default speed limit, frequently asked questions](https://ddot.dc.gov/page/twenty-mph-20-mph-default-speed-limit-frequently-asked-questions).
- **Maryland**: the statutory maximums, Transportation Article 21-801.1: 30 mph
  [48 km/h] in a business district; 30 mph [48 km/h] on an undivided and 35 mph [56 km/h]
  on a divided residential road; 50 mph [80 km/h] undivided and 55 mph [89 km/h] divided
  elsewhere; 70 mph [113 km/h] on interstates and expressways. Maryland DOT State Highway
  Administration, [speed limits](https://roads.maryland.gov/mdotsha/pages/Index.aspx?PageId=295).
  RouteMaker reads 30 mph [48 km/h] (35 mph [56 km/h] divided) inside an urban area and 50
  mph [80 km/h] (55 mph [89 km/h] divided) outside one.
- **Virginia** (469a): unless posted otherwise, 55 mph [89 km/h] on most highways, 25 mph
  [40 km/h] in business and residence districts, and at most 35 mph [56 km/h] on unpaved
  roads; Code of Virginia 46.2-870 to 46.2-878 and 46.2-1300. VDOT,
  [speed limits](https://www.vdot.virginia.gov/about/our-system/highways/speed-limits/).

The rider page (`/about/stress.html`) credits these three sources under "Sources".

**Open point:** decision 469 also asks that the classifier read these defaults wherever
it needs a speed. It does in the District (20 mph [32 km/h]). In Maryland's and
Virginia's urban areas it still reads the MDOT imputation by road class (25 to 35 mph
[40 to 56 km/h]), which is not the statute, and outside them one table for both states.
Moving it would change tiers on many roads, so it is left for the owner to confirm
([classification.md](classification.md); [intersections.md](intersections.md), section 9).

## Where the evidence has gaps

We found no test, on whole routes, of rating a route by its worst stretch against rating
it by its average. Trucks are not an input, though the sources do measure their effect: Jones (2004) above;
Montgomery's Appendix D floors industrial streets at 2.5 "given the greater volume of
truck traffic"; and a 2026 Caltrans survey of state methods reports that Colorado raises
the level where heavy trucks exceed 10% of more than 1,500 vehicles a day (reported at
second hand; the Colorado document is internal). We found no measured effect for driveways
per mile, and no table that rates a one-way street calmer than a two-way street at the same
volume (the published ones read a one-way's count at 1.5 times), and there are no
figures for leisure loops. At junctions: no source we opened prices a slip lane, a right
hook in feet, a lane change before a left, or a roundabout by the data the map has; those
are marked "our default, unmeasured" in [intersections.md](intersections.md). The top of
2 calm mi [3.22 km] for one junction follows the owner's direction in decision 467, not a
published value. The share of a day's traffic in each hour is a typical figure, not a
count.
The project's reviews read these figures from the sources. Some came from search
summaries, and the reviews say which.
