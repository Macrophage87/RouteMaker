/**
 * Stops in any order (OWNER-DECISIONS 449): "Best order" puts the stops in the
 * order that rides least. The API (POST /api/stop-order, core.stoporder) gets the
 * ride as a route request would send it and answers the new order; the page then
 * reorders its points as one edit, which Undo takes back, and the route is asked
 * for as after any edit. The start stays first and the end last; in a loop the
 * rider chose (OWNER-DECISIONS 374) every point after the start is a stop and
 * may move. What changed is said in words, stop by stop.
 */
import { describeError } from "./api.ts";
import { dialFields, type Dials } from "./dials.ts";
import { formatDistance, formatDuration } from "./format.ts";
import { coordinatesText } from "./geocode.ts";
import type { LonLat } from "./geo.ts";
import { isRoundTrip } from "./loop.ts";
import type { PresetId } from "./presets.ts";
import { pointName } from "./summary.ts";

export const BEST_ORDER_LABEL = "Best order";

/** What the API answers (core.api.StopOrderOut). */
export interface StopOrder {
  order: number[];
  changed: boolean;
  by: "riding_time" | "straight_line" | null;
  exact: boolean;
  before_s: number | null;
  after_s: number | null;
  before_m: number | null;
  after_m: number | null;
}

export type StopOrderResult = { ok: true; answer: StopOrder } | { ok: false; message: string };

/** Whether the last point is a stop that may move: in a loop the rider chose, unless the ride already ends on its start. */
function lastMoves(points: readonly LonLat[], loop: boolean): boolean {
  return loop && !isRoundTrip(points);
}

/** How many points Best order may move: those between the start and the end, or every one after a loop's start. */
export function stopsThatMove(points: readonly LonLat[], loop: boolean): number {
  return Math.max(0, points.length - (lastMoves(points, loop) ? 1 : 2));
}

/** Why Best order cannot help yet, when there is a ride but fewer than two stops to order; null otherwise. */
export function bestOrderUnavailableHint(points: readonly LonLat[], loop: boolean): string | null {
  if (points.length < 2 || stopsThatMove(points, loop) >= 2) return null;
  return loop
    ? "Best order needs at least two stops in the loop. Add another stop to use it."
    : "Best order needs at least two stops between the start and the end. Add another stop to use it.";
}

/** Whether an answer fits these points: every point once, the start first, and the end last unless it is a stop. */
export function fitsOrder(order: readonly number[], points: readonly LonLat[], loop: boolean): boolean {
  const n = points.length;
  if (order.length !== n || order[0] !== 0) return false;
  if (!lastMoves(points, loop) && order[n - 1] !== n - 1) return false;
  const seen = new Set(order);
  return seen.size === n && order.every((i) => Number.isInteger(i) && i >= 0 && i < n);
}

export function reorderedPoints(points: readonly LonLat[], order: readonly number[]): LonLat[] {
  return order.map((i) => points[i]);
}

function looksLikeOrder(value: unknown): value is StopOrder {
  if (!value || typeof value !== "object") return false;
  const v = value as Partial<StopOrder>;
  return Array.isArray(v.order) && typeof v.changed === "boolean";
}

type FetchLike = (url: string, init: RequestInit) => Promise<Response>;

/** Ask the API for the best order. A Mass Ride has no loop, so its flag is not sent, as for a route. */
export async function requestStopOrder(
  points: readonly LonLat[],
  preset: PresetId,
  dials: Dials,
  fetchImpl: FetchLike = (url, init) => fetch(url, init),
): Promise<StopOrderResult> {
  let response: Response;
  try {
    response = await fetchImpl("/api/stop-order", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        points,
        preset,
        ...dialFields(preset === "mass-ride" ? { ...dials, loop: false } : dials),
      }),
    });
  } catch {
    return { ok: false, message: "Best order did not get through. Check your connection and try again." };
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (response.ok && looksLikeOrder(body)) return { ok: true, answer: body };
  const error = describeError(response.ok ? 500 : response.status, body, response.headers.get("Retry-After"));
  return { ok: false, message: `Best order not found. ${error.message}` };
}

/** How a point is said: its place name, or its coordinates. */
type Names = { name: (point: LonLat) => { name: string } | undefined };

function placeOf(point: LonLat, names: Names): string {
  return names.name(point)?.name ?? `the point at ${coordinatesText(point)}`;
}

function savings(answer: StopOrder): string {
  const parts: string[] = [];
  const { before_s, after_s, before_m, after_m } = answer;
  if (answer.by === "riding_time" && before_s !== null && after_s !== null && before_s > after_s) {
    parts.push(`about ${formatDuration(before_s - after_s)} less riding`);
  }
  if (before_m !== null && after_m !== null && before_m !== after_m) {
    const diff = formatDistance(Math.abs(before_m - after_m));
    const way = after_m < before_m ? "shorter" : "longer";
    parts.push(answer.by === "straight_line" ? `${diff} ${way} in straight lines` : `${diff} ${way}`);
  }
  if (parts.length === 0) return "";
  const text = parts.join(", ");
  return ` ${text[0].toUpperCase()}${text.slice(1)}.`;
}

const STRAIGHT_LINE_NOTE = " The router's riding times were not available, so this is by straight-line distance.";

/**
 * What is said after Best order: each stop in its new place, by name, with the
 * number it had where that changed; what it saves; and that Undo puts it back.
 * `points` are the points as they were before the reorder.
 */
export function bestOrderSaid(points: readonly LonLat[], answer: StopOrder, names: Names, loop: boolean): string {
  const note = answer.by === "straight_line" ? STRAIGHT_LINE_NOTE : "";
  if (!answer.changed) return `The stops are already in the best order.${note}`;
  const n = points.length;
  const last = lastMoves(points, loop) ? n : n - 1;
  const stops: string[] = [];
  for (let at = 1; at < last; at++) {
    const was = answer.order[at];
    const place = placeOf(points[was], names);
    const now = pointName(at, n, loop);
    stops.push(was === at ? `${now} stays ${place}` : `${now} is now ${place} (was ${pointName(was, n, loop)})`);
  }
  return `Stops put in the best order: ${stops.join(", ")}.${savings(answer)}${note} Undo puts the old order back.`;
}
