/**
 * The known road hazards a route rides (v0.10.0; core/route_hazards.py). The owner, 2026-10-19: "We should have a
 * symbol for roads with known other hazards on the map. One example is the cobblestones in Georgetown or the
 * streetcar rails on H street", then "Roads with hazards like this should get a major penalty. You only need to show
 * it if it's routed on".
 *
 * So the route network prices them as LTS 4 (lua/routemaker_remap.lua) and only a route that still rides one shows
 * it: a small dark disc with an amber "!" repeated along the stretch, over the route line, never on the rest of the map.
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
/**
 * A near-black disc, an amber "!" and a white rim (the owner, 2026-10-20: "the on a route marker looks identical to a
 * higher stress intersection"). Not a triangle or a diamond, the junction markers' shapes, and dark where they are
 * light: told apart by shape and by lightness, not by hue alone. The "!" 10.7:1 on the disc; the rim parts it
 * from the route line and a dark map.
 */
export const ROUTE_HAZARD_FILL = "#111827";
export const ROUTE_HAZARD_MARK = "#fbbf24";
export const ROUTE_HAZARD_EDGE = "#ffffff";
/** Pixels between two marks along the stretch, and a mark at the middle of one too short for two. */
export const ROUTE_HAZARD_SPACING_PX = 90;

/** The mark: a near-black disc with a white rim, and an amber "!" in the middle. */
export function routeHazardIcon(pixelRatio = 2, cssSize = ROUTE_HAZARD_ICON_PX): Raster {
  const size = Math.round(cssSize * pixelRatio);
  const rim = 1.5 * pixelRatio;
  const fill: Rgb = hexToRgb(ROUTE_HAZARD_FILL);
  const mark: Rgb = hexToRgb(ROUTE_HAZARD_MARK);
  const edge: Rgb = hexToRgb(ROUTE_HAZARD_EDGE);
  const c = size / 2;
  const bar = 0.06 * size;
  return rasterise(size, pixelRatio, (x, y): Rgb | null => {
    const r = Math.hypot(x - c, y - c);
    if (r > c - 0.5) return null;
    if (r > c - 0.5 - rim) return edge;
    // The "!": a bar, a gap and a dot.
    if (Math.abs(x - c) <= bar && y >= 0.24 * size && y <= 0.6 * size) return mark;
    if (Math.hypot(x - c, y - 0.74 * size) <= bar * 1.25) return mark;
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

/** The key's name for the mark, its shape in a hint as the junctions' key says theirs ("Higher stress (triangle)"). */
export const ROUTE_HAZARD_KEY_NAME = "Road hazard";
export const ROUTE_HAZARD_KEY_SHAPE = "dark circle";
export const ROUTE_HAZARD_KEY_TEXT =
  "Cobblestones or rails in the road, marked on a route only. Routes avoid them where they can and the directions name each.";

/** The mark as a small inline picture: the key's swatch and the directions' symbol. Seen, not heard. */
export function RouteHazardSwatch({ size = 16 }: { size?: number }): ReactElement {
  const c = size / 2;
  return h(
    "svg",
    { width: size, height: size, viewBox: `0 0 ${size} ${size}`, "aria-hidden": "true", focusable: "false", className: "route-hazard-swatch" },
    h("circle", { cx: c, cy: c, r: c - 0.75, fill: ROUTE_HAZARD_FILL, stroke: ROUTE_HAZARD_EDGE, strokeWidth: 1.5 }),
    h("rect", { x: c - 0.06 * size, y: 0.24 * size, width: 0.12 * size, height: 0.36 * size, fill: ROUTE_HAZARD_MARK }),
    h("circle", { cx: c, cy: 0.74 * size, r: 0.075 * size, fill: ROUTE_HAZARD_MARK }),
  );
}

/**
 * The key's one entry, in the Traffic stress section of Layers, laid out as the Junctions key under it: the mark,
 * then its name and words with the row's whole width (the owner, 2026-10-20: the text "has very short margins",
 * squeezed into the stress key's 52 px figure column).
 */
export function RouteHazardKey(): ReactElement {
  return h(
    "ul",
    { className: "route-hazard-key", "aria-label": "Route hazards key" },
    h(
      "li",
      { key: "hazard" },
      h(RouteHazardSwatch, { size: 20 }),
      h(
        "span",
        null,
        h("span", { className: "route-hazard-name" }, ROUTE_HAZARD_KEY_NAME),
        h("span", { className: "hint" }, ` (${ROUTE_HAZARD_KEY_SHAPE}): `),
        ROUTE_HAZARD_KEY_TEXT,
      ),
    ),
  );
}
