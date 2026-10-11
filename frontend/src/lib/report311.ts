/**
 * Report to DC 311 from Ride mode (OWNER-DECISIONS 369, 370, 465; WEB-NAV-plan.md section 7 and
 * phase N6): a pothole, a streetlight out or anything else, with where it is from the route's own
 * street names, sent by the rider from their own phone. RouteMaker sends nothing and keeps nothing.
 *
 * DC's Text to 311 (ouc.dc.gov/service/text-311, read 2026-10-10): the short code is 32311; the keywords
 * POTHOLE, STREETLIGHT and TRASH go straight to that request, past the menu; anything else starts with
 * MENU, NEW or SERVICE, and "Other Service Requests" there sends the texter to 311 Online
 * (https://311.dc.gov/). The page names no keyword for a fallen tree, and does not say what the
 * service asks after the keyword. So: a pothole or a streetlight is a text starting with its keyword;
 * anything else is the same words to copy into 311 Online (370), which on a desktop is the one way
 * for everything, since a desktop has no texts.
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

export type ReportKind = "pothole" | "streetlight" | "other";

/** What the rider picks, and DC's keyword for it (null: no keyword, 311 Online). */
export const REPORT_KINDS: { kind: ReportKind; label: string; keyword: string | null }[] = [
  { kind: "pothole", label: "Pothole", keyword: "POTHOLE" },
  { kind: "streetlight", label: "Streetlight out", keyword: "STREETLIGHT" },
  { kind: "other", label: "Something else (a fallen tree, debris, a blocked lane)", keyword: null },
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

/**
 * The report: where, then the rider's note. `forText`: the text message, with DC's keyword first where
 * it has one; the copy for DC 311 online has none (its form asks what the problem is itself).
 */
export function reportText(kind: ReportKind, place: RoutePlace, note = "", forText = false): string | null {
  const where = placeWords(place);
  if (!where) return null;
  const keyword = forText ? keywordOf(kind) : null;
  const tidy = note.replace(/\s+/g, " ").trim().slice(0, REPORT_NOTE_MAX);
  const what = keyword ? `${keyword} ` : "";
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
