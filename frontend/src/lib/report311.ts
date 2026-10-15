/**
 * Report to DC 311 from Ride mode (OWNER-DECISIONS 369, 370, 465; WEB-NAV-plan.md section 7 and
 * phase N6): a pothole, a downed tree, a vehicle parked in a bike lane, a roadway or bikeway
 * obstructed, a streetlight out or anything else (the owner, 2026-10-11: "311 should have the following
 * at least: Pothole / Downed tree / Vehicle parked in a bike lane / Roadway/bikeway obstructed"), with
 * where it is from the route's own street names, sent by the rider from their own phone. RouteMaker
 * sends nothing and keeps nothing.
 *
 * DC's Text to 311 (ouc.dc.gov/service/text-311, read 2026-10-10 and again 2026-10-11): the short code
 * is 32311; the keywords POTHOLE, STREETLIGHT and TRASH go straight to that request, past the menu;
 * anything else starts with MENU, NEW or SERVICE, and "Other Service Requests" there sends the texter
 * to 311 Online (https://311.dc.gov/). The page names no keyword for a tree, a parked vehicle or an
 * obstruction, and does not say what the service asks after the keyword. So: a pothole or a
 * streetlight is a text starting with its keyword; anything else is the same words to copy into 311
 * Online (370), which on a desktop is the one way for everything, since a desktop has no texts. A kind
 * with no keyword names the problem at the start of the words ("Downed tree. Location: ..."), so DC
 * knows what it is without the rider's note.
 *
 * DC 311 Online's request names (DC GIS, "SR_30days_Open" service requests of the last 30 days,
 * https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_APPS/SR_30days_Open/MapServer/0, distinct
 * SERVICECODEDESCRIPTION values, read 2026-10-11) include "Parking Enforcement", "Tree Inspection"
 * and "Tree Removal". Neither source says which request a vehicle in a bike lane is, so the hint
 * only names Parking Enforcement as one of DC's parking requests, not as the one to pick. DPW places its bike lane enforcement officers partly by 311 requests (dpw.dc.gov/node/1442566,
 * 2019-11-12, read 2026-10-11). No request named for an obstructed roadway or bikeway was found there,
 * and 311.dc.gov itself could not be read from here (its robots.txt refuses fetches), so that hint
 * names none.
 *
 * The place (465, plan owner question 7; the owner, 2026-10-12: "Put the GPS coordinates in the 311.
 * Sometimes it says, about 1.2 miles south of unnamed path." and "Description if you can. Like put the
 * road and the coordinates"): the way the rider is on, in the route's own street names ("on 14th Street
 * Northwest", or plainly "on an unnamed path"), a cross street only when a named junction of the route
 * is within PLACE_NEAR_M ("near U Street Northwest"), never a distance from a far junction, and always
 * the GPS position: latitude then longitude in decimal degrees to 5 places (about 1 m), the point on the
 * route the words describe (`pointAt`). The position is never looked up (no /api/reverse with
 * it); it leaves the phone only in the message the rider sends. Washington, DC only (369: "DC only for
 * now"); elsewhere the action says so.
 */
import type { LonLat } from "./geo.ts";
import { isUnnamed, pointAt, routeJunctions, stretchAt, wayRidden, type RideModel } from "./navigate.ts";

export const DC_311_SHORT_CODE = "32311";
export const DC_311_ONLINE = "https://311.dc.gov/";

export type ReportKind = "pothole" | "tree" | "bikeLane" | "obstruction" | "streetlight" | "other";

/**
 * What the rider picks (the owner's words, 2026-10-11; "or" for the slash, which a screen reader reads aloud), DC's keyword for it (null: no keyword, 311 Online), the
 * problem as the words for 311 Online name it where there is no keyword (null: the keyword says it, or
 * the rider's note does), and a line on DC 311 Online's request for it (null: none to name).
 */
export const REPORT_KINDS: { kind: ReportKind; label: string; keyword: string | null; problem: string | null; service: string | null }[] = [
  { kind: "pothole", label: "Pothole", keyword: "POTHOLE", problem: null, service: null },
  {
    kind: "tree",
    label: "Downed tree",
    keyword: null,
    problem: "Downed tree",
    service: "DC 311 online's tree requests include Tree Inspection and Tree Removal.",
  },
  {
    kind: "bikeLane",
    label: "Vehicle parked in a bike lane",
    keyword: null,
    problem: "Vehicle parked in a bike lane",
    service: "DC 311 online's parking requests include Parking Enforcement.",
  },
  {
    kind: "obstruction",
    label: "Roadway or bikeway obstructed",
    keyword: null,
    problem: "Roadway or bikeway obstructed",
    service: "Pick the DC 311 online request that fits best; the report says what it is.",
  },
  { kind: "streetlight", label: "Streetlight out", keyword: "STREETLIGHT", problem: null, service: null },
  { kind: "other", label: "Something else", keyword: null, problem: null, service: "Say what it is in the note, so DC knows." },
];

export const REPORT_SUMMARY = "Report a problem to DC 311";
/** Said on the screen beside the action (369: "the screen says the message goes to DC 311"). */
export const REPORT_PRIVACY =
  "The message goes to DC 311 from your own phone. RouteMaker sends nothing and keeps nothing. The place is the road you are on and your GPS position, so check it before you send.";
/** The same where the server sends reports to DC 311 itself (it has DC's key; core/dc311.py). */
export const REPORT_PRIVACY_SERVER =
  "A problem you pick is sent to DC 311 by RouteMaker's server, with the road you are on and your GPS position. RouteMaker keeps nothing.";
export const REPORT_OUTSIDE_DC = "Reports to 311 are for Washington, DC only, and this part of the route is outside the District.";
export const REPORT_NO_PLACE = "Your place on the route is not known yet, so there is no location to report.";
export const REPORT_OFF_ROUTE = "Off the planned route: the report's place comes from the route's street names, so it waits until you are back on a route.";
/** The short code said digit by digit (the text link's accessible name), not as one large number. */
export const SHORT_CODE_SPOKEN = "3 2 3 1 1";
export const REPORT_OTHER_HINT =
  "DC's text service takes potholes and streetlights by keyword; for anything else, open DC 311 online and paste the report.";
export const REPORT_NOTE_MAX = 120;

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
 * coordinates"): "on <the way ridden>", then "near <cross street>" when a named junction of the route is
 * within PLACE_NEAR_M. Never a distance from a far junction. Null when neither is known.
 */
export function placeWords(way: string | null, cross: string | null): string | null {
  if (way) return cross ? `on ${way} near ${cross}` : `on ${way}`;
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
 * the nearest named junction's other street when within PLACE_NEAR_M, and always the point on the
 * route there (`pointAt`, the same point the words describe).
 */
export function reportPlace(model: RideModel, progressM: number): ReportPlace {
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
  return { words: placeWords(way, cross), point: pointAt(model, progressM) };
}

/** DC's text keyword for a kind, or null where it has none. */
export function keywordOf(kind: ReportKind): string | null {
  return REPORT_KINDS.find((k) => k.kind === kind)?.keyword ?? null;
}

/** The hint beside DC 311 online for a kind with no keyword: why online, then its request there. */
export function onlineHint(kind: ReportKind): string | null {
  const k = REPORT_KINDS.find((r) => r.kind === kind);
  if (!k || k.keyword) return null;
  return k.service ? `${REPORT_OTHER_HINT} ${k.service}` : REPORT_OTHER_HINT;
}

/**
 * The report: what (for a kind with no keyword), where (the words, when any help, then the GPS
 * position), then the rider's note. `forText`: the text message, with DC's keyword first where it has
 * one; the copy for DC 311 online has no keyword (its form asks what the problem is itself), but a kind
 * with no keyword names the problem first. The only cap is the note's (REPORT_NOTE_MAX); the
 * coordinates are never trimmed.
 */
export function reportText(kind: ReportKind, place: ReportPlace | null, note = "", forText = false): string | null {
  if (!place) return null;
  const where = `${place.words ? `${place.words}, ` : ""}Washington, DC. ${gpsWords(place.point)}`;
  const keyword = forText ? keywordOf(kind) : null;
  const tidy = note.replace(/\s+/g, " ").trim().slice(0, REPORT_NOTE_MAX);
  const problem = REPORT_KINDS.find((k) => k.kind === kind)?.problem ?? null;
  const what = keyword ? `${keyword} ` : problem ? `${problem}. ` : "";
  return `${what}Location: ${where}.${tidy ? ` ${/[.!?]$/.test(tidy) ? tidy : `${tidy}.`}` : ""}`;
}

/** Whether the browser is a phone's, which can send a text (Android, iPhone, an iPad, which says it is a Mac). */
export function canText(userAgent: string, maxTouchPoints = 0): boolean {
  return /Android|iPhone|iPad|iPod/i.test(userAgent) || (/Macintosh/.test(userAgent) && maxTouchPoints > 1);
}

function isApple(userAgent: string, maxTouchPoints: number): boolean {
  return /iPhone|iPad|iPod/i.test(userAgent) || (/Macintosh/.test(userAgent) && maxTouchPoints > 1);
}

/**
 * The sms: link (369: "Handle the iOS/Android sms body syntax differences"): iOS's Messages reads the
 * body after "&" (sms:32311&body=...), Android's after "?" (RFC 5724, sms:32311?body=...).
 */
export function smsHref(text: string, userAgent: string, maxTouchPoints = 0): string {
  const join = isApple(userAgent, maxTouchPoints) ? "&" : "?";
  return `sms:${DC_311_SHORT_CODE}${join}body=${encodeURIComponent(text)}`;
}

// ---- One tap (v0.7.0, "Go riding fixes" item 3) -----------------------------------------------------
//
// The owner, 2026-10-15: "When reporting to 311 you should be able to select the report and send it. Too
// many steps in between." So: tap 311, tap the problem, sent. Where the server sends to DC 311 itself (it
// has DC's Open311 key: GET /api/report311, core/dc311.py), the pick sends it there; otherwise, on a phone,
// the pick opens the text app to 311 with the problem, the place and the GPS filled in, one tap from sent;
// on a computer, which sends no texts, the report opens below to copy into DC 311 online. The note is
// optional and comes after, never before: "Add a note" opens the report, with the note under the sending.

export const REPORT_SENT = "Sent to DC 311.";
export const REPORT_READY = "Ready to send in Messages.";
export const REPORT_FORM = "The report is below, to copy into DC 311 online.";
export const REPORT_SEND_FAILED = "Could not send to DC 311 from here; the report is ready in Messages.";

/** How a pick goes: sent by the server, a filled-in text message, or the report to copy. */
export type PickWay = "server" | "sms" | "form";

export function pickWay(serverOn: boolean, phone: boolean): PickWay {
  return serverOn ? "server" : phone ? "sms" : "form";
}

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
 * the words for DC 311 online. True when DC took it; false otherwise (off, refused, no signal), and the pick
 * falls back to the text message.
 */
export async function sendReport311(origin: string, kind: ReportKind, place: ReportPlace, note = "", post: Fetch = fetch): Promise<boolean> {
  const description = reportText(kind, place, note);
  if (!description) return false;
  try {
    const response = await post(`${origin}/api/report311`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ kind, lat: Number(place.point[1].toFixed(5)), lon: Number(place.point[0].toFixed(5)), description }),
    });
    if (!response.ok) return false;
    const body = (await response.json()) as { sent?: unknown };
    return body.sent === true;
  } catch {
    return false;
  }
}
