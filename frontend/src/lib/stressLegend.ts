/**
 * What the stress legend says about zoom: what the overlay draws at the zoom
 * the map is at. The owner, 2026-09-28: "It looks way too busy zoomed out
 * though." and "Zoomed out just show the trails." - so below
 * `STRESS_ZOOMS.quiet` the tiles carry only the long traffic-free paths, and the
 * legend says why the roads have no stress lines there (core/stress_tiles.py);
 * from it every road, the busy ones and the quiet streets (73, 76, 77, 78). Zoom 12-13
 * was a "where to ride" layer with no busy road (OWNER-DECISIONS 391) until the owner,
 * 2026-10-17: "Show traffic stress a couple more zoom levels up", then, of the busy
 * roads and every street, "Both from 12".
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
  MTB_TRAILS_ROUTABLE,
  MTB_TRAIL,
  MTB_HALO,
  MTB_LEVELS,
  MTB_MIN_ZOOM,
  SOLID_MIN_ZOOM,
  UNKNOWN_SURFACE_DASH,
  UNPAVED_DASH,
  accessibilityOn,
  currentTiers,
  mtbTrailPaint,
  mtbTrailHaloPaint,
  mtbTicksPaint,
  MTB_TICKS,
  mtbLevelPaint,
  legendWidths,
  unpavedWidth,
} from "../stressStyle.js";
import { useHighStressLanes, useMtbTrails, useStressStyle } from "../useStressStyle.ts";
import { HIGH_STRESS_LANES_LABEL } from "./highStressLanesSwitch.ts";
import { isPlainClick, rememberPlanForPage, tabSession } from "./signIn.ts";

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
 * OWNER-DECISIONS 452a: the mountain-bike trails draw in a look of their own that says they are not
 * used for routes (stressStyle.js, MTB_TRAIL), and the legend says so in words in a row of its own,
 * so a rider who cannot see the map knows what the brown dashed line on a ticked white edge is. The row's name and words;
 * null once they are routable (a future mountain-bike mode, MTB_TRAILS_ROUTABLE). Gravel, Mountain Goat and
 * Mountain Bike route on them, the rated ones too since the owner's choice of 2026-10-19 ("Rated, MTB and Gravel").
 */
export const MTB_LEGEND: { short: string; label: string } | null = MTB_TRAILS_ROUTABLE
  ? null
  : { short: "Mountain-bike trail", label: "Only off-road ride types route on these (Gravel, Mountain Goat and Mountain Bike): brown dashes on a white edge with dark ticks for an unrated trail. Rated ones show by level below; from the next map update, Gravel and Mountain Goat ride green (level 1)." };

type MtbLevel = (typeof MTB_LEVELS)[number];

/**
 * OWNER-DECISIONS 456: a rated mountain-bike trail's row, one a level, naming the level in words (its number
 * and colour), what it is on the two scales, and its pattern, so the colour is never the only cue. The row's
 * name is the road panel's wording (core/segment_info.py, mtb_level_words): "Level 2 (blue)".
 */
export function mtbLevelLegend(shape: MtbLevel): { short: string; label: string } {
  const who = shape.level <= OFFROAD_MAX_LEVEL ? "Only Gravel, Mountain Goat and Mountain Bike route on it." : "Only Mountain Bike routes use it.";
  return {
    short: `Level ${shape.level} (${shape.name})`,
    label: `Mountain-bike trail rated ${shape.scale}: ${shape.name} ${shape.pattern} on a white edge with dark ticks. ${who}`,
  };
}

/** The hardest level Gravel and Mountain Goat ride (routemaker/singletrack.py OFFROAD_MAX_LEVEL; the owner, 2026-10-19). */
export const OFFROAD_MAX_LEVEL = 1;

/** Where the paths and trails the long-distance rule leaves out come back (STRESS_ZOOMS.quiet). */
export function everyTrailFrom(quiet: number): string {
  return `Every other path and trail, the short ones too, shows from zoom ${quiet}. Mountain-bike trails show from zoom ${MTB_MIN_ZOOM} when their layer is on.`;
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
  if (zoom < STRESS_ZOOMS.quiet) return `Zoom in to see more paths and trails and traffic stress on every road. ${ZOOMED_OUT}`;
  return null;
}

/** The standing note on what is drawn at which zoom. */
export function stressZoomHint(zoom: number | null): string {
  const { min, quiet } = STRESS_ZOOMS;
  let text =
    `${ZOOMED_OUT} A named paved trail counts when it runs ${formatDistance(PAVED_RUN_MI[11] * METRES_PER_MILE)} ` +
    `or more at zoom 11, or ${formatDistance(PAVED_RUN_MI[10] * METRES_PER_MILE)} at zoom 10 and further out; an unpaved one ` +
    `needs a regional bike route or a longer run. Trails beside a road count ` +
    `the same way. Lines are drawn thinner at zoom 11 and further out. ${ROUTE_AT_EVERY_ZOOM} ` +
    `${everyTrailFrom(quiet)} From zoom ${quiet} the busy roads at LTS 3 and above and the quiet streets, footways and ` +
    `sidewalks show too, the busy roads faintly until zoom ${SOLID_MIN_ZOOM}. Roads bikes may not use, such as expressways, are left unmarked. A busy road with a bike lane ` +
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

/**
 * The rider-facing page on how the ratings work (OWNER-DECISIONS 461: "Something that can be
 * linked to on the website"), a static page in public/ served at this path by both edges
 * (Caddyfile, deploy/beta/nginx-routemaker.conf.template). Opens in the same tab.
 */
export const STRESS_PAGE = "/about/stress.html";
/**
 * The link's words, visible and its whole accessible name: no hidden part, which iOS VoiceOver
 * can read as a second swipe stop (the accessibility review's N8).
 */
export const STRESS_PAGE_TEXT = "How stress ratings work";

/**
 * The hub of the rider-facing documentation (the owner, 2026-10-19: "a full set of documentation
 * ... linked within the app"): how ratings, ride types and closures work, the architecture and the
 * acknowledgements, static pages in public/about/ beside STRESS_PAGE. Settings links to it, once.
 */
export const DOCS_PAGE = "/about/how-it-works.html";
export const DOCS_PAGE_TEXT = "How RouteMaker works";

/**
 * The link to DOCS_PAGE, at the end of Settings. Like StressPageLink it keeps the plan for the
 * page's "Back to the map" links.
 */
export function DocsPageLink(): ReactElement {
  return h(
    "p",
    { className: "hint docs-page-link" },
    h("a", { href: DOCS_PAGE, onClick: (e) => isPlainClick(e) && rememberPlanForPage(tabSession(), window.location.hash) }, DOCS_PAGE_TEXT),
  );
}

/**
 * The link to STRESS_PAGE, as the legend and the road panel show it. Following it keeps the
 * plan for the page's "Back to the map" links, which go to a bare "/" (`rememberPlanForPage`).
 */
export function StressPageLink({ className }: { className?: string }): ReactElement {
  return h(
    "p",
    { className: `hint stress-page-link${className ? ` ${className}` : ""}` },
    h("a", { href: STRESS_PAGE, onClick: (e) => isPlainClick(e) && rememberPlanForPage(tabSession(), window.location.hash) }, STRESS_PAGE_TEXT),
  );
}

/** The unpaved mark's line in the legend: what it is, and that an unpaved trail has no edge lines. */
export const UNPAVED_LEGEND =
  "Brown, darker = busier: dirt, grass or another natural surface, or a rutted unpaved track, with the dashes above and a dotted center line. An unpaved trail has no edge lines, which a paved path has. A short bridge is drawn like the trail it is on; tap it to read its own surface.";

/** The gravel row (the owner, 2026-10-21: "Maybe make natural surface trails brown and gravel grey?"; stressStyle.js GRAVEL_PALETTES). */
export const GRAVEL_LEGEND =
  "Grey, darker = busier: gravel or another firm unpaved surface, with the same dashes and dotted center line as dirt.";

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
export function UnpavedSwatch({ tiers, widths, gravel = false }: { tiers: readonly Tier[]; widths: { line: number; casing: number }; gravel?: boolean }): ReactElement {
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
        seg(i, gravel ? tier.gravelCasing : tier.unpavedCasing, widths.casing),
        seg(i, gravel ? tier.gravelColor : tier.unpavedColor, widths.line),
        seg(i, gravel ? tier.gravelCasing : tier.unpavedCasing, mark, dashPx(UNPAVED_DASH, mark)),
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

/** The shared not-for-routes ticks (452a), as the map draws them, for a swatch (14 px high, centred at 7). */
function ticks(strong: boolean): ReactElement {
  const paint = mtbTicksPaint(strong);
  return line(7, paint["line-color"], paint["line-width"], dashPx(MTB_TICKS.dash, paint["line-width"]));
}

/**
 * The mountain-bike trail's swatch (452a): its dark ticks, white edge and brown dashes at the map's widths, on a strip of the
 * base map's earth colour, as the map draws them, so they read in a dark panel too.
 */
export function MtbTrailSwatch({ strong }: { strong: boolean }): ReactElement {
  const paint = mtbTrailPaint(strong);
  const width = paint["line-width"];
  return h(
    "svg",
    { width: SVG_WIDTH, height: 14, "aria-hidden": "true", className: "mtb-trail-swatch" },
    h("rect", { x: X1, y: 1, width: LEGEND_SWATCH_PX, height: 12, rx: 2, fill: MTB_TRAIL.legendGround }),
    ticks(strong),
    line(7, MTB_HALO.color, mtbTrailHaloPaint(strong)["line-width"]),
    line(7, paint["line-color"], width, dashPx(MTB_TRAIL.dash, width)),
  );
}

/**
 * A mountain-bike level's swatch (456): the dark ticks, its white edge and its coloured pattern at the map's widths, on a strip of
 * the base map's earth colour, as the map draws them.
 */
export function MtbLevelSwatch({ shape, strong }: { shape: MtbLevel; strong: boolean }): ReactElement {
  const paint = mtbLevelPaint(shape.level, strong);
  const width = paint.line["line-width"];
  return h(
    "svg",
    { width: SVG_WIDTH, height: 14, "aria-hidden": "true", className: `mtb-level-swatch mtb-level-swatch-${shape.level}` },
    h("rect", { x: X1, y: 1, width: LEGEND_SWATCH_PX, height: 12, rx: 2, fill: MTB_TRAIL.legendGround }),
    ticks(strong),
    line(7, paint.casing["line-color"], paint.casing["line-width"]),
    line(7, shape.color, width, dashPx(shape.dash, width)),
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
    // Avoid is just "Avoid" (OWNER-DECISIONS 441j): said once, not as its name and its label.
    label === short ? null : h("span", { className: "stress-label" }, label),
  );

/**
 * The mountain-bike trail layer's rows (452a, 456): the unrated trails' brown dashes, then each level, in words.
 * Empty once the trails are routable.
 */
function mtbRows(): ReactElement[] {
  if (!MTB_LEGEND) return [];
  const strong = accessibilityOn();
  return [
    row("mtb", h(MtbTrailSwatch, { strong }), MTB_LEGEND.short, MTB_LEGEND.label, "mtb-trail"),
    ...MTB_LEVELS.map((shape) => {
      const words = mtbLevelLegend(shape);
      return row(`mtb-${shape.level}`, h(MtbLevelSwatch, { shape, strong }), words.short, words.label, `mtb-level mtb-level-${shape.level}`);
    }),
  ];
}

/**
 * The mountain-bike trails' key, under their switch in Layers' Trails and terrain section, in every ride type
 * (454; the owner, 2026-10-19: "include the legend within the accordion settings in layers"): the trail's row
 * in words, not behind the zoom fold (452a), and a row a level (456), while the layer is on. Null while it is
 * off, or once the trails are routable.
 */
export function MtbTrailLegend(): ReactElement | null {
  useStressStyle();
  const on = useMtbTrails();
  if (!MTB_LEGEND || !on) return null;
  return h(
    "ul",
    { className: "legend", "aria-label": "Mountain-bike trail legend" },
    ...mtbRows(),
  );
}

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
    h(StressPageLink, null),
    h(
      "ul",
      { className: "legend", "aria-label": "Traffic stress legend" },
      ...tiers.map((tier, i) => row(tier.tier, h(TierSwatch, { tier, widths: widths.tiers[i] }), tier.short, tier.label)),
      row("gravel", h(UnpavedSwatch, { tiers, widths: widths.tiers[0], gravel: true }), "Gravel", GRAVEL_LEGEND),
      row("unpaved", h(UnpavedSwatch, { tiers, widths: widths.tiers[0] }), "Dirt", UNPAVED_LEGEND),
      row("unknown", h(UnknownSurfaceSwatch, { tier: tiers[0], widths: widths.tiers[0] }), "Surface unknown", UNKNOWN_SURFACE_LEGEND),
      // The mountain-bike trails' rows (452a, 456) are in their own key, under their switch in Trails and terrain
      // (MtbTrailLegend), once in Layers.
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

/** The map key's heading and its hint (the owner, 2026-10-19). */
export const MTB_MAP_KEY_TITLE = "Mountain-bike trails";
export const MTB_MAP_KEY_HINT = "Tap a trail for details";

/** The key's short names: the level and its colour, as the legend's rows and the road panel say it. */
export function mtbMapKeyRows(): { key: string; name: string }[] {
  return [{ key: "unrated", name: "Unrated" }, ...MTB_LEVELS.map((l) => ({ key: String(l.level), name: `${l.level} ${l.name[0].toUpperCase()}${l.name.slice(1)}` }))];
}

/**
 * The mountain-bike trails' key on the map itself (the owner, 2026-10-19: "Mountain bike trails need to have a
 * key on the map"): while their layer is on and the map is close enough in to draw them (`drawn`), a small box
 * in the map's corner with each look (the unrated brown dashes, then each level) and its short name, and that a
 * tap on a trail tells more. Not a control: it has nothing to press. Layers keeps the long words.
 */
export function MtbMapKey({ drawn }: { drawn: boolean }): ReactElement | null {
  useStressStyle();
  const on = useMtbTrails();
  if (!MTB_LEGEND || !on || !drawn) return null;
  const strong = accessibilityOn();
  const rows = mtbMapKeyRows();
  return h(
    "section",
    { className: "mtb-map-key", "aria-label": MTB_MAP_KEY_TITLE + " key" },
    h("p", { className: "mtb-map-key-title", "aria-hidden": "true" }, MTB_MAP_KEY_TITLE),
    h(
      "ul",
      null,
      ...rows.map((r, i) =>
        h(
          "li",
          { key: r.key },
          i === 0 ? h(MtbTrailSwatch, { strong }) : h(MtbLevelSwatch, { shape: MTB_LEVELS[i - 1], strong }),
          h("span", null, r.name),
        ),
      ),
    ),
    h("p", { className: "mtb-map-key-hint" }, MTB_MAP_KEY_HINT),
  );
}
