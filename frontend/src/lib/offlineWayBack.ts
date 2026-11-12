/**
 * Off-grid riding in Ride (Stephen, 2026-11-12): the road network within a mile of the route, fetched with the
 * route's kept map (POST /api/offline/network), and, when a re-plan fails for want of a signal, the way back to the
 * planned line found on the phone (lib/offlineRouter.ts), made a route Ride rides like the server's way back: its
 * turns as cues, joined to the planned route where it meets it (lib/rejoin.ts joinRoutes). Said as approximate.
 *
 * Privacy: the request carries the route's line, as a route plan does; nothing about the rider. The network is kept
 * in memory for the ride only.
 */
import type { DescriptionEntry, RouteResponse, StressSpan } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { METRES_PER_MILE } from "./format.ts";
import { turnWords } from "./navigate.ts";
import { offlineWayBack, readableGraph, type CorridorGraph, type OfflineWayBack, type OfflineWeights } from "./offlineRouter.ts";
import { continueWords, joinRoutes } from "./rejoin.ts";

/** The network and the ride's prices for it, as the API answers. */
export interface OfflineNetwork {
  graph: CorridorGraph;
  levelFactor: number[];
}

/** Riding speed offline, about 11 mph, and walking, about 3 mph. Our defaults, unmeasured; only the choice between ways uses them. */
export const OFFLINE_SPEED_MPS = 5;
export const OFFLINE_WALK_MPS = 1.3;
/** An unpaved stretch at this share of the paved speed. Our default, unmeasured. */
export const OFFLINE_UNPAVED_FACTOR = 0.8;

/** The network around `line`, or null (no signal, not built yet, refused). Never throws. */
export async function fetchOfflineNetwork(
  line: readonly LonLat[],
  ride: { preset: string; stress?: number | null; carrying?: string | null },
  fetcher: typeof fetch = fetch,
): Promise<OfflineNetwork | null> {
  try {
    const answer = await fetcher("/api/offline/network", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ line: line.map((p) => [p[0], p[1]]), preset: ride.preset, stress: ride.stress ?? null, carrying: ride.carrying ?? null }),
    });
    if (!answer.ok) return null;
    const body = (await answer.json()) as CorridorGraph & { level_factor?: number[] };
    if (!readableGraph(body) || !Array.isArray(body.level_factor)) return null;
    return { graph: body, levelFactor: body.level_factor };
  } catch {
    return null;
  }
}

export function weightsOf(network: OfflineNetwork): OfflineWeights {
  return { speedMps: OFFLINE_SPEED_MPS, unpavedSpeedFactor: OFFLINE_UNPAVED_FACTOR, walkMps: OFFLINE_WALK_MPS, levelFactor: network.levelFactor };
}

function entry(fromM: number, toM: number, street: string | null, tier: number | null, turn: DescriptionEntry["turn"], text: string): DescriptionEntry {
  return {
    kind: "stretch",
    from_m: fromM,
    to_m: toM,
    from_mi: fromM / METRES_PER_MILE,
    to_mi: toM / METRES_PER_MILE,
    street,
    tier,
    facility: null,
    turn,
    text,
  };
}

/** The way back as a route of its own: its line, a stretch per turn with the turn's words, and its worst level. */
export function offlineLeg(way: OfflineWayBack, planned: RouteResponse): RouteResponse {
  const description: DescriptionEntry[] = [];
  const ends = [...way.turns.map((turn) => turn.atM), way.distanceM];
  const tier = Math.max(1, Math.min(5, Math.floor(way.worstLevel2 / 2)));
  let from = 0;
  let street = way.startStreet;
  description.push(entry(0, ends[0], street, tier, null, continueWords(street)));
  from = ends[0];
  way.turns.forEach((turn, i) => {
    street = turn.street;
    description.push(
      entry(from, ends[i + 1], street, tier, { movement: turn.movement, onto: street, control: null, severity: null }, turnWords(turn.movement, street)),
    );
    from = ends[i + 1];
  });
  const spans: StressSpan[] = [{ from_m: 0, to_m: way.distanceM, tier, facility: null }];
  return {
    ...planned,
    geometry: { type: "LineString", coordinates: way.line.map((p) => [p[0], p[1]] as LonLat) },
    distance_m: way.distanceM,
    duration_s: way.durationS,
    leg_ends: undefined,
    description,
    stress_spans: spans,
    trail_levels: [],
    dirt_trails: false,
    dirt_closed: false,
  };
}

/**
 * With no signal off the route: the way back found on the phone, joined to the planned route where it meets it, or
 * null where the rider is off the network or no join is reachable. `kept` renumbers the planned route's kept points
 * as lib/rejoin.ts wayBackRoute does.
 */
export function offlineWayBackRoute(
  network: OfflineNetwork,
  planned: RouteResponse,
  here: LonLat,
  progressM: number,
  kept: readonly number[],
): RouteResponse | null {
  const way = offlineWayBack(network.graph, weightsOf(network), here, planned.geometry.coordinates as LonLat[], progressM);
  if (!way) return null;
  const renumber = new Map(kept.map((old, i) => [old, i + 1] as const));
  return joinRoutes(offlineLeg(way, planned), planned, way.joinAtM, renumber);
}
