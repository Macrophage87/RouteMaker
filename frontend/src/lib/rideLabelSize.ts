/**
 * THE RIDE MAP'S OTHER LABELS, LARGER. In a ride the street, trail and route names go up to ROAD_LABEL.rideSize (20 px,
 * MapView's rideLabels effect). The map's smaller labels go up by the same share (the accessibility review,
 * 2026-10-29): the steep-grade marks' grades, a safety cue on Mass and Novice rides (13 to 17 px), the trail mile
 * markers (13 to 17 px), the mountain-bike trail names (15 to 20 px) and the climbs' category numbers (9-11 to 12-15
 * px). After the ride each goes back to its own size.
 */
import { MTB_LABEL_LAYER_ID, ROAD_LABEL } from "../stressStyle.js";
import { STEEP_GRADE_LAYER } from "./steepGrades.ts";
import { MILES_LABEL_LAYER } from "./trailMiles.ts";
import { CLIMBS_MARKER_LAYER } from "./climbs.ts";

/** How much larger in a ride: the street names' share (20 / 15). */
export const RIDE_LABEL_SCALE = ROAD_LABEL.rideSize / ROAD_LABEL.size;

/** The layers whose text goes up by RIDE_LABEL_SCALE in a ride. */
export const RIDE_SCALED_LABEL_LAYERS: readonly string[] = [STEEP_GRADE_LAYER, MILES_LABEL_LAYER, MTB_LABEL_LAYER_ID, CLIMBS_MARKER_LAYER];

/**
 * A layer's `text-size` times `k`, to the whole pixel: a number, or a zoom curve ("interpolate" or "step"), whose
 * sizes are scaled and stops kept (MapLibre takes a zoom curve only at the top, so it cannot be wrapped in a "*").
 * Anything else is left as it is.
 */
export function scaledTextSize(size: unknown, k: number): unknown {
  if (typeof size === "number") return Math.round(size * k);
  if (!Array.isArray(size)) return size;
  const scale = (v: unknown) => (typeof v === "number" ? Math.round(v * k) : v);
  // ["interpolate", type, input, stop, size, stop, size, ...]: the sizes from index 4, every other one.
  if (size[0] === "interpolate") return size.map((v, i) => (i >= 4 && i % 2 === 0 ? scale(v) : v));
  // ["step", input, size, stop, size, ...]: the sizes at index 2, 4, ...
  if (size[0] === "step") return size.map((v, i) => (i >= 2 && i % 2 === 0 ? scale(v) : v));
  return size;
}
