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
import { ACCESSIBILITY_PALETTE, FACILITIES, currentPalette, currentTiers, styleKey } from "../stressStyle.js";
import { MASS_AVOID, MASS_BANDS, bandIndex, dashInWidths } from "../massStyle.js";
import type { StressSpan } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { unrated } from "./stressBar.ts";

export type MassClassKey = "m0" | "m1" | "m2" | "m3" | "mavoid";
export type RouteClassKey = "path" | "1" | "2" | "3" | "4" | "5" | "u1" | "u2" | "u3" | "u4" | "u5" | "unknown" | MassClassKey;

/** A Mass Ride's classes (massStyle.js): the capacity bands, and a stretch marked Avoid with no capacity colour. */
export const MASS_CLASS_KEYS: readonly MassClassKey[] = ["m0", "m1", "m2", "m3", "mavoid"];

export const isMassClass = (key: RouteClassKey): key is MassClassKey => (MASS_CLASS_KEYS as readonly string[]).includes(key);

/** Whether a class is one of the unpaved browns. */
export const isUnpavedClass = (key: RouteClassKey): boolean => key.startsWith("u") && key !== "unknown";

/** The dotted mark over an unpaved section: a little under half its width, at least 1.5 px (as the map's, stressStyle.js unpavedWidth). */
export const routeMarkWidth = (width: number): number => Math.max(1.5, width * 0.4);

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
  /** A Mass Ride class's dash, in line widths (the cue besides colour); absent for a solid line. */
  dash?: readonly number[];
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
  // Unpaved: the tier's own width (OWNER-DECISIONS 302: the same ladder).
  u1: 4,
  u2: 4.5,
  u3: 5,
  u4: 5.5,
  u5: 6,
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
  return [
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
    // Unpaved, in the one brown ramp, light to dark (OWNER-DECISIONS 302): the
    // tier's width, its unpaved casing as the halo, and the dotted mark over it
    // (MapView's route-unpaved layer) as the cue that is not colour.
    ...tiers.map((tier: { tier: number; short: string; label: string; unpavedColor: string; unpavedCasing: string }) => ({
      key: `u${tier.tier}` as RouteClassKey,
      short: `Unpaved ${tier.short}`,
      label: `Unpaved: ${tier.label.charAt(0).toLowerCase()}${tier.label.slice(1)}`,
      color: tier.unpavedColor,
      halo: tier.unpavedCasing,
      width: ROUTE_SECTION_WIDTHS[`u${tier.tier}` as RouteClassKey],
      haloWidth: ROUTE_SECTION_WIDTHS[`u${tier.tier}` as RouteClassKey] + ROUTE_HALO_EXTRA,
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
      label: "Marked Avoid: no capacity is given",
      color: MASS_AVOID.color,
      halo: MASS_AVOID.casing,
      width: MASS_AVOID.width,
      haloWidth: MASS_AVOID.width + ROUTE_HALO_EXTRA,
      dash: [...MASS_AVOID.dash],
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
 * A section's class: unpaved (the API's `unpaved: true`) in its tier's brown, a
 * traffic-free path at LTS 1's when it has no tier; else traffic-free before its
 * tier, and unknown without one. An unknown surface (null, or an older API) is drawn as paved.
 */
export function spanClass(
  span: Pick<StressSpan, "tier" | "facility"> & Partial<Pick<StressSpan, "unpaved" | "rpm">>,
  capacity = false,
): RouteClass {
  // A Mass Ride's section (`capacity`: the route's sections carry riders per minute, usesCapacity): by
  // capacity band, or Avoid alone for a stretch marked Avoid; a section with no capacity is the unknown
  // grey (OWNER-DECISIONS 325, 327).
  if (capacity) {
    if (span.tier === 5) return classByKey("mavoid") as RouteClass;
    const band = bandIndex(span.rpm);
    return (band !== null ? classByKey(`m${band}` as RouteClassKey) : classByKey("unknown")) as RouteClass;
  }
  if (span.unpaved === true) {
    const tier = span.tier ?? (span.facility === "path" ? 1 : null);
    const brown = tier !== null ? classByKey(`u${tier}` as RouteClassKey) : undefined;
    if (brown) return brown;
  }
  if (span.facility === "path") return classByKey("path") as RouteClass;
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
  dash?: readonly number[];
  coordinates: LonLat[];
}

/** Whether a route's sections are drawn by capacity: any carries a figure (a Mass Ride on a table that has the column). */
export function usesCapacity(spans: readonly StressSpan[] | undefined): boolean {
  return !!spans && spans.some((span) => typeof span.rpm === "number");
}

function usableSpans(spans: readonly StressSpan[] | undefined): spans is readonly StressSpan[] {
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
  if (coordinates.length < 2 || !usableSpans(spans)) return null;
  const along = [0];
  for (let i = 1; i < coordinates.length; i += 1) {
    along.push(along[i - 1] + haversineM(coordinates[i - 1], coordinates[i]));
  }
  const drawn = along[along.length - 1];
  if (!(drawn > 0)) return null;
  const scale = drawn / spans[spans.length - 1].to_m;
  const capacity = usesCapacity(spans);

  const sections: RouteSection[] = [];
  let vertex = 1; // the next vertex not yet passed
  let start: LonLat = coordinates[0];
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
    const cls = spanClass(span, capacity);
    const previous = sections[sections.length - 1];
    if (previous && previous.key === cls.key) {
      previous.coordinates.push(...points.slice(1));
    } else if (points.length >= 2) {
      sections.push({ key: cls.key, color: cls.color, halo: cls.halo, width: cls.width, haloWidth: cls.haloWidth, ...(cls.ring ? { ring: cls.ring, ringWidth: cls.ringWidth } : {}), ...(cls.dash ? { dash: cls.dash } : {}), coordinates: points });
    }
  });
  return sections.length > 0 ? sections : null;
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
    casingColor: hasSections ? sectionCasing : ROUTE_CASING_PLAIN,
  };
}
