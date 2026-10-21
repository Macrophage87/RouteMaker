/**
 * A transit trip's rides as one (Stephen, 2026-10-21: "The elevation and climbs are only shown for the first stretch
 * in a multi-modal trip"; the header's 1.7 mi was the first ride's alone). The answer's own line is the first ride;
 * each later ride the API routed carries its length, climb, descent and elevation profile on its step
 * (core.api._with_leg_lines). Joined end to end in riding order, they are the totals and the chart the panel shows:
 * the distance ridden, the climb, and one elevation profile with a gap where the train or bus runs.
 */
import type { ProfileCalm, RouteProfile, RouteResponse, StressSpan } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { lonLatAt } from "./profileChart.ts";
import { drawOf } from "./transit.ts";

/** One ride of the trip, where it sits along the joined distance, and its own line on the map. */
export interface RidePiece {
  startM: number;
  endM: number;
  coordinates: LonLat[];
}

/** The route with its totals, profile and stress sections the whole trip's rides', and the rides' pieces. */
export type TripRoute = RouteResponse & { ridePieces?: RidePiece[] };

interface Piece {
  distance: number;
  climb: number;
  descent: number;
  profile: RouteProfile | null;
  spans: readonly StressSpan[] | null | undefined;
  coordinates: LonLat[];
}

/**
 * The route as the panel totals it: a transit trip with more than one routed ride has them joined; any other answer,
 * or a trip whose later rides were not routed in time (no length to add), is the route itself.
 */
export function tripRoute(route: RouteResponse): TripRoute {
  const steps = route.transit?.steps ?? [];
  const pieces: Piece[] = [];
  for (const step of steps) {
    if (drawOf(step) !== "ride") continue;
    if (step.route_line) {
      pieces.push({
        distance: route.distance_m,
        climb: route.climb_m,
        descent: route.descent_m,
        profile: route.profile ?? null,
        spans: route.stress_spans,
        coordinates: route.geometry.coordinates,
      });
    } else if (step.distance_m != null && step.coordinates.length >= 2) {
      pieces.push({
        distance: step.distance_m,
        climb: step.climb_m ?? 0,
        descent: step.descent_m ?? 0,
        profile: step.profile ?? null,
        spans: step.stress_spans,
        coordinates: step.coordinates,
      });
    }
  }
  if (pieces.length < 2) return route;
  const ridePieces: RidePiece[] = [];
  let at = 0;
  for (const piece of pieces) {
    ridePieces.push({ startM: at, endM: at + piece.distance, coordinates: piece.coordinates });
    at += piece.distance;
  }
  return {
    ...route,
    distance_m: at,
    climb_m: pieces.reduce((sum, p) => sum + p.climb, 0),
    descent_m: pieces.reduce((sum, p) => sum + p.descent, 0),
    profile: joinedProfile(pieces, ridePieces),
    stress_spans: joinedSpans(pieces, ridePieces) ?? route.stress_spans,
    ridePieces,
  };
}

/** The profiles end to end, a null height at each joint (the train or bus between), or null where a ride has none. */
function joinedProfile(pieces: Piece[], at: RidePiece[]): RouteProfile | null {
  if (pieces.some((p) => !p.profile)) return null;
  const first = pieces[0].profile as RouteProfile;
  const out: RouteProfile = { interval_m: first.interval_m, m: [], elevation_m: [], grade_pct: [], climbs: [] };
  const calms: (ProfileCalm | null | undefined)[] = [];
  pieces.forEach((piece, index) => {
    const profile = piece.profile as RouteProfile;
    const offset = at[index].startM;
    if (index > 0) {
      // The gap: the chart draws no line across it.
      out.m.push(offset);
      out.elevation_m.push(null);
      out.grade_pct.push(null);
    }
    out.m.push(...profile.m.map((m) => m + offset));
    out.elevation_m.push(...profile.elevation_m);
    out.grade_pct.push(...profile.grade_pct);
    out.climbs.push(...profile.climbs.map((c) => ({ ...c, from_m: c.from_m + offset, to_m: c.to_m + offset })));
    calms.push(profile.calm);
  });
  out.calm = joinedCalm(calms, pieces, at);
  return out;
}

/** The rolling stress score end to end, where every ride has one; else none (the chart leaves it out). */
function joinedCalm(calms: (ProfileCalm | null | undefined)[], pieces: Piece[], at: RidePiece[]): ProfileCalm | null {
  if (calms.some((c) => !c)) return null;
  const all = calms as ProfileCalm[];
  const ratio: (number | null)[] = [];
  all.forEach((calm, index) => {
    if (index > 0) ratio.push(null);
    ratio.push(...calm.ratio);
  });
  if (ratio.length !== (joinedLength(pieces))) return null;
  return {
    ...all[0],
    ratio,
    steps: all.flatMap((calm, i) => calm.steps.map((s) => ({ ...s, from_m: s.from_m + at[i].startM, to_m: s.to_m + at[i].startM }))),
    points: all.flatMap((calm, i) => calm.points.map((p) => ({ ...p, m: p.m + at[i].startM }))),
    total_calm_m: all.reduce((sum, c) => sum + c.total_calm_m, 0),
    rated_m: all.reduce((sum, c) => sum + c.rated_m, 0),
    junctions_counted: all.every((c) => c.junctions_counted),
    estimate: all.some((c) => c.estimate),
  };
}

function joinedLength(pieces: Piece[]): number {
  return pieces.reduce((sum, p) => sum + (p.profile as RouteProfile).m.length, 0) + pieces.length - 1;
}

/** The stress sections end to end along the same distance, or the route's own where a ride has none. */
function joinedSpans(pieces: Piece[], at: RidePiece[]): StressSpan[] | undefined {
  if (pieces.some((p) => !p.spans || p.spans.length === 0)) return undefined;
  return pieces.flatMap((piece, i) => (piece.spans as StressSpan[]).map((s) => ({ ...s, from_m: s.from_m + at[i].startM, to_m: s.to_m + at[i].startM })));
}

/** The map point `metres` along the trip's rides (the chart's scrub), on the ride it falls in. */
export function tripPointAt(route: TripRoute, metres: number, totalM: number): LonLat | null {
  const pieces = route.ridePieces;
  if (!pieces || pieces.length === 0) return lonLatAt(route.geometry.coordinates, metres, totalM);
  const piece = pieces.find((p) => metres <= p.endM) ?? pieces[pieces.length - 1];
  return lonLatAt(piece.coordinates, metres - piece.startM, piece.endM - piece.startM);
}
