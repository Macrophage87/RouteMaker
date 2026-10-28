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
import { t } from "./i18n.ts";

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
    label: t("Classic bike"),
    hint: t("A few gears and heavy: slower, and hills count against a route."),
  },
  {
    id: "ebike",
    label: t("E-bike"),
    hint: t("Assisted: hills barely count and the pace is faster. It may also start from an e-bike left outside a dock."),
  },
];

export function bikeLabel(bike: Bike): string {
  return BIKES.find((b) => b.id === bike)?.label ?? bike;
}

/** The plan's heading: "Bikeshare plan: classic bike", or on a Rebalance Ride "Rebalance Ride: classic bike". */
export function planHeading(plan: Pick<BikesharePlan, "bike" | "rebalance">): string {
  return `${plan.rebalance ? "Rebalance Ride" : "Bikeshare plan"}: ${bikeLabel(plan.bike).toLowerCase()}`;
}

export function bikeshareOf(route: Pick<RouteResponse, "bikeshare"> | null | undefined): BikesharePlan | null {
  return route?.bikeshare ?? null;
}

/** Whether bikeshare data is displayed with this route: its credit goes wherever it is. */
export function showsBikeshare(route: Pick<RouteResponse, "bikeshare"> | null | undefined): boolean {
  return bikeshareOf(route) !== null;
}

/** The route panel's credits: the route's own, and the bikeshare source citation wherever bikeshare data is shown. */
export function routeCredits(route: Pick<RouteResponse, "attribution" | "bikeshare" | "transit">): string[] {
  const credits = [...route.attribution];
  if (bikeshareOf(route) && !credits.includes(BIKESHARE_CREDIT)) credits.push(BIKESHARE_CREDIT);
  // A transit ride type's schedule sources (each system's, from systems.json), and the operator's wherever its docks are used.
  if (route.transit) {
    if (route.transit.mode === "bikeshare-transit" && !credits.includes(BIKESHARE_CREDIT)) credits.push(BIKESHARE_CREDIT);
    for (const credit of route.transit.credits) if (!credits.includes(credit)) credits.push(credit);
  }
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
  features: { type: "Feature"; properties: { leg: "start" | "end" | "past" }; geometry: { type: "LineString"; coordinates: LonLat[] } }[];
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

/** The walk legs a route draws: a Bikeshare plan's, else the walks at its ends where the ride stops short (`walk_in`). */
export function routeWalkFeatures(route: RouteResponse | null): WalkFeatureCollection {
  const plan = bikeshareOf(route);
  if (plan) return walkFeatures(plan);
  const features: WalkFeatureCollection["features"] = [];
  for (const leg of ["start", "end"] as const) {
    const walk = route?.walk_in?.[leg];
    if (walk && walk.geometry.coordinates.length >= 2) features.push({ type: "Feature", properties: { leg }, geometry: walk.geometry });
  }
  // Novice and Nervous's walks past a short busy stretch, on the sidewalk beside it (v0.11.0; core.novice_walks).
  for (const walk of route?.novice?.walks ?? []) {
    if (walk.geometry.coordinates.length >= 2) features.push({ type: "Feature", properties: { leg: "past" }, geometry: walk.geometry });
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

/** A dock's count in words: "5 classic bikes available" to take a bike, "3 free slots" to return one. */
export function dockCountWords(stop: BikeshareStop, bike: Bike, taking: boolean): string {
  // Whole phrases, so a language with its own plural and word order says them its own way (routing audit D30).
  if (stop.availability === "unknown") return t("availability unknown");
  if (taking) {
    const n = stop.bikes_available ?? 0;
    if (bike === "ebike") return n === 1 ? t("1 e-bike available") : t("{n} e-bikes available", { n });
    return n === 1 ? t("1 classic bike available") : t("{n} classic bikes available", { n });
  }
  const n = stop.docks_available ?? 0;
  return n === 1 ? t("1 free slot") : t("{n} free slots", { n });
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
        ? t("Step 1: take an e-bike parked outside a dock")
        : plan.bike === "ebike"
          ? t("Step 1: take an e-bike at the dock at {place}, {count}", { place: start.name, count: dockCountWords(start, plan.bike, true) })
          : t("Step 1: take a classic bike at the dock at {place}, {count}", { place: start.name, count: dockCountWords(start, plan.bike, true) }),
  });
  if (end.kind === "dock") {
    markers.push({
      role: "return",
      lon: end.lon,
      lat: end.lat,
      badge: "2",
      label: t("Step 2: return the bike at the dock at {place}, {count}", { place: end.name, count: dockCountWords(end, plan.bike, false) }),
    });
  }
  return markers;
}

// --- The words -------------------------------------------------------------------

/** What a screen reader hears when a bikeshare plan arrives: the plan in plain words, US units first. */
export function bikeshareSaid(route: Pick<RouteResponse, "bikeshare">): string | null {
  const plan = bikeshareOf(route);
  if (!plan) return null;
  const said = t("Bikeshare plan: {summary}", { summary: plan.summary });
  return plan.availability === "unknown" ? `${said} ${t("Availability is unknown.")}` : said;
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
