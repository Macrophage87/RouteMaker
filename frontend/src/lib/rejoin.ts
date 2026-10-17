// Back to the planned route when a re-plan finds none (the owner, 2026-10-17: "when off route if no route
// can be found try to find the nearest route back to the route"). Off route, a re-plan from here to the end
// can fail where a short ride back to the line does not: a long ride's plan runs out of time, or the rest
// of the trip cannot be planned again. The way back is planned on its own, to a point on the line ahead,
// and joined to the planned route from there, so the rest of the ride is the route already planned.
import type { DescriptionEntry, ErrorKind, RouteResult, RouteResponse, StressSpan } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { ARRIVE_M, lineAlong, measureMap, pointAt, snap, type RideModel } from "./navigate.ts";

/**
 * The way back aims this far along the line past its nearest point ahead (about 300 ft), so it ends on the
 * planned road with the turn onto it, not at the edge of it.
 */
export const REJOIN_AHEAD_M = 100;
/** Further points the way back tries when the nearer one cannot be reached, past the first. */
export const REJOIN_FURTHER_M = [500, 1500] as const;
/** Two points closer than this along the line are one try. */
const REJOIN_SAME_M = 50;

const METRES_PER_MILE = 1609.344;

/**
 * Whether a failed re-plan is worth a way back: not with no signal (a way back would not get through either)
 * nor when the planner asked the rider to slow down (it would be refused too).
 */
export function triesWayBack(kind: ErrorKind): boolean {
  return kind !== "network" && kind !== "rate-limited";
}

/**
 * Whether a failed re-plan starts the way back: as `triesWayBack`, but a slow-down is tried once, since a long
 * re-plan can be refused for the long ride's one slot, which a short way back does not take.
 */
export function startsWayBack(kind: ErrorKind): boolean {
  return kind !== "network";
}

/**
 * The way back as the ride's new route, or the last failure's kind (null where none was asked): each target in
 * turn (`rejoinTargets`) asked for with `request` (here to that point), the first answered joined to `planned`
 * there (`joinRoutes`). `kept` is navigate.ts replanKept's answer for the plan's points. A failure that a
 * further point would meet too (no signal, slow down) ends the tries, as does `cancelled` (Keep the planned
 * route, End ride, a newer re-plan).
 */
export async function wayBackRoute(
  planned: RouteResponse,
  model: RideModel,
  progressM: number,
  here: LonLat,
  kept: readonly number[],
  request: (points: LonLat[]) => Promise<RouteResult>,
  cancelled: () => boolean = () => false,
): Promise<{ route: RouteResponse } | { failed: ErrorKind | null }> {
  // A kept point's index in the new plan's points: after the rider's position, in order.
  const renumber = new Map(kept.map((old, i) => [old, i + 1] as const));
  let failed: ErrorKind | null = null;
  for (const target of rejoinTargets(model, progressM, here)) {
    if (cancelled()) break;
    const result = await request([here, target.point]);
    if (result.ok) return { route: joinRoutes(result.route, planned, target.atM, renumber) };
    failed = result.error.kind;
    if (!triesWayBack(failed)) break;
  }
  return { failed };
}

export interface RejoinTarget {
  /** Metres along the planned line. */
  atM: number;
  point: LonLat;
}

/**
 * Where the way back may join the planned route, nearest first: the line's nearest point to `here` ahead
 * of the rider's last place on it (as wayBack finds it), a little past that, then further along. Never
 * past the next stop or via point not yet reached, so none is skipped. Empty when none is left ahead.
 */
export function rejoinTargets(model: RideModel, progressM: number, here: LonLat): RejoinTarget[] {
  const cap = Math.min(model.lengthM, nextStopM(model, progressM));
  if (!(cap > progressM)) return [];
  const nearest = snap(model, here, progressM, cap);
  if (!nearest) return [];
  const first = Math.min(nearest.alongM + REJOIN_AHEAD_M, cap);
  const out: RejoinTarget[] = [];
  for (const m of [first, ...REJOIN_FURTHER_M.map((d) => Math.min(first + d, cap))]) {
    if (out.length && m - out[out.length - 1].atM < REJOIN_SAME_M) continue;
    out.push({ atM: m, point: pointAt(model, m) });
  }
  return out;
}

/** The line's place for the next stop or via point the rider has not reached (replanPoints' test); the end where none. */
function nextStopM(model: RideModel, progressM: number): number {
  let next = Infinity;
  for (const c of model.cues) if (c.kind === "stop" && c.atM > progressM + ARRIVE_M) next = Math.min(next, c.atM);
  for (const p of model.passes ?? []) if (p.atM > progressM + ARRIVE_M) next = Math.min(next, p.atM);
  return next;
}

/**
 * One route: `leg` (here to the line, planned on its own) and then `planned` from `atM` metres along its
 * line to its end. The description and the stress sections are carried over in line metres (the measure the
 * ride model and the map draw by), the planned part shifted to follow the leg. `kept` maps a planned point's
 * index to its index in the new plan's points (navigate.ts replanKept, after the rider's position), so its
 * stops keep their numbers right; a stop or via point it leaves out is not carried. The route's own summary
 * (its stress and facility miles, its climbs) is the planned route's still: Ride mode does not show it.
 */
export function joinRoutes(leg: RouteResponse, planned: RouteResponse, atM: number, kept: ReadonlyMap<number, number>): RouteResponse {
  const legLine = leg.geometry.coordinates;
  const plannedLine = planned.geometry.coordinates;
  const legAlong = lineAlong(legLine);
  const plannedAlong = lineAlong(plannedLine);
  const legM = legAlong.length ? legAlong[legAlong.length - 1] : 0;
  const plannedM = plannedAlong.length ? plannedAlong[plannedAlong.length - 1] : 0;
  const cut = Math.min(Math.max(atM, 0), plannedM);
  const rest = plannedM - cut;
  // The planned line from the cut: its point there, then each vertex past it (none for a metre or less).
  const tail: LonLat[] = [];
  if (rest > 1) {
    tail.push(pointAt({ coordinates: plannedLine, along: plannedAlong }, cut));
    for (let i = 0; i < plannedLine.length; i += 1) if (plannedAlong[i] > cut) tail.push(plannedLine[i]);
  }
  const gap = tail.length && legLine.length ? haversineM(legLine[legLine.length - 1], tail[0]) : 0;
  const shift = legM + gap;
  const totalM = shift + (tail.length ? rest : 0);
  const coordinates = [...legLine, ...tail];

  const legToLine = measureMap(leg, legAlong);
  const plannedToLine = measureMap(planned, plannedAlong);
  const description: DescriptionEntry[] = [];
  for (const entry of leg.description ?? []) {
    // A two-point leg has no stops; its arrival is the planned route's to give.
    if (entry.kind === "via") continue;
    description.push(atMetres(entry, legToLine(entry.from_m), legToLine(entry.to_m)));
  }
  if (tail.length) {
    for (const entry of planned.description ?? []) {
      let from = plannedToLine(entry.from_m);
      const to = plannedToLine(entry.to_m);
      // Behind the cut: gone. A point exactly at it (a stop the way back aimed for) stays.
      if (to < cut || (to === cut && from < cut)) continue;
      let moved = entry;
      if (from < cut) {
        // Joined part way along: the turn onto it was the planned route's, not the way back's, so its words go too.
        from = cut;
        moved = entry.turn ? { ...entry, turn: null, text: continueWords(entry.street), text_lanes_hidden: null } : entry;
      }
      if (entry.via != null) {
        const via = kept.get(entry.via);
        if (via === undefined) continue;
        moved = { ...moved, via };
      }
      description.push(atMetres(moved, from - cut + shift, to - cut + shift));
    }
  }

  const spans = joinSpans(leg, legM, planned, plannedM, cut, shift, totalM, tail.length > 0);
  const fraction = plannedM > 0 ? rest / plannedM : 0;
  const ended = tail.length === 0;
  return {
    ...planned,
    geometry: { type: "LineString", coordinates },
    distance_m: leg.distance_m + planned.distance_m * fraction,
    duration_s: leg.duration_s + planned.duration_s * fraction,
    // Description metres are line metres now, so no leg ends are needed to map them.
    leg_ends: undefined,
    // Both or neither: one route's line metres stretched over the other's would put its cues in the wrong places.
    description: leg.description && (planned.description || !tail.length) ? description : null,
    description_overview: null,
    stress_spans: spans,
    profile: null,
    candidates: null,
    avoid_alternate: null,
    arrival_side: ended ? leg.arrival_side : planned.arrival_side,
  };
}

/** A joined stretch's words where the planned route turned onto it: what Ride mode says of it, with no turn. */
function continueWords(street: string | null): string {
  return street ? `Continue on ${street}.` : "Continue.";
}

function atMetres(entry: DescriptionEntry, from: number, to: number): DescriptionEntry {
  return { ...entry, from_m: from, to_m: to, from_mi: from / METRES_PER_MILE, to_mi: to / METRES_PER_MILE };
}

/**
 * The stress sections of the joined line, end to end from 0 (routeColours.ts usableSpans): the leg's, then the
 * planned route's from the cut, each scaled to its line as the map scales them. Undefined, drawn in one colour,
 * where either has none to give.
 */
function joinSpans(
  leg: RouteResponse,
  legM: number,
  planned: RouteResponse,
  plannedM: number,
  cut: number,
  shift: number,
  totalM: number,
  hasTail: boolean,
): StressSpan[] | undefined {
  const legSpans = leg.stress_spans ?? [];
  const plannedSpans = planned.stress_spans ?? [];
  const legEnd = legSpans.length ? legSpans[legSpans.length - 1].to_m : 0;
  const plannedEnd = plannedSpans.length ? plannedSpans[plannedSpans.length - 1].to_m : 0;
  if (!(legEnd > 0) || (hasTail && !(plannedEnd > 0))) return undefined;
  const pieces: { span: StressSpan; to: number }[] = [];
  const legScale = legM / legEnd;
  for (const span of legSpans) pieces.push({ span, to: span.to_m * legScale });
  if (hasTail) {
    const scale = plannedM / plannedEnd;
    for (const span of plannedSpans) {
      const to = span.to_m * scale;
      if (to <= cut) continue;
      pieces.push({ span, to: to - cut + shift });
    }
  }
  const out: StressSpan[] = [];
  let at = 0;
  pieces.forEach(({ span, to }, i) => {
    // The last ends at the line's end; the gap from the leg's end to the cut goes to the leg's last.
    const end = i === pieces.length - 1 ? totalM : !hasTail || i !== legSpans.length - 1 ? to : shift;
    if (!(end > at)) return;
    out.push({ ...span, from_m: at, to_m: end });
    at = end;
  });
  return out.length ? out : undefined;
}
