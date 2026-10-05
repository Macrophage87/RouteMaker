/**
 * What the stress legend says about zoom: what the overlay draws at the zoom
 * the map is at. The owner, 2026-09-28: "It looks way too busy zoomed out
 * though." and "Zoomed out just show the trails." - so below
 * `STRESS_ZOOMS.busy` the tiles carry only the traffic-free paths, and the
 * legend says why the roads have no stress lines there (core/stress_tiles.py);
 * from it the busy roads, faint, and from `STRESS_ZOOMS.quiet` the quiet
 * streets (OWNER-DECISIONS 73, 76, 77, 78).
 * Written with createElement so a test renders it (as pointsList.ts).
 */
import { createElement as h, Fragment, type ReactElement } from "react";
import { STRESS_ZOOMS } from "./mapStyle.ts";
import { METRES_PER_MILE, formatDistance } from "./format.ts";
import {
  ALLEY_MIN_ZOOM,
  BESIDE_ROAD_MIN_ZOOM,
  FACILITIES,
  LEGEND_SWATCH_PX,
  SOLID_MIN_ZOOM,
  UNPAVED_DASH,
  currentTiers,
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

/** Where every other path and trail comes back (STRESS_ZOOMS.busy). */
export function everyTrailFrom(busy: number): string {
  return `Every other path and trail, mountain-bike trails and local routes included, shows from zoom ${busy}.`;
}

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
  if (zoom < STRESS_ZOOMS.busy) return `Zoom in to see every path and trail, and traffic stress on roads. ${ZOOMED_OUT}`;
  if (zoom < STRESS_ZOOMS.quiet) return `Zoom in to see the quiet streets. Busy roads are drawn faintly until zoom ${SOLID_MIN_ZOOM}.`;
  return null;
}

/** The standing note on what is drawn at which zoom. */
export function stressZoomHint(zoom: number | null): string {
  const { min, busy, quiet } = STRESS_ZOOMS;
  let text =
    `${ZOOMED_OUT} A named paved trail counts when it runs ${formatDistance(PAVED_RUN_MI[11] * METRES_PER_MILE)} ` +
    `or more at zoom 11, or ${formatDistance(PAVED_RUN_MI[10] * METRES_PER_MILE)} at zoom 10; an unpaved one ` +
    `needs a regional bike route or a longer run. Trails beside a road count ` +
    `the same way. Lines are drawn thinner at zooms 10 and 11. ${everyTrailFrom(busy)} From zoom ${busy} the ` +
    `busy roads at LTS 3 and above show, faintly, and from zoom ${quiet} the quiet streets, footways and sidewalks, with every line solid ` +
    `from zoom ${SOLID_MIN_ZOOM}. Roads bikes may not use, such as expressways, are left unmarked. A busy road with a bike lane ` +
    `or path mapped beside it shows only from zoom ${BESIDE_ROAD_MIN_ZOOM}, and faintly, so the bike lane is the ` +
    `main line. Alleys show only from zoom ${ALLEY_MIN_ZOOM}, faintly, and the roads inside cemeteries, military ` +
    `bases and parking lots not at all. Further out than zoom ${min} nothing is drawn, and streets with no ` +
    `stress rating are not drawn.`;
  if (zoom !== null) text += ` The map is at zoom ${Math.floor(zoom)}.`;
  return text;
}

export function StressZoomNotes({ zoom, shown }: { zoom: number | null; shown: boolean }): ReactElement {
  const notice = stressZoomNotice(zoom, shown);
  return h(
    Fragment,
    null,
    notice && h("p", { className: "notice", role: "status" }, notice),
    h("p", { className: "hint" }, stressZoomHint(zoom)),
    h("p", { className: "hint" }, CAR_FREE_NOTE),
  );
}

// ---- The legend itself (moved out of App.tsx so a test renders it) ----------

/** The legend's first line: what "LTS" is, said once in plain words (the a11y review's N2). */
export const LTS_MEANS = "LTS is Level of Traffic Stress, from 1 (calmest) to 4 (heavy traffic); Avoid is legal but best avoided.";

/** The unpaved mark's line in the legend: what it is, and that an unpaved trail has no edge lines. */
export const UNPAVED_LEGEND =
  "Brown, darker = busier: gravel, dirt or other unpaved surface, with the dashes above and a dotted center line. An unpaved trail has no edge lines, which a paved path has.";

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

const row = (key: string | number, swatch: ReactElement, short: string, label: string) =>
  h(
    "li",
    { key },
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
}: {
  facilities: ReadonlySet<string>;
  zoom: number | null;
  shown: boolean;
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
    ),
    // What the tiles leave out as the map zooms out (core/stress_tiles.py).
    h(StressZoomNotes, { zoom, shown }),
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
