# Rating roads beside schools at arrival time (lean brief)

Use with RATER-BRIEF-LEAN.md: same scale (1 to 4.5, 5 Avoid, half steps), same rules (rate blind,
no Street View, no crash records for the road itself, describe the road and never the people around
it). Studies of school zones as a type of road (national or published injury data by road type and
time of day) may be cited where they bear on the question, with the source.

## The question

Each road you are given lies on a school's grounds or within about 30 m of them: a bus loop, a
drop-off lane, a car park aisle, or the street in front. You are given the road (OSM way id,
name, class, its usual level and why), and the school (name, OSM id, location).

How stressful is riding this road on a school weekday between about 7:30 and 9 AM, when pupils
arrive? Rate that hour only. Its usual level stays as it is.

## What to weigh

- What the school is (elementary, middle, high; public or private) and roughly how many pupils,
  from the school's own site or a public school directory.
- Whether this road is the bus loop or the parents' drop-off lane (the school's arrival plan or
  map often says), the staff car park, or the street the queue spills onto.
- Buses turning across the road, cars stopping and pulling out, doors opening, children crossing
  between cars, crossing guards or staff directing traffic.
- A road the school closes to cars at arrival, or one used only by staff arriving early, may stay
  calm: say so.

Usually a busy bus loop or drop-off lane is about 3 at arrival, and the street in front 2.5 to 3,
less for a small school or a road the arrival plan keeps cars off. These are starting points, not
rules: depart from them where the evidence says, and give the reason.

## Output

One row a road: `way_id,level,why` (fixtures/school-times/rush-levels.csv). The why names what
you found and where. A level no higher than the road's usual one changes nothing.
