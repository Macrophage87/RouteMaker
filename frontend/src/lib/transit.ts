/**
 * The transit ride types on the page (TRANSIT-ASSIST; Stephen, 2026-10-12): Own Bike + 🚆🚌 and
 * Bikeshare + 🚶🚆🚌. The API answers each with its best combination (core.transit): the route's
 * line is the first ride leg, and the route's `transit` object is the whole trip, step by step, with
 * a scheduled total and the time of riding the whole way. These are the words, the map's lines and
 * markers and the credit, as plain functions so they can be tested without a browser.
 *
 * Every time here is scheduled (WMATA's static timetables), not live: the words say "about" and
 * "scheduled" wherever a total is given.
 */
import type { ClosedStation, RouteResponse, TransitOption, TransitPlan, TransitStep } from "./api.ts";
import type { Dials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import { isTransit, presetSaid, type PresetId } from "./presets.ts";
import { legsSaid, legsText } from "./transitMarks.ts";

export function transitOf(route: Pick<RouteResponse, "transit"> | null | undefined): TransitPlan | null {
  return route?.transit ?? null;
}

/** The route's door-to-door time as the totals show it: "about 28 min". */
export function transitTime(plan: TransitPlan): string {
  return `about ${plan.minutes} min`;
}

/** The list's name, which a screen reader announces with the list. */
export const STEPS_LABEL = "Steps, in order";
/** The options' list's name (the owner, 2026-10-12: riding directly there always, then the quickest). */
export const OPTIONS_LABEL = "Trips, quickest first";
/** Said under every transit plan: the timetables carry only the closures an agency published in them. */
export const TRACK_WORK = "Scheduled service; check for track work.";

/** Whether an option's row shows its legs as marks: a trip with a transit leg (Stephen, 2026-10-12). */
function marked(option: Pick<TransitOption, "legs">): boolean {
  return (option.legs ?? []).some((leg) => leg.mode !== "walk" && leg.mode !== "ride" && leg.mode !== "bikeshare");
}

/**
 * An option as its button shows it: "A. Ride the whole way: about 12 min", and a transit trip by its
 * legs, "B. 🚶 4 min · 🔴 18 min · 🚶 3 min: about 25 min" (the marks aria-hidden: `optionSaid`).
 */
export function optionText(option: Pick<TransitOption, "label" | "minutes" | "legs">, index: number): string {
  const what = marked(option) ? legsText(option.legs ?? []) : option.label;
  return `${String.fromCharCode(65 + index)}. ${what}: about ${option.minutes} min`;
}

/** The same option in words: "B. walk 4 minutes, Red Line 18 minutes, walk 3 minutes: about 25 min". */
export function optionSaid(option: Pick<TransitOption, "label" | "minutes" | "legs">, index: number): string {
  const what = marked(option) ? legsSaid(option.legs ?? []) : option.label;
  return `${String.fromCharCode(65 + index)}. ${what}: about ${option.minutes} min`;
}

/** What is said when an option is chosen. */
export function optionChosenSaid(option: Pick<TransitOption, "label" | "minutes">): string {
  return `Planning ${option.label}, about ${option.minutes} min.`;
}

/** The option the rider chose, held for one trip (its start and end), so a new trip starts from the quickest. */
export interface TransitPick {
  trip: string;
  key: string;
}

/** The request's dials with the chosen option, on a transit ride type and for the same trip only. */
export function withTransitOption(dials: Dials, preset: PresetId, pick: TransitPick | null, trip: string): Dials {
  const { transitOption: _old, ...rest } = dials;
  return isTransit(preset) && pick && pick.trip === trip ? { ...rest, transitOption: pick.key } : rest;
}

/** A station closed for the day, in words: "Camden Station, closed: no MARC weekend service". */
export function closedName(station: Pick<ClosedStation, "name" | "reason">): string {
  return `${station.name}, closed: ${station.reason}`;
}

/** What a screen reader hears when the plan arrives: the total, scheduled, and the comparison. Brief. */
export function transitSaid(route: Pick<RouteResponse, "transit">): string | null {
  const plan = transitOf(route);
  if (!plan) return null;
  const parts = [`${presetSaid(plan.mode)} planned: ${plan.summary}`];
  if (plan.comparison) parts.push(plan.comparison);
  if (plan.bike_blackout) parts.push("Bikes aren't allowed on Metro today.");
  return parts.join(" ");
}

// --- The map -------------------------------------------------------------------

/**
 * How each step is drawn past the route's own line, told apart by pattern and never by colour
 * alone (the markers name Metro and the bus in text, and the panel lists every step):
 * Metro and bus dashed, walks dotted (as Bikeshare's), the far end's ride solid and thinner.
 */
export type TransitDraw = "transit" | "walk" | "ride";

export const TRANSIT_COLOUR = "#5b21b6";
export const TRANSIT_CASING = "#ffffff";
export const TRANSIT_LINE_WIDTH = 4;
export const TRANSIT_CASING_WIDTH = 8;
/** In line widths: a long dash and a gap. */
export const TRANSIT_DASH: [number, number] = [2.5, 1.5];
export const RIDE_COLOUR = "#1d4ed8";
export const RIDE_LINE_WIDTH = 4;

export function drawOf(step: Pick<TransitStep, "mode">): TransitDraw | null {
  switch (step.mode) {
    case "metro":
    case "rail":
    case "light-rail":
    case "subway":
    case "bus":
      return "transit";
    case "walk":
    case "take":
      return "walk";
    case "ride":
    case "bikeshare":
      return "ride";
    default:
      return null;
  }
}

export interface TransitFeatureCollection {
  type: "FeatureCollection";
  features: { type: "Feature"; properties: { draw: TransitDraw }; geometry: { type: "LineString"; coordinates: LonLat[] } }[];
}

export function transitFeatures(plan: TransitPlan | null): TransitFeatureCollection {
  const features: TransitFeatureCollection["features"] = [];
  for (const step of plan?.steps ?? []) {
    const draw = drawOf(step);
    if (!draw || step.route_line || step.coordinates.length < 2) continue;
    features.push({ type: "Feature", properties: { draw }, geometry: { type: "LineString", coordinates: step.coordinates } });
  }
  return { type: "FeatureCollection", features };
}

/** The map's attribution while a transit trip shows: the timetables it uses, from the plan's own credits. */
export function transitAttribution(plan: Pick<TransitPlan, "credits"> | null): string {
  return plan ? plan.credits.join("; ") : "";
}

export interface TransitMarker {
  lon: number;
  lat: number;
  /** On the marker: "Metro" or "Bus", in text, so colour is not the only cue. */
  badge: string;
  /** What a screen reader says: the marker's whole text equivalent. */
  label: string;
}

function middle(points: readonly LonLat[]): LonLat {
  return points[Math.floor((points.length - 1) / 2)];
}

/** One text marker on each transit step, at its middle stop: "Metro", "MARC", "Bus". */
export function transitMarkers(plan: TransitPlan | null): TransitMarker[] {
  const out: TransitMarker[] = [];
  for (const step of plan?.steps ?? []) {
    if (drawOf(step) !== "transit" || step.coordinates.length < 2) continue;
    const [lon, lat] = middle(step.coordinates);
    const lines = step.lines.join(" or ");
    const bus = step.mode === "bus";
    const badge = bus ? "Bus" : (step.system ?? "Train");
    const sameName = !bus && lines.toLowerCase() === badge.toLowerCase();
    const named = bus ? `Bus ${lines}` : sameName ? badge : `${badge}, ${lines}`;
    out.push({ lon, lat, badge, label: step.to ? `${named}, to ${step.to}` : named });
  }
  return out;
}

/** The step's icon in the list (lib/iconPaths.ts names). */
export function stepIcon(step: Pick<TransitStep, "mode">): "bike" | "bikeshare" | "user" | "train" | "routes" {
  switch (step.mode) {
    case "ride":
      return "bike";
    case "take":
    case "bikeshare":
      return "bikeshare";
    case "walk":
      return "user";
    case "metro":
    case "rail":
    case "light-rail":
    case "subway":
    case "enter":
    case "exit":
      return "train";
    default:
      return "routes";
  }
}
