/**
 * Steep grades on a Mass Ride or a Novice and Nervous ride (v0.12.5; routemaker/steep_grades.py). The owner,
 * 2026-10-26: "For mass rides put an elevation warning (orange marker) on any incline in either direction above 5%
 * grade and provide a penalty, above 8% this becomes a red marker with an even steeper penalty. Have the warning
 * marker indicate the direction of the incline (uphill/downhill)" and "Do this for novice rides as well."
 *
 * Drawn as the route hazards are (lib/routeHazards.ts): over the route line only, a mark at the middle of each stretch
 * and repeated along a long one from zoom 14. The mark is a rounded square, the road sign's ramp in it rising left to
 * right for uphill and falling for downhill, as the rider meets it. Not a circle (the hazards), a triangle or a
 * diamond (the junctions). Orange with a dark ramp past 5%, red with a white ramp past 8%: told apart by lightness as
 * well as hue, and each mark carries its grade as words from zoom 13 ("+9%", "-6%"). Never the mark alone: the
 * route's announcement counts them (`steepGradesSaid`) and the elevation chart shows each grade.
 */
import { createElement as h, type ReactElement } from "react";
import type { RouteResponse, SteepGradeSpan } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { LABEL_FONT } from "./railLayer.ts";
import { hexToRgb, rasterise, type Raster, type Rgb } from "./stationIcons.ts";

export const STEEP_GRADE_SOURCE = "route-steep-grades";
export const STEEP_GRADE_LAYER = "route-steep-grade-marks";
export const STEEP_GRADE_ICON_PX = 18;
/** Pixels between two marks along a long stretch. */
export const STEEP_GRADE_SPACING_PX = 110;
export const STEEP_GRADE_LABEL_ZOOM = 13;

/** Orange past 5% (a dark ramp on it, 7.7:1), red past 8% (a white ramp, 6.5:1); a white rim parts each from the line. */
export const STEEP_COLOURS = {
  steep: { fill: "#f97316", mark: "#111827" },
  very_steep: { fill: "#b91c1c", mark: "#ffffff" },
} as const;
export const STEEP_EDGE = "#ffffff";

export type SteepLevel = SteepGradeSpan["level"];
export type SteepDirection = SteepGradeSpan["direction"];

export function steepIconName(level: SteepLevel, direction: SteepDirection): string {
  return `steep-${level}-${direction}`;
}

export const STEEP_ICONS: readonly { level: SteepLevel; direction: SteepDirection }[] = [
  { level: "steep", direction: "up" },
  { level: "steep", direction: "down" },
  { level: "very_steep", direction: "up" },
  { level: "very_steep", direction: "down" },
];

/** True inside the ramp: a right triangle along the square's foot, its tall side right for uphill, left for downhill. */
function inRamp(x: number, y: number, size: number, direction: SteepDirection): boolean {
  const left = 0.22 * size;
  const right = 0.78 * size;
  const foot = 0.74 * size;
  const top = 0.28 * size;
  if (x < left || x > right || y > foot) return false;
  const t = (x - left) / (right - left);
  const rise = direction === "up" ? t : 1 - t;
  return y >= foot - rise * (foot - top);
}

/** The mark: a rounded square with a white rim, the ramp inside it. */
export function steepGradeIcon(level: SteepLevel, direction: SteepDirection, pixelRatio = 2, cssSize = STEEP_GRADE_ICON_PX): Raster {
  const size = Math.round(cssSize * pixelRatio);
  const rim = 1.5 * pixelRatio;
  const corner = 0.22 * size;
  const fill: Rgb = hexToRgb(STEEP_COLOURS[level].fill);
  const mark: Rgb = hexToRgb(STEEP_COLOURS[level].mark);
  const edge: Rgb = hexToRgb(STEEP_EDGE);
  // Distance outside a rounded square of half-side `half` (negative inside).
  const outside = (x: number, y: number, half: number): number => {
    const dx = Math.max(Math.abs(x - size / 2) - (half - corner), 0);
    const dy = Math.max(Math.abs(y - size / 2) - (half - corner), 0);
    return Math.hypot(dx, dy) - corner;
  };
  return rasterise(size, pixelRatio, (x, y): Rgb | null => {
    const half = size / 2 - 0.5;
    if (outside(x, y, half) > 0) return null;
    if (outside(x, y, half - rim) > 0) return edge;
    return inRamp(x, y, size, direction) ? mark : fill;
  });
}

/** The grade as the label says it: "+9%" uphill, "-6%" downhill. */
export function steepLabel(span: Pick<SteepGradeSpan, "direction" | "grade_pct">): string {
  return `${span.direction === "up" ? "+" : "-"}${span.grade_pct}%`;
}

const ICON_EXPRESSION = ["concat", "steep-", ["get", "level"], "-", ["get", "direction"]];

/** The marks' layer, over the route line: one at the middle of each stretch, its grade beside it from zoom 13. */
export function steepGradeLayer(): Record<string, unknown> {
  return {
    id: STEEP_GRADE_LAYER,
    type: "symbol",
    source: STEEP_GRADE_SOURCE,
    layout: {
      "symbol-placement": "line-center",
      "icon-image": ICON_EXPRESSION,
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
      "icon-rotation-alignment": "viewport",
      "text-field": ["step", ["zoom"], "", STEEP_GRADE_LABEL_ZOOM, ["get", "label"]],
      "text-font": [LABEL_FONT],
      "text-size": 13,
      "text-anchor": "left",
      "text-offset": [1.0, 0],
      "text-rotation-alignment": "viewport",
      "text-optional": true,
    },
    paint: { "text-color": "#111827", "text-halo-color": "#ffffff", "text-halo-width": 2 },
  };
}

/** A second placement for a long stretch: repeated every STEEP_GRADE_SPACING_PX from zoom 14. */
export function steepGradeRepeatLayer(): Record<string, unknown> {
  return {
    id: `${STEEP_GRADE_LAYER}-along`,
    type: "symbol",
    source: STEEP_GRADE_SOURCE,
    minzoom: 14,
    layout: {
      "symbol-placement": "line",
      "symbol-spacing": STEEP_GRADE_SPACING_PX,
      "icon-image": ICON_EXPRESSION,
      "icon-allow-overlap": false,
      "icon-rotation-alignment": "viewport",
    },
  };
}

export const STEEP_GRADE_LAYERS = [STEEP_GRADE_LAYER, `${STEEP_GRADE_LAYER}-along`] as const;

type SteepFeature = {
  type: "Feature";
  properties: { level: SteepLevel; direction: SteepDirection; label: string };
  geometry: { type: "LineString"; coordinates: LonLat[] };
};

/**
 * Each steep stretch as a line cut from the route's own geometry. Its metres are along the router's elevation profile,
 * so they are scaled by the route's distance to the line as drawn. Empty with none or no line.
 */
export function steepGradeFeatures(route: (Pick<RouteResponse, "geometry" | "distance_m"> & Partial<Pick<RouteResponse, "steep_grades">>) | null) {
  const features: SteepFeature[] = [];
  const found = route?.steep_grades ?? [];
  const coordinates = (route?.geometry.coordinates ?? []) as LonLat[];
  if (!route || found.length === 0 || coordinates.length < 2) return { type: "FeatureCollection" as const, features };
  const along = [0];
  for (let i = 1; i < coordinates.length; i += 1) along.push(along[i - 1] + haversineM(coordinates[i - 1], coordinates[i]));
  const drawn = along[along.length - 1];
  if (!(drawn > 0) || !(route.distance_m > 0)) return { type: "FeatureCollection" as const, features };
  const scale = drawn / route.distance_m;
  const at = (m: number): LonLat => {
    let k = 0;
    while (k < along.length - 2 && along[k + 1] < m) k += 1;
    const piece = along[k + 1] - along[k];
    const t = piece > 0 ? Math.min(1, Math.max(0, (m - along[k]) / piece)) : 0;
    const a = coordinates[k];
    const b = coordinates[k + 1];
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  };
  for (const span of found) {
    const from = Math.min(drawn, Math.max(0, span.from_m * scale));
    const to = Math.min(drawn, Math.max(span.to_m * scale, from + 1));
    const line: LonLat[] = [at(from)];
    for (let i = 0; i < coordinates.length; i += 1) if (along[i] > from && along[i] < to) line.push(coordinates[i]);
    line.push(at(to));
    features.push({
      type: "Feature",
      properties: { level: span.level, direction: span.direction, label: steepLabel(span) },
      geometry: { type: "LineString", coordinates: line },
    });
  }
  return { type: "FeatureCollection" as const, features };
}

/** Said with the route: "This route has 2 steep grades, 1 of them past 8%: the steepest is 10% downhill." */
export function steepGradesSaid(route: Partial<Pick<RouteResponse, "steep_grades">>): string | null {
  const found = route.steep_grades ?? [];
  if (found.length === 0) return null;
  const n = found.length;
  const red = found.filter((s) => s.level === "very_steep").length;
  const steepest = found.reduce((a, b) => (b.grade_pct > a.grade_pct ? b : a));
  const past8 = red > 0 ? `, ${red} of them past 8%` : "";
  const way = steepest.direction === "up" ? "uphill" : "downhill";
  return `This route has ${n} steep ${n === 1 ? "grade" : "grades"} past 5%${past8}: the steepest is ${steepest.grade_pct}% ${way}. The map marks each.`;
}

/** The ride types that warn of steep grades (routemaker/steep_grades.py RIDE_TYPES). */
export const STEEP_GRADE_RIDE_TYPES: ReadonlySet<string> = new Set(["mass-ride", "novice"]);

export function steepGradesFor(preset: string): boolean {
  return STEEP_GRADE_RIDE_TYPES.has(preset);
}

export const STEEP_KEY_ROWS = [
  { level: "steep" as const, name: "Steep grade", shape: "orange square", text: "Over 5%, uphill or downhill. Routes avoid them where they can." },
  { level: "very_steep" as const, name: "Very steep grade", shape: "red square", text: "Over 8%. The ramp rises for uphill and falls for downhill." },
];

/** The mark as a small inline picture, for the key. Seen, not heard. */
export function SteepGradeSwatch({ level, direction = "up", size = 16 }: { level: SteepLevel; direction?: SteepDirection; size?: number }): ReactElement {
  const l = 0.22 * size;
  const r = 0.78 * size;
  const foot = 0.74 * size;
  const top = 0.28 * size;
  const ramp = direction === "up" ? `${l},${foot} ${r},${foot} ${r},${top}` : `${l},${foot} ${r},${foot} ${l},${top}`;
  return h(
    "svg",
    { width: size, height: size, viewBox: `0 0 ${size} ${size}`, "aria-hidden": "true", focusable: "false", className: "steep-grade-swatch" },
    h("rect", { x: 0.75, y: 0.75, width: size - 1.5, height: size - 1.5, rx: 0.22 * size, fill: STEEP_COLOURS[level].fill, stroke: STEEP_EDGE, strokeWidth: 1.5 }),
    h("polygon", { points: ramp, fill: STEEP_COLOURS[level].mark }),
  );
}

/** The key's two entries, laid out as the route hazard key (lib/routeHazards.ts RouteHazardKey). */
export function SteepGradeKey(): ReactElement {
  return h(
    "ul",
    { className: "route-hazard-key", "aria-label": "Steep grades key" },
    ...STEEP_KEY_ROWS.map((row) =>
      h(
        "li",
        { key: row.level },
        h(SteepGradeSwatch, { level: row.level, size: 20 }),
        h("span", null, h("span", { className: "route-hazard-name" }, row.name), h("span", { className: "hint" }, ` (${row.shape}): `), row.text),
      ),
    ),
  );
}
