/**
 * Ride mode's dock button on a share bike (the owner, 2026-10-17: "On bikeshare add a special detour separate
 * from the rest to go to the nearest dock. Put on that button the rough time that a person is undocked because
 * there's a fine if you go over. Count up because it varies by subscription.").
 *
 * - The time: counted up from the undock, which the ride takes as the moment the rider reaches the first dock
 *   (or the ride's start, where the plan has no walk to it). Docked again (the owner: "Restart the docked timer
 *   if they dock"): stopped within DOCKED_M of a dock, the button says Docked, and the time starts again from 0
 *   as the rider leaves that dock. At the dock the rider chose with this button, CHOSEN_STILL_MS stopped is
 *   enough; at any other, DOCK_STILL_MS, longer than a red light on a corner with a dock (the review). "Restart the time" in its menu does it by
 *   hand. Rough: the app cannot see the dock's own clock, so it says "about".
 * - Two ways (the owner: "give options for closest or shortest detour"): the closest dock by bike, or the one
 *   that adds least to the ride. The Capital Bikeshare docks near the rider with room to dock (GET
 *   /api/bikeshare/docks, the map's own source), the likeliest few in straight lines measured by bike (POST
 *   /api/nearest), and the pick becomes a detour stop: the ride goes there and then on, as the water and
 *   restroom detours do.
 *
 * Plain data in, plain data out, so node --test runs all of it.
 */
import { docksPath, loadDocks, type DockInfo, type DocksAnswer } from "./bikeshareDocks.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { formatDistance } from "./format.ts";
import { NEAREST_CANDIDATES, howFar, nearestInStraightLine, rankNearest, type Nearby, type NearestAnswer, type NearestPlace, type NearestResult } from "./nearest.ts";
import { t } from "./i18n.ts";

/** The button's name, heard before the time. */
export const DOCK_NAME = t("Ride to the nearest dock");
export const dockFinding = (way: "closest" | "detour"): string =>
  way === "closest" ? "Finding the closest dock with room." : "Finding the dock with room that adds least to the ride.";
export const DOCK_NONE = t("No Capital Bikeshare dock with room was found nearby.");
export const DOCK_UNAVAILABLE = t("Bikeshare docks are unavailable for now; try again shortly.");
/** Stopped this long within DOCKED_M of a dock (moving under DOCK_STILL_M): taken as docked. */
export const DOCK_STILL_MS = 150_000;
export const CHOSEN_STILL_MS = 20_000;
/** A dock this near the ride's end is not a detour (the shortest detour would otherwise be the end itself). */
export const NOT_THE_END_M = 400;
export const DOCK_STILL_M = 15;
export const DOCKED_M = 30;
/** Docked, then this far from the dock: a bike taken again, so the time starts from 0. */
export const LEFT_DOCK_M = 50;
export const DOCKED_SHOWN = "Docked";
export const RESTART_TIME = t("Restart the time");
export const TIME_RESTARTED = t("Undocked time restarted.");
export const dockedSaid = (name: string): string => `Docked at ${name}? The undocked time starts again when you ride off.`;

/** Where the rider has stood still, since when, and whether the docks there have been looked at. */
export interface Still {
  point: LonLat;
  since: number;
  checked: boolean;
}

/** One fix into the stillness: the same place (within DOCK_STILL_M) keeps it; moving starts afresh. */
export function stillStep(s: Still | null, point: LonLat, at: number): Still {
  if (s && haversineM(s.point, point) <= DOCK_STILL_M) return s;
  return { point, since: at, checked: false };
}

/** Still long enough (DOCK_STILL_MS, or `ms`), not yet looked at: time to ask whether this is a dock. */
export function stillAtLength(s: Still, at: number, ms = DOCK_STILL_MS): boolean {
  return !s.checked && at - s.since >= ms;
}

/** The open dock within DOCKED_M of `point`, nearest first; null if none. */
export function dockAt(point: LonLat, docks: readonly DockInfo[]): DockInfo | null {
  let best: DockInfo | null = null;
  let bestM = DOCKED_M;
  for (const d of docks) {
    if (d.closed) continue;
    const m = haversineM(point, [d.lon, d.lat]);
    if (m <= bestM) {
      best = d;
      bestM = m;
    }
  }
  return best;
}

/** The docks right around a point (a small box), for dockAt. */
export async function docksAround(point: LonLat, docks: (path: string) => Promise<DocksAnswer | null>): Promise<DockInfo[]> {
  const path = docksPath(around(point, { lon: 0.003, lat: 0.002 }), ZOOM, ["cabi"]);
  const answer = path ? await docks(path) : null;
  return answer?.docks ?? [];
}
/** The first look: about a mile each way, then the server's largest. */
const NEAR_SPAN = { lon: 0.02, lat: 0.015 };
const WIDE_SPAN = { lon: 0.12, lat: 0.09 };
const ZOOM = 15;

/**
 * Said aloud at 35 minutes undocked and every 5 minutes after (the owner, 2026-10-17: "There's an additional
 * charge at either 45 minutes or 60 depending on subscription"): the mark due now, if it is newer than the last
 * said; null otherwise. A mark missed (the page asleep) is said once at the next, not one by one.
 */
export const WARN_FIRST_MIN = 35;
export const WARN_EVERY_MIN = 5;
export function warningDue(minutes: number, lastSaid: number | null): number | null {
  if (minutes < WARN_FIRST_MIN) return null;
  const mark = WARN_FIRST_MIN + Math.floor((minutes - WARN_FIRST_MIN) / WARN_EVERY_MIN) * WARN_EVERY_MIN;
  return lastSaid !== null && mark <= lastSaid ? null : mark;
}
export const undockedWarning = (minutes: number): string => `You have been undocked for ${minutes} minutes.`;

/** Whole minutes since the undock (never below 0). */
export function undockedMinutes(sinceMs: number, nowMs: number): number {
  return Math.max(0, Math.floor((nowMs - sinceMs) / 60_000));
}

/** On the button: "12 min", "1:05" from an hour. */
export function undockedShown(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}

/** Heard: "Ride to the nearest dock. Undocked about 12 minutes." */
export function dockButtonName(minutes: number | null): string {
  if (minutes === null) return `${DOCK_NAME}.`;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  const parts = [hours ? `${hours} ${hours === 1 ? "hour" : "hours"}` : "", hours && !mins ? "" : `${mins} ${mins === 1 ? "minute" : "minutes"}`].filter(Boolean);
  return `${DOCK_NAME}. Undocked about ${parts.join(" ")}.`;
}

/** Docks a bike can be left at: open, and with a free slot (or counts unknown, which may still have one). */
export function docksWithRoom(docks: readonly DockInfo[]): NearestPlace[] {
  return docks
    .filter((d) => !d.closed && (d.docks === null || d.docks > 0))
    .map((d) => ({
      id: `dock-${d.id}`,
      kind: "dock" as const,
      point: [d.lon, d.lat] as LonLat,
      title: d.name,
      details: d.docks === null ? [] : [`${d.docks} open ${d.docks === 1 ? "dock" : "docks"}.`],
    }));
}

/** The box to ask for around the rider. */
function around(here: LonLat, span: { lon: number; lat: number }) {
  return { west: here[0] - span.lon, south: here[1] - span.lat, east: here[0] + span.lon, north: here[1] + span.lat };
}

/** The two ways to pick (the owner, 2026-10-17: "give options for closest or shortest detour"). */
export type DockWay = "closest" | "detour";
export const DOCK_WAYS: ReadonlyArray<{ way: DockWay; label: string; hint: string }> = [
  { way: "closest", label: "Closest dock", hint: "Nearest by bike from here" },
  { way: "detour", label: "Shortest detour", hint: "Adds the least to the ride" },
];

export interface DockDeps {
  here: LonLat;
  /** The ride's end, and how far it is to ride there now (toGo), for the shortest detour. */
  end: LonLat;
  remainingM: number;
  /** GET a docks path (lib/bikeshareDocks.ts loadDocks); null when it fails. */
  docks: (path: string) => Promise<DocksAnswer | null>;
  /** POST /api/nearest on the ride's own settings: from one point to each place. */
  request: (from: LonLat, places: readonly NearestPlace[]) => Promise<NearestResult>;
}

export type DockOutcome = { ok: true; dock: Nearby; said: string } | { ok: false; said: string };

/** "Riding to 15th & P St NW, 0.2 mi (0.3 km) by bike, about 1 min. 6 open docks." */
export function dockSaid(dock: Nearby, way: DockWay = "closest", addedM: number | null = null): string {
  const added = way === "detour" && addedM !== null ? ` It adds about ${formatDistance(Math.max(0, addedM))} to the ride.` : "";
  return [`Riding to ${dock.place.title}, ${howFar(dock)}.${added}`, ...dock.place.details].join(" ");
}

/** The docks with room in the box around the rider: the near box first, then a wider one; null when unanswered. */
async function docksNear(deps: Pick<DockDeps, "here" | "docks">, wide: boolean): Promise<NearestPlace[] | null> {
  let places: NearestPlace[] | null = null;
  for (const span of wide ? [WIDE_SPAN] : [NEAR_SPAN, WIDE_SPAN]) {
    const path = docksPath(around(deps.here, span), ZOOM, ["cabi"]);
    const answer = path ? await deps.docks(path) : null;
    if (!answer || answer.availability === "unavailable") continue;
    places = docksWithRoom(answer.docks);
    if (places.length > 0) break;
  }
  return places;
}

/**
 * The straight-line pick for the shortest detour: the docks whose here-to-dock-to-end is least over the
 * straight here-to-end (an ellipse round the way on), so the docks measured by bike are the ones on the way.
 */
export function onTheWay(here: LonLat, end: LonLat, places: readonly NearestPlace[], n = NEAREST_CANDIDATES): NearestPlace[] {
  return places
    .map((place, index) => ({ place, index, extra: haversineM(here, place.point) + haversineM(place.point, end) }))
    .sort((a, b) => a.extra - b.extra || a.index - b.index)
    .slice(0, n)
    .map(({ place }) => place);
}

/**
 * The added distance of each candidate by bike: here to the dock, plus the dock to the end (measured from the end,
 * the router's one-to-many; near enough both ways for a choice), less the ride left. Null where either is unknown.
 */
export function addedByBike(toDock: NearestAnswer, fromEnd: NearestAnswer, remainingM: number): Array<number | null> {
  return toDock.places.map((cell, i) => {
    const a = cell?.distance_m;
    const b = fromEnd.places[i]?.distance_m;
    return typeof a === "number" && typeof b === "number" && Number.isFinite(a) && Number.isFinite(b) ? a + b - remainingM : null;
  });
}

/** The dock to ride to, the closest by bike or the one that adds least to the ride. */
export async function findDock(deps: DockDeps, way: DockWay = "closest"): Promise<DockOutcome> {
  const near = await docksNear(deps, false);
  if (near === null) return { ok: false, said: DOCK_UNAVAILABLE };
  if (near.length === 0) return { ok: false, said: DOCK_NONE };
  // The shortest detour leaves out the docks at the ride's end: riding on to them is no detour (the review).
  const notEnd = near.filter((place) => haversineM(place.point, deps.end) >= NOT_THE_END_M);
  const places = way === "detour" && notEnd.length > 0 ? notEnd : near;
  const straight = (place: NearestPlace): Nearby => ({ place, distanceM: haversineM(deps.here, place.point), timeS: null, byBike: false });
  if (way === "closest") {
    const candidates = nearestInStraightLine(deps.here, places);
    const result = await deps.request(deps.here, candidates);
    // No riding distances: the nearest in a straight line, said as such.
    const ranked = result.ok ? rankNearest(candidates, result.answer, 1) : [straight(candidates[0])];
    if (ranked.length === 0) return { ok: false, said: DOCK_NONE };
    return { ok: true, dock: ranked[0], said: dockSaid(ranked[0]) };
  }
  const candidates = onTheWay(deps.here, deps.end, places);
  const [toDock, fromEnd] = await Promise.all([deps.request(deps.here, candidates), deps.request(deps.end, candidates)]);
  if (!toDock.ok || !fromEnd.ok) {
    // No riding distances: the least added in straight lines.
    const first = candidates[0];
    const added = haversineM(deps.here, first.point) + haversineM(first.point, deps.end) - haversineM(deps.here, deps.end);
    return { ok: true, dock: straight(first), said: dockSaid(straight(first), "detour", added) };
  }
  const added = addedByBike(toDock.answer, fromEnd.answer, deps.remainingM);
  // Least added, to the nearest 100 m (the router's noise); among those the nearer dock.
  const score = (i: number) => Math.round((added[i] as number) / 100);
  const reach = (i: number) => toDock.answer.places[i]?.distance_m ?? Infinity;
  let best = -1;
  added.forEach((m, i) => {
    if (m === null) return;
    if (best < 0 || score(i) < score(best) || (score(i) === score(best) && reach(i) < reach(best))) best = i;
  });
  if (best < 0) return { ok: false, said: DOCK_NONE };
  const cell = toDock.answer.places[best];
  const byBike = toDock.answer.by === "riding";
  const dock: Nearby = { place: candidates[best], distanceM: cell.distance_m as number, timeS: byBike ? cell.time_s : null, byBike };
  return { ok: true, dock, said: dockSaid(dock, "detour", added[best]) };
}

/** The real docks request, as the map makes it. */
export const fetchDocks = (path: string): Promise<DocksAnswer | null> => loadDocks(path);
