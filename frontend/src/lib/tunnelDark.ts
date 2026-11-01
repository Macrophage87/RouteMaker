/**
 * THE DARK MAP IN A TUNNEL. The owner, 2026-11-01: "Can you do dark mode in tunnels too?" In a ride or Roam the base
 * map goes dark while the rider is in a tunnel (lib/mapFlavour.ts), and light again after it, unless the theme or
 * the hour keeps it dark anyway. The route carries no tunnel flag; the base map's roads do (Protomaps' `roads` tile
 * layer, `is_tunnel`, which its tunnel layers filter on). So: at the rider's spot (the last fix, which a tunnel
 * usually freezes) and at TUNNEL_AHEAD_M along the route ahead, the nearest base-map road within TUNNEL_NEAR_M
 * decides: a tunnel, dark. A road over a tunnel is nearer than the tunnel only if it is the road ridden, which is
 * what nearest-wins wants. A GPS dropout alone changes nothing: only the roads at the last spot are read.
 *
 * Leaving is held back (TUNNEL_CLEAR_MS or TUNNEL_CLEAR_M clear of any tunnel), so the map does not flicker at a
 * portal or under an overpass. The check runs only as a new fix comes, at most every TUNNEL_CHECK_MS (tunnelCheckWait,
 * useMapFlavour.ts): with no new fix there is nothing new to read, and a free-running timer would wake the phone for
 * nothing (the owner, 2026-11-01: battery audit).
 */
import { haversineM, type LonLat } from "./geo.ts";
import { pointAlong } from "./lightTimes.ts";

export const TUNNEL_NEAR_M = 15;
export const TUNNEL_AHEAD_M = 50;
export const TUNNEL_CLEAR_MS = 10_000;
export const TUNNEL_CLEAR_M = 50;
export const TUNNEL_CHECK_MS = 5000;

/**
 * A new fix has come: how long until the tunnel check for it, or null when one is already waiting (it reads the
 * latest fix when it runs). At once if the last check was TUNNEL_CHECK_MS ago or more, or there was none.
 */
export function tunnelCheckWait(lastCheckAt: number | null, waiting: boolean, now: number): number | null {
  if (waiting) return null;
  return lastCheckAt === null ? 0 : Math.max(0, lastCheckAt + TUNNEL_CHECK_MS - now);
}

/** A base-map road near the rider: its lines and whether it is a tunnel. */
export interface NearRoad {
  tunnel: boolean;
  lines: ReadonlyArray<readonly LonLat[]>;
}

/** Metres from `p` to the segment a-b, on a local flat projection (fine at these distances). */
function toSegmentM(p: LonLat, a: LonLat, b: LonLat): number {
  const k = Math.cos((p[1] * Math.PI) / 180);
  const ax = (a[0] - p[0]) * k;
  const ay = a[1] - p[1];
  const bx = (b[0] - p[0]) * k;
  const by = b[1] - p[1];
  const dx = bx - ax;
  const dy = by - ay;
  const len = dx * dx + dy * dy;
  const t = len === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len));
  const x = ax + t * dx;
  const y = ay + t * dy;
  return Math.hypot(x, y) * 111_320;
}

/** Whether the nearest road to `at`, within `radiusM`, is a tunnel; false with no road that near. */
export function inTunnelAt(roads: readonly NearRoad[], at: LonLat, radiusM = TUNNEL_NEAR_M): boolean {
  let best = Infinity;
  let tunnel = false;
  for (const road of roads) {
    for (const line of road.lines) {
      for (let i = 0; i < line.length; i += 1) {
        const d = line.length === 1 ? toSegmentM(at, line[0], line[0]) : i === 0 ? Infinity : toSegmentM(at, line[i - 1], line[i]);
        // A tie goes to the tunnel: a portal is where the two meet.
        if (d < best || (d === best && road.tunnel)) {
          best = d;
          tunnel = road.tunnel;
        }
      }
    }
  }
  return best <= radiusM && tunnel;
}

/** The point `metres` ahead of `at` along `line` (from the nearest point on it), or null without a line. */
export function aheadOnLine(line: readonly LonLat[] | null | undefined, at: LonLat, metres = TUNNEL_AHEAD_M): LonLat | null {
  if (!line || line.length < 2) return null;
  let bestD = Infinity;
  let along = 0;
  let done = 0;
  for (let i = 1; i < line.length; i += 1) {
    const step = haversineM(line[i - 1], line[i]);
    const d = toSegmentM(at, line[i - 1], line[i]);
    if (d < bestD) {
      bestD = d;
      // How far along this segment the nearest point is, by the distances to its ends.
      const fromStart = haversineM(line[i - 1], at);
      along = done + Math.min(step, Math.sqrt(Math.max(0, fromStart * fromStart - (d * d))));
    }
    done += step;
  }
  return pointAlong(line, along + metres);
}

/** Where the rider is held to be in a tunnel, and since when and where they have been clear of one. */
export interface TunnelState {
  dark: boolean;
  clear: { ms: number; at: LonLat } | null;
}

export const NO_TUNNEL: TunnelState = { dark: false, clear: null };

/**
 * One check: `seen` is whether a tunnel is at the spot or just ahead. Dark at once; light again only after
 * TUNNEL_CLEAR_MS or TUNNEL_CLEAR_M clear of any tunnel.
 */
export function tunnelStep(state: TunnelState, seen: boolean, now: number, at: LonLat): TunnelState {
  if (seen) return { dark: true, clear: null };
  if (!state.dark) return NO_TUNNEL;
  const clear = state.clear ?? { ms: now, at };
  if (now - clear.ms >= TUNNEL_CLEAR_MS || haversineM(clear.at, at) >= TUNNEL_CLEAR_M) return NO_TUNNEL;
  return { dark: true, clear };
}

/** The base map's road layers a rendered-feature query reads (Protomaps' ids: roads_*, tunnels and bridges among them). */
export function roadLayerIds(styleLayers: ReadonlyArray<{ id: string; "source-layer"?: string }>): string[] {
  return styleLayers.filter((layer) => layer["source-layer"] === "roads" && !layer.id.includes("label") && !layer.id.includes("shield")).map((layer) => layer.id);
}

/** A rendered road feature as inTunnelAt reads it. */
export function nearRoad(feature: { properties?: Record<string, unknown> | null; geometry: { type: string; coordinates: unknown } }): NearRoad | null {
  const { type, coordinates } = feature.geometry;
  const lines = type === "LineString" ? [coordinates as LonLat[]] : type === "MultiLineString" ? (coordinates as LonLat[][]) : null;
  if (!lines) return null;
  const flag = feature.properties?.is_tunnel;
  return { tunnel: flag === true || flag === "true" || flag === 1, lines };
}
