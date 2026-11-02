/**
 * The planned route drawn in its traffic stress, section by section
 * (OWNER-DECISIONS item 81: "Could we also get a color on the route for what
 * LTS it is?").
 *
 * The API answers `stress_spans`, the route's sections in whole metres along
 * its traced length (core.routing.stress_spans). This cuts the route's own
 * geometry at those distances - scaled to the line as drawn, whose length the
 * trace measures a little differently - and gives each section the colour the
 * stress map gives the same class, from the shared tokens (stressStyle.js), so
 * a change to the map's palette reaches the route too.
 */
import { ACCESSIBILITY_PALETTE, FACILITIES, HIGH_STRESS_LANE_MIN_TIER, currentPalette, currentTiers, darkMapOn, halfStep, styleKey } from "../stressStyle.js";
import { MASS_AVOID, MASS_BANDS, bandIndex, dashInWidths } from "../massStyle.js";
import type { StressSpan } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { unrated } from "./stressBar.ts";
import { STEP_WORDS } from "./stepWords.ts";
import { ROUTE_AVOID_HALO, ROUTE_AVOID_MAGENTA, ROUTE_AVOID_MARK, ROUTE_AVOID_MARK_DASH } from "./avoidColour.ts";

export { ROUTE_AVOID_HALO, ROUTE_AVOID_MAGENTA, ROUTE_AVOID_MARK, ROUTE_AVOID_MARK_DASH } from "./avoidColour.ts";

export type MassClassKey = "m0" | "m1" | "m2" | "m3" | "mavoid";
/** A half step's class (OWNER-DECISIONS 461a; the owner, 2026-10-30): its lower level's key and "h". */
export type HalfClassKey = "1h" | "2h" | "3h" | "4h";
export type RouteClassKey = "path" | "1" | "2" | "3" | "4" | "5" | HalfClassKey | "u1" | "u2" | "u3" | "u4" | "u5" | "g1" | "g2" | "g3" | "g4" | "g5" | "unknown" | MassClassKey;

/** A Mass Ride's classes (massStyle.js): the capacity bands, and a stretch marked Avoid with no capacity colour. */
export const MASS_CLASS_KEYS: readonly MassClassKey[] = ["m0", "m1", "m2", "m3", "mavoid"];

export const isMassClass = (key: RouteClassKey): key is MassClassKey => (MASS_CLASS_KEYS as readonly string[]).includes(key);

/** Whether a class is unpaved: one of the browns (natural surface) or the gravel greys (2026-10-21). */
export const isUnpavedClass = (key: RouteClassKey): boolean => (key.startsWith("u") && key !== "unknown") || key.startsWith("g");

/** The dotted mark over an unpaved section: a little under half its width, at least 1.5 px (as the map's, stressStyle.js unpavedWidth). */
export const routeMarkWidth = (width: number): number => Math.max(1.5, width * 0.4);

/**
 * Avoid's dash-dot as an SVG `stroke-dasharray` for a line `width` wide (the route legend's swatch,
 * FacilityBreakdown): the map layer's `line-dasharray` is in mark widths, so this is the same
 * pattern, scaled by the mark's width (OWNER-DECISIONS 397).
 */
export const routeMarkDash = (width: number): string => ROUTE_AVOID_MARK_DASH.map((d) => d * routeMarkWidth(width)).join(" ");

export interface RouteClass {
  key: RouteClassKey;
  short: string;
  label: string;
  color: string;
  /** The thin ring between the section and the route's casing: a colour 3:1 from `color` (see ROUTE_HALO_PATH). */
  halo: string;
  /** The section's line width in pixels: wider as the stress rises (see ROUTE_SECTION_WIDTHS). */
  width: number;
  /** The halo's width: a pixel wider each side than `width`. */
  haloWidth: number;
  /** The near-black ring outside the halo (OWNER-DECISIONS 371: two-tone LTS 3 and 4), or none. */
  ring?: string;
  /** Its width: a pixel wider each side than `haloWidth`. */
  ringWidth?: number;
  /** The dash-dot down the middle of a paved Avoid section (ROUTE_AVOID_MARK), the cue that is not colour; none elsewhere. */
  mark?: string;
  /** A Mass Ride class's dash, in line widths (the cue besides colour); absent for a solid line. */
  dash?: readonly number[];
  /**
   * A half step's dash over its section in the colour-blind-friendly palette, in the next level's colour
   * (HALF_STEP_DASH, MapView's route-half layer), where the half step has no colour of its own; absent elsewhere.
   */
  halfDash?: string;
  /** The outline under that dash where it is too close to its line (458b: the colour-blind palette's 4.5). */
  halfOutline?: string;
}

/**
 * The route's section widths in pixels, by class: visual weight rises with
 * stress here as it does on the overlay (OWNER-DECISIONS 274), so a stretch of
 * LTS 4 or Avoid is the heavier mark on the route. The traffic-free path is the
 * lightest, the unrated grey sits at the middle's width. The halo is a pixel
 * wider each side (ROUTE_HALO_EXTRA) and the casing outside it stays wider than
 * the widest halo (ROUTE_CASING_WIDTH).
 */
export const ROUTE_SECTION_WIDTHS: Readonly<Record<RouteClassKey, number>> = {
  path: 4,
  "1": 4,
  "2": 4.5,
  "3": 5,
  "4": 5.5,
  "5": 6,
  // A half step: halfway between its two levels' widths.
  "1h": 4.25,
  "2h": 4.75,
  "3h": 5.25,
  "4h": 5.75,
  // Unpaved: the tier's own width (OWNER-DECISIONS 302: the same ladder).
  u1: 4,
  u2: 4.5,
  u3: 5,
  u4: 5.5,
  u5: 6,
  // Gravel: the same ladder.
  g1: 4,
  g2: 4.5,
  g3: 5,
  g4: 5.5,
  g5: 6,
  unknown: 5,
  // A Mass Ride's: the capacity bands' own widths, rising with the capacity (OWNER-DECISIONS 327).
  m0: MASS_BANDS[0].width,
  m1: MASS_BANDS[1].width,
  m2: MASS_BANDS[2].width,
  m3: MASS_BANDS[3].width,
  mavoid: MASS_AVOID.width,
};

/** The halo under the unrated grey: a near-black neutral, 6.0:1 from #9aa0a6 and 6.2:1 from the cvd grey. */
export const UNRATED_HALO = "#202326";

/** The halo's extra width over its section: a pixel on each side. */
export const ROUTE_HALO_EXTRA = 2;

/**
 * The halo under the traffic-free violet: white, 10.9:1 from it. The route's
 * casing is one colour for the whole route, and no one colour is 3:1 from
 * every class (the calm tiers, the unrated grey and the amber are mid to
 * light, the violet, LTS 4 and Avoid dark, so a casing that suits one half
 * fails the other: the luminance a casing would need is at most 0.045 for the
 * amber and at least 0.5 for the violet). So each section also carries a
 * one-pixel halo of its own, dark under the light classes and white under the
 * dark ones (the stress map's own casings, stressStyle.js), and the casing
 * outside it is the route's identity, not the thing the section is read
 * against (WCAG 1.4.11; stressContrast.test.ts holds every class to 3:1 from
 * its halo in both palettes, plain and strengthened).
 */
export const ROUTE_HALO_PATH = "#ffffff";

const PATH = FACILITIES.find((facility) => facility.facility === "path");

/**
 * Avoid on the planned route (OWNER-DECISIONS 397: "Avoid as a single color should be magenta. It's
 * a very striking danger color. Only do if a route uses it"): one magenta in every palette, paved or
 * unpaved, in place of the palette's Avoid (avoidColour.ts). Only the route's own sections: the map's
 * general Avoid roads keep the palette's Avoid (stressStyle.js), and the legend lists Avoid only when
 * the route rides some (`routeLegend`). The route chart's Avoid and the route panel's stress bar are
 * the same magenta. Its halo is near-black, 4.1:1 from it (the halo rule: dark under a class lighter
 * than 0.14 luminance; the magenta is 0.16). A paved Avoid also carries a white dash-dot down its
 * middle (ROUTE_AVOID_MARK, MapView's route-avoid layer), so it is not told by colour alone: in the
 * high contrast palette the magenta is close to LTS 3 and LTS 2 for some colour visions. An unpaved
 * Avoid keeps its dotted unpaved mark instead, which already sets it apart from every paved class.
 */
const avoidOnTheRoute = (c: RouteClass): RouteClass =>
  c.key === "5" || c.key === "mavoid"
    ? { ...c, color: ROUTE_AVOID_MAGENTA, halo: ROUTE_AVOID_HALO, mark: ROUTE_AVOID_MARK }
    : c.key === "u5" || c.key === "g5"
      ? { ...c, color: ROUTE_AVOID_MAGENTA, halo: ROUTE_AVOID_HALO }
      : c;

/**
 * The classes a section is drawn in, in the legend's order: traffic-free
 * first (a path, or a road closed to cars at the ride's time, whatever its
 * tier), then the stress tiers, then what no segment rated. Read from the
 * palette in use each time: the rider can flip the accessibility switch while a route is up
 * (stressStyle.js, setAccessibility), so a list built once at import would keep the
 * old colours.
 */
export function routeClasses(): readonly RouteClass[] {
  const none = unrated();
  const tiers = currentTiers();
  const drawn: RouteClass[] = [
    {
      key: "path",
      short: "Traffic-free",
      label: "Off-road path, or a road closed to cars",
      color: PATH ? PATH.color : "#4c1d95",
      halo: ROUTE_HALO_PATH,
      width: ROUTE_SECTION_WIDTHS.path,
      haloWidth: ROUTE_SECTION_WIDTHS.path + ROUTE_HALO_EXTRA,
    },
    ...tiers.map((tier: { tier: number; short: string; label: string; color: string; casing: string; ring?: string }) => ({
      key: String(tier.tier) as RouteClassKey,
      short: tier.short,
      label: tier.label,
      color: tier.color,
      halo: tier.casing,
      width: ROUTE_SECTION_WIDTHS[String(tier.tier) as RouteClassKey],
      haloWidth: ROUTE_SECTION_WIDTHS[String(tier.tier) as RouteClassKey] + ROUTE_HALO_EXTRA,
      ...(tier.ring ? { ring: tier.ring, ringWidth: ROUTE_SECTION_WIDTHS[String(tier.tier) as RouteClassKey] + 2 * ROUTE_HALO_EXTRA } : {}),
    })),
    // The half steps (the owner, 2026-10-30: "There's definitely room in the color spectrum where we are
    // drawing routes to include half steps"), each after its lower level: its own colour, casing and ring
    // (stressStyle.js HALF_PALETTES), or in the colour-blind-friendly palette its lower level's look with
    // the next level's dash over it, as the map draws one (HALF_DASHED).
    ...tiers.filter((tier: { tier: number }) => tier.tier < 5).map((tier: { tier: number; color: string; casing: string; ring?: string }) => {
      const key = `${tier.tier}h` as HalfClassKey;
      const step = String(tier.tier + 0.5);
      // Never null: every level below Avoid has a step above it.
      const half = halfStep(tier.tier, tiers)!;
      const width = ROUTE_SECTION_WIDTHS[key];
      const ring = half.solid ? half.ring : tier.ring;
      return {
        key,
        short: `LTS ${step}`,
        label: STEP_WORDS[step],
        color: half.solid ? half.color : tier.color,
        halo: half.solid ? half.outline : tier.casing,
        width,
        haloWidth: width + ROUTE_HALO_EXTRA,
        ...(ring ? { ring, ringWidth: width + 2 * ROUTE_HALO_EXTRA } : {}),
        ...(half.solid ? {} : { halfDash: half.color, ...(half.outline ? { halfOutline: half.outline } : {}) }),
      };
    }),
    // Unpaved, in the one brown ramp, light to dark (OWNER-DECISIONS 302): the
    // tier's width, its unpaved casing as the halo, and the dotted mark over it
    // (MapView's route-unpaved layer) as the cue that is not colour.
    ...tiers.map((tier: { tier: number; short: string; label: string; unpavedColor: string; unpavedCasing: string }) => ({
      key: `u${tier.tier}` as RouteClassKey,
      short: `Dirt ${tier.short}`,
      label: `Dirt or other natural surface: ${tier.label.charAt(0).toLowerCase()}${tier.label.slice(1)}`,
      color: tier.unpavedColor,
      halo: tier.unpavedCasing,
      width: ROUTE_SECTION_WIDTHS[`u${tier.tier}` as RouteClassKey],
      haloWidth: ROUTE_SECTION_WIDTHS[`u${tier.tier}` as RouteClassKey] + ROUTE_HALO_EXTRA,
    })),
    // Gravel (an unpaved section the API says is not rough), in the grey ramp (the owner, 2026-10-21:
    // "Maybe make natural surface trails brown and gravel grey?"; stressStyle.js GRAVEL_PALETTES), with the same dots.
    ...tiers.map((tier: { tier: number; short: string; label: string; gravelColor: string; gravelCasing: string }) => ({
      key: `g${tier.tier}` as RouteClassKey,
      short: `Gravel ${tier.short}`,
      label: `Gravel: ${tier.label.charAt(0).toLowerCase()}${tier.label.slice(1)}`,
      color: tier.gravelColor,
      halo: tier.gravelCasing,
      width: ROUTE_SECTION_WIDTHS[`g${tier.tier}` as RouteClassKey],
      haloWidth: ROUTE_SECTION_WIDTHS[`g${tier.tier}` as RouteClassKey] + ROUTE_HALO_EXTRA,
    })),
    // A Mass Ride's classes: the capacity bands and Avoid (massStyle.js). Drawn when the API's spans carry `rpm`.
    ...MASS_BANDS.map((band: (typeof MASS_BANDS)[number], i: number) => ({
      key: `m${i}` as RouteClassKey,
      short: band.short,
      label: `${band.name.charAt(0).toUpperCase()}${band.name.slice(1)}: ${band.short.toLowerCase()} riders per minute`,
      color: band.color,
      halo: band.halo,
      width: band.width,
      haloWidth: band.width + ROUTE_HALO_EXTRA,
      ...(band.dashPx ? { dash: dashInWidths(band) as number[] } : {}),
    })),
    {
      key: "mavoid" as RouteClassKey,
      short: "Avoid",
      label: "Marked Avoid: no capacity given",
      // The route's own Avoid is the one magenta with the white dash-dot on a Mass Ride too
      // (OWNER-DECISIONS 397, `avoidOnTheRoute`), as the route chart draws it; the capacity map's
      // general Avoid roads keep MASS_AVOID's look (massStyle.js).
      color: MASS_AVOID.color,
      halo: MASS_AVOID.casing,
      width: MASS_AVOID.width,
      haloWidth: MASS_AVOID.width + ROUTE_HALO_EXTRA,
    },
    // The unrated grey is a mid colour: a dark neutral halo of its own stands under it. It was LTS 1's
    // casing, until 357 softened that to a green the grey is not 3:1 on (2.86:1).
    {
      key: "unknown",
      short: none.short,
      label: none.label,
      color: none.color,
      halo: UNRATED_HALO,
      width: ROUTE_SECTION_WIDTHS.unknown,
      haloWidth: ROUTE_SECTION_WIDTHS.unknown + ROUTE_HALO_EXTRA,
    },
  ];
  return interleaveHalfSteps(drawn).map(avoidOnTheRoute);
}

/** The paved levels in the legend's order, each half step after its lower level: 1, 1.5, 2 ... 4.5, Avoid. */
const PAVED_ORDER: readonly RouteClassKey[] = ["1", "1h", "2", "2h", "3", "3h", "4", "4h", "5"];

function interleaveHalfSteps(drawn: RouteClass[]): RouteClass[] {
  const paved = PAVED_ORDER.map((key) => drawn.find((c) => c.key === key)).filter((c): c is RouteClass => c !== undefined);
  const first = drawn.findIndex((c) => PAVED_ORDER.includes(c.key));
  const rest = drawn.filter((c) => !PAVED_ORDER.includes(c.key));
  return [...rest.slice(0, first), ...paved, ...rest.slice(first)];
}

/** The classes by key, built once per look of the tiers (styleKey) rather than once per section. */
let classes: { style: string; byKey: Map<RouteClassKey, RouteClass> } | null = null;

function classByKey(key: RouteClassKey): RouteClass | undefined {
  const style = styleKey();
  if (classes === null || classes.style !== style) {
    classes = { style, byKey: new Map(routeClasses().map((c) => [c.key, c])) };
  }
  return classes.byKey.get(key);
}

/**
 * A section's class: unpaved (the API's `unpaved: true`) in its tier's brown, or its grey on gravel (`rough: false`), a
 * traffic-free path at LTS 1's when it has no tier; else traffic-free before its
 * tier, and unknown without one. An unknown surface (null, or an older API) is drawn as paved.
 */
export function spanClass(
  span: Pick<StressSpan, "tier" | "facility"> & Partial<Pick<StressSpan, "unpaved" | "rough" | "rpm" | "outside_dc" | "half">>,
  capacity = false,
): RouteClass {
  // A Mass Ride's section (`capacity`: the route's sections carry riders per minute, usesCapacity): by
  // capacity band, or Avoid alone for a stretch marked Avoid; a section with no capacity is the unknown
  // grey (OWNER-DECISIONS 325, 327).
  // Outside DC (427) a Mass Ride's section has no figure and is not greyed: it keeps its stress colour.
  if (capacity && !span.outside_dc) {
    if (span.tier === 5) return classByKey("mavoid") as RouteClass;
    const band = bandIndex(span.rpm);
    return (band !== null ? classByKey(`m${band}` as RouteClassKey) : classByKey("unknown")) as RouteClass;
  }
  if (span.unpaved === true) {
    const tier = span.tier ?? (span.facility === "path" ? 1 : null);
    // Gravel grey only where the API says it is not rough; rough, or not said (an older API or table), brown.
    const brown = tier !== null ? classByKey(`${span.rough === false ? "g" : "u"}${tier}` as RouteClassKey) : undefined;
    if (brown) return brown;
  }
  // Avoid before traffic-free: a path rated Avoid (only an access override could make one) is drawn
  // as the route chart draws it, in the Avoid magenta, not the path's violet (r3 correctness, N3).
  if (span.tier === 5) return classByKey("5") as RouteClass;
  if (span.facility === "path") return classByKey("path") as RouteClass;
  // A paved half step (the API's `half: true`, core.routing.stress_spans) in its own class; an unpaved one
  // took its level's brown or grey above.
  if (span.half === true && span.tier !== null && span.tier < 5) return classByKey(`${span.tier}h` as HalfClassKey) as RouteClass;
  const tier = classByKey(String(span.tier) as RouteClassKey);
  return span.tier !== null && tier ? tier : (classByKey("unknown") as RouteClass);
}

export interface RouteSection {
  key: RouteClassKey;
  color: string;
  halo: string;
  width: number;
  haloWidth: number;
  ring?: string;
  ringWidth?: number;
  mark?: string;
  dash?: readonly number[];
  halfDash?: string;
  halfOutline?: string;
  coordinates: LonLat[];
}

/** Whether a route's sections are drawn by capacity: any carries a figure (a Mass Ride on a table that has the column). */
export function usesCapacity(spans: readonly StressSpan[] | undefined): boolean {
  return !!spans && spans.some((span) => typeof span.rpm === "number");
}

/** Whether sections can be drawn: some, meeting end to end from 0. */
export function usableSpans(spans: readonly StressSpan[] | null | undefined): spans is readonly StressSpan[] {
  if (!spans || spans.length === 0) return false;
  let at = 0;
  for (const span of spans) {
    if (!(Number.isFinite(span.from_m) && Number.isFinite(span.to_m))) return false;
    if (span.from_m !== at || span.to_m <= span.from_m) return false;
    at = span.to_m;
  }
  return at > 0;
}

function pointAt(a: LonLat, b: LonLat, t: number): LonLat {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

/**
 * The route's line cut at its spans' distances (scaled to the line as drawn), in route order: one piece
 * a run of spans `keyOf` gives one key, each piece sharing its first point with the last one's end, so
 * the pieces have no gaps. A span `keyOf` gives null is passed over and starts no piece. Null when the
 * line or the spans are unusable.
 */
function cutAtSpans(
  coordinates: readonly LonLat[],
  spans: readonly StressSpan[] | undefined,
  keyOf: (span: StressSpan) => string | null,
): { key: string; span: StressSpan; coordinates: LonLat[] }[] | null {
  if (coordinates.length < 2 || !usableSpans(spans)) return null;
  const along = [0];
  for (let i = 1; i < coordinates.length; i += 1) {
    along.push(along[i - 1] + haversineM(coordinates[i - 1], coordinates[i]));
  }
  const drawn = along[along.length - 1];
  if (!(drawn > 0)) return null;
  const scale = drawn / spans[spans.length - 1].to_m;

  const pieces: { key: string; span: StressSpan; coordinates: LonLat[] }[] = [];
  let vertex = 1; // the next vertex not yet passed
  let start: LonLat = coordinates[0];
  let previousKey: string | null = null;
  spans.forEach((span, index) => {
    const last = index === spans.length - 1;
    const end = last ? drawn : span.to_m * scale;
    const points: LonLat[] = [start];
    while (vertex < coordinates.length && (last || along[vertex] < end)) {
      points.push(coordinates[vertex]);
      vertex += 1;
    }
    let finish: LonLat;
    if (last || vertex >= coordinates.length) {
      finish = points[points.length - 1];
    } else {
      const a = coordinates[vertex - 1];
      const b = coordinates[vertex];
      const piece = along[vertex] - along[vertex - 1];
      finish = pointAt(a, b, piece > 0 ? (end - along[vertex - 1]) / piece : 1);
      points.push(finish);
    }
    start = finish;
    const key = keyOf(span);
    const previous = pieces[pieces.length - 1];
    if (key !== null && previous && previousKey === key) {
      previous.coordinates.push(...points.slice(1));
    } else if (key !== null && points.length >= 2) {
      pieces.push({ key, span, coordinates: points });
    }
    // The previous span's key, not the last piece's: a skipped span (null, or a point past the line's end)
    // ends the run, so lane marks never bridge a stretch with none.
    previousKey = key;
  });
  return pieces;
}

/**
 * The route cut into its coloured sections, in route order, or null when the
 * answer has no usable sections (an older API, or ones that do not meet end to
 * end) and the route is drawn as one line instead. Adjacent sections of one
 * class are joined; each section shares its first point with the last one's
 * end, so the line has no gaps.
 */
export function routeSections(
  coordinates: readonly LonLat[],
  spans: readonly StressSpan[] | undefined,
): RouteSection[] | null {
  const capacity = usesCapacity(spans);
  const pieces = cutAtSpans(coordinates, spans, (span) => spanClass(span, capacity).key);
  if (!pieces || pieces.length === 0) return null;
  return pieces.map(({ span, coordinates: points }) => {
    const cls = spanClass(span, capacity);
    return { key: cls.key, color: cls.color, halo: cls.halo, width: cls.width, haloWidth: cls.haloWidth, ...(cls.ring ? { ring: cls.ring, ringWidth: cls.ringWidth } : {}), ...(cls.mark ? { mark: cls.mark } : {}), ...(cls.dash ? { dash: cls.dash } : {}), ...(cls.halfDash ? { halfDash: cls.halfDash } : {}), ...(cls.halfOutline ? { halfOutline: cls.halfOutline } : {}), coordinates: points };
  });
}

/** The bike lanes the route marks in its white band: a protected lane's posts and a painted lane's dots. */
export type RouteLaneFacility = "protected" | "lane";

/**
 * The lane marks' rails (the owner, 2026-11-01: "See if you can mark pbls and painted lanes on the
 * highlighted route as well", and "Add it in" to the mockup): the map's own facility rails
 * (stressStyle.js FACILITIES), drawn either side of the route's section inside its white band, so the
 * route's stress colours are untouched. A protected lane's are its magenta posts, a painted lane's the
 * pale violet dots, thinner. A path needs none: it has its own colour on the route. Each rail keeps half a
 * pixel of white from the section's outer edge (its ring, or else its halo) and a pixel from the casing.
 */
export const ROUTE_LANE_RAIL = { protected: 2.5, lane: 1.5 } as const;
/** The posts' and dots' `line-dasharray`, in rail widths: posts about 3 px on, 2 off; dots 1.6 on, 4 off. */
export const ROUTE_LANE_DASH: Readonly<Record<RouteLaneFacility, readonly number[]>> = { protected: [1.2, 0.8], lane: [1.07, 2.67] };
const LANE_COLOURS = Object.fromEntries(
  FACILITIES.filter((f: { facility: string }) => f.facility === "protected" || f.facility === "lane").map((f: { facility: string; color: string }) => [f.facility, f.color]),
) as Record<RouteLaneFacility, string>;

/** A span's lane mark: its facility when it is one the route marks and shown, else null. */
function laneFacility(span: StressSpan, showHighStressLanes: boolean): RouteLaneFacility | null {
  if (span.facility === "protected") return "protected";
  // A painted lane on LTS 4 and Avoid is not drawn unless the rider asks (OWNER-DECISIONS 275), as on the map.
  if (span.facility === "lane") return showHighStressLanes || !(typeof span.tier === "number" && span.tier >= HIGH_STRESS_LANE_MIN_TIER) ? "lane" : null;
  return null;
}

export interface RouteLaneMark {
  facility: RouteLaneFacility;
  color: string;
  /** The rail's width, thinner where the section is wide and leaves less white. */
  width: number;
  /** The gap between the two rails: the section's outer edge and half a pixel of white each side. */
  gap: number;
  coordinates: LonLat[];
}

/**
 * The route's lane marks, in route order: one a run of one facility on one width of section. None on a
 * Mass Ride's route (its capacity bands are wider and its rails on the map give way, OWNER-DECISIONS
 * 325), none without usable spans, and none on a transit trip's later rides (only `coordinates` is cut).
 */
export function routeLaneMarks(
  coordinates: readonly LonLat[],
  spans: readonly StressSpan[] | undefined,
  showHighStressLanes: boolean,
): RouteLaneMark[] {
  if (usesCapacity(spans)) return [];
  const outer = (span: StressSpan): number => {
    const cls = spanClass(span);
    return cls.ringWidth ?? cls.haloWidth;
  };
  const pieces = cutAtSpans(coordinates, spans, (span) => {
    const facility = laneFacility(span, showHighStressLanes);
    return facility ? `${facility}:${outer(span)}` : null;
  });
  return (pieces ?? []).map(({ span, coordinates: points }) => {
    const facility = laneFacility(span, showHighStressLanes) as RouteLaneFacility;
    const gap = outer(span) + 1;
    // The band less a pixel of white each side against the casing, shared by the gap and the two rails.
    const width = Math.max(1, Math.min(ROUTE_LANE_RAIL[facility], (ROUTE_BAND_WIDTH - 2 - gap) / 2));
    return { facility, color: LANE_COLOURS[facility], width, gap, coordinates: points };
  });
}

/** The lane marks as GeoJSON, for the map's route-lanes source. */
export function laneMarkFeatures(marks: readonly RouteLaneMark[]) {
  return {
    type: "FeatureCollection" as const,
    features: marks.map(({ coordinates, ...properties }) => ({
      type: "Feature" as const,
      properties,
      geometry: { type: "LineString" as const, coordinates },
    })),
  };
}

/** The sections as GeoJSON, for the map's "route-stress" source. */
export function sectionFeatures(sections: readonly RouteSection[] | null) {
  return {
    type: "FeatureCollection" as const,
    features: (sections ?? []).map((section) => ({
      type: "Feature" as const,
      properties: {
        key: section.key,
        color: section.color,
        halo: section.halo,
        width: section.width,
        haloWidth: section.haloWidth,
        // The near-black ring outside the halo (371), transparent where the class has none.
        ring: section.ring ?? "rgba(0, 0, 0, 0)",
        ringWidth: section.ringWidth ?? 0,
        // The dotted unpaved mark (MapView's route-unpaved layer draws only these).
        unpaved: isUnpavedClass(section.key),
        markWidth: routeMarkWidth(section.width),
        // The white dash-dot over a paved Avoid section (MapView's route-avoid layer draws only these).
        avoid: section.mark !== undefined,
        mark: section.mark ?? "rgba(0, 0, 0, 0)",
        // A half step's dash in the colour-blind-friendly palette (MapView's route-half layer draws only these).
        half: section.halfDash !== undefined,
        halfDash: section.halfDash ?? "rgba(0, 0, 0, 0)",
        halfOutline: section.halfOutline ?? "rgba(0, 0, 0, 0)",
      },
      geometry: { type: "LineString" as const, coordinates: section.coordinates },
    })),
  };
}

export interface RouteLegendRow extends RouteClass {
  metres: number;
}

/** The route's own colours, in the legend's order, with their length on this route. */
export function routeLegend(spans: readonly StressSpan[] | undefined): RouteLegendRow[] {
  if (!usableSpans(spans)) return [];
  const metres = new Map<RouteClassKey, number>();
  const capacity = usesCapacity(spans);
  for (const span of spans) {
    const key = spanClass(span, capacity).key;
    metres.set(key, (metres.get(key) ?? 0) + (span.to_m - span.from_m));
  }
  return routeClasses().filter((c) => metres.has(c.key)).map((c) => ({ ...c, metres: metres.get(c.key) ?? 0 }));
}

/** The route's own blue: its line when it has no sections, and its casing when it has. */
export const ROUTE_BLUE = "#1d4ed8";
/**
 * The casing under the route's sections in the colour-blind-friendly palette,
 * where the blue no longer stands apart: that palette's LTS 2 is a mid blue,
 * 2.22:1 and about 20 CIEDE2000 from it, so an LTS 2 section read as a plain
 * route (review r1, accessibility). A dark slate: LTS 2 is 3.04:1 from it and
 * at least 32 CIEDE2000 under every simulated colour vision. No one colour is
 * 3:1 from every class (LTS 1 is near white and Avoid near black), so the
 * others are held apart by hue: every class, the unrated grey and the
 * traffic-free violet at least 19 CIEDE2000 from it under every vision, the
 * best a search of sRGB found with LTS 2 at 3:1 (docs/DEVELOPMENT.md;
 * stressContrast.test.ts).
 */
export const ROUTE_CASING_CVD = "#344c4c";

/** The casing under the route's sections, for the palette in use. */
export function routeCasing(palette: string = currentPalette()): string {
  return palette === ACCESSIBILITY_PALETTE ? ROUTE_CASING_CVD : ROUTE_BLUE;
}

/**
 * The route's casing on the dark map (the owner, 2026-11-01: battery audit; stressStyle.js DARK_MAP): the blue and the
 * slate are under 3:1 on the dark flavour's surfaces, so there the blue is a lighter blue and the slate white, each 3:1
 * or more on every dark surface (darkMap.test.ts). White is the one colour 3:1 from the colour-blind-friendly LTS 2
 * that is also light enough for the dark map; the halo under each section still tells it from the class. The light
 * map's casings are unchanged, and so are the legend's and the route choice's colours, which sit on the panel.
 */
export const ROUTE_BLUE_DARK_MAP = "#60a5fa";
export const ROUTE_CASING_CVD_DARK_MAP = "#ffffff";

/** A route casing as the map draws it: its dark-map variant while the dark map shows, else as given. */
export function casingOnMap(casing: string, dark: boolean = darkMapOn()): string {
  if (!dark) return casing;
  if (casing === ROUTE_BLUE) return ROUTE_BLUE_DARK_MAP;
  if (casing === ROUTE_CASING_CVD) return ROUTE_CASING_CVD_DARK_MAP;
  return casing;
}

/** The casing under a one-colour route, as it was before the sections. */
export const ROUTE_CASING_PLAIN = "#ffffff";
export const ROUTE_LINE_WIDTH = 5;
/** Wide enough that the widest halo (Avoid's, 8 px) leaves the casing's own pixel and more each side. */
export const ROUTE_CASING_WIDTH = 11;
/** The halo's width under a section of ROUTE_LINE_WIDTH: a pixel wider each side than the line, inside the casing's own pixel. Each section's own is `haloWidth`. */
export const ROUTE_HALO_WIDTH = 7;

/**
 * How the three route layers are painted. With sections, the casing is the
 * route's blue (a dark slate in the colour-blind-friendly palette), so a
 * route drawn in the stress map's own colours still reads as one route over
 * the stress map, and the one-colour line is hidden; without
 * them the route is drawn as it was, blue on white. A stale route is dimmed
 * either way.
 */
export function routePaint(
  hasSections: boolean,
  stale: boolean,
  sectionCasing: string = routeCasing(),
): { lineOpacity: number; sectionOpacity: number; haloOpacity: number; casingColor: string } {
  const shown = stale ? 0.45 : 1;
  return {
    lineOpacity: hasSections ? 0 : shown,
    sectionOpacity: hasSections ? shown : 0,
    haloOpacity: hasSections ? shown : 0,
    casingColor: hasSections ? casingOnMap(sectionCasing) : ROUTE_CASING_PLAIN,
  };
}

/**
 * The route as a corridor over the road colours (Stephen, 2026-10-12: "The colors on mass ride are
 * so bright that I can't see the actual route." and, of a regular route, "It's similar for regular
 * routes too, but not as pronounced."). The route's sections are drawn in the map's own colours (a
 * Mass Ride's in the capacity bands' colours, widths and dashes, the same as the roads under it),
 * and the 11 px casing left a pixel or less of blue each side of the widest: the route read as one
 * more road. So a route with sections is drawn on a white band (ROUTE_BAND_WIDTH) inside a wider
 * casing in the route's own colour (ROUTE_CORRIDOR_CASING_WIDTH): about three pixels of white and
 * three of blue each side of the widest halo (a Mass Ride's Wide open, 10.5 px). Every class's
 * edge against the white is 3:1 (its halo or ring, or the section itself where its halo is white;
 * routeCorridor.test.ts). The roads behind it fade (`overlayFade`). The route's own colours, halos
 * and dashes are unchanged, so its legend still reads. A one-colour route (no sections) is as before.
 */
export const ROUTE_BAND = "#ffffff";
export const ROUTE_BAND_WIDTH = 16;
export const ROUTE_CORRIDOR_CASING_WIDTH = 22;
/**
 * The route legend's swatch, the corridor in miniature (FacilityBreakdown, massLegend's
 * RouteClassSwatch): an 18 px tall swatch with a 17 px casing round a 13 px white band, so the
 * section sits on white inside blue as on the map, with a pixel or more of each round the widest halo.
 */
export const ROUTE_SWATCH_HEIGHT = 18;
export const ROUTE_SWATCH_CASING_WIDTH = 17;
export const ROUTE_SWATCH_BAND_WIDTH = 13;
/** The capacity roads' opacity while a Mass Ride's route is on the map: there to read, not to compete. */
export const MASS_NETWORK_DIMMED = 0.45;
/**
 * The stress map's opacity under any other route (Stephen, 2026-10-12: "Maybe mute most of the
 * colors when there's a route, for default too. Like an alpha of 0.8"): a lighter fade than a
 * Mass Ride's, whose route has its own outline over roads of its own colours.
 */
export const ROUTE_OVERLAY_FADE = 0.8;

/**
 * The corridor's paint: the casing's width and the white band's opacity, for a route drawn in
 * sections (`hasSections`) or as one line. A stale route's band dims with it.
 */
export function routeCorridorPaint(hasSections: boolean, stale: boolean): { casingWidth: number; bandOpacity: number } {
  return {
    casingWidth: hasSections ? ROUTE_CORRIDOR_CASING_WIDTH : ROUTE_CASING_WIDTH,
    bandOpacity: hasSections ? (stale ? 0.45 : 1) : 0,
  };
}

/**
 * How much the map's road colours are faded under the route: MASS_NETWORK_DIMMED under a Mass
 * Ride's capacity route, ROUTE_OVERLAY_FADE under any other route, none (1) with no route.
 * Applied as a factor on each layer's own opacity (mapGlue.ts, setOverlayFade), so the overlay's
 * zoom fades are kept.
 */
export function overlayFade(hasRoute: boolean, capacity: boolean): number {
  if (!hasRoute) return 1;
  return capacity ? MASS_NETWORK_DIMMED : ROUTE_OVERLAY_FADE;
}
