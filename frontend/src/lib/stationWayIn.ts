/**
 * A Metro or MARC station's quickest way in with a bike (Stephen 2026-10-20, riding to Shady Grove from the west:
 * "Somehow it missed one of the metro entrances"). A point placed at a station starts at its way in nearest where
 * the rider comes from in a straight line (railStations.ts, bikeEntrance); where the station has more than one, the
 * router is asked how long each takes to ride to (POST /api/nearest, the ride's own graph and settings), and the
 * point moves to the quickest. A straight line can cross the tracks: the nearest elevator may be a long way round.
 *
 * Only with a bike: on foot (presets.ts, endsOnFoot) the nearest entrance in a straight line stands, since the
 * router's riding times say nothing of the walk. A way in the rider tapped on the map stays where it is.
 *
 * Plain data in, plain data out, so node --test runs all of it; App.tsx asks and moves the point.
 */
import { haversineM, type LonLat } from "./geo.ts";
import type { NearestPlace, NearestResult } from "./nearest.ts";
import { AT_ENTRANCE_M, bikeWaysIn, type BikeEntrance, type Station } from "./railStations.ts";

/** A point as text, to remember it by: five decimals, as a shared link keeps it (about 1 m). */
export const lonLatKey = (point: LonLat): string => `${point[0].toFixed(5)},${point[1].toFixed(5)}`;

/** A different way in must save at least this much riding to move the point: no moves for a few seconds. */
export const QUICKER_BY_S = 15;

/** A plan's point at one of a station's bike ways in, with the other ways in it could use. */
export interface WayInCheck {
  index: number;
  station: Station;
  kind: BikeEntrance["kind"];
  /** The station's bike ways in, the point's own among them. */
  ways: readonly LonLat[];
  /** Where the leg to the station comes from: the point before, or for a start the point after. */
  from: LonLat;
}

/** The points of a plan worth asking about: at a station's bike way in, where the station has another. */
export function wayInChecks(points: readonly LonLat[], stations: readonly Station[]): WayInCheck[] {
  const checks: WayInCheck[] = [];
  if (points.length < 2) return checks;
  points.forEach((point, index) => {
    for (const station of stations) {
      const { kind, points: ways } = bikeWaysIn(station);
      if (ways.length < 2 || !ways.some((way) => haversineM(way, point) <= AT_ENTRANCE_M)) continue;
      const from = index === 0 ? points[1] : points[index - 1];
      if (haversineM(from, point) <= AT_ENTRANCE_M) return;
      checks.push({ index, station, kind, ways, from });
      return;
    }
  });
  return checks;
}

/**
 * The way in to move to, from the router's answer for `check.ways` in order, or null to stay: the answer must be by
 * bike, and the quickest must save QUICKER_BY_S over the point's own (or the point's own must be unreachable).
 */
export function quickerWayIn(point: LonLat, check: WayInCheck, result: NearestResult): LonLat | null {
  if (!result.ok || result.answer.by !== "riding") return null;
  const times = result.answer.places.map((cell) => (typeof cell?.time_s === "number" && Number.isFinite(cell.time_s) ? cell.time_s : null));
  let best = -1;
  times.forEach((t, i) => {
    if (t !== null && (best < 0 || t < (times[best] as number))) best = i;
  });
  if (best < 0) return null;
  const own = check.ways.findIndex((way) => haversineM(way, point) <= AT_ENTRANCE_M);
  if (own === best) return null;
  const ownTime = own >= 0 ? times[own] : null;
  if (ownTime !== null && ownTime - (times[best] as number) < QUICKER_BY_S) return null;
  return check.ways[best];
}

/** The station's ways in as the nearest request's places. */
export function wayInPlaces(check: WayInCheck): NearestPlace[] {
  return check.ways.map((point, i) => ({ id: `${check.station.id}-way-${i}`, kind: "metro", point, title: check.station.name, details: [] }));
}

/** "End moved to Shady Grove Metro station's elevator that is quicker to reach by bike. Undo puts it back." */
export function wayInSaid(pointName: string, stationName: string, kind: BikeEntrance["kind"]): string {
  const way = kind === "elevator" || kind === "osm-elevator" ? "elevator" : "entrance";
  return `${pointName} moved to ${stationName}'s ${way} that is quicker to reach by bike. Undo puts it back.`;
}
