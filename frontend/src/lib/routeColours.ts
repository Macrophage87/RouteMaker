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
import type { StressSpan } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { unrated } from "./stressBar.ts";

export type RouteClassKey = "path" | "1" | "2" | "3" | "4" | "5" | "unknown";

export interface RouteClass {
  key: RouteClassKey;
  short: string;
  label: string;
  color: string;
}

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
  return [
    {
      key: "path",
      short: "Traffic-free",
      label: "Off-road path, or a road closed to cars",
      color: PATH ? PATH.color : "#4c1d95",
    },
    ...currentTiers().map((tier: { tier: number; short: string; label: string; color: string }) => ({
      key: String(tier.tier) as RouteClassKey,
      short: tier.short,
      label: tier.label,
      color: tier.color,
    })),
    { key: "unknown", short: none.short, label: none.label, color: none.color },
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

/** A section's class: traffic-free before its tier, and unknown without one. */
export function spanClass(span: Pick<StressSpan, "tier" | "facility">): RouteClass {
  if (span.facility === "path") return classByKey("path") as RouteClass;
  const tier = classByKey(String(span.tier) as RouteClassKey);
  return span.tier !== null && tier ? tier : (classByKey("unknown") as RouteClass);
}

export interface RouteSection {
  key: RouteClassKey;
  color: string;
  coordinates: LonLat[];
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
    const cls = spanClass(span);
    const previous = sections[sections.length - 1];
    if (previous && previous.key === cls.key) {
      previous.coordinates.push(...points.slice(1));
    } else if (points.length >= 2) {
      sections.push({ key: cls.key, color: cls.color, coordinates: points });
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
      properties: { key: section.key, color: section.color },
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
  for (const span of spans) {
    const key = spanClass(span).key;
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
export const ROUTE_CASING_WIDTH = 9;

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
): { lineOpacity: number; sectionOpacity: number; casingColor: string } {
  const shown = stale ? 0.45 : 1;
  return {
    lineOpacity: hasSections ? 0 : shown,
    sectionOpacity: hasSections ? shown : 0,
    casingColor: hasSections ? sectionCasing : ROUTE_CASING_PLAIN,
  };
}
