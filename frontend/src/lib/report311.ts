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
 * and "Tree Removal". DPW places its bike lane enforcement officers partly by 311 requests (dpw.dc.gov/node/1442566,
 * 2019-11-12, read 2026-10-11). No request named for an obstructed roadway or bikeway was found there,
 * and 311.dc.gov itself could not be read from here (its robots.txt refuses fetches), so that hint
 * names none.
 *
 * The place (465, plan owner question 7): the nearest junction in the route's own street names, or on a
 * long trail the trail and a distance from one of its junctions (navigate.ts `placeOnRoute`). The
 * position is never looked up (no /api/reverse with it), and the message carries no coordinates.
 * Washington, DC only (369: "DC only for now"); elsewhere the action says so.
 */
import { spokenDistance } from "./format.ts";
import { otherStreet, type RoutePlace } from "./navigate.ts";

export const DC_311_SHORT_CODE = "32311";
export const DC_311_ONLINE = "https://311.dc.gov/";

export type ReportKind = "pothole" | "tree" | "bikeLane" | "obstruction" | "streetlight" | "other";

/**
 * What the rider picks (short, for a phone), DC's keyword for it (null: no keyword, 311 Online), the
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
    label: "Vehicle parked in bike lane",
    keyword: null,
    problem: "Vehicle parked in a bike lane",
    service: "In DC 311 online, a vehicle in a bike lane is a Parking Enforcement request.",
  },
  {
    kind: "obstruction",
    label: "Road or bikeway blocked",
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
  "The message goes to DC 311 from your own phone. RouteMaker sends nothing and keeps nothing. The place is the nearest junction on your route, so check it before you send.";
export const REPORT_OUTSIDE_DC = "Reports to 311 are for Washington, DC only, and this part of the route is outside the District.";
export const REPORT_NO_PLACE = "Your place on the route is not known yet, so there is no location to report.";
export const REPORT_OFF_ROUTE = "Off the planned route: the report's place comes from the route's street names, so it waits until you are back on a route.";
/** The short code said digit by digit (the text link's accessible name), not as one large number. */
export const SHORT_CODE_SPOKEN = "3 2 3 1 1";
export const REPORT_OTHER_HINT =
  "DC's text service takes potholes and streetlights by keyword; for anything else, open DC 311 online and paste the report.";
export const REPORT_NOTE_MAX = 120;

/** The place as the message says it (US units: it is the text DC receives). */
export function placeWords(place: RoutePlace): string | null {
  if (!place) return null;
  if (place.kind === "junction") return `near ${place.junction.streets[0]} and ${place.junction.streets[1]}`;
  if (place.kind === "trail") {
    return `on the ${place.trail}, about ${spokenDistance(place.metres)} ${place.direction} of ${otherStreet(place.junction, place.trail)}`;
  }
  return `on ${place.street}`;
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
 * The report: what (for a kind with no keyword), where, then the rider's note. `forText`: the text
 * message, with DC's keyword first where it has one; the copy for DC 311 online has no keyword (its
 * form asks what the problem is itself), but a kind with no keyword names the problem first.
 */
export function reportText(kind: ReportKind, place: RoutePlace, note = "", forText = false): string | null {
  const where = placeWords(place);
  if (!where) return null;
  const keyword = forText ? keywordOf(kind) : null;
  const tidy = note.replace(/\s+/g, " ").trim().slice(0, REPORT_NOTE_MAX);
  const problem = REPORT_KINDS.find((k) => k.kind === kind)?.problem ?? null;
  const what = keyword ? `${keyword} ` : problem ? `${problem}. ` : "";
  return `${what}Location: ${where}, Washington, DC.${tidy ? ` ${/[.!?]$/.test(tidy) ? tidy : `${tidy}.`}` : ""}`;
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
