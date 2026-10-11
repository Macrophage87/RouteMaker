/**
 * Bikeshare on the page (FOLLOWUP-BIKESHARE, OWNER-DECISIONS 243-245, 299-301): the words,
 * the map's walk legs and dock markers, and the credit, as plain functions so they can be
 * tested without a browser.
 *
 * The data comes from the API's `bikeshare` object, planned server side from the operator's
 * GBFS feeds; the page fetches nothing from the operator and keeps nothing of it. The
 * controls and the markers say "Bikeshare" and name no operator and show no mark; the one
 * place the operator is named is the plain source citation, `BIKESHARE_CREDIT`
 * (OWNER-DECISIONS 301), shown wherever bikeshare data is.
 */
import type { BikeshareEnding, BikesharePlan, BikeshareStop, RouteResponse } from "./api.ts";
import type { Bike, Ending } from "./dials.ts";
import { formatDistance, formatDuration } from "./format.ts";
import type { LonLat } from "./geo.ts";

/**
 * The source citation (OWNER-DECISIONS 301: "Even if the license doesn't require crediting
 * them, sources need citing."), as the operator's name alone (OWNER-DECISIONS 304: "don't clog
 * up the map with extra words"): plain text, no logo, no brand styling, no wording of
 * affiliation. The fuller description is in docs/OPERATIONS.md. The same words as `core.gbfs.CREDIT`, which tests/test_bikeshare_api.py holds
 * this to. The owner confirms the wording.
 */
export const BIKESHARE_CREDIT = "Capital Bikeshare";

/** The operator's page on e-bike parking rules (OWNER-DECISIONS 305), shown as text and a link. */
export const EBIKE_PAGE = "https://capitalbikeshare.com/how-it-works/ebike";

/** A sentence as text and links: the e-bike page's address becomes a link, the rest stays text. */
export function linkParts(text: string): { text: string; href?: string }[] {
  const at = text.indexOf(EBIKE_PAGE);
  if (at < 0) return [{ text }];
  const parts: { text: string; href?: string }[] = [];
  if (at > 0) parts.push({ text: text.slice(0, at) });
  parts.push({ text: EBIKE_PAGE, href: EBIKE_PAGE });
  const rest = text.slice(at + EBIKE_PAGE.length);
  if (rest) parts.push({ text: rest });
  return parts;
}

export const BIKES: readonly { id: Bike; label: string; hint: string }[] = [
  {
    id: "classic",
    label: "Classic bike",
    hint: "A few gears and heavy: slower, and hills count against a route.",
  },
  {
    id: "ebike",
    label: "E-bike",
    hint: "Assisted: hills barely count and the pace is faster. It may also start from an e-bike left outside a dock.",
  },
];

export function bikeLabel(bike: Bike): string {
  return BIKES.find((b) => b.id === bike)?.label ?? bike;
}

export function bikeshareOf(route: Pick<RouteResponse, "bikeshare"> | null | undefined): BikesharePlan | null {
  return route?.bikeshare ?? null;
}

/** Whether bikeshare data is displayed with this route: its credit goes wherever it is. */
export function showsBikeshare(route: Pick<RouteResponse, "bikeshare"> | null | undefined): boolean {
  return bikeshareOf(route) !== null;
}

/** The route panel's credits: the route's own, and the bikeshare source citation wherever bikeshare data is shown. */
export function routeCredits(route: Pick<RouteResponse, "attribution" | "bikeshare">): string[] {
  const credits = [...route.attribution];
  if (bikeshareOf(route) && !credits.includes(BIKESHARE_CREDIT)) credits.push(BIKESHARE_CREDIT);
  return credits;
}

// --- The map -------------------------------------------------------------------

/**
 * Walk legs are drawn dotted, in a dark neutral with a white casing, against the route's
 * solid line in its stress colours: told apart by pattern and width, never by colour alone,
 * and the panel's legend and steps name them.
 */
export const WALK_COLOUR = "#3d3d3d";
export const WALK_CASING = "#ffffff";
export const WALK_LINE_WIDTH = 4;
export const WALK_CASING_WIDTH = 8;
/** In line widths: a dot and a gap (line-dasharray, with round caps for dots). */
export const WALK_DASH: [number, number] = [0.1, 2];

export interface WalkFeatureCollection {
  type: "FeatureCollection";
  features: { type: "Feature"; properties: { leg: "start" | "end" }; geometry: { type: "LineString"; coordinates: LonLat[] } }[];
}

export function walkFeatures(plan: BikesharePlan | null): WalkFeatureCollection {
  const features: WalkFeatureCollection["features"] = [];
  if (plan?.walk_start && plan.walk_start.geometry.coordinates.length >= 2) {
    features.push({ type: "Feature", properties: { leg: "start" }, geometry: plan.walk_start.geometry });
  }
  if (plan?.walk_end && plan.walk_end.geometry.coordinates.length >= 2) {
    features.push({ type: "Feature", properties: { leg: "end" }, geometry: plan.walk_end.geometry });
  }
  return { type: "FeatureCollection", features };
}

export interface DockMarker {
  role: "take" | "return";
  lon: number;
  lat: number;
  /** The badge on the marker: 1 to take a bike, 2 to return it (shape and number, not colour). */
  badge: "1" | "2";
  /** What a screen reader says: the whole text equivalent of the marker. */
  label: string;
}

function countWords(stop: BikeshareStop, bike: Bike, taking: boolean): string {
  if (stop.availability === "unknown") return "availability unknown";
  if (taking) {
    const n = stop.bikes_available ?? 0;
    return `${n} ${bike === "ebike" ? (n === 1 ? "e-bike" : "e-bikes") : n === 1 ? "classic bike" : "classic bikes"} available`;
  }
  const n = stop.docks_available ?? 0;
  return `${n} ${n === 1 ? "free slot" : "free slots"}`;
}

/** Where a bike is taken and where it is returned, as markers; an out-of-dock end has no marker of its own (the End point is there). */
export function dockMarkers(plan: BikesharePlan | null): DockMarker[] {
  if (!plan) return [];
  const markers: DockMarker[] = [];
  const { start, end } = plan;
  markers.push({
    role: "take",
    lon: start.lon,
    lat: start.lat,
    badge: "1",
    label:
      start.kind === "free_bike"
        ? "Step 1: take an e-bike parked outside a dock"
        : `Step 1: take ${plan.bike === "ebike" ? "an e-bike" : "a classic bike"} at the dock at ${start.name}, ${countWords(start, plan.bike, true)}`,
  });
  if (end.kind === "dock") {
    markers.push({
      role: "return",
      lon: end.lon,
      lat: end.lat,
      badge: "2",
      label: `Step 2: return the bike at the dock at ${end.name}, ${countWords(end, plan.bike, false)}`,
    });
  }
  return markers;
}

// --- The words -------------------------------------------------------------------

/** What a screen reader hears when a bikeshare plan arrives: the plan in plain words, US units first. */
export function bikeshareSaid(route: Pick<RouteResponse, "bikeshare">): string | null {
  const plan = bikeshareOf(route);
  if (!plan) return null;
  const unknown = plan.availability === "unknown" ? " Availability is unknown." : "";
  return `Bikeshare plan: ${plan.summary}${unknown}`;
}

/** The totals, as dt/dd rows: walking, riding, and both. */
export function totals(plan: BikesharePlan): { label: string; value: string }[] {
  return [
    { label: "Walking", value: `${formatDistance(plan.walk_m)}, ${formatDuration(plan.walk_s)}` },
    { label: "Riding", value: `${formatDistance(plan.ride_m)}, ${formatDuration(plan.ride_s)}` },
    { label: "Total time, without stops", value: formatDuration(plan.total_s) },
  ];
}

export function availabilityLine(plan: BikesharePlan): string {
  switch (plan.availability) {
    case "live":
      return "Bike and dock availability is the operator's live count, a minute or so old at most.";
    case "stale":
      return "Availability is from a minute or two ago: the operator's feed did not answer just now.";
    default:
      return "Availability is unknown: the operator's feed could not be read, so docks were chosen by distance alone.";
  }
}

/** The ending choices: only the offered ones can be chosen; the others say why not. */
export function endingChoices(plan: BikesharePlan): { offered: BikeshareEnding[]; declined: BikeshareEnding[] } {
  return {
    offered: plan.endings.filter((e) => e.offered),
    declined: plan.endings.filter((e) => !e.offered && e.reason !== "classic_bikes_end_at_docks"),
  };
}

export function endingLabel(kind: Ending): string {
  return kind === "outside_dock" ? "At your destination, outside a dock" : "At a dock, then walk";
}

/** Whether the choice of ending is a real one: more than the dock is offered. */
export function hasEndingChoice(plan: BikesharePlan): boolean {
  return endingChoices(plan).offered.length > 1;
}
