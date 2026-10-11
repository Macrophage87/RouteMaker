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
5. **Climbs layer** (454). Named climbs drawn on the map with their length and average grade
   (US units first). Source and definition to propose: the sustained-climb reading in
   `routemaker.climbs` run over the road and trail network once at build time, or a curated
   list. Needs the owner's pick.
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

## Questions for the owner, when their slice starts

- Slice 2: the four colours' exact values, if the starting values above do not suit, and
  whether unrated mountain-bike-class trails keep the grey dots.
- Slice 4: a contour overlay on the current base map, or a whole topo base map in
  OpenTopoMap's look; approval to fetch 3DEP 1/3 arcsecond for the region; the contour
  interval.
- Slice 5: what counts as a climb on the layer (length and grade thresholds), or a curated list.
- Slice 6: the MTB mode's criteria, and the MORE link's form (one link, or per trail system).
