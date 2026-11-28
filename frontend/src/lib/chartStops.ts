/**
 * The route's stops on Plan's chart (Stephen 2026-11-22: "Put the stop icons on the map here", the elevation and
 * stress chart): each stop's place along the route, its number and its icon, as Ride's graph draws them in its turns'
 * row (AheadGraph.tsx). A via point is ridden through and is no stop, so it is left out, as in Ride.
 */
import type { RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";
import type { NoteIcon } from "./routeNotes.ts";
import { descriptionEntries } from "./routeDescription.ts";
import { viaIndices } from "./pointKinds.ts";

export interface ChartStop {
  /** Metres along the route, as the chart's axis. */
  m: number;
  /** Its number among the stops, as the map's pin and Ride's cue give it. */
  number: number;
  icon: NoteIcon | null;
}

/** The stops along `route`, planned from `points`: numbered among themselves, as Ride numbers them (navigate.ts rideModel). */
export function chartStops(
  route: Pick<RouteResponse, "description" | "description_overview">,
  points: readonly LonLat[],
  isVia: (p: LonLat) => boolean,
  iconOf: (p: LonLat) => NoteIcon | undefined,
): ChartStop[] {
  const vias = viaIndices(points, isVia);
  const out: ChartStop[] = [];
  for (const entry of descriptionEntries(route, "full", false) ?? []) {
    const index = entry.via;
    if (entry.kind !== "via" || index == null || vias.includes(index)) continue;
    const point = points[index];
    out.push({ m: entry.from_m, number: index - vias.filter((v) => v < index).length, icon: (point && iconOf(point)) ?? null });
  }
  return out;
}
