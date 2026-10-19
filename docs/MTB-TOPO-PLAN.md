# Mountain-bike and topo: plan

The backlog item "MTB/topo modes". This plan collects what the owner has decided, splits the
work into slices that each ship on their own, and says which defaults were picked where nothing
settles a detail. Owner decision numbers refer to the owner decisions record
(OWNER-DECISIONS-2026-09-26b.md, outside the repository; PLAN.md "Owner amendments" carries the
ones already built).

## What the owner has decided

- **A dedicated MTB mode, much later** (90, 111, 148). 111: "We will need a whole dedicated MTB
  mode. There's a whole set of criteria there." 148: "Mountain bike mode is much later." Every
  current ride type keeps closing mountain-bike singletrack (`rm:no_bicycle=singletrack`, and the
  `routemaker.trailaccess.MTB` class).
- **Optional map layers** (454, 2026-10-08; the record's entry is a heading with bullets, the
  owner's decisions as recorded, quoted here as written there):
  - "Three map layers for everyone (every mode, signed out too), off until clicked on: topo
    lines, climbs, mountain-bike trails."
  - "The mountain-bike trail layer replaces the always-drawn 'not used for routes' trails (452a);
    those trails are hidden until the layer is turned on."
  - "Mountain Goat and Mountain Bike are separate modes. Build our own topo map from
    OpenTopoMap's style. Link to MORE for trailheads and trail info. All this comes after the
    Capital Bikeshare work."
- **Trail difficulty colours** (456, 456a-c, 2026-10-08). One scale of levels, the higher of
  `mtb:scale` and `mtb:scale:imba` setting it: level 1 (IMBA 1, S1) green, 2 (IMBA 2, S2) blue,
  3 (IMBA 3, S3) black, 4+ (IMBA 4, S4-S6) red. A way rated 0 on its scale or scales, and not
  1 or more on the other, is a gravel trail, not an MTB level (456b: a way rated 1+ on the other
  scale is singletrack): it keeps the ordinary unpaved path look (main already treats it so:
  `routemaker.singletrack`, `routemaker.trailaccess`). Each level also has its own line pattern
  and a contrasting casing (not colour alone), and the legend and road panel name the level in
  words.
- **Gravel's "roughest I'll ride" setting** (456d, 457, 457a, 457b for the name, 457c;
  FOLLOWUP-GRAVEL-MTB). Gravel keeps to level 0 by default; a setting lets the rider allow MTB
  levels 1, 2, 3 and 4+. It lifts
  only the singletrack closure: trails closed for access (`bicycle=no`, park rules such as Rock
  Creek and Potomac Overlook, err closed) stay closed. No gravel (ISGG) numbers in the product
  for now (457c).
- **Rated trails with no bicycle tag** (the owner's choice of 2026-10-19, "Rated, MTB and
  Gravel"): a natural surface with no bicycle tag no longer keeps a rated trail closed (a
  rating means mappers saw bicycles ride it; `pipeline.trail_closures.RATING_OPENS`), so the
  layer draws it and the Mountain Bike graph rides it. The off-road graph (Gravel, Mountain
  Goat) rides the drawn rated singletrack up to `routemaker.singletrack.OFFROAD_MAX_LEVEL`
  (green, 1, while the owner's level choice is open). Unrated dirt paths stay closed.

## Slices

Each slice is its own branch, review panel and PR. 454 puts this work after the Capital
Bikeshare work; slice 1 is small and front end only (a switch and its wiring, in hunks of
App.tsx and MapView.tsx apart from the bikeshare branch's), so it goes first without holding
bikeshare up; that is a departure from 454's order, stated here and in PLAN.md. The data
slices (2-6) wait for bikeshare.

1. **The mountain-bike trail layer switch** (454). Built on `claude/mtb-topo-modes-auy24x`.
   A "Mountain-bike trails" switch in the Map layers sheet, under a new "Trails and terrain"
   heading that topo lines and climbs join later. Off by default; remembered per browser
   (`routemaker.mtbTrails`), like "Show bike lanes on high-stress roads". It shows or hides the
   existing not-for-routes line (`mtb-trail`, 452a) and nothing else. Front end only: the tiles
   already carry `mtb`, so no rebuild.
   - Default picked: the layer follows its own switch alone, with the traffic-stress map on or
     off and in every ride type, Mass Ride included, because 454 says "every mode". For this
     one layer that overrides 126 ("Ignore off road trails and the like, don't even show them")
     and 417a; Mass Ride still draws no other trail.
   - Default picked: the legend's mountain-bike row shows only while the layer is on, so the
     legend names what the map draws; in Mass Ride it sits under the capacity legend. The
     switch's own description also says what the line looks like.
   - Default picked: kept per browser, like "Show bike lanes on high-stress roads".
   - The road panel still describes a mountain-bike trail as "not used for routes" when asked
     about one, with the layer on or off, because it answers from the segment table, not from
     what is drawn; its Bike access line now says the dotted line is drawn "when the
     Mountain-bike trails map layer is on".
2. **Difficulty levels on the layer** (456-456c). A tile property `mtb_level` (1-4, left out
   for the rest) from a new `segment.mtb_level` column written at build time from
   `mtb:scale`/`mtb:scale:imba` (higher of the two; S1-S3 to 1-3, S4-S6 to 4). The layer then
   draws each level in its colour (green #2e7d32, blue #1565c0, black #1c1917, red #c62828 as
   starting values, checked against the base map at 3:1 like `MTB_TRAIL`), with a pattern per
   level and a casing. Default picked: unrated mountain-bike-class trails keep today's grey
   dots. Legend rows
   per level, and the road panel names the level ("Mountain-bike trail, level 2 (blue)").
   Needs: a core migration (0013 or later: the stress editor took 0011 and bikeshare 0012), a tile ETag letter, and a rebuild on the
   owner's host.
   - Status: built on `claude/v0-4-0-mtb-levels` (from release/v0.4.0); waits for a rebuild on the
     owner's host (docs/OPERATIONS.md, "Mountain-bike difficulty levels"). `segment.mtb_level`
     (smallint 1-4, CHECK), migration core 0013 (state-only, after 0012), tile property
     `mtb_level` (left out when null), ETag letter `d`; `FORMAT_VERSION` stays 8 (the property
     comes only with a new table). The front end draws each level in its colour (the starting
     values, the green darkened to #28702c), each with its own dash pattern (long dashes, short
     dashes, dash-dot, dash-dot-dot) and the shared dark cross-ticks; legend rows per level while the layer is on (Mass Ride legend too); the road panel's
     Bikes line reads "Mountain-bike trail, level 2 (blue), not used for routes" and its Riding
     section has a "Mountain-bike difficulty" row. The rebuild log gives the ways and miles per level
     (drawn and not) that slice 3 is to be shown with.
   - Default picked: **a rating of 0 is no level** (null), on either scale, unless the other scale
     says 1 or more, as 456b has it (a gravel trail, not an MTB level): such a way keeps the look
     it has unrated (an ordinary unpaved path, or the grey dots if it is mountain-bike class).
   - Default picked: values read as their number (`2+` 2, `1-` 1, `S2` 2); a range or list (`1-2`,
     `1;2`) as its higher end, so a trail is never drawn easier than its mapper rated any part of
     it; a number past the scale's top (7 on `mtb:scale`, 5 on IMBA) reads as the top, level 4
     (review of slice 2: never the unrated grey, which says Gravel and Mountain Goat may use it).
   - Default picked (review of slice 2): the level is written **on rated singletrack only**
     (`pipeline.trail_closures.mtb_level`), so a level always means closed on every graph. A
     mountain-bike-class way whose rating the singletrack rule does not read (`S2`, `0-2`) gets no
     level and stays the grey dots the off-road graph rides; a paved trail with a rating (Upper Rock
     Creek, the Cross County Trail) is not singletrack and gets none.
   - Default picked, and a change the levels need: **rated singletrack is now drawn on the layer**.
     It was `map_class='hidden'` (never in a tile), so with no change the levels would have had
     almost nothing to draw. It is now drawn (with `mtb`, so only on this layer) where nothing but
     its rating closes it; where the tag rules would close it anyway (`bicycle=no`, private, park
     paths, err closed and the rest) or it is a walk-your-bike way, it stays hidden, so the layer
     never draws a trail a bicycle may not be allowed on. Routing is unchanged. This is a change
     of what the map shows: rated singletrack that is open but for its rating was hidden under 126
     and is now drawn on the opt-in layer, under 452a (the not-for-routes look), 454 (an optional
     layer, off by default, which overrides 126 for the trails it draws) and 457a.
   - Default picked (review of slice 2, 452a "clearly unlike any routable trail or road"): one
     not-for-routes mark shared by every level (`MTB_LEVEL`), the colour and the pattern differing
     by level: short dark cross-ticks under the line in place of a casing (every stress tier has a
     solid casing), gaps of 1.5 line widths or more (no tier's passes 1), and a 2 px line (2.5 px
     with the accessibility switch), thinner than any tier. It replaced a solid white casing, which
     made a level read as one more routable line. mtbLevels.test.ts compares every level with every
     tier on dash, edge and width; the z15 screenshot is reports/v0.4.0/mtb-levels-vs-stress.png in
     the project files. Contrast against the base map, lowest surface (scrub): green #28702c 3.57:1
     (darkened from the starting #2e7d32, 3.0009:1), blue 3.36:1, black 10.24:1, red 3.29:1.
   - Trail names: the owner, 2026-10-10 (15:16 UTC): "Also, for mountain bikes, try to make sure trail names are added in if they are available." Built
     on the same branch as a later commit: `segment.mtb_name` (core migration 0014) from the OSM
     `name`, else `mtb:name`, else `ref`, on the mountain-bike-only ways; tile property `name`
     (left out when none), ETag letter `n`; labels along the line on the mountain-bike layer only,
     from zoom 15, in the line's colour on a white halo (each 4.5:1 or more), thinned by MapLibre's
     collision; the road panel's Bikes line names the trail ("Mountain-bike trail, level 2 (blue):
     Rosaryville Trail, not used for routes"); the rebuild log counts the named ways.
   - Default picked: names come from the way's own tags only, not from a route relation's name, so
     a way is never labelled with the name of a long route it merely shares.
   - Default picked: the switch's description names the levels ("From zoom 14: levels 1 to 4 by
     colour and pattern, unrated as grey dots. Not used for routes; Gravel and Mountain Goat may use
     unrated ones."), since rated singletrack is closed for Gravel and Mountain Goat too.
3. **Gravel's "roughest I'll ride" setting** (FOLLOWUP-GRAVEL-MTB). Needs slice 2's level per
   way in the graph: a per-level `rm:no_bicycle` variant, or Valhalla's own `mtb:scale` reading
   in the off-road graph's costing. To be designed once slice 2's counts per level are known,
   and shown to the owner with those counts.
4. **Topo lines** (454). Contours drawn from USGS 3DEP (public domain; docs/SOURCES.md already
   lists the one-arcsecond tiles the ELEVATION stage fetches). One arcsecond (about 100 ft
   (30 m)) is coarse for contours; the 1/3 arcsecond product (about 33 ft (10 m)) is the
   candidate, at a 20 ft (6 m) interval with every fifth line an index line labelled in feet.
   Built on the owner's host (`gdal_contour` to vector tiles, served beside the base map as
   PMTiles), off until turned on. Default picked: "Build our own topo map from OpenTopoMap's
   style" is read as a contour overlay on the current base map, which fits 454's "topo lines"
   layer; a whole topo base map is the alternative, asked below. The look follows OpenTopoMap's (brown contours, index lines
   heavier); its repository's README gives the online map's licence as CC-BY-SA and names no
   licence for the style code (checked 2026-10-10), so the style is rewritten here, not copied,
   and the credit line names OpenTopoMap as the look's source. Needs: owner approval of the
   download, disk and build time on the host.
   - Answered (the owner, 2026-10-10, 5:34 pm, with the defaults: a contour overlay on the current
     base map, 3DEP 1/3 arc-second): "For topo, have the lines scale with zoom." Every 100 ft (30 m)
     at zoom 12 and below, 40 ft (12 m) at zoom 13, 20 ft (6 m) from zoom 14, every fifth line a
     heavier index line labelled in feet (metres in brackets), widths growing with zoom.
   - Status: built on `claude/v0-5-0-mtb-topo`; the data waits for the build host
     (docs/OPERATIONS.md, "Topo lines"). `scripts/build_contours.py` traces every 20 ft line and
     writes `contours.pmtiles` with three layers by coarsest spacing (`c100` from zoom 10, `c40`
     from 13, `c20` from 14); `frontend/src/lib/topoLines.ts` draws each zoom band's own spacing
     and its index lines and labels, under the base map's roads, and adds the switch under "Trails
     and terrain".
   - Default picked: drawn from zoom 10 (the archive's lowest zoom); nothing zoomed further out,
     where a 100 ft spacing over the region is a smear.
   - Default picked: brown lines (#b07d4f, index #8a5a2c), labels #7a4e24 on a white halo (over
     4.5:1); written here, not taken from OpenTopoMap. The source's credit reads "Topo look after
     OpenTopoMap"; USGS 3DEP is already in the map's credits.
   - Default picked: no 0 ft line (it would trace every tidal shoreline the base map draws).
5. **Climbs layer** (454). Named climbs drawn on the map with their length and average grade
   (US units first). Source and definition to propose: the sustained-climb reading in
   `routemaker.climbs` run over the road and trail network once at build time, or a curated
   list. Needs the owner's pick.
   - Decided (the owner, 2026-10-10 and 2026-10-11; reports/v0.5.0/climb-categories.md in the
     project files): Garmin's scale, score = length (m) x average grade (%), with a Cat 5: Cat 5 over
     4,000, Cat 4 over 8,000, Cat 3 over 16,000, Cat 2 over 32,000, Cat 1 over 64,000, HC over
     80,000; "Uncategorized is not a hill". Scored on net gain with short dips and flats as breaks.
     At least 0.31 mi (500 m) at 1% (rail trails count) and a Cat 5 score. The summit marker shows
     the category; its shape follows the average grade: circle under 4%, square 4-7.9%, diamond 8%+.
   - Status: built on `claude/v0-5-0-climbs`; the data waits for the build host
     (docs/OPERATIONS.md, "The Climbs layer"). `routemaker.climb_categories` finds and categorises
     climbs (its own break rule: a dip ends a climb past 20% of the gain so far, at least 33 ft
     (10 m) and at most 165 ft (50 m); a flat, or the way down into a dip, past 25% of the length
     so far, at least 0.25 mi (400 m) and at most 1 mi (1,600 m), the climb back out of a dip not
     counted but the whole stretch capped at twice that; gentle ends trimmed); the route
     cost's 3 m rule in `routemaker.climbs` is unchanged. `pipeline.climb_layer` joins the live
     table's routable ways into strokes, samples the 3DEP tiles every 98 ft (30 m), reads both
     ways, drops a climb against a one-way, and writes the file; `manage.py build_climbs` runs it.
     The file is committed as `frontend/src/climb-data/climbs.json` (empty until then). The front
     end draws the summit markers from zoom 9 and the dashed lines from zoom 12, a card on a tap,
     a legend, and "Climbs on your route" in words.
   - Default picked: climbs come from the build-time reading, not a curated list, and only on
     ways a ride type can use (not the mountain-bike-only ways, closed for every ride type until
     slice 6).
   - Default picked: one colour for every climb (#9d174d), the shape and the number carrying the
     meaning; where two summits meet, the bigger climb's marker is drawn and both are listed.
6. **The Mountain Bike mode** (90, 111, 148, 454). A ride type of its own, separate from
   Mountain Goat, that seeks trails rather than closing them: its own graph or variant built on
   the off-road graph, opening singletrack up to a chosen level, with the mountain-bike layer on
   and drawing those trails as routable (`MTB_TRAILS_ROUTABLE` / `routableMtb`). It must then
   filter the routable mountain-bike lines on `mtb_level` (the levels it opens), as the
   not-for-routes layer does: `routableMtb` today only switches the not-for-routes layers off and
   lets the routable layers draw every `mtb` way, whatever its level. Trail pages
   link to MORE (Mid-Atlantic Off-Road Enthusiasts) for trailheads and trail information. The
   criteria ("a whole set of criteria") are the owner's to set; this plan asks for them when the
   slice starts.
   - Answered (the owner, 2026-10-11, 7:45 am, "Those work for me.", to the criteria
     listed in /mnt/project-files/plans/v0.5.0-plan.md): hardest trail level 2 (blue, IMBA 2),
     a choice of 1-4; unrated mountain-bike trails as level 2; strong trail seeking (a trail mile
     about half a road mile); connecting roads up to LTS 2, LTS 3 for gaps under 0.5 mi; hills at
     "fine with hills"; a loop from a trailhead on by default; about 6 mph (10 km/h) on
     singletrack for the time; the mountain-bike and contour layers on; one-way trails followed;
     bike-banned and hiking-only trails always closed (unclear access closed); wet closures not
     routed on, the trail page linking to MORE's conditions; one MORE link per trail system where
     MORE has a page, else one general link.
   - Status: built on `claude/v0-5-0-mtb-topo-mode` (stacked on slice 4); the graph waits for the
     release's rebuild on the owner's host. PLAN.md, 454, "Status, the Mountain Bike mode", says
     what it does; docs/OPERATIONS.md, "The Mountain Bike graph", how to build and start it.
   - How the level is held: one graph opens every level (`pipeline.trail_closures.mtb_graph_keeps`:
     the mountain-bike class, and rated singletrack that only its rating closes), and the rider's
     level is held at plan time on the router's routes (`core.mtb.settle`, rules in
     `routemaker.mtbmode`), so a level change needs no other graph.
   - The map: `stressFilters`' `routableMtb` takes the chosen level (`setRoutableMtb`): trails up to
     it (an unrated one as 2) draw in the routable layers, harder ones keep their level's
     not-for-routes look, and every trail keeps its name.
   - Default picked: a route that cannot avoid a harder trail is answered, with `mtb.over_level_m`
     and a warning in words, not refused ("unclear access is closed" is the graph's, and a harder
     trail is open to bicycles; the rider decides).
   - Default picked: "trail" for the seeking is a mountain-bike-only way or an unpaved trail-class
     way; a paved path is not trail.
   - Default picked: stress 80 (the old top), the stress-averse exposure, a Mountain bicycle type
     with every surface accepted, no brake grade (a rider who chose it wants the descent).
   - Default picked: a wet closure is closed on the Mountain Bike graph always (the graph cannot
     know the ground); the trail page sends the rider to MORE for the day's conditions.
   - Default picked: MORE's system is matched by the words in the trail's OSM names; no match gives
     MORE's trail guide, never a guess.
   - Default picked: the profile-gated routers share the 1536M the off-road router had alone, one
     worker each in 768M, so the 32G swap-time check holds at 32.0G.

## Second pass: preferred and max difficulty

The owner, 2026-10-11: "two options for difficulty: preferred difficulty and max difficulty.
Basically it would try to find routes near that intended difficulty and avoid routes past max
difficulty." Built on `claude/v0-6-0-mtb-difficulty` (from release/v0.6.0). No graph change and no
rebuild: like the hardest level, the preference is held at plan time on the router's routes
(`core.mtb.settle`, rules in `routemaker.mtbmode`).

- **Max** is slice 6's hardest level, unchanged (`mtb_level`, the `level` link parameter, default
  2): a trail past it is avoided exactly as before (excluded and asked again, else answered with
  `over_level_m` and its warning).
- **Preferred** is new (`mtb_preferred`, the `prefer` link parameter, 1-4, default 2). In the
  ranking's weighted length the preference is a discount, never a surcharge (review of #104): a
  mountain-bike trail metre up to the max counts TRAIL_WEIGHT - LEVEL_STEP x max(0, LEVEL_REACH -
  levels away) of a road metre, with TRAIL_WEIGHT 0.5, LEVEL_STEP 0.05 and LEVEL_REACH 2: 0.4 at
  the preferred level, 0.45 one level easier or harder, 0.5 two or more away (the step kept small,
  re-review of #104, so the owner's "a trail mile counts about half a road mile" moves little). So
  the preferred level is cheapest, an off-level trail never weighs more than a gravel path (0.5) or
  than it did in slice 6, and no trail is free. At preferred 3, 1,100 m of level 3 (440) beats 1,000 m of level 2 (450);
  1,150 m (460) does not. An unrated mountain-bike trail counts as level 2, as for the max.
- **Preferred is never above max.** The API holds a higher one to the max and says what it used
  (`mtb.preferred_level`); the panel disables the levels above the hardest, and lowering the hardest
  below the preferred lowers the preferred with it, said in a polite status line ("Preferred trail
  level lowered to level 1 (green): it can't be harder than the hardest level.").
- **Old links and requests** with only the level read it as the max, the preferred min(2, max) (a
  level of 1 prefers 1; 2-4 prefer 2). They keep the same max and the same over-max handling, but
  are not ranked exactly as before: their trails at or a level from that preferred level now weigh
  0.4 or 0.45 in place of 0.5, so among the router's routes they may now pick one with more
  mountain-bike trail (over gravel paths or roads) than slice 6 did.
- **The route in words:** the answer's `mtb` adds `preferred_level`, `easier_m` and `harder_m`
  (metres on trails easier, and harder up to the max, than preferred), and the route panel says
  "1.0 mi (1.6 km) of trail is easier than your preferred level 2 (blue)." and "... harder than your
  preferred level 2 (blue), up to level 3 (black).", or that its trails are at the preferred level.
- Default picked: an ordinary unpaved path (no MTB level, 456b) and a road get no discount: a
  gravel path keeps 0.5 and a road 1.0, so a mountain-bike trail within a level of the preferred one
  beats an equal length of gravel, and one two or more levels away ties it.
- Default picked: the two pickers are radio groups in the Ride settings, "Hardest trail level"
  first (where it was) and "Preferred trail level" under it, so the limit is chosen before what
  fits within it.
- Limit: the preference chooses among the routes the router offers (its alternatives and the
  exclusion rounds' routes), as trail seeking does; it does not make the router look for trails of
  a level it would not otherwise offer.

## Questions for the owner, when their slice starts

- Slice 2: the four colours' exact values, if the starting values above do not suit, and
  whether unrated mountain-bike-class trails keep the grey dots.
- Slice 4: a contour overlay on the current base map, or a whole topo base map in
  OpenTopoMap's look; approval to fetch 3DEP 1/3 arcsecond for the region; the contour
  interval.
- Slice 5: answered 2026-10-11 (above).
- Slice 6: the MTB mode's criteria, and the MORE link's form (one link, or per trail system).
