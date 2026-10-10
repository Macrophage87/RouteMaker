# The Mass Ride flow model against the literature

FOLLOWUP-FLOW-CALIBRATION (OWNER-DECISIONS 394; 406 and 407, provisional), the
literature half. This page checks each constant of `routemaker.flow` and
`routemaker.massflow` against published bicycle-flow studies. The other half is
the owner's DC event videos, and it is not done yet. **No constant has been
changed.** Changing one is the owner's call, after the video check. The full
references are in [SOURCES.md](SOURCES.md), "The Mass Ride flow model: literature
checked". Figures are US units first, with metric in brackets.

## What the literature can and cannot say

- **No rigorous mass-ride study was found.** Searches for Critical Mass, Bike Party
  and mass-participation rides turned up press counts of riders, but nothing that
  measured flow, density or speed. Every figure below comes from bicycle traffic:
  commuters on cycle tracks, queues at signals, or students on closed test tracks.
  None of it is a corked group on a closed road lane.
- Field capacities vary about threefold between studies. Wierbos et al. (2019) put the
  range at "between 2,600 and 8,100 bicycles per hour". Kaths et al. (2025) list
  1,500 to about 4,500 bicycles an hour per metre of width, and the spread comes from
  method (experiment or field count, how a "lane" is defined) as much as from
  behaviour. So the literature can show whether a constant is in a plausible range.
  It cannot set the constant to two figures.
- Experiments on closed tracks with students (Navin, Zhang, Wierbos, Guo) give
  higher capacities than field counts of everyday traffic (Buch and Greibe,
  Hoogendoorn and Daamen as Kaths tabulates them). A Bike Party, with its mixed
  abilities, slow pace and social riding, is closer to the field counts.

## The level figure: riders a minute per unit of width

The model: 60 × 0.37 riders/m² × 0.7 × usable width × 1.9 m/s. That is **9.0 riders
a minute per foot of usable width [29.5 per metre], about 99 per 11 ft (3.35 m)
lane**, or 1,770 riders an hour per metre.

| Source | Setting | As published | Riders/min per ft [per m] | Per 11 ft lane |
|---|---|---|---|---|
| Buch and Greibe 2014 | Copenhagen cycle tracks, field | about 3,000/h on 6.6 ft [2.0 m] | 7.6 [25] | 84 |
| Kaths et al. 2025, Table 1 | Copenhagen; Delft (field) | 1,500 and 1,531/h/m | 7.6 [25] | 84 |
| FHWA-RD-98-108 (1998) | signal discharge, 4 to 6 ft [1.2 to 1.8 m] lane | 2,000/h of green (ideal 2,600) | 5.6 to 8.3 (ideal 7.2 to 10.8) [18 to 27 (24 to 36)] | 61 to 92 (79 to 119) |
| Guo et al. 2021 | 10 ft [3 m] wide ring track, experiment | "go" state 0.55/s/m; Kaths: ~1,800/h/m | 9.1 to 10.1 [30 to 33] | 100 to 111 |
| Seriani et al. 2015 | Santiago cycle track, saturation flow | 2,070/h (3.3 ft [1 m]); 4,657/h (6.6 ft [2 m]) | 10.5 to 11.8 [35 to 39] | 116 to 130 |
| Yuan et al. 2019 | Amsterdam signal, 6.6 ft [2 m] path | saturation flow 4,376 to 4,626/h | 11.1 to 11.8 [36 to 39] | 122 to 129 |
| Guo et al. 2024 | 4.9 ft [1.5 m] bottleneck, experiment | 1.15 to 1.3/s | 14.0 to 15.8 [46 to 52] | 154 to 174 |
| Wierbos et al. 2019 | 1.6 to 4.9 ft [0.5 to 1.5 m] bottleneck, experiment | +1.11/s for each extra metre | 20.3 [67] (marginal) | 223 |
| Kaths et al. 2025, Table 1 | experiments (Navin; Zhang et al.) | ~4,500 and ~3,600/h/m | 18.3 to 22.9 [60 to 75] | 201 to 251 |
| Seriani et al. 2015 | London, Tavistock Square | 4,320/h on 3.3 ft [1 m] | 21.9 [72] | 241 |
| **The model** | DC Bike Party, owner's counts | 0.37 × 0.7 × 1.9 m/s | **9.0 [29.5]** | **99** |

**Supported.** The model sits in the field cluster (7.6 to 11.8 riders a minute per
foot [25 to 39 per metre]), in its lower half, and below every experiment. Its closest
match is Guo et al. (2021), the one study of a wide track at high density: once the
track held more than about one rider to 63 ft² [0.17/m²], flow "remained nearly
constant" at about 0.55 riders/s/m until one rider to about 22 ft² [0.5/m²]. The
model's 0.37 × 0.7 is 0.26 riders/m² of the full width at 1.9 m/s, which is 0.49
riders/s/m: inside that plateau. **Literature range:** about 5.6 to 23 riders a minute
per foot [18 to 75 per metre]; 7.6 to 11.8 per foot [25 to 39 per metre] for field
counts. **Recommendation:** no change.

## Each constant

### Safe density, 0.37 riders/m² (one rider to 29 ft² [2.7 m²])

- Guo et al. (2021), a 10 ft [3 m] track: free flow below 0.17/m² (one to 63 ft²);
  a flow plateau from there to 0.5/m² (one to 22 ft²); stop-and-go above 0.5; a jam
  density "around 0.8 bicycles/m²" (one to 13.5 ft² [1.25 m²]).
- Guo et al. (2024), a bottleneck experiment: critical densities "approximately
  0.125" and "0.2 cyclists/m2" upstream of the bottleneck.
- The model's 0.37 is measured over the effective width (0.7 of the road). Over the
  whole width it is 0.26/m² (one to 42 ft²). The owner's peak, 0.45/m², is 0.32/m² over
  the whole width. Both are inside Guo's plateau and below the 0.5/m² where flow
  breaks down. The owner's packed-solid estimate of 0.66/m² (one to 16 ft²) is
  looser than Guo's jam density of 0.8/m², which is the safe side.
- **Supported.** Range: about 0.17 to 0.5/m² for a moving, dense flow (one rider to
  63 to 22 ft²). **Recommendation:** no change.

### Utilisation, 0.7

- No study gives a utilisation factor for a group on a road. The nearest evidence is
  how riders spread across cycle tracks:
  - Buch and Greibe (2014), eight Copenhagen tracks 5.7 to 9.4 ft [1.73 to 2.85 m]
    wide: the second rider abreast rode with the centre of the bike 4.3 to 6.1 ft
    [1.30 to 1.85 m] from the kerb, and a third abreast was seen "only in a few
    cases, and only on the four widest tracks". On a 9.4 ft [2.85 m] track, two
    abreast reach about 7 ft [2.15 m], about 75% of the width; on the 5.7 ft
    [1.73 m] tracks, about 92%.
  - Kaths et al. (2025): density "built first on the right-hand side", and "only very
    low densities occurred on the far left-hand sublane".
  - FHWA-RD-98-108: a bicycle "lane" is "approximately 1.0 m (3.3 ft)" wide, and a
    lane up to 6 ft [1.8 m] "will operate with two effective lanes".
  - Guo et al. (2021): on a 10 ft [3 m] track, riders formed more lanes as density
    rose, so a dense flow used more of the width.
- **Partly supported.** Cycle tracks suggest about 0.75 to 0.9 of the width is used,
  and wide-track experiments suggest more at high density. The owner's measured 0.7
  (12.8 ft of 18.4 ft [3.9 m of 5.6 m]) is at or below that range, so it errs low.
  **Recommendation:** no change now. The video should measure the share of the width
  used on streets of different widths. If streets 30 ft [9 m] and wider show 0.8
  or more, raising utilisation for those streets would be justified, and would raise
  their figures by about 14%.

### Pace at the compressed state, 4.3 mph (1.9 m/s)

- Guo et al. (2021): in the plateau, flow of about 0.5 to 0.55/s/m at a density of
  0.26 to 0.5/m² means a mean speed of about 2.2 to 4.7 mph [1.0 to 2.1 m/s] (flow
  divided by density, worked here). The paper's maximum speed was 9.3 mph ("around
  15 km/h").
- Guo et al. (2024): congested riders upstream of a bottleneck rode 1.8 mph ("limited
  to a low value of approximately 0.8 m/s"); the desired free speed was 8.5 mph
  ("about 3.8 m/s").
- Free-flowing commuters are much faster: 13.4 mph [21.6 km/h] on the level (Parkin
  and Rotheram 2010); 13.5 mph [21.7 km/h] on Copenhagen tracks (Buch and Greibe
  2014); 11.2 mph [18 km/h] on US paths (FHWA-RD-98-108).
- Turning alone does not slow a rider to 4.3 mph: a solo rider took about 13 ft
  [3.9 m] radius turns at 6.6 mph [10.6 km/h] (Attalla et al. 2015, a small pilot).
  The model's slowing at a turn is the group's own (the owner's item 174), not the
  turn's geometry.
- **Supported** as a speed for a dense, moving flow. Range: about 1.8 to 4.7 mph
  [0.8 to 2.1 m/s] for congested to plateau flow. **Recommendation:** no change. No
  study measured the 6 to 8 mph cruising pace of a mass ride; it remains the owner's
  figure (item 174).

### Compression at turns, signals and pinches

- The model has no separate turn factor. The headline is already the compressed
  state, "a ride flows at its narrowest point". PLAN's part 2 plans a further
  capacity drop at sharp or narrow turns, which is not built.
- Capacity drop in the literature: Wierbos et al. (2019) found "the flow rate drops
  0.45 cyc/s when the cycling conditions change from free flow to congested". Their
  fit puts a 3.3 ft [1 m] path's capacity at about 1.59/s, so the drop is about 28%
  there (worked here). Guo et al. (2024) found 1.3/s while a bottleneck loaded and
  1.15/s while it unloaded, about 12% lower (worked here).
- Queue discharge at signals: 2,000 bicycles an hour of green on a 4 to 6 ft [1.2 to
  1.8 m] lane (FHWA-RD-98-108), and 4,376 to 4,626 an hour on a 6.6 ft [2 m] path
  (Yuan et al. 2019). Per foot these are close to the model's level figure (see the
  table), so the model's headline already holds at a signal restart.
- **Supported**, with a caution. A further turn drop on top of the headline would
  count the compression twice unless it is kept to turns sharper or narrower than
  the ones the owner filmed. **Recommendation:** no change. If part 2 adds a drop,
  the literature range is about 12 to 28%. The video should show whether the filmed
  turns already include it.

### Climbing: 1 / (1 + 12 × (grade − 1%)), set in over 490 ft (150 m), floor 30%

- Parkin and Rotheram (2010), UK commuters: on the flat, 13.4 mph ("6.01 m/s (21.6 kph)"), and
  "for every additional 1% of uphill gradient, the mean speed is reduced by 0.4002
  m/s". That is about 6.7% of the level speed for each percent of grade.
- Their line against the model's factor: 3%, 80% and 81%; 6%, 60% and 62%; 8%, 47%
  and 54%; 10%, 33% and 48%. The model has no loss up to 1%, where Parkin and
  Rotheram already lose 7%.
- Caveats: commuters riding alone at 13 mph, not a group at 7 mph; uphill sections in
  their data averaged 2.2%, so 8% and above is an extrapolation; adjusted R² 0.27.
- **Supported** to about 6%; the model is gentler above that. No source gives the
  490 ft (150 m) set-in or the 30% floor. **Recommendation:** no change before the video. A
  steep climb filmed at a ride would settle whether 8% and above should slow more.

### Descending: density × 1 / (1 + 5 × (grade − 4%)) past 4%, floor 60%; pace not raised

- No published source on group spacing on descents was found.
- Parkin and Rotheram (2010) found commuters speed up downhill, "0.2379 m/s" for each
  percent. The model does not raise the pace, which errs low.
- **Not checked: no literature.** **Recommendation:** no change. Keep "not from a
  measurement" in SOURCES.md, and film one descent.

### Width rules (OWNER-DECISIONS 404, 406, 407)

- **Travel lane, 11 ft (3.35 m), where no width is mapped.** NACTO's Urban Street
  Design Guide: "Lane widths of 10 feet are appropriate in urban areas"; "one travel
  lane of 11 feet may be used" on truck or transit routes; "lanes greater than 11
  feet should not be used". So 11 ft is the top of current guidance, and many
  untagged residential lanes will be narrower. **Partly supported.**
  **Recommendation (optional, owner's call):** read untagged residential and
  unclassified lanes at 10 ft (3.05 m), which lowers those figures by about 9%. DC's
  own Roadway Block widths are not affected.
- **Parked cars, 8 ft (2.4 m) a side where OSM gives no width (407 (2)).** NACTO:
  "Parking lane widths of 7–9 feet are generally recommended". NCHRP Report 766
  (2014): "the suggested width for the parking lane is 8 ft". **Supported.** No
  change.
- **Door zone, 3.5 ft (1.07 m), kept out of a bike lane beside parking (407 (1)).**
  NCHRP Report 766: "the open door zone width of parked vehicles extends approximately
  11 ft from the curb", "assuming the 95th-percentile parked vehicle displacement and
  an open door width of 45 in" (3.75 ft [1.14 m]). Past an 8 ft parking lane that is
  3 ft [0.9 m] of door zone, and past a 7 ft one 4 ft [1.2 m]. **Supported** (range
  3 to 4 ft [0.9 to 1.2 m]). No change.
- **A 16 ft or wider "lane" with no parking read at 11 ft (407 (3)).** No design
  guide gives a travel lane that wide (NACTO tops out at 11 ft), so reading it as a
  lane that also holds parked cars is consistent with the guidance. No study tests it
  directly. **Plausible; no direct source.** No change.
- **Own side of a two-way street only (406), reversible lanes counted as zero (405,
  407 (4)).** These are the owner's policy for how a ride should behave, not flow
  questions. The literature has nothing to add. No change.

## Summary

| Constant | Code value | Literature range | Verdict | Recommendation |
|---|---|---|---|---|
| Level figure | 9.0 riders/min per ft [29.5 per m]; 99 per 11 ft lane | 5.6 to 23 per ft [18 to 75 per m]; field 7.6 to 11.8 [25 to 39] | Supported, lower half of field counts | None |
| Safe density | one rider to 29 ft² of effective width (0.37/m²); to 42 ft² of full width (0.26/m²) | plateau one to 63 to 22 ft² (0.17 to 0.5/m²); jam one to 13.5 ft² (0.8/m²) | Supported | None |
| Utilisation | 0.7 | about 0.75 to 0.9 on cycle tracks; more at high density | Partly supported; errs low | Video: measure it by street width; maybe 0.8 on wide streets |
| Compressed pace | 4.3 mph (1.9 m/s) | 1.8 to 4.7 mph (0.8 to 2.1 m/s), congested to plateau | Supported | None |
| Turn compression | none beyond the headline | capacity drop 12 to 28% | Supported; caution on double counting | None; if part 2 adds a drop, 12 to 28% and only for sharper turns than those filmed |
| Climb slowing | 12 per unit above 1%, 490 ft (150 m) set-in, floor 0.3 | 6.7% of speed per 1% (one commuter study) | Supported to 6%; gentler above | None before video; film a steep climb |
| Descent spacing | 5 per unit past 4%, floor 0.6 | none found | Not checked | None; film a descent |
| Lane width default | 11 ft (3.35 m) | 10 to 11 ft (NACTO) | Partly supported (top of range) | Optional: 10 ft for untagged residential |
| Parking width default | 8 ft (2.4 m) parallel | 7 to 9 ft; 8 ft suggested | Supported | None |
| Door zone | 3.5 ft (1.07 m) | 3 to 4 ft past the parking lane | Supported | None |
| Wide-lane cap | 16 ft and up, no parking → 11 ft | none direct; guidance tops out at 11 ft | Plausible | None |
| Own side only; reversible zero | policy | n/a | Policy | None |

## For the video check

The literature leaves three open questions for the owner's DC event videos:

1. The share of the width a ride uses on streets of different widths (utilisation).
2. Density and pace on a straight at cruising pace, which no clip and no study has.
3. Pace on a climb of 6% or more, and spacing on a descent past 4%.
