/**
 * Low tides for the beach path (the owner, 2026-11-23: a beach is ridden "generally only
 * adviseable in low tide below the high tide lines"). The data is tide-data/tides.json,
 * NOAA's predicted low tides for the Gulf stations by the Southwest Florida beaches,
 * written by scripts/build_tides.py and loaded only when a route uses a beach path.
 */
import type { LonLat } from "./geo.ts";

export interface TideStation {
  id: string;
  name: string;
  lon: number;
  lat: number;
  /** [minutes since 1970 UTC, height in tenths of a foot above mean lower low water]. */
  lows: [number, number][];
}

export interface TideData {
  from: string;
  to: string;
  stations: TideStation[];
}

export interface LowTide {
  at: Date;
  feet: number;
}

/** The read file, or null when it is not tide data. */
export function readTides(raw: unknown): TideData | null {
  const data = raw as Partial<TideData> | null;
  if (!data || !Array.isArray(data.stations)) return null;
  const stations = data.stations.filter(
    (s): s is TideStation =>
      !!s && typeof s.id === "string" && typeof s.name === "string" && Number.isFinite(s.lon) && Number.isFinite(s.lat) && Array.isArray(s.lows),
  );
  return stations.length ? { from: String(data.from ?? ""), to: String(data.to ?? ""), stations } : null;
}

let loading: Promise<TideData | null> | null = null;

/** The tide file, fetched once; null where it cannot be had (offline before it was cached). */
export function loadTides(url: string, fetcher: typeof fetch = fetch): Promise<TideData | null> {
  loading ??= fetcher(url)
    .then((r) => (r.ok ? r.json() : null))
    .then(readTides)
    .catch(() => {
      loading = null;
      return null;
    });
  return loading;
}

/** The station nearest a place (flat distance is enough over a hundred miles of coast). */
export function nearestStation(data: TideData, [lon, lat]: LonLat): TideStation {
  const scale = Math.cos((lat * Math.PI) / 180);
  let best = data.stations[0];
  let bestD = Infinity;
  for (const s of data.stations) {
    const d = ((s.lon - lon) * scale) ** 2 + (s.lat - lat) ** 2;
    if (d < bestD) [best, bestD] = [s, d];
  }
  return best;
}

/** The low tides on the calendar day of `day` in `timeZone` (the beaches' own, Eastern). */
export function lowTidesOn(station: TideStation, day: Date, timeZone = "America/New_York"): LowTide[] {
  const key = (d: Date) => d.toLocaleDateString("en-CA", { timeZone });
  const want = key(day);
  return station.lows
    .map(([minutes, tenths]) => ({ at: new Date(minutes * 60_000), feet: tenths / 10 }))
    .filter((low) => key(low.at) === want);
}
