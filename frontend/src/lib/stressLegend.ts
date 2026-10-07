/**
 * What the stress legend says about zoom: what the overlay draws at the zoom
 * the map is at. The owner, 2026-09-28: "It looks way too busy zoomed out
 * though." and "Zoomed out just show the trails." - so below
 * `STRESS_ZOOMS.ride` the tiles carry only the long traffic-free paths, and the
 * legend says why the roads have no stress lines there (core/stress_tiles.py);
 * from it the "where to ride" layer, with no busy road (OWNER-DECISIONS 391), and
 * from `STRESS_ZOOMS.quiet` every road, the busy ones and the quiet streets (73, 76,
 * 77, 78).
 * Written with createElement so a test renders it (as pointsList.ts).
 */
import { createElement as h, Fragment, type ReactElement } from "react";
import { STRESS_ZOOMS } from "./mapStyle.ts";
import { METRES_PER_MILE, formatDistance, formatRunMiles } from "./format.ts";
import {
  ALLEY_MIN_ZOOM,
  BESIDE_ROAD_MIN_ZOOM,
  FACILITIES,
  LEGEND_SWATCH_PX,
  MTB_TRAILS_ROUTABLE,
  MTB_TRAIL,
  SOLID_MIN_ZOOM,
  UNKNOWN_SURFACE_DASH,
  UNPAVED_DASH,
  accessibilityOn,
  currentTiers,
  mtbTrailPaint,
  legendWidths,
  unpavedWidth,
} from "../stressStyle.js";
import { useHighStressLanes, useStressStyle } from "../useStressStyle.ts";
import { HIGH_STRESS_LANES_LABEL } from "./highStressLanesSwitch.ts";

/**
 * The one phrase for what the map shows zoomed out, wherever the legend says
 * it (review of round 1: it had three names for one thing). Since
 * OWNER-DECISIONS 375, 377 and 378 that is the long-distance ones only: the
 * paths on regional or national bike routes, the long named trails, and the
 * roads closed to cars at set times. It says which, because a rider who cannot
 * see the map cannot tell a trail left out from a trail that is not there
 * (accessibility review SF3, spec review SF2 of ZOOMED-TRAILS).
 */
export const ZOOMED_OUT =
  "Zoomed out, only the long-distance paths and trails are shown: those on regional or national bike routes, " +
  "long named trails, and roads closed to cars at set times.";

/**
 * The run a named paved trail needs to show at z11 and at z10, in miles
 * (`pipeline.schema.Z11_PAVED_RUN_MI` and `Z10_PAVED_RUN_MI`, OWNER-DECISIONS 375
 * and 380; tests/test_stress_tiles.py holds them equal).
 */
export const PAVED_RUN_MI = { 11: 2.5, 10: 5 };

/**
 * The runs the ride layer needs at zoom 12-13, in miles (`pipeline.schema.RIDE_PATH_RUN_MI` and
 * `RIDE_ROAD_RUN_MI`, OWNER-DECISIONS 391, 402a; tests/test_stress_tiles.py holds them equal): a path
 * or trail in a connected network of the first, a calm road (LTS 1 or 2) in a run of the second with
 * no junction with a busy road.
 */
export const RIDE_RUN_MI = { path: 0.25, road: 2 };

/**
 * OWNER-DECISIONS 452a: the mountain-bike trails draw in a look of their own that says they are not
 * used for routes (stressStyle.js, MTB_TRAIL), and the legend says so in words in a row of its own,
 * so a rider who cannot see the map knows what the dotted grey line is. The row's name and words;
 * null once they are routable (a future mountain-bike mode, MTB_TRAILS_ROUTABLE). Gravel and
 * Mountain Goat route on them (the off-road graph), and the words say so rather than over-claim.
 */
export const MTB_LEGEND: { short: string; label: string } | null = MTB_TRAILS_ROUTABLE
  ? null
  : { short: "Mountain-bike trail", label: "Not used for routes (Gravel and Mountain Goat may use it): a thin grey dotted line." };

/** Where the paths and trails the long-distance rule leaves out come back (STRESS_ZOOMS.ride). */
export function everyTrailFrom(ride: number): string {
  return `Paths on local routes and other connected paths show from zoom ${ride}; mountain-bike trails and every short path show from zoom ${STRESS_ZOOMS.quiet}.`;
}

/**
 * What zoom 12 and 13 show (OWNER-DECISIONS 391, "I'm more concerned with the places to ride than the
 * places not to."): where to ride, and what waits for zoom 14, said so a rider who cannot see the map
 * knows a missing road is not a missing street.
 */
export function rideLayerText(ride: number, quiet: number): string {
  return (
    `From zoom ${ride} the map shows where to ride: the paths and trails that connect into a network of ` +
    `${formatRunMiles(RIDE_RUN_MI.path)} or more, and calm roads (LTS 1 and 2) that run ` +
    `${formatRunMiles(RIDE_RUN_MI.road)} or more without crossing or joining a busy road. Busy roads (LTS 3 and above, ` +
    `and best avoided), mountain-bike trails, shorter paths, the other streets and the junction warnings on the map ` +
    `show from zoom ${quiet}.`
  );
}

/** A planned route is drawn whole at every zoom (OWNER-DECISIONS 391). */
export const ROUTE_AT_EVERY_ZOOM =
  "A route you plan still shows its own busy stretches and junction warnings at every zoom.";

/** The bike-facility legend's note on the protected lanes the zoomed-out map leaves out. */
export const ROADWAY_LANES = "Protected lanes in the roadway show with their street.";

/**
 * Roads closed to cars (the owner, 2026-09-29: "One note: Car-free roads
 * should be regarded the same as an off-road path on a map."), and those
 * closed at set times, which follow the ride time chosen ("Path on weekends
 * only").
 */
export const CAR_FREE_NOTE =
  "Roads closed to cars are shown as traffic-free paths, and roads closed only at set times, such as Sligo Creek " +
  "Parkway on weekends, are too when that ride time is chosen.";

/** The notice for the zoom the map is at, when the overlay is shown; null when there is none. */
export function stressZoomNotice(zoom: number | null, shown: boolean): string | null {
  if (zoom === null || !shown) return null;
  if (zoom < STRESS_ZOOMS.min) return "Zoom in to see traffic-free paths, trails and traffic stress.";
  if (zoom < STRESS_ZOOMS.ride) return `Zoom in to see more paths and trails, calm roads and traffic stress on roads. ${ZOOMED_OUT}`;
  if (zoom < STRESS_ZOOMS.quiet) {
    return `Zoom in to see busy roads and every street. This is the where-to-ride view: connected paths and trails and long calm roads. Busy roads, mountain-bike trails and short paths show from zoom ${STRESS_ZOOMS.quiet}.`;
  }
  return null;
}

/** The standing note on what is drawn at which zoom. */
export function stressZoomHint(zoom: number | null): string {
  const { min, ride, quiet } = STRESS_ZOOMS;
  let text =
    `${ZOOMED_OUT} A named paved trail counts when it runs ${formatDistance(PAVED_RUN_MI[11] * METRES_PER_MILE)} ` +
    `or more at zoom 11, or ${formatDistance(PAVED_RUN_MI[10] * METRES_PER_MILE)} at zoom 10; an unpaved one ` +
    `needs a regional bike route or a longer run. Trails beside a road count ` +
    `the same way. Lines are drawn thinner at zooms 10 and 11. ${rideLayerText(ride, quiet)} ${ROUTE_AT_EVERY_ZOOM} ` +
    `${everyTrailFrom(ride)} From zoom ${quiet} the busy roads at LTS 3 and above and the quiet streets, footways and ` +
    `sidewalks show too, every line solid from zoom ${SOLID_MIN_ZOOM}. Roads bikes may not use, such as expressways, are left unmarked. A busy road with a bike lane ` +
    `or path mapped beside it shows only from zoom ${BESIDE_ROAD_MIN_ZOOM}, and faintly, so the bike lane is the ` +
    `main line. Alleys show only from zoom ${ALLEY_MIN_ZOOM}, faintly, and the roads inside cemeteries, parking ` +
    `lots, military bases and secure government sites, such as prisons and guarded research campuses, not at ` +
    `all, but for the numbered public roads and the few streets open to the public through them. Further out than zoom ${min} nothing is drawn, and streets with no ` +
    `stress rating are not drawn.`;
  if (zoom !== null) text += ` The map is at zoom ${Math.floor(zoom)}.`;
  return text;
}

/** The link text of the disclosure the sidebar's Map layers sheet puts the zoom explanations behind (OWNER-DECISIONS 312). */
export const ZOOM_LEVELS_LINK = "What each zoom level shows";

export function StressZoomNotes({
  zoom,
  shown,
  folded = false,
}: {
  zoom: number | null;
  shown: boolean;
  /**
   * The sidebar's Map layers sheet: the notice for the zoom the map is at stays in view (it says why the
   * map looks empty), and the standing explanations are behind "What each zoom level shows".
   */
  folded?: boolean;
}): ReactElement {
  const notice = stressZoomNotice(zoom, shown);
  const noticeEl = notice && h("p", { className: "notice", role: "status" }, notice);
  const hint = h("p", { className: "hint" }, stressZoomHint(zoom));
  const carFree = h("p", { className: "hint" }, CAR_FREE_NOTE);
  if (folded) {
    return h(
      Fragment,
      null,
      noticeEl,
      h("details", { className: "fold zoom-notes" }, h("summary", null, ZOOM_LEVELS_LINK), h("div", { className: "fold-body" }, hint, carFree)),
    );
  }
  return h(Fragment, null, noticeEl, hint, carFree);
}

// ---- The legend itself (moved out of App.tsx so a test renders it) ----------

/** The legend's first line: what "LTS" is, said once in plain words (the a11y review's N2). */
export const LTS_MEANS = "LTS is Level of Traffic Stress, from 1 (calmest) to 4 (heavy traffic); Avoid is legal but best avoided.";

/** The unpaved mark's line in the legend: what it is, and that an unpaved trail has no edge lines. */
export const UNPAVED_LEGEND =
  "Brown, darker = busier: gravel, dirt or other unpaved surface, with the dashes above and a dotted center line. An unpaved trail has no edge lines, which a paved path has.";

/**
 * The surface-unknown line's entry (OWNER-DECISIONS 376, A): the shape that says so, in words, and why.
 * A paved path has edge lines; an unpaved trail is brown with a dotted center line; this is neither.
 */
export const UNKNOWN_SURFACE_LEGEND =
  "A park path or trail away from roads with no surface mapped in OpenStreetMap, so it may be paved or unpaved: short dashes in the LTS 1 colors, with no edge lines. A trail beside a road, or a path built for bicycles (a bike path or a path signed for bicycles), with no surface mapped shows as a paved path.";

/** The bike-facility legend's words, with the lane switch's state. */
export function facilityLegendHint(showHighLanes: boolean): string {
  return (
    "Bike facilities are edges on either side of the stress line: a solid dark rail for a paved path, blocks like posts for a " +
    "protected lane, and a thin dotted rail for paint. An unpaved trail has no edge lines, only the dotted center line. " +
    "Painted lanes on heavy-traffic (LTS 4) and best-avoided roads are " +
    (showHighLanes ? "shown, because the switch above is on." : `hidden unless you turn on "${HIGH_STRESS_LANES_LABEL}".`)
  );
}

/** The swatch's drawing: its line runs from x 2 for LEGEND_SWATCH_PX. */
const X1 = 2;
const X2 = X1 + LEGEND_SWATCH_PX;
const SVG_WIDTH = X2 + 2;

type Tier = ReturnType<typeof currentTiers>[number];

/** A dash in line widths as an SVG dash array in pixels, or undefined for a solid line. */
export function dashPx(dash: readonly number[] | null | undefined, width: number): string | undefined {
  return dash ? dash.map((d) => d * width).join(" ") : undefined;
}

const line = (y: number, stroke: string, strokeWidth: number, strokeDasharray?: string) =>
  h("line", { x1: X1, y1: y, x2: X2, y2: y, stroke, strokeWidth, strokeDasharray });

/** A tier's swatch: its casing, its gap colour where it is dashed (OWNER-DECISIONS 356), then its line with its dash, at the map's widths. */
export function TierSwatch({ tier, widths }: { tier: Tier; widths: { line: number; casing: number; ring?: number } }): ReactElement {
  // The ring outside the casing (371): the map's near-black one, or the legend's own (Avoid's grey).
  const ring = tier.ring ?? tier.legendRing;
  return h(
    "svg",
    { width: SVG_WIDTH, height: 12, "aria-hidden": "true" },
    ring ? line(6, ring, widths.ring ?? widths.casing + 2) : null,
    line(6, tier.casing, widths.casing),
    tier.dash ? line(6, tier.gap ?? tier.casing, widths.line) : null,
    line(6, tier.color, widths.line, dashPx(tier.dash, widths.line)),
  );
}

/**
 * The unpaved swatch (OWNER-DECISIONS 302): the brown ramp, light to dark, one
 * stretch a tier from LTS 1 to Avoid, each on its unpaved casing at LTS 1's
 * widths, with the dotted mark over it in that casing.
 */
export function UnpavedSwatch({ tiers, widths }: { tiers: readonly Tier[]; widths: { line: number; casing: number } }): ReactElement {
  const step = LEGEND_SWATCH_PX / tiers.length;
  const mark = unpavedWidth(tiers[0]);
  const seg = (i: number, stroke: string, strokeWidth: number, strokeDasharray?: string) =>
    h("line", { x1: X1 + i * step, y1: 6, x2: X1 + (i + 1) * step, y2: 6, stroke, strokeWidth, strokeDasharray });
  return h(
    "svg",
    { width: SVG_WIDTH, height: 12, "aria-hidden": "true", className: "unpaved-ramp" },
    ...tiers.map((tier, i) =>
      h(
        "g",
        { key: tier.tier },
        seg(i, tier.unpavedCasing, widths.casing),
        seg(i, tier.unpavedColor, widths.line),
        seg(i, tier.unpavedCasing, mark, dashPx(UNPAVED_DASH, mark)),
      ),
    ),
  );
}

/** The surface-unknown swatch: LTS 1's casing and line, both in short dashes of the same length (UNKNOWN_SURFACE_DASH), at the map's widths. */
export function UnknownSurfaceSwatch({ tier, widths }: { tier: Tier; widths: { line: number; casing: number } }): ReactElement {
  const on = dashPx(UNKNOWN_SURFACE_DASH, widths.line);
  return h(
    "svg",
    { width: SVG_WIDTH, height: 12, "aria-hidden": "true", className: "unknown-surface" },
    line(6, tier.casing, widths.casing, on),
    line(6, tier.color, widths.line, on),
  );
}

/**
 * The mountain-bike trail's swatch (452a): its fine grey dots at the map's width, on a strip of the base
 * map's earth colour, as the map draws them, so the dots read in a dark panel too.
 */
export function MtbTrailSwatch({ strong }: { strong: boolean }): ReactElement {
  const paint = mtbTrailPaint(strong);
  const width = paint["line-width"];
  return h(
    "svg",
    { width: SVG_WIDTH, height: 12, "aria-hidden": "true", className: "mtb-trail-swatch" },
    h("rect", { x: X1, y: 1, width: LEGEND_SWATCH_PX, height: 10, rx: 2, fill: MTB_TRAIL.legendGround }),
    line(6, paint["line-color"], width, dashPx(MTB_TRAIL.dash, width)),
  );
}

type Facility = (typeof FACILITIES)[number];

/** A facility's swatch: its rails, with the casing of LTS 1's line over them. */
export function FacilitySwatch({ facility, rails, casing }: { facility: Facility; rails: number; casing: number }): ReactElement {
  return h(
    "svg",
    { width: SVG_WIDTH, height: 14, "aria-hidden": "true" },
    h("line", { x1: X1, y1: 7, x2: X2, y2: 7, stroke: facility.color, strokeWidth: rails, strokeDasharray: dashPx(facility.dash, rails) }),
    h("line", { x1: X1, y1: 7, x2: X2, y2: 7, stroke: "#ffffff", strokeWidth: casing }),
  );
}

const row = (key: string | number, swatch: ReactElement, short: string, label: string, className?: string) =>
  h(
    "li",
    { key, className },
    swatch,
    h("span", { className: "stress-name" }, short),
    h("span", { className: "stress-label" }, label),
  );

/**
 * The panel's stress legend: the tiers, the unpaved mark, what the zoom leaves out,
 * and the bike facilities the map has drawn (`facilities`). Drawn from the tiers in
 * use and legendWidths, so it cannot differ from the map from zoom 12; below it the
 * map draws the same colours thinner (ZOOMED_OUT_SCALE), which the hint says.
 */
export function StressLegend({
  facilities,
  zoom,
  shown,
  foldedZoom = false,
}: {
  facilities: ReadonlySet<string>;
  zoom: number | null;
  shown: boolean;
  /** The zoom explanations behind a disclosure (the Map layers sheet); false keeps them in the text. */
  foldedZoom?: boolean;
}): ReactElement {
  useStressStyle();
  const showHighLanes = useHighStressLanes();
  const tiers = currentTiers();
  const widths = legendWidths(tiers);
  return h(
    Fragment,
    null,
    h("p", { className: "hint lts-means" }, LTS_MEANS),
    h(
      "ul",
      { className: "legend", "aria-label": "Traffic stress legend" },
      ...tiers.map((tier, i) => row(tier.tier, h(TierSwatch, { tier, widths: widths.tiers[i] }), tier.short, tier.label)),
      row("unpaved", h(UnpavedSwatch, { tiers, widths: widths.tiers[0] }), "Unpaved", UNPAVED_LEGEND),
      row("unknown", h(UnknownSurfaceSwatch, { tier: tiers[0], widths: widths.tiers[0] }), "Surface unknown", UNKNOWN_SURFACE_LEGEND),
      // 452a: the mountain-bike trails' not-for-routes line, in words in the list, not behind the zoom fold.
      MTB_LEGEND && row("mtb", h(MtbTrailSwatch, { strong: accessibilityOn() }), MTB_LEGEND.short, MTB_LEGEND.label, "mtb-trail"),
    ),
    // What the tiles leave out as the map zooms out (core/stress_tiles.py).
    h(StressZoomNotes, { zoom, shown, folded: foldedZoom }),
    facilities.size > 0 &&
      h(
        Fragment,
        null,
        h("p", { className: "hint" }, facilityLegendHint(showHighLanes)),
        h(
          "ul",
          { className: "legend", "aria-label": "Bike facility legend" },
          ...FACILITIES.filter((facility) => facilities.has(facility.facility)).map((facility) =>
            row(
              facility.facility,
              h(FacilitySwatch, { facility, rails: widths.rails[facility.facility], casing: widths.facilityCasing }),
              facility.short,
              facility.label,
            ),
          ),
        ),
        h("p", { className: "hint" }, `Sharrows count as ordinary streets. ${ROADWAY_LANES}`),
      ),
  );
}
