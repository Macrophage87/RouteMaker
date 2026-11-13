/**
 * Sudden closures ahead in a ride (Stephen 2026-11-12, of a shooting's road closures at Logan Circle: "Police activity
 * closures should generally be treated like tornadoes or similar. If the route takes you onto one, pop up a notice and
 * offer a reroute"; "Any other closures like crashes too would be offered a reroute if nearby"; "If it's more than 10
 * miles away, perhaps less strong of a warning").
 *
 * Each minute (WATCH_MS, our default) the ride asks whether the closures in force changed (GET /api/closures/stamp, a
 * few bytes); only when they did is the line still to ride checked (POST /api/closures/check). A closure on it within
 * NEAR_M (10 mi, along the route) is said urgently and asked about: Reroute around it, or Keep going. One further
 * than that is said once, quietly, and asked about once the rider comes within NEAR_M, if it is still in force. The
 * closures already on the route when the ride started were asked about by Start ride's own check, so they are not
 * asked again.
 */
import type { Closure } from "./closureCheck.ts";
import { METRES_PER_MILE } from "./format.ts";
import { t } from "./i18n.ts";

/** How often a ride asks whether the closures changed (our default, 2026-11-12, unmeasured). */
export const WATCH_MS = 60_000;
/** Within this along the route, a closure is asked about; past it, said quietly (Stephen: 10 miles). */
export const NEAR_M = 10 * METRES_PER_MILE;

export const CLOSED_AHEAD = t("Road closed ahead");
export const KEEP_GOING = t("Keep going");
export const REROUTE_AROUND_IT = t("Reroute around it");

/** "Road closed ahead, 2.1 mi: Police activity: streets closed near 15th St & P St NW". */
export function closedAheadSaid(distance: string, name: string): string {
  return t("Road closed ahead, {distance}: {name}", { distance, name });
}

/** A closure on the line still to ride, placed on the ride's own line: metres along it where it starts and ends. */
export interface Watched {
  id: string;
  name: string;
  atM: number;
  toM: number;
}

/** What the ride has said of each closure: said quietly, or asked about (or known since the start). */
export interface WatchState {
  seeded: boolean;
  quiet: Set<string>;
  asked: Set<string>;
}

export function newWatchState(): WatchState {
  return { seeded: false, quiet: new Set(), asked: new Set() };
}

/**
 * The closures of an answer for the line from `fromM` along the ride's line, placed on it. Only real closures: one that
 * "may still apply" (no end given, on a later ride) is never in a ride's answer, and is left out all the same.
 */
export function watchedOf(closures: readonly Closure[], fromM: number): Watched[] {
  return closures
    .filter((c) => (c.kind === "closed" || c.kind === "unknown") && !c.may_still_apply)
    .map((c) => ({ id: c.id, name: c.title || c.road || CLOSED_AHEAD, atM: fromM + c.from_m, toM: fromM + c.to_m }));
}

export type WatchStep = { kind: "ask" | "note"; closure: Watched; aheadM: number };

/**
 * What to say now, at `progressM` along the line: a quiet note for each closure newly seen past NEAR_M, and at most one
 * ask, the nearest closure within NEAR_M not yet asked about (the next waits for the next step). The first answer of a
 * ride only marks what is already on its route as known. Closures behind the rider are left alone.
 */
export function watchStep(state: WatchState, closures: readonly Watched[], progressM: number): WatchStep[] {
  if (!state.seeded) {
    state.seeded = true;
    for (const c of closures) state.asked.add(c.id);
    return [];
  }
  const out: WatchStep[] = [];
  let ask: WatchStep | null = null;
  for (const closure of closures) {
    if (closure.toM <= progressM || state.asked.has(closure.id)) continue;
    const aheadM = Math.max(0, closure.atM - progressM);
    if (aheadM <= NEAR_M) {
      if (!ask || aheadM < ask.aheadM) ask = { kind: "ask", closure, aheadM };
    } else if (!state.quiet.has(closure.id)) {
      state.quiet.add(closure.id);
      out.push({ kind: "note", closure, aheadM });
    }
  }
  if (ask) {
    state.asked.add(ask.closure.id);
    out.push(ask);
  }
  return out;
}

/** The vertex to send the line from: the last at or before `progressM` (the ride's line's `along`). */
export function lineFromIndex(along: ArrayLike<number>, progressM: number): number {
  let lo = 0;
  let hi = along.length - 1;
  if (hi < 0) return 0;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (along[mid] <= progressM) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

/** GET /api/closures/stamp: the closures' fingerprint, or null where it could not be asked. */
export async function closuresStamp(origin: string, get: typeof fetch = fetch, timeoutMs = 5000): Promise<string | null> {
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), timeoutMs);
  try {
    const response = await get(`${origin}/api/closures/stamp`, { headers: { Accept: "application/json" }, signal: stop.signal });
    if (!response.ok) return null;
    const body = (await response.json()) as { stamp?: unknown };
    return typeof body.stamp === "string" ? body.stamp : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
