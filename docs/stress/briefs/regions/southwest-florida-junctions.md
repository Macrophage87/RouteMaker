# Regional note: rating junctions in Southwest Florida

Read with the junction brief (docs/stress/briefs/JUNCTION-BRIEF-LEAN.md). These are guidelines for
how Southwest Florida tends to differ from DC to Baltimore, not rules. Each says "usually": depart
from it whenever a junction's own facts say otherwise, and give the reason in `why`.

## The roads

- Many main roads are six- or eight-lane divided arterials posted 45 to 55 mph, with long signal
  cycles, turn bays on every approach and free right-turn slip lanes: crossing a 45 mph six-lane
  road with bays is usually ten or more lanes of distance even at a signal.
- Most riders on these roads use a side path or wide sidewalk, not the roadway. Florida gives a
  rider on a sidewalk or crosswalk a pedestrian's rights and duties (Fla. Stat. 316.2065(9)-(10)).
  A sidewalk or side path beside an arterial is usually where the rider actually is at the
  junction, so rate `along` for the rider on that path, and say so in `why`.
- Rural two-lane roads at 55 mph usually have a paved shoulder; crossing one is a gap search at
  high closing speed: usually 3 to 3.5 with light traffic, 4 with steady traffic.

## Movements that usually differ from DC

- **Riding along a side path through a signalled junction.** The rider crosses the side street in
  a crosswalk while drivers turn right on green or on red, looking left for cars, not right for a
  rider coming the other way on the path. That is usually the main hazard here: about 2 to 2.5 at a
  plain side street, 3 or more where a free slip lane or a dual right turn crosses the path. Side
  paths are two-way, so assume the rider may come from the side drivers are not looking at.
- **Riding along a side path past an unsignalled side street or a busy driveway** (plaza, gated
  community entrance): drivers pull across the crosswalk to see gaps in the main road. About 1.5 to
  2; more where the side road is wide or fast.
- **Lefts at a median opening without a signal** across two or more lanes each way at 45 mph or more are
  usually 4.5 to 5: two gap searches at high speed with a short refuge. Where a directional median
  allows only a U-turn, the rider's left may not exist: leave it out.
- **Beacons at trail crossings.** Pedestrian hybrid beacons and rectangular flashing
  beacons are common at trail crossings. A hybrid beacon stops traffic like a signal. A flashing
  beacon helps about half a level on two lanes and little across four or more lanes at 45 mph.

## Waits

No signal waits have been measured on rides here yet. Long
arterial signal cycles usually mean a longer wait than a DC city grid: give your estimate from the
road's width and speed and put "signal wait not measured in this region" in `missing`. A gap
search across fast six-lane traffic is usually a minute or more at busy times.

## Data you will see

Speeds, lane counts and traffic counts on state roads come from FDOT (Roadway Characteristics
Inventory and AADT); elsewhere from OpenStreetMap. A missing signal tag is common on
suburban junctions; if a junction of two six-lane arterials has no signal tag, the tag is probably
missing: say so and set `second_look`. Do not rate from crash records or Street View.
