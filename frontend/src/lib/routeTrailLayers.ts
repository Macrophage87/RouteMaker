/**
 * The route line on mountain-bike trails (Stephen 2026-11-07, of the ride ribbon's trail colours and rocks: "Put that on
 * the main track too", "and map, makes it easy to tell you're on a mtb trail"): over the route's stress colours, each
 * trail stretch (`trail_levels`) in its trail's colour (its level's, or the unrated trails' brown; lib/aheadGraph.ts
 * trailLevelColor), with brown stones along both edges (lib/trailRocks.ts). Plan and Ride both draw it.
 */
import type { RouteResponse } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { trailLevelColor, trailsBesideAvoid } from "./aheadGraph.ts";
import { ROUTE_LINE_WIDTH } from "./routeColours.ts";
import { TRAIL_ROCK } from "./trailRocks.ts";

export const ROUTE_TRAIL_SOURCE = "route-trails";
export const ROUTE_TRAIL_LAYER = "route-trail";
export const ROUTE_TRAIL_ROCK_EDGE_LAYER = "route-trail-rocks-edge";
export const ROUTE_TRAIL_ROCK_LAYER = "route-trail-rocks";
export const ROUTE_TRAIL_LAYER_IDS = [ROUTE_TRAIL_ROCK_EDGE_LAYER, ROUTE_TRAIL_ROCK_LAYER, ROUTE_TRAIL_LAYER] as const;
/** The stones: each this wide (pixels), on each side of the line, this far apart along it. */
export const ROCK_PX = 3;
export const ROCK_EDGE_PX = 4.5;
export const ROCK_SPACING_PX = 7.2;

type TrailFeature = { type: "Feature"; properties: { level: number; color: string }; geometry: { type: "LineString"; coordinates: LonLat[] } };

/** Each trail stretch as a line along the route, its traced metres scaled to the drawn line (as lib/routeHazards.ts). */
export function routeTrailFeatures(
  route: (Pick<RouteResponse, "geometry" | "distance_m"> & Partial<Pick<RouteResponse, "trail_levels" | "stress_spans">>) | null,
) {
  const features: TrailFeature[] = [];
  const found = route?.trail_levels ?? [];
  const coordinates = (route?.geometry.coordinates ?? []) as LonLat[];
  if (!route || found.length === 0 || coordinates.length < 2) return { type: "FeatureCollection" as const, features };
  const along = [0];
  for (let i = 1; i < coordinates.length; i += 1) along.push(along[i - 1]! + haversineM(coordinates[i - 1]!, coordinates[i]!));
  const drawn = along[along.length - 1]!;
  const traced = route.stress_spans?.length ? route.stress_spans[route.stress_spans.length - 1]!.to_m : route.distance_m;
  if (!(drawn > 0) || !(traced > 0)) return { type: "FeatureCollection" as const, features };
  const scale = drawn / traced;
  const at = (m: number): LonLat => {
    let k = 0;
    while (k < along.length - 2 && along[k + 1]! < m) k += 1;
    const piece = along[k + 1]! - along[k]!;
    const f = piece > 0 ? Math.min(1, Math.max(0, (m - along[k]!) / piece)) : 0;
    const a = coordinates[k]!;
    const b = coordinates[k + 1]!;
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
  };
  for (const span of trailsBesideAvoid(found, route.stress_spans)) {
    const color = trailLevelColor(span.level);
    if (!color) continue;
    const from = Math.max(0, span.from_m * scale);
    const to = Math.min(drawn, Math.max(span.to_m * scale, from + 1));
    const line: LonLat[] = [at(from)];
    for (let i = 0; i < coordinates.length; i += 1) if (along[i]! > from && along[i]! < to) line.push(coordinates[i]!);
    line.push(at(to));
    features.push({ type: "Feature", properties: { level: span.level, color }, geometry: { type: "LineString", coordinates: line } });
  }
  return { type: "FeatureCollection" as const, features };
}

/**
 * The layers, bottom to top: each stone's dark rim, the stones (round dots either side of the line, line-gap-width the
 * route's width), and the trail's colour over the route's own. Dots of one spacing: each layer's dash is in its own width.
 */
export function routeTrailLayers(): Record<string, unknown>[] {
  const stones = (id: string, color: string, width: number) => ({
    id,
    type: "line",
    source: ROUTE_TRAIL_SOURCE,
    layout: { "line-join": "round", "line-cap": "round" },
    paint: { "line-color": color, "line-width": width, "line-gap-width": ROUTE_LINE_WIDTH, "line-dasharray": [0, ROCK_SPACING_PX / width] },
  });
  return [
    stones(ROUTE_TRAIL_ROCK_EDGE_LAYER, TRAIL_ROCK.edge, ROCK_EDGE_PX),
    stones(ROUTE_TRAIL_ROCK_LAYER, TRAIL_ROCK.fill, ROCK_PX),
    {
      id: ROUTE_TRAIL_LAYER,
      type: "line",
      source: ROUTE_TRAIL_SOURCE,
      layout: { "line-join": "round", "line-cap": "butt" },
      paint: { "line-color": ["get", "color"], "line-width": ROUTE_LINE_WIDTH },
    },
  ];
}
