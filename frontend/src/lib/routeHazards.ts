/**
 * The known road hazards a route rides (v0.10.0; core/route_hazards.py). The owner, 2026-10-19: "We should have a
 * symbol for roads with known other hazards on the map. One example is the cobblestones in Georgetown or the
 * streetcar rails on H street", then "Roads with hazards like this should get a major penalty. You only need to show
 * it if it's routed on".
 *
 * So the route network prices them as LTS 4 (lua/routemaker_remap.lua) and only a route that still rides one shows
 * it: a small amber warning triangle repeated along the stretch, over the route line, never on the rest of the map.
 * Never the symbol alone: each stretch is a line of the directions ("Rails in the road on H Street Northeast, ..."),
 * Ride says it ahead, and the route's announcement counts them (`roadHazardsSaid`). Written with createElement so a
 * test renders the key.
 */
import { createElement as h, type ReactElement } from "react";
import type { RoadHazardSpan, RouteResponse } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { hexToRgb, rasterise, type Raster, type Rgb } from "./stationIcons.ts";

export const ROUTE_HAZARD_SOURCE = "route-hazards";
export const ROUTE_HAZARD_LAYER = "route-hazard-marks";
export const ROUTE_HAZARD_ICON = "route-hazard";
export const ROUTE_HAZARD_ICON_PX = 18;
/** Amber with a near-black edge and mark: 10.7:1 between the two, and the edge 3:1 or more on every map surface. */
export const ROUTE_HAZARD_FILL = "#fbbf24";
export const ROUTE_HAZARD_EDGE = "#111827";
/** Pixels between two marks along the stretch, and a mark at the middle of one too short for two. */
export const ROUTE_HAZARD_SPACING_PX = 90;

/** How far (x, y) lies inside the upward triangle filling a box of `size` (negative outside), in pixels. */
function triangleDepth(x: number, y: number, size: number): number {
  const top: [number, number] = [size / 2, 1];
  const left: [number, number] = [1, size - 2];
  const right: [number, number] = [size - 1, size - 2];
  const side = (a: [number, number], b: [number, number]) => {
    // Distance from the edge a-b, positive on the triangle's side (the edges run clockwise).
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    return ((y - a[1]) * dx - (x - a[0]) * dy) / Math.hypot(dx, dy);
  };
  return Math.min(side(top, right), side(right, left), side(left, top));
}

/** The mark: an amber triangle with a near-black edge, and a near-black "!" in the middle. */
export function routeHazardIcon(pixelRatio = 2, cssSize = ROUTE_HAZARD_ICON_PX): Raster {
  const size = Math.round(cssSize * pixelRatio);
  const edge = 1.5 * pixelRatio;
  const fill: Rgb = hexToRgb(ROUTE_HAZARD_FILL);
  const dark: Rgb = hexToRgb(ROUTE_HAZARD_EDGE);
  const c = size / 2;
  const bar = 0.055 * size;
  return rasterise(size, pixelRatio, (x, y): Rgb | null => {
    const depth = triangleDepth(x, y, size);
    if (depth < 0) return null;
    if (depth < edge) return dark;
    // The "!": a bar, a gap and a dot.
    if (Math.abs(x - c) <= bar && y >= 0.42 * size && y <= 0.68 * size) return dark;
    if (Math.hypot(x - c, y - 0.8 * size) <= bar * 1.2) return dark;
    return fill;
  });
}

/** The marks' layer, over the route line: placed along each stretch, at its middle where it is short. */
export function routeHazardLayer(): Record<string, unknown> {
  return {
    id: ROUTE_HAZARD_LAYER,
    type: "symbol",
    source: ROUTE_HAZARD_SOURCE,
    layout: {
      "symbol-placement": "line-center",
      "icon-image": ROUTE_HAZARD_ICON,
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
      "icon-rotation-alignment": "viewport",
    },
  };
}

/** A second placement for a long stretch: repeated every ROUTE_HAZARD_SPACING_PX. */
export function routeHazardRepeatLayer(): Record<string, unknown> {
  return {
    id: `${ROUTE_HAZARD_LAYER}-along`,
    type: "symbol",
    source: ROUTE_HAZARD_SOURCE,
    minzoom: 14,
    layout: {
      "symbol-placement": "line",
      "symbol-spacing": ROUTE_HAZARD_SPACING_PX,
      "icon-image": ROUTE_HAZARD_ICON,
      "icon-allow-overlap": false,
      "icon-rotation-alignment": "viewport",
    },
  };
}

export const ROUTE_HAZARD_LAYERS = [ROUTE_HAZARD_LAYER, `${ROUTE_HAZARD_LAYER}-along`] as const;

/**
 * Each hazard stretch as a line cut from the route's own geometry, at its metres along the traced route scaled to
 * the line as drawn (as routeColours.ts cuts the stress sections). Empty with no hazards or no line.
 */
export function routeHazardFeatures(route: (Pick<RouteResponse, "geometry" | "distance_m"> & Partial<Pick<RouteResponse, "road_hazards" | "stress_spans">>) | null) {
  const features: { type: "Feature"; properties: { kinds: string; road: string }; geometry: { type: "LineString"; coordinates: LonLat[] } }[] = [];
  const found = route?.road_hazards ?? [];
  const coordinates = (route?.geometry.coordinates ?? []) as LonLat[];
  if (!route || found.length === 0 || coordinates.length < 2) return { type: "FeatureCollection" as const, features };
  const along = [0];
  for (let i = 1; i < coordinates.length; i += 1) along.push(along[i - 1] + haversineM(coordinates[i - 1], coordinates[i]));
  const drawn = along[along.length - 1];
  const traced = route.stress_spans?.length ? route.stress_spans[route.stress_spans.length - 1].to_m : route.distance_m;
  if (!(drawn > 0) || !(traced > 0)) return { type: "FeatureCollection" as const, features };
  const scale = drawn / traced;
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
    const from = Math.max(0, span.from_m * scale);
    const to = Math.min(drawn, Math.max(span.to_m * scale, from + 1));
    const line: LonLat[] = [at(from)];
    for (let i = 0; i < coordinates.length; i += 1) if (along[i] > from && along[i] < to) line.push(coordinates[i]);
    line.push(at(to));
    features.push({ type: "Feature", properties: { kinds: span.kinds.join(","), road: span.road }, geometry: { type: "LineString", coordinates: line } });
  }
  return { type: "FeatureCollection" as const, features };
}

const SHORT: Record<RoadHazardSpan["kinds"][number], string> = { cobbles: "cobblestones", rails: "rails in the road" };

/** Said with the route (a polite announcement): "This route rides 2 known hazards: rails in the road on H Street ...". */
export function roadHazardsSaid(route: Partial<Pick<RouteResponse, "road_hazards">>): string | null {
  const found = route.road_hazards ?? [];
  if (found.length === 0) return null;
  const n = found.length;
  const names = found.map((s) => `${s.kinds.map((k) => SHORT[k]).join(" and ")} on ${s.road}`).join(", ");
  return `This route rides ${n} known ${n === 1 ? "hazard" : "hazards"}: ${names}. The directions list ${n === 1 ? "it" : "them"}.`;
}

export const ROUTE_HAZARD_KEY_TEXT =
  "On a route, amber triangles mark cobblestones or rails in the road. From the next map update, routes avoid them where they can and the directions name each.";

/** The key's one entry, in the Traffic stress section of Layers: the mark, and the words. */
export function RouteHazardKey(): ReactElement {
  const s = 16;
  return h(
    "ul",
    { className: "legend route-hazard-key", "aria-label": "Route hazards key" },
    h(
      "li",
      { key: "hazard" },
      h(
        "svg",
        { width: s, height: s, viewBox: `0 0 ${s} ${s}`, "aria-hidden": "true", className: "route-hazard-swatch" },
        h("polygon", { points: `${s / 2},1 ${s - 1},${s - 1} 1,${s - 1}`, fill: ROUTE_HAZARD_FILL, stroke: ROUTE_HAZARD_EDGE, strokeWidth: 1.5, strokeLinejoin: "round" }),
        h("rect", { x: s / 2 - 0.9, y: 6, width: 1.8, height: 4.5, fill: ROUTE_HAZARD_EDGE }),
        h("circle", { cx: s / 2, cy: 12.4, r: 1, fill: ROUTE_HAZARD_EDGE }),
      ),
      h("span", { className: "stress-label" }, ROUTE_HAZARD_KEY_TEXT),
    ),
  );
}
