/**
 * Trail mile markers (OWNER-DECISIONS 465, 2026-10-09: "some trails like the MBT and CCT should have mile
 * markers as they can go a distance without crossing a road"; Stephen, 2026-10-16: "Make sure the mile markers
 * are added to 311 when built."). On a named trail the 311 report, "Where am I?" and the road panel name the
 * nearest posted mile marker OSM maps, within MARKER_NEAR_M ("Capital Crescent Trail at mile marker 3"); else
 * the distance along the trail from its mile 0, worked out here ("Capital Crescent Trail at about mile 3.2").
 * Everything is on the device: the rider's position is never sent anywhere for it.
 *
 * The data is amenity-data/trail-miles.json, built from the project's extract by scripts/build_trail_miles.py
 * (what counts as a marker and as a trail, how a trail's line is found and which end is mile 0, in its
 * docstring): the markers, each with its trail's name and posted figure, and a line from mile 0 for each long
 * trail whose mile 0 is known (from its own posts, or the build's table of known trails), with `s`, the metres
 * at the line's first point that make the computed mile agree with the posts. A trail with no line gets no
 * computed mile, only its posts: a guessed mile 0 would be wrong.
 * The map draws the markers from MILE_MIN_ZOOM in, always (no switch: the owner's "Go stays one control per
 * feature"); a tap names the marker in words, and the road panel names the nearest for a trail way.
 *
 * A trail is matched by name (`trailKey`: case, "&" and punctuation aside), the route's street name and the
 * road panel's title being the way's OSM name, as the file's are.
 */
import { formatDistance, METRES_PER_MILE } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";

export interface TrailMarker {
  /** The OSM node, "n123". */
  id: string;
  lon: number;
  lat: number;
  /** The trail's name, as OSM names it. */
  trail: string;
  /** `trailKey(trail)`, worked out once when the file is read. */
  key: string;
  /** The figure on the post, in miles. */
  mile: number;
}

export interface TrailLine {
  trail: string;
  /** `trailKey(trail)`, worked out once when the file is read. */
  key: string;
  /** The line from mile 0. */
  line: LonLat[];
  /** Metres along the line to each point. */
  along: Float64Array;
  /** Metres at the line's first point (the posts' mile 0 may lie before or after it). */
  startM: number;
}

export interface TrailMiles {
  markers: TrailMarker[];
  lines: TrailLine[];
}

/** A posted marker this near (500 ft, about 0.1 mi) is named; farther, the computed mile is said. */
export const MARKER_NEAR_M = 500 / 3.28084;
/** A point farther than this (200 ft, 60 m) from a trail's line is not on it (a branch, a parallel road). */
export const LINE_NEAR_M = 200 / 3.28084;
/** With no line, a posted marker this near (half a mile) is still named, as "near mile marker 3". */
export const MARKER_FAR_M = METRES_PER_MILE / 2;

const text = (value: unknown): string | null => (typeof value === "string" && value.trim() ? value.trim() : null);
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** The file's markers and lines; empty lists for a file with none yet; null if it is not the file's shape. */
export function parseTrailMiles(value: unknown): TrailMiles | null {
  const body = value as { trails?: unknown; markers?: unknown } | null;
  if (!body || !Array.isArray(body.trails) || !Array.isArray(body.markers)) return null;
  const markers: TrailMarker[] = [];
  for (const raw of body.markers as Array<Record<string, unknown>>) {
    const trail = text(raw?.t);
    if (!raw || typeof raw.id !== "string" || !trail || !finite(raw.x) || !finite(raw.y) || !finite(raw.m) || raw.m < 0) continue;
    markers.push({ id: raw.id, lon: raw.x, lat: raw.y, trail, key: trailKey(trail), mile: raw.m });
  }
  const lines: TrailLine[] = [];
  for (const raw of body.trails as Array<Record<string, unknown>>) {
    const trail = text(raw?.n);
    if (!raw || !trail || !Array.isArray(raw.l)) continue;
    const line = (raw.l as unknown[]).filter((p): p is LonLat => Array.isArray(p) && p.length === 2 && finite(p[0]) && finite(p[1]));
    if (line.length < 2) continue;
    const along = new Float64Array(line.length);
    for (let i = 1; i < line.length; i++) along[i] = along[i - 1] + haversineM(line[i - 1], line[i]);
    lines.push({ trail, key: trailKey(trail), line, along, startM: finite(raw.s) ? raw.s : 0 });
  }
  return { markers, lines };
}

/** Fetch and parse the file; null if it cannot be had (empty lists are "none yet", not a failure). */
export async function loadTrailMiles(
  url: string,
  fetcher: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u) => fetch(u),
): Promise<TrailMiles | null> {
  try {
    const response = await fetcher(url);
    if (!response.ok) return null;
    return parseTrailMiles(await response.json());
  } catch {
    return null;
  }
}

/** A trail's name to match on: lower case, "&" as "and", punctuation and extra spaces dropped. */
export function trailKey(name: string): string {
  return name
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** The nearest place on a line to a point: metres off it and metres along it (flat, plenty at trail scale). */
export function projectOnLine(line: readonly LonLat[], along: Float64Array, point: LonLat): { offM: number; alongM: number } {
  const kx = Math.cos((point[1] * Math.PI) / 180) * 111_195;
  const ky = 111_195;
  const px = point[0] * kx;
  const py = point[1] * ky;
  let best = { offM: Infinity, alongM: 0 };
  for (let i = 1; i < line.length; i++) {
    const ax = line[i - 1][0] * kx;
    const ay = line[i - 1][1] * ky;
    const dx = line[i][0] * kx - ax;
    const dy = line[i][1] * ky - ay;
    const seg2 = dx * dx + dy * dy;
    const t = seg2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / seg2));
    const off = Math.hypot(ax + t * dx - px, ay + t * dy - py);
    if (off < best.offM) best = { offM: off, alongM: along[i - 1] + t * (along[i] - along[i - 1]) };
  }
  return best;
}

/** Where on a trail a point is: a posted marker (and how far it is), or the computed mile. */
export type TrailMile =
  | { kind: "marker"; trail: string; mile: number; metres: number }
  | { kind: "computed"; trail: string; mile: number };

/**
 * The mile at `point` on the trail named `trail` (the way ridden, or the road panel's way): the nearest posted
 * marker of that trail within MARKER_NEAR_M; else the computed mile on the nearest of its lines within
 * LINE_NEAR_M, to a tenth, never below 0; else a posted marker within MARKER_FAR_M; else null (not a trail in
 * the file, or too far from it).
 */
export function trailMileAt(data: TrailMiles | null | undefined, trail: string | null | undefined, point: LonLat): TrailMile | null {
  if (!data || !trail) return null;
  const key = trailKey(trail);
  if (!key) return null;
  let marker: TrailMarker | null = null;
  let markerM = Infinity;
  for (const m of data.markers) {
    if (m.key !== key) continue;
    const d = haversineM(point, [m.lon, m.lat]);
    if (d < markerM) {
      marker = m;
      markerM = d;
    }
  }
  if (marker && markerM <= MARKER_NEAR_M) return { kind: "marker", trail: marker.trail, mile: marker.mile, metres: markerM };
  let best: { line: TrailLine; offM: number; alongM: number } | null = null;
  for (const line of data.lines) {
    if (line.key !== key) continue;
    const at = projectOnLine(line.line, line.along, point);
    if (at.offM <= LINE_NEAR_M && (!best || at.offM < best.offM)) best = { line, ...at };
  }
  if (best) {
    const mile = Math.max(0, Math.round(((best.line.startM + best.alongM) / METRES_PER_MILE) * 10) / 10);
    return { kind: "computed", trail: best.line.trail, mile };
  }
  if (marker && markerM <= MARKER_FAR_M) return { kind: "marker", trail: marker.trail, mile: marker.mile, metres: markerM };
  return null;
}

/** A posted figure as the post says it: "3", "3.5". */
export function mileFigure(mile: number): string {
  return Number.isInteger(mile) ? String(mile) : String(Math.round(mile * 100) / 100);
}

/**
 * The mile in words, for the 311 report and "Where am I?": "mile marker 3" at a post, "near mile marker 3" for
 * a post farther than MARKER_NEAR_M, "about mile 3.2" computed. Miles only: a post says miles, and the report is
 * the message itself.
 */
export function mileWords(at: TrailMile): string {
  if (at.kind === "computed") return `about mile ${at.mile.toFixed(1)}`;
  return at.metres <= MARKER_NEAR_M ? `mile marker ${mileFigure(at.mile)}` : `near mile marker ${mileFigure(at.mile)}`;
}

/**
 * The road panel's line for a trail way: "Mile marker 3, 300 ft (90 m) away" for a post, "About mile 3.2 here"
 * computed; US units first, metric in brackets.
 */
export function milePanelValue(at: TrailMile): string {
  if (at.kind === "computed") return `About mile ${at.mile.toFixed(1)} here`;
  return `Mile marker ${mileFigure(at.mile)}, ${formatDistance(at.metres)} away`;
}

export const MILE_PANEL_LABEL = "Trail mile";

/**
 * The road panel's summary line for the way found (its name, the panel's title) at `point` (the nearest
 * place on the way, else the spot asked about), or null when the way is not a trail the file knows.
 */
export function milePanelRow(data: TrailMiles | null | undefined, way: string | null | undefined, point: LonLat): { id: string; label: string; value: string } | null {
  const at = trailMileAt(data, way, point);
  return at ? { id: "trail-mile", label: MILE_PANEL_LABEL, value: milePanelValue(at) } : null;
}

// --- The map ---------------------------------------------------------------

export const MILES_SOURCE_ID = "trail-miles";
export const MILES_LAYER = "trail-miles";
export const MILES_LABEL_LAYER = "trail-miles-label";
/** The trail zooms: a marker a mile from the next means little further out. */
export const MILE_MIN_ZOOM = 14;
export const MILES_COLOUR = "#5b4a2f";
export const MILES_FONT = "Noto Sans Medium";

export function milesGeoJson(markers: readonly TrailMarker[]): object {
  return {
    type: "FeatureCollection",
    features: markers.map((m) => ({
      type: "Feature",
      properties: { id: m.id, label: mileFigure(m.mile) },
      geometry: { type: "Point", coordinates: [m.lon, m.lat] },
    })),
  };
}

/** A small brown post with a white ring, the trail-sign colour; the label beside it and the tap card say the figure. */
export function milesLayer(): Record<string, unknown> {
  return {
    id: MILES_LAYER,
    type: "circle",
    source: MILES_SOURCE_ID,
    minzoom: MILE_MIN_ZOOM,
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], MILE_MIN_ZOOM, 3.5, 17, 5.5],
      "circle-color": MILES_COLOUR,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1.5,
    },
  };
}

/** The posted figure beside the post, in text with a white halo, so it reads on any base. */
export function milesLabelLayer(): Record<string, unknown> {
  return {
    id: MILES_LABEL_LAYER,
    type: "symbol",
    source: MILES_SOURCE_ID,
    minzoom: MILE_MIN_ZOOM,
    layout: {
      "text-field": ["concat", "MM ", ["get", "label"]],
      "text-font": [MILES_FONT],
      // The street names' face, a little smaller: a number, not a name (the owner, 2026-10-21: "All into stret name style").
      "text-size": 13,
      "text-anchor": "left",
      "text-offset": [0.7, 0],
      "text-optional": true,
    },
    paint: { "text-color": MILES_COLOUR, "text-halo-color": "#ffffff", "text-halo-width": 3 },
  };
}

/** The tap card's lines: the trail and the marker, then where it is from. */
export function milesCard(marker: TrailMarker): string[] {
  return [marker.trail, `Mile marker ${mileFigure(marker.mile)}.`, "From OpenStreetMap."];
}
