/**
 * A problem's place for 311 (OWNER-DECISIONS 369, 370, 465; WEB-NAV-plan.md section 7 and phase N6): the six
 * problems the rider picks from (the owner, 2026-10-11: "311 should have the following at least: Pothole /
 * Downed tree / Vehicle parked in a bike lane / Roadway/bikeway obstructed"), and where it is, from the
 * route's own street names and the GPS position. Since 2026-10-20 a pick is logged (lib/report311Log.ts),
 * not texted: DC's Text to 32311 answers every message, even a plain NEW, with only "Welcome to DC311"
 * (Stephen's screenshot of 2026-10-20), so the text never reported anything.
 *
 * The place (465, plan owner question 7; the owner, 2026-10-12: "Put the GPS coordinates in the 311.
 * Sometimes it says, about 1.2 miles south of unnamed path." and "Description if you can. Like put the
 * road and the coordinates"): the way the rider is on, in the route's own street names ("on 14th Street
 * Northwest", or plainly "on an unnamed path"), a cross street only when a named junction of the route
 * is within PLACE_NEAR_M ("near U Street Northwest"), never a distance from a far junction, and always
 * the GPS position: latitude then longitude in decimal degrees to 5 places (about 1 m), the point on the
 * route the words describe (`pointAt`).
 *
 * On a named trail (465: "some trails like the MBT and CCT should have mile markers as they can go a distance
 * without crossing a road"; Stephen, 2026-10-16: "Make sure the mile markers are added to 311 when built") the
 * words add the trail's mile (lib/trailMiles.ts, worked out on the phone): "on Capital Crescent Trail at mile
 * marker 3" where OSM maps a post within 500 ft, else "on Capital Crescent Trail at about mile 3.2".
 */
import type { LonLat } from "./geo.ts";
import { isUnnamed, pointAt, routeJunctions, stretchAt, wayRidden, type RideModel } from "./navigate.ts";
import { mileWords, trailMileAt, type TrailMiles } from "./trailMiles.ts";

export type ReportKind = "pothole" | "tree" | "bikeLane" | "obstruction" | "streetlight" | "other";

/** What the rider picks, in the owner's words and order (2026-10-11; "or" for the slash, which a screen reader reads aloud). */
export const REPORT_KINDS: { kind: ReportKind; label: string }[] = [
  { kind: "pothole", label: "Pothole" },
  { kind: "tree", label: "Downed tree" },
  { kind: "bikeLane", label: "Vehicle parked in a bike lane" },
  { kind: "obstruction", label: "Roadway or bikeway obstructed" },
  { kind: "streetlight", label: "Streetlight out" },
  { kind: "other", label: "Something else" },
];

/**
 * A cross street farther than this (500 ft, about 0.1 mi) from the rider is too far to help DC find the
 * spot (the old "about 1.2 miles south of ..."), so the report names only the way the rider is on, and
 * the GPS position carries the place.
 */
export const PLACE_NEAR_M = 500 / 3.28084;

/** Whether a street name says nothing ("unnamed path"): shared with "Where am I?" (lib/navigate.ts). */
export { isUnnamed };

/**
 * The place words (the owner, 2026-10-12: "Description if you can. Like put the road and the
 * coordinates"): "on <the way ridden>", then on a trail "at <its mile>" (465), then "near <cross street>"
 * when a named junction of the route is within PLACE_NEAR_M. Never a distance from a far junction. Null
 * when nothing is known.
 */
export function placeWords(way: string | null, cross: string | null, mile: string | null = null): string | null {
  const near = cross ? ` near ${cross}` : "";
  if (way) return `on ${way}${mile ? ` at ${mile}` : ""}${near}`;
  return cross ? `near ${cross}` : null;
}

/** The GPS position as the report says it: "GPS 38.91234, -77.01234" (latitude first, 5 decimals, about 1 m). */
export function gpsWords(point: LonLat): string {
  return `GPS ${point[1].toFixed(5)}, ${point[0].toFixed(5)}`;
}

/** Where the report says the rider is: the words (null when none are known) and the GPS point. */
export interface ReportPlace {
  words: string | null;
  point: LonLat;
}

/**
 * The rider's place for the report at `progressM`: the way ridden there (the route's own street names),
 * on a trail in `miles` its mile there (lib/trailMiles.ts), the nearest named junction's other street
 * when within PLACE_NEAR_M, and always the point on the route there (`pointAt`, the same point the words
 * describe).
 */
export function reportPlace(model: RideModel, progressM: number, miles: TrailMiles | null = null): ReportPlace {
  const stretch = stretchAt(model, progressM);
  const way = wayRidden(stretch);
  let cross: string | null = null;
  let best = PLACE_NEAR_M;
  for (const j of routeJunctions(model)) {
    const d = Math.abs(j.atM - progressM);
    if (d > best) continue;
    // The junction's street that is not the one ridden ("on 14th St NW near U St NW").
    const other = j.streets[0] === stretch?.street ? j.streets[1] : j.streets[1] === stretch?.street ? j.streets[0] : j.streets[1];
    if (isUnnamed(other)) continue;
    cross = other;
    best = d;
  }
  const point = pointAt(model, progressM);
  const mile = isUnnamed(stretch?.street) ? null : trailMileAt(miles, stretch?.street, point);
  return { words: placeWords(way, cross, mile ? mileWords(mile) : null), point };
}

// ---- Sent by the server (v0.7.0, "Go riding fixes" item 3) ------------------------------------------
//
// Where the server has DC's Open311 key (GET /api/report311, core/dc311.py; off unless the deployment sets
// DC311_API_KEY), a DC pick in a ride is also sent there, and its log entry is checked off as reported.

export const REPORT_SENT = "Sent to DC 311.";

type Fetch = typeof fetch;

/** Whether the server sends reports to DC 311 itself (GET /api/report311); false when it cannot be asked. */
export async function report311Enabled(origin: string, get: Fetch = fetch): Promise<boolean> {
  try {
    const response = await get(`${origin}/api/report311`, { headers: { Accept: "application/json" } });
    if (!response.ok) return false;
    const body = (await response.json()) as { enabled?: unknown };
    return body.enabled === true;
  } catch {
    return false;
  }
}

/**
 * Send one report through the server (POST /api/report311): the problem, the point the words describe and
 * the report's words (lib/report311Log.ts entryText). True when DC took it; false otherwise (off, refused,
 * no signal), and the entry stays on the checklist.
 */
export async function sendReport311(origin: string, kind: ReportKind, place: ReportPlace, description: string, post: Fetch = fetch): Promise<boolean> {
  try {
    // A fresh short-lived ticket from GET /api/report311 first: the server takes a send only with one.
    const status = await post(`${origin}/api/report311`, { headers: { Accept: "application/json" } });
    if (!status.ok) return false;
    const { ticket } = (await status.json()) as { ticket?: unknown };
    if (typeof ticket !== "string") return false;
    const response = await post(`${origin}/api/report311`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ kind, lat: Number(place.point[1].toFixed(5)), lon: Number(place.point[0].toFixed(5)), description, ticket }),
    });
    if (!response.ok) return false;
    const body = (await response.json()) as { sent?: unknown };
    return body.sent === true;
  } catch {
    return false;
  }
}
