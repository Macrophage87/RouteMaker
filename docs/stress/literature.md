# The literature RouteMaker draws on, and where it differs

[Index](README.md). This page summarizes, in our own words, the research consulted for
the stress model. It draws on the project's two literature reviews
(`LTS-literature-review.md` and `LTS-literature-review-2.md`, kept with the project's
reports, not in this repository). For each source it says what the source found, what
RouteMaker took from it, and where RouteMaker **deliberately differs**, and why. Figures
are US first, with metric in brackets; a cost in calm miles has kilometers in brackets
(decision 467). Where a figure is a judgment, or comes from a small sample, this page
says so. What is not built is marked **planned**, and what the owner has not yet
confirmed is marked **proposed**. Related pages: [intersections.md](intersections.md),
[classification.md](classification.md), [routing-costs.md](routing-costs.md) and
[stress-number.md](stress-number.md). Riders see a short version of this page, with the
main sources listed, under "Why our ratings differ from the studies" and "Sources" at
`/about/stress.html`.

## Level of Traffic Stress

### Mekuria, Furth and Nixon (2012), Mineta Transportation Institute Report 11-19
[Low-Stress Bicycling and Network Connectivity](https://transweb.sjsu.edu/sites/default/files/1005-low-stress-bicycling-network-connectivity.pdf).
This report defines Level of Traffic Stress, LTS 1 to 4, from lookup tables on speed,
lanes, traffic volume and bike facility, with the worst factor deciding the level. It
also scores crossings by the crossed road's speed and lanes, and a median refuge lowers
a crossing's score by about one level.
- **Taken:** the four levels, the rule that the worst factor decides, the tables
  ([classification.md](classification.md)), and the crossing logic behind the junction
  costs.
- **Differs:** RouteMaker adds a fifth tier, **Avoid**, for a road a bicycle may legally
  use but nobody should be sent onto; the tables never produce it. It also plans **half
  steps** (**planned**), each costed at the midpoint of its two levels, which the
  published scale does not define. The published levels are ordered categories, not
  amounts, so a route's cost does not add up level numbers. It adds up each stretch's
  length times that ride type's **cost multiplier** for the level.

### Furth, Level of Traffic Stress criteria, versions 2.0 (2017) and 2.2 (2022)
[Furth's Level of Traffic Stress pages](https://peterfurth.sites.northeastern.edu/level-of-traffic-stress/)
and [the version 2.2 tables](https://bpb-us-e1.wpmucdn.com/sites.northeastern.edu/dist/e/618/files/2014/05/LTS-Tables-v2.2.pdf).
These versions refine the tables: lanes per direction, volume bands, speed bands,
bike-lane width including its buffer, the 15 ft [4.6 m] reach beside parked cars, and
one-way streets.
- **Taken:** the base of the classifier, including the lane and buffer rules.
- **Differs:** the owner's data corrections (speed limits, bike lanes, curated
  corridors) and approved overrides are applied after the rule tables.
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
  the slip lane rule; charging for the lane changes before a left; and the rural idea,
  which became our rural crossing factor of 1.25.
- **Differs:** Oregon lowers a crossing with a refuge by a whole level, which by our base
  costs would be about x0.4. RouteMaker multiplies the cost by 0.75 instead, a milder
  credit chosen by the owner (decision 196) so that an unsignalized crossing of a divided
  LTS 4 road stays red. Oregon scores a two-stage left as two crossings; RouteMaker caps a
  left at a signal at the price of a two-stage box turn. We have no roundabout rule yet.
- **An open question:** our cost for a left off an LTS 3 road, 0.11 calm mi [0.18 km], is
  below the range for crossing an LTS 3 road from a stop. The reasoning is that the rider
  already holds a lane and crosses one oncoming lane, but the code marks this value as a
  question for the owner (`intersections.py:139-141`), not a settled choice.

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
Transportation Research Part A. A GPS study of how riders trade distance against
traffic. Turns, signals, stops and unsignalized movements across busy roads each made a
route feel longer, by a share of a mile for each one. Each unsignalized movement straight
across, or left across, a road carrying 20,000 or more vehicles a day was worth 32-62% of
a mile, about 0.32 to 0.62 mi [0.51 to 1.00 km] of extra riding each time. Bike lanes
made up for traffic but added little on their own, and paths made a route feel 16-26%
shorter. Half of the trips were less than 10% longer than the shortest route.
- **Taken:** the size of the crossing costs (our 0.57 calm mi [0.91 km] for an LTS 4
  crossing sits inside the 0.32 to 0.62 mi range), the signal and stop costs, and the idea
  that a stretch of path counts for less than the same length of quiet street.
- **Differs:** Broach's figures describe the average choices of the Portland riders
  studied. **RouteMaker is stress-averse by default** (owner decision 14: most people
  should be sent on trails rather than faster LTS 3 and LTS 4 roads, and traffic-free
  paths get a category of their own). So its LTS 3 and LTS 4 road costs are well above
  Broach's (at Default, 2.9-5.8 and 12.9-15.8 calm miles per mile). Its path discount is
  also deeper than Broach's. Broach found a path made a route feel 16-26% shorter, so a
  meter of path counted as about 0.74 to 0.84 of a meter of quiet street. In RouteMaker a
  meter of path counts as about 0.55. The 0.55 is RouteMaker's own figure, not Broach's.

### Zimmermann, Mai and Frejinger (2017), Eugene
["Bike route choice modeling using GPS data without choice sets of paths"](https://doi.org/10.1016/j.trc.2016.12.009),
Transportation Research Part C (working paper
[CIRRELT-2016-49](https://www.cirrelt.ca/DocumentsTravail/CIRRELT-2016-49.pdf)). A route
choice model for Eugene, Oregon. Each intersection was worth about 716 ft [218 m] of
riding, and an unsignalized left across a busy road about 818 ft [249 m]. Lefts and
rights were otherwise much alike.
- **Taken:** our range for crossing an LTS 3 road from a stop, about 0.15 to 0.30 calm mi
  [0.24 to 0.48 km], starts at Eugene's 818 ft.
- **Differs:** we charge more for a left than a right (onto a busy road, a left is the
  crossing cost times 1.5 and a right times 0.1), following Copenhagen rather than
  treating them alike.

### Skov-Petersen, Barkow, Lundhede and Jacobsen (2018), Copenhagen
["How do cyclists make their way? A GPS-based revealed preference study in Copenhagen"](https://repository.up.ac.za/bitstream/handle/2263/65159/SkovPetersen_How_2018.pdf?sequence=1),
International Journal of Geographical Information Science. A left turn cost riders about
154 ft [47 m] of riding, and a right turn 62 ft [19 m]. Real detours averaged 28%,
against 40% in a survey.
- **Taken:** that a left costs more than a right (about 2.5 times as much in
  Copenhagen).
- **Differs:** Copenhagen's costs are small because its network is already calm. Ours
  price mixing with fast traffic, so they are much larger, and the gap between a left and
  a right onto a busy road is wider.

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
- **Taken:** the direction of the **planned** time-of-day factor (decision 468a).
- **Differs:** the size. The owner set the bands (decisions 469c-469e, **planned**, not
  built): x1.25 in the weekday rush windows (7-10 AM and 4-7 PM), x1.0 at other weekday
  hours to about 9 PM, x0.85 in weekend daytime, and at night x0.5 in urban areas and
  x0.85 outside them. The rush-hour factor is much milder than 1.75 because the sample is
  so small, and the factors would apply only to junctions with a busy road. The night
  bands are the owner's own judgment, not from this study.

## Other design guides and studies

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
- **Valhalla** 3.6.3 ([bicyclecost.cc](https://github.com/valhalla/valhalla/blob/master/src/sif/bicyclecost.cc)):
  the router. It cannot see which road is crossed at a junction, which is why the
  junction model works on the traced route ([intersections.md](intersections.md),
  section 1).

## Where the evidence has gaps

We found no test, on whole routes, of rating a route by its worst stretch against rating
it by its average. Comfort studies give no measured effect for trucks, for driveways per
mile, or for one-way against two-way streets at the same volume, and there are no
figures for leisure loops. The rural crossing factor at 45 mph [72 km/h] is a judgment
within the published ranges. So is the planned severe junction tier, and its cap of
about 2 mi [3.2 km] follows the owner's direction in decision 467, not a published value.
The project's reviews read these figures from the sources. Some came from search
summaries, and the reviews say which.
