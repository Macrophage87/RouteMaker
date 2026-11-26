# Rating junctions for a rider (lean brief, draft 2026-11-14)

You rate how hard a junction is to get through on a bike, for an open-source bike route planner.
Each item is one junction: its legs (name, class, the road's stress level, lanes, speed, traffic
count, one-way, bearing, bike facility) and what is tagged about its control (signal, stop or yield
by approach, crosswalk and bike crossing tags, refuge island, beacon). Make a reasoned call from the
evidence and use your best judgment. Everything below is a starting point with its reason, not a
limit: depart from it whenever this junction's own evidence says so, and say why.

## What you rate

For each junction rate up to three movements. Each gets two separate numbers: `stress`, a level on
the road scale (1, 1.5, ... 4.5, 5), and `delay_s`, the seconds a rider typically loses there
(waiting for a signal or a gap, slowing and starting again). Keep them apart: a long red light at
a safe signal is high delay and low stress; darting across fast traffic can be low delay and high
stress. The planner weighs the two differently for different kinds of ride. Rate the hardest
ordinary case of each movement:

- `cross`: riding straight across the busiest road here, from the quieter legs.
- `left`: turning left off or onto the busiest road.
- `along`: what the junction adds for a rider going straight through on the main road, or on a
  path beside it: 1 when it adds nothing, however stressful the road. A trail crossing a road is
  `cross`. When two roads are alike, rate the harder and name it.

Leave out a movement that cannot be made. Levels mean what they mean for roads (Furth): 1 a child
can do it, 2 easy for most adults, 3 takes confidence, 4 hard even for confident riders, 4.5 very
hard but sometimes the only way, 5 not a real option. The planner turns a level into a cost in
quiet riding: about 100 ft for 1.5, 500 ft for 2, a third of a mile for 3, three quarters of a
mile for 4, two miles for 5.

## What matters

How many lanes the rider crosses in one go, how fast the traffic is, how much of it there is, and
whether anything stops it for them. Then: how far it is across, whether there is a place to wait
half way, whether drivers turning can see the rider, and how many things happen at once.

Waiting matters as well as fear: sitting at a stop sign for a gap in steady traffic is no fun, and
most riders would rather keep riding a little further (rider observation). Put the wait in
`delay_s`, and be honest about it: with no signal, steady traffic on two lanes means tens of
seconds, and a busy multilane road at rush hour can mean a minute or more. For signals, start from
the figures measured in the region you are rating (see "Measured waits by region" at the end).

Half a level off is fine; calling a hard crossing easy is the worst miss. You are not told signal
phasing, bike boxes, island width, sight lines, often turn lanes or which approaches stop: assume
the ordinary case, never the best, and list what you assumed in `missing`.

## Starting points

**A signal** stops the traffic, so the crossing is mostly delay: about 1 to 1.5 across a two-lane
road, 2 across four to six lanes, 2.5 across more or with fast free right turns. Cars turning
across the rider on green are what is left; a bike phase or leading interval takes most of that
away. A left turn at a signal on a multilane road is about a level harder than crossing it, unless
there is a bike box, a two-stage turn or a left arrow the rider can use from a bike lane.

**No signal, rider must find a gap** (stop sign or yield on the rider's leg, traffic on the other
road does not stop): one lane each way at 25 mph or less with light traffic: 1 to 1.5. Up to
30 mph or steady traffic: 2. One lane each way at 35 to 40 mph, or three to four lanes at 30 or
less: 3. Four or more lanes at 35 mph or more: 4 (a level above Furth's table at 35 mph, on purpose: riders reported that easier crossing levels left them at stop signs they could not get across from). Fast, wide and
busy with no gaps to speak of: 4.5 to 5. A refuge island: up to a level easier at 30 mph or less,
half a level at most on fast multilane roads. A flashing beacon: about half a level, less across
four fast lanes; a full bike or pedestrian signal makes it a signal. With no signal, a left off or
onto the main road is about as hard as crossing it, half a level more when merging across two
lanes.

**All-way stop on one-lane streets, or a mini circle on quiet streets:** about 1.

**Rider on the main road, side traffic stops:** `along` is about 1; do not add for quiet
side streets.

**Roundabouts and circles:** one circulating lane at low speed is about 2 to ride through. Two or
more circulating lanes, or fast entries: 3 to 4, because cars cross the rider's path at every exit.
A big signalled city circle ridden on the roadway is still about 3 to 3.5 (lane changes, many
exits); about 2 where a path or signalled crossings carry riders round. Give one level for all
movements unless going further round is clearly harder.

**Slip lanes and ramps:** a free-flowing right-turn lane or highway ramp the rider must cross, or
that crosses the rider, is the hard part of the junction even at a signal, unless the slip lane is itself signalled: about 3 at city
speed with a marked crossing, 4 where traffic is accelerating onto a highway.

**Trails and protected lanes crossing a road** are rated as `cross` from the trail. Riders there
include children, so look hardest at these: an unsignalled trail crossing of a fast multilane road
is about 4 or more: a good trail does not make the road easier to cross. A marked trail crossing
is a crosswalk, where drivers must by law stop or yield for someone in it: better than a plain
give-way, not nearly as good as a signal (the owner, 2026-11-15). Take about half a level to a
level off on a two-lane road or at 30 mph or less, little across fast multilane roads, where the
driver in the second lane often does not stop; expect some wait either way and say it in `delay_s`.

**Many legs or offset legs** (five or more, or two junctions a few yards apart): about half a level
harder than the same crossing at a plain four-way, more if the signal has long gaps between turns.

## Things that fool raters

- The road's stress level is about riding along it. A road rated calm because it has a protected
  lane is no easier to cross: judge crossing from its lanes, speed and traffic.
- Lanes at the junction include turn lanes. For crossing, count them all: that is the distance.
- A tagged crosswalk says paint, not that traffic stops.
- A count may belong to another road, and a missing signal tag is common on small junctions. Say
  when the control is a guess.
- Do not rate from crash records, and do not look at Street View.

## Output

A JSON array, one object per junction id:

```json
{"id": "J000123",
 "cross": {"stress": 3, "delay_s": 35},
 "left": {"stress": 3.5, "delay_s": 40},
 "along": {"stress": 1, "delay_s": 3},
 "confidence": "medium",
 "why": "Two-way stop for the side street across a four-lane 30 mph road with about 14,000 cars a day and no refuge: gaps are short.",
 "missing": ["whether the crossing has a beacon"], "second_look": false}
```

`why` is one or two plain sentences a rider can read, with the facts that decided it. Set
`second_look` true when you are torn by 1.5 levels or more, when the control is a guess on a major
road, or when you rate a crossing of a major road at 2 or less without a signal.


## Measured waits by region

Averages over green and red, from rides in that region. Where a region has none yet, start from the
nearest kind of place and say so in `missing`: a signal's wait grows with how wide and fast the main
road is, so a long-cycle signal on a six-lane 45 mph road usually costs more than a city-grid one.

| Region | Riding along a main road, per signal | Crossing one | Source |
|---|---|---|---|
| DC to Baltimore | about 6 s | about 13.5 s | the owner's rides, 2026-11 |
| Southwest Florida | not measured yet | not measured yet | |
