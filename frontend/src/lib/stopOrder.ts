/**
 * Stops in any order (OWNER-DECISIONS 449): "Best order" puts the stops in the
 * order that rides best. The API (POST /api/stop-order, core.stoporder) gets the
 * ride as a route request would send it and answers the new order; the page then
 * reorders its points as one edit, which Undo takes back, and the route is asked
 * for as after any edit. "Best" is what any route is best by (the owner, 2026-10-10):
 * the router's cost, riding time with the ride's stress and hills priced in. The start stays first and the end last; in a loop the
 * rider chose (OWNER-DECISIONS 374) every point after the start is a stop and
 * may move. What changed is said in words, stop by stop.
 */
import { describeError } from "./api.ts";
import { dialFields, type Dials } from "./dials.ts";
import { formatDistance, formatDuration } from "./format.ts";
import { coordinatesText } from "./geocode.ts";
import type { LonLat } from "./geo.ts";
import { reverseKeepsStart } from "./loop.ts";
import type { PresetId } from "./presets.ts";
import { pointName } from "./summary.ts";

export const BEST_ORDER_LABEL = "Best order";

/** What the API answers (core.api.StopOrderOut). */
export interface StopOrder {
  order: number[];
  changed: boolean;
  by: "route_cost" | "riding_time" | "straight_line" | null;
  exact: boolean;
  before_s: number | null;
  after_s: number | null;
  before_m: number | null;
  after_m: number | null;
}

export type StopOrderResult = { ok: true; answer: StopOrder } | { ok: false; message: string };

/**
 * Whether the last point is a stop that may move: in a loop the rider chose, unless the ride
 * already ends on its start. The same test as Reverse keeping the start (loop.ts).
 */
const lastMoves = reverseKeepsStart;

/** How many points Best order may move: those between the start and the end, or every one after a loop's start. */
export function stopsThatMove(points: readonly LonLat[], loop: boolean): number {
  return Math.max(0, points.length - (lastMoves(points, loop) ? 1 : 2));
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

/** Ask the API for the best order; not for a Mass Ride (the page has no button there). The weight is not sent. */
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
        // The order does not use the weight, so it is not sent (OWNER-DECISIONS 264's privacy:
        // the weight leaves the device only for the plan that uses it).
        ...dialFields({ ...dials, systemWeightKg: undefined }),
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
  // Whether every part is a cost to the rider (more riding, longer): then the calmer roads are a "but".
  let allCosts = true;
  const { before_s, after_s, before_m, after_m } = answer;
  const timed = answer.by !== "straight_line" && before_s !== null && after_s !== null;
  if (timed && before_s > after_s) {
    parts.push(`about ${formatDuration(before_s - after_s)} less riding`);
    allCosts = false;
  } else if (timed && answer.by === "route_cost" && after_s > before_s) {
    parts.push(`about ${formatDuration(after_s - before_s)} more riding`);
  }
  if (before_m !== null && after_m !== null && before_m !== after_m) {
    const diff = formatDistance(Math.abs(before_m - after_m));
    const way = after_m < before_m ? "shorter" : "longer";
    if (after_m < before_m) allCosts = false;
    parts.push(answer.by === "straight_line" ? `${diff} ${way} in straight lines` : `${diff} ${way}`);
  }
  // By the router's cost, an order no quicker is chosen for its calmer or flatter ways.
  const calmer = answer.by === "route_cost" && !(timed && before_s > after_s);
  if (parts.length === 0) return calmer ? " The new order is on calmer or flatter roads." : "";
  const reason = allCosts ? ", but on calmer or flatter roads" : ", on calmer or flatter roads";
  const text = calmer ? `${parts.join(" and ")}${reason}` : parts.join(", ");
  return ` ${text[0].toUpperCase()}${text.slice(1)}.`;
}

const STRAIGHT_LINE_NOTE = " The router's riding times were not available, so this is by straight-line distance.";
/** Up to this many stops the server orders by the router's cost (core.stoporder.COST_MAX_STOPS). */
export const COST_MAX_STOPS = 10;

function ridingTimeNote(points: readonly LonLat[], loop: boolean): string {
  return stopsThatMove(points, loop) > COST_MAX_STOPS
    ? ` With more than ${COST_MAX_STOPS} stops, this is by riding time alone, without traffic stress and hills.`
    : " The router could not weigh traffic stress and hills for these stops, so this is by riding time alone.";
}

/**
 * What is said after Best order: each stop that moved, in its new place, by name, with the
 * number it had; how many stayed; what it saves; and that Undo puts it back.
 * `points` are the points as they were before the reorder.
 */
export function bestOrderSaid(points: readonly LonLat[], answer: StopOrder, names: Names, loop: boolean): string {
  const note =
    answer.by === "straight_line" ? STRAIGHT_LINE_NOTE : answer.by === "riding_time" ? ridingTimeNote(points, loop) : "";
  if (!answer.changed) return `The stops are already in the best order.${note}`;
  const n = points.length;
  const last = lastMoves(points, loop) ? n : n - 1;
  const moved: string[] = [];
  let stayed = 0;
  for (let at = 1; at < last; at++) {
    const was = answer.order[at];
    if (was === at) {
      stayed += 1;
      continue;
    }
    moved.push(`${pointName(at, n, loop)} is now ${placeOf(points[was], names)} (was ${pointName(was, n, loop)})`);
  }
  const rest = stayed === 0 ? "" : stayed === 1 ? " The other stop stays where it was." : ` The other ${stayed} stops stay where they were.`;
  return `Stops put in the best order: ${moved.join(", ")}.${rest}${savings(answer)}${note} Undo puts the old order back.`;
}

/** The ride a press asked about, and the ride when the answer came. */
export interface OrderAsked {
  points: readonly LonLat[];
  preset: PresetId;
  dials: Dials;
  loop: boolean;
}

/**
 * What to do with an answer: the points to commit (a new order only), and what to say.
 * It is used only for the ride it was asked about: the same points, ride type and dials
 * (the costing it was chosen under), and only if it fits them.
 */
export function applyAnswer(
  asked: OrderAsked,
  now: { points: readonly LonLat[]; preset: PresetId; dials: Dials },
  result: StopOrderResult,
  names: Names,
): { commit?: LonLat[]; say: string } {
  if (now.points !== asked.points || now.preset !== asked.preset || now.dials !== asked.dials) {
    return { say: "The ride changed while the best order was being found. Press Best order again." };
  }
  if (!result.ok) return { say: result.message };
  if (!fitsOrder(result.answer.order, asked.points, asked.loop)) {
    return { say: "Best order not found. The planner's answer did not fit these points; try again." };
  }
  const say = bestOrderSaid(asked.points, result.answer, names, asked.loop);
  return result.answer.changed ? { commit: reorderedPoints(asked.points, result.answer.order), say } : { say };
}

export const FINDING_ORDER_SAID = "Finding the best order for the stops.";
export const STILL_FINDING_ORDER_SAID = "Still finding the best order.";
