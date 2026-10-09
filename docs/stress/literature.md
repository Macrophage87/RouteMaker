# The literature RouteMaker draws on, and where it differs

[Index](README.md). A summary, in our words, of the research consulted for the stress
model, from the project's two literature reviews (`LTS-literature-review.md`,
`LTS-literature-review-2.md`). For each source: what it found, what RouteMaker took, and
where RouteMaker **deliberately differs**, and why. Figures are US first, metric in
brackets. Where a figure is a judgement or from a small sample, it is said. Related:
[intersections.md](intersections.md), [classification.md](classification.md),
[routing-costs.md](routing-costs.md), [stress-number.md](stress-number.md).

## Level of Traffic Stress

### Mekuria, Furth and Nixon (2012), Mineta Transportation Institute 11-19
[Low-Stress Bicycling and Network Connectivity](https://transweb.sjsu.edu/sites/default/files/1005-low-stress-bicycling-network-connectivity.pdf).
Defines Level of Traffic Stress, LTS 1-4, from lookup tables on speed, lanes, volume and
facility, the worst factor governing. It also scores crossings by the crossed road's speed
and lanes, with a median refuge lowering the score about a level.
- **Taken:** the four levels, the weakest-link rule, the tables ([classification.md](classification.md)), and the crossing logic behind the junction costs.
- **Differs:** RouteMaker adds a fifth tier, **Avoid**, for a road a bicycle may legally use but nobody should be sent onto; the tables never produce it. It also plans **half steps**, costed at the midpoint of the two levels, which the published scale does not define. The published levels are ordinal, so RouteMaker sums a per-preset **cost multiplier**, not the level.

### Furth, LTS 2.0 and 2.2 (2017, 2022)
[Furth's LTS pages](https://peterfurth.sites.northeastern.edu/level-of-traffic-stress/) and
[LTS Tables v2.2](https://bpb-us-e1.wpmucdn.com/sites.northeastern.edu/dist/e/618/files/2014/05/LTS-Tables-v2.2.pdf).
Refines the tables: lanes per direction, volume bands, speed bins, bike-lane width
including the buffer, the 15 ft [4.6 m] reach beside parking, one-way streets, and rural
crossings (a road at 45 mph or more starts above the lowest level).
- **Taken:** the base for the classifier, including the lane and buffer rules; the rural idea became our 1.25 rural crossing factor.
- **Differs:** the owner's data corrections (speed limits, bike lanes, curated corridors) and approved overrides are applied after the rule tables. Furth keeps LTS 1 and 2 as different levels, but **RouteMaker's routing cost does not separate them**: no rule in the router distinguishes LTS 1 from LTS 2.

### Oregon DOT Analysis Procedures Manual, chapter 14
[ODOT APM v2 ch. 14](https://www.oregon.gov/odot/Planning/Documents/APMv2_Ch14.pdf).
Tables for unsignalised crossings by speed, lanes and volume; a median refuge lowering the
level (a 10 ft [3 m] refuge for LTS 1); vehicular lefts by lanes crossed (any left at 35 mph
or more is LTS 4); right-turn lanes and slip lanes; roundabouts.
- **Taken:** the shape of the crossing costs, the left-across-oncoming values (LTS 3 for one lane, LTS 4 beyond), the refuge credit (x0.75), the slip lane rule, and lane merges for lefts.
- **Differs:** our cost for a left off an LTS 3 road (0.11 calm mi) is below the range for an LTS 3 crossing from a stop, because the rider already holds the lane. Oregon scores a two-stage left as two crossings; RouteMaker caps a signalised left at a box turn. We have no roundabout rule yet.

### Montgomery County Planning, LTS 0-5 (Appendix D)
[Montgomery Bicycle Master Plan, Appendix D](https://montgomeryplanning.org/wp-content/uploads/2017/11/Appendix-D.pdf).
A county variant on a 0-5 scale: LTS 0 for traffic-free paths, an LTS 2.5 for the gap
between 2 and 3, stricter on sidepaths with driveways, and LTS 5 for roads to avoid.
- **Taken:** the county layer as calibration data and as a source of Avoid rows; its 2.5 inspired half steps; its LTS 0 supports the traffic-free path category.
- **Differs:** our half steps are 1.5, 2.5, 3.5 and 4.5, not only 2.5. The county's rows are input; the owner's approved overrides can change them (the Veirs Mill Road decision, for example).

### MDOT statewide LTS (2022)
[MDOT methodology](https://www.mdot.maryland.gov/OPCP/MDOT_LTS_Metadata_Methodology_Full.pdf).
A statewide 0-5 layer whose LTS 5 means "Bicycle Access Prohibited". It imputes speeds from
road class and ignores intersections and blockage.
- **Taken:** a statewide comparison, and the idea of imputing a missing speed.
- **Differs:** RouteMaker's Avoid is legal-but-avoid. Access is decided separately and **errs closed**: where it is unclear whether bicycles are allowed, the way is closed, and reopened only by an override with evidence.

### Arlington County Bicycle Comfort Index (2024) and DC, Virginia and Census data
[Arlington BCI methodology](https://www.bikearlington.com/wp-content/uploads/2024/12/bikearlington-bicycle-comfort-level-map-methodolgy-2024.pdf):
a 0-150 composite with published point weights (signal 0, all-way stop -1, two-way stop -2,
uncontrolled -5). Also used: DDOT traffic volume and roadway block data, VDOT traffic
volumes, and US Census TIGER/Line street records.
- **Taken:** local volumes and street records (credited on the rider page); Arlington's ordering of controls guides our control costs.
- **Differs:** agency data is input to the rule set, not the answer, and the owner's curated files take precedence. Arlington's index is a compensatory sum, while RouteMaker keeps a weakest-link tier and sums only costs.

## Route choice and node costs

### Broach, Dill and Gliebe (2012), Portland
[Broach et al.](https://ppms.trec.pdx.edu/media/1307553839HIVYEAW.pdf). A GPS study of how
riders trade distance against traffic. Turns, signals, stops and unsignalised crossings of
busy roads each add a share of a mile; a crossing of a road with 20,000 or more vehicles a
day cost 32-62% extra per mile ridden. Bike lanes offset traffic but added little; paths
were worth a 16-26% distance bonus. Half of trips were under 10% longer than the shortest.
- **Taken:** the size of the crossing costs (our 0.57 calm mi for an LTS 4 crossing sits within the derived 0.32-0.62 mi range), the signal and stop costs, and the idea that a path meter counts for less than a quiet one (about 0.55).
- **Differs:** Broach's coefficients are averages of mostly commuting riders; non-commute trips were more sensitive. **RouteMaker is stress-averse by default** (an owner decision: most people should be sent on trails over faster LTS 3 and 4 roads), so its LTS 3 and 4 road costs are well above Broach's (Default: 2.9-5.8 and 12.9-15.8 calm mi per mile).

### Zimmermann et al. (2017), Eugene
[Zimmermann, Mai and Frejinger](https://doi.org/10.1016/j.trc.2016.12.009) (working paper
[CIRRELT-2016-49](https://www.cirrelt.ca/DocumentsTravail/CIRRELT-2016-49.pdf)). A route
choice model: about 716 ft [218 m] per intersection and 818 ft [249 m] for an unsignalised
left across a busy road; lefts and rights otherwise alike.
- **Taken:** the LTS 3 crossing range (0.15-0.30 calm mi) is anchored on 818 ft.
- **Differs:** we price lefts above rights (x1.5 onto a busy road, 0.1 for a right), following Copenhagen, not equal.

### Skov-Petersen et al. (2018), Copenhagen
[Skov-Petersen, Barkow, Lundhede and Jacobsen](https://repository.up.ac.za/bitstream/handle/2263/65159/SkovPetersen_How_2018.pdf?sequence=1).
A left turn cost riders about 154 ft [47 m], a right 62 ft [19 m]; real detours averaged
28%, against 40% in a survey.
- **Taken:** lefts cost 2-3 times rights.
- **Differs:** Copenhagen's costs are small because its network is already calm. Ours price mixing with fast traffic and are much larger.

### Ton et al. (2017), Amsterdam
[Ton and colleagues](https://swov.nl/en/publicatie/how-do-people-cycle-amsterdam-netherlands)
(abstract only). In a saturated network riders cared more about fewer intersections per km
than about separate paths.
- **Taken:** support for pricing junctions as well as road meters.
- **Differs:** this is a dense Dutch grid; for a mixed American region we rank the road's own stress first.

### Caviedes and Figliozzi (2018), Portland wearable sensors
[Caviedes and Figliozzi](https://doi.org/10.1016/j.trf.2018.06.032). A small sensor study of
riders' stress response. Peak-hour stress was reported at about 1.75 times off-peak, in a
sample said to be five riders (not confirmed from the full text).
- **Taken:** the direction of the **planned** time-of-day factor (decision 468a).
- **Differs:** the size. **The x1.25 rush-hour and x0.85 off-hours factors are the owner's choice**, far milder than 1.75 because of the sample, and they apply only to busy-road junctions.

## Other design guides and studies

- **CROW (Netherlands) and UK LTN 1/20** ([LTN 1/20](https://assets.publishing.service.gov.uk/media/5ffa1f96d3bf7f65d9e35825/cycle-infrastructure-design-ltn-1-20.pdf)): mixing with cars is acceptable below about 2,000-2,500 vehicles a day at 20 mph [30 km/h]. *Taken:* a cross-check on LTS 1-2. *Differs:* we use the US tables and volumes.
- **TfL and Germany's ERA 2010** ([Peters summary](https://verkehrslexikon.de/PDF/Peters_ERA_2010.pdf)): signals above about 800-1,000 vehicles per peak hour; direct lefts limited to one lane change; sidepaths disfavoured where junctions and driveways are frequent. *Taken:* that lane changes before a left are stressful, and that frequent junctions matter. *Differs:* we price them as costs, not design rules.
- **Transport for NSW** ([Cycleway Design Toolbox](https://www.transport.nsw.gov.au/system/files/media/documents/2023/Cycleway-Design-Toolbox-Web.pdf)): mixing only on quiet streets of 19 mph or less; painted lanes unsuitable on priority routes. *Taken:* support for a strict comfort line. *Differs:* a cross-check only.
- **Harris et al. (2013)**, Vancouver and Toronto injuries ([PMC3786647](https://pmc.ncbi.nlm.nih.gov/articles/PMC3786647)): crossings where two minor streets meet had far lower odds of injury than major-major. *Taken:* supports charging only junctions that involve a busy road. *Differs:* injury risk is not comfort; we price comfort.
- **Harvey, Fang and Rodriguez** (MTI 19-20, [report](https://transweb.sjsu.edu/sites/default/files/1711-Fang-Bicycle-Level-of-Stress-Crowdsourced-Route-Satisfaction.pdf)): LTS is ordinal, so averaging levels assumes spacing it was not designed for. *Taken:* we average per-preset costs, not levels. *Differs:* their crowd ratings tracked LTS only weakly (rank correlation 0.13-0.26), so we do not claim the fine steps are validated.

## Data and software

- **OpenStreetMap** contributors (ODbL): the map data. *Differs:* **we err closed** on access, as above.
- **Valhalla** 3.5.1 ([bicyclecost.cc](https://github.com/valhalla/valhalla/blob/master/src/sif/bicyclecost.cc)): the router. It cannot see which road is crossed at a node, which is why the junction model works on the traced route ([intersections.md](intersections.md) section 1).

## Where the evidence has holes

No route-level test of worst-link against average was found. Comfort studies give no
dose-response for trucks, driveways per mile, or one-way against two-way at equal volume,
and there are no leisure-loop coefficients. The rural 45 mph crossing and the planned severe
junction tier are judgement within published ranges, and its 2 mi ceiling is the owner's
choice (decision 467), not a published value. Figures were read from the sources by the
project's reviews; some came from search summaries, which the reviews label.
