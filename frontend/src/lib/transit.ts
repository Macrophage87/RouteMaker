/**
 * The transit ride types on the page (TRANSIT-ASSIST; Stephen, 2026-10-12): Own Bike + 🚆🚌 and
 * Bikeshare + 🚶🚆🚌. The API answers each with its best combination (core.transit): the route's
 * line is the first ride leg, and the route's `transit` object is the whole trip, step by step, with
 * a scheduled total and the time of riding the whole way. These are the words, the map's lines and
 * markers and the credit, as plain functions so they can be tested without a browser.
 *
 * The times are scheduled (the systems' timetables) except where WMATA predicts a Metro or Metrobus
 * departure on a plan for now (v0.10.0): the words say "about" and "scheduled", or "live", wherever a
 * time is given.
 */
import type { ClosedStation, RouteResponse, StressSpan, TransitOption, TransitPlan, TransitStep } from "./api.ts";
import type { Dials } from "./dials.ts";
import { formatDistance } from "./format.ts";
import type { LonLat } from "./geo.ts";
import { isTransit, presetSaid, type PresetId } from "./presets.ts";
import { stressShares } from "./profileChart.ts";
import { routeSections, usableSpans, type RouteSection } from "./routeColours.ts";
import { legsSaid, legsText } from "./transitMarks.ts";

export function transitOf(route: Pick<RouteResponse, "transit"> | null | undefined): TransitPlan | null {
  return route?.transit ?? null;
}

/** The route's door-to-door time as the totals show it: "about 28 min". */
export function transitTime(plan: TransitPlan): string {
  return `about ${plan.minutes} min`;
}

/** The total's name: live where a departure is WMATA's prediction, scheduled where the trip rides transit. */
export function transitTimeName(plan: Pick<TransitPlan, "scheduled" | "live_times">): string {
  if (plan.live_times) return "Door-to-door time, with live departures";
  return plan.scheduled ? "Door-to-door time, scheduled" : "Door-to-door time";
}

/** The list's name, which a screen reader announces with the list. */
export const STEPS_LABEL = "Steps, in order";
/**
 * The options' list's name (the owner, 2026-10-12: riding directly there always). Stephen, 2026-10-21: "order by time
 * to get there with a penalty for time taken on busy roads and intersections", each row saying its busy riding,
 * "which should explain why they might not be in complete order".
 */
export const OPTIONS_LABEL = "Trips, best first, counting busy roads";
/** The legend's words for the rides: each is coloured by traffic stress, as the route is. */
export const RIDES_LEGEND = "Every ride is coloured by traffic stress, as on the route, and a thin solid line is a ride whose streets could not be read in time.";
/** Said under every transit plan: the timetables carry only the closures an agency published in them. */
export const TRACK_WORK = "Scheduled service; check for track work.";

/** The credit Metro's typical timetable carries (core/transitdata/metro-typical.json): no counted departures. */
const TYPICAL_CREDIT = /\(typical service\)/;

/**
 * Where a scheduled plan's times are from, and so what its waits are (review TB-13): the systems'
 * published timetables, Metro's typical service (from its credit), or both.
 */
export function timesFromText(plan: Pick<TransitPlan, "credits" | "day_type" | "holiday">): string {
  const day = `${plan.day_type === "weekday" ? "weekday" : plan.day_type}${plan.holiday ? " (a holiday)" : ""}`;
  const typical = plan.credits.filter((credit) => TYPICAL_CREDIT.test(credit)).length;
  const metro = (when: string) => `Metro's times are its typical ${when}service from wmata.com, not a timetable: its wait is half the usual time between trains.`;
  if (typical > 0 && typical === plan.credits.length) return metro(`${day} `);
  const published = `Times are from each system's published timetables for this ${day}: where trains or buses come every 15 minutes or less, the wait is half the time between them; otherwise it is the time to the next one.`;
  return typical > 0 ? `${published} ${metro("")}` : published;
}

/**
 * The plan's last word on its times: which are live (WMATA's next trains, and from v0.9.0 Metrobus's next
 * buses), or that none are.
 */
export function liveTimesText(plan: Pick<TransitPlan, "live" | "steps">): string {
  if (!plan.live) return "Not live arrivals.";
  const bus = plan.steps.some((s) => s.mode === "bus" && s.live);
  const train = plan.steps.some((s) => s.mode !== "bus" && s.live);
  const what = bus && train ? "next trains and buses" : bus ? "next buses" : "next trains";
  return `Times marked live are WMATA's ${what}.`;
}

/** Whether an option's row shows its legs as marks: a trip with a transit leg (Stephen, 2026-10-12). */
function marked(option: Pick<TransitOption, "legs">): boolean {
  return (option.legs ?? []).some((leg) => leg.mode !== "walk" && leg.mode !== "ride" && leg.mode !== "bikeshare");
}

/**
 * An option as its button shows it: "A. Ride the whole way: about 12 min", and a transit trip by its
 * legs, "B. 🚶 4 min · 🔴 18 min · 🚶 3 min: about 25 min" (the marks aria-hidden: `optionSaid`).
 */
export function optionText(
  option: Pick<TransitOption, "label" | "minutes" | "legs" | "hop" | "busy_m">,
  index: number,
): string {
  const what = marked(option) ? legsText(option.legs ?? []) : option.label;
  return `${String.fromCharCode(65 + index)}. ${what}${hopWords(option)}: about ${option.minutes} min${busyText(option.busy_m, "busy")}`;
}

/** Novice and Nervous's hop past the busy stretch (v0.11.0): ", skips the busy stretch", on screen and said. */
function hopWords(option: Pick<TransitOption, "hop">): string {
  return option.hop ? ", skips the busy stretch" : "";
}

/**
 * An option's busy riding after its time (Stephen, 2026-10-21: "arrive in X min with x mi of busy roads"):
 * ", 0.4 mi (0.6 km) busy" on screen, "on busy roads" said; ", no busy roads" under a tenth of a mile (a crossing,
 * a driveway); nothing where it is not known.
 */
export function busyText(busyM: number | null | undefined, words: string): string {
  if (busyM == null || !Number.isFinite(busyM)) return "";
  if (busyM < NO_BUSY_M) return ", no busy roads";
  return `, ${formatDistance(busyM)} ${words}`;
}
const NO_BUSY_M = 160;

/** Said with an option whose row shows the elevator icon (`TransitOption.elevator_out`). */
export const ELEVATOR_OUT_SAID = "an elevator is out on the way, so it is ranked lower";

/** The same option in words: "B. walk 4 minutes, Red Line 18 minutes, walk 3 minutes: about 25 min". */
export function optionSaid(
  option: Pick<TransitOption, "label" | "minutes" | "legs" | "hop" | "busy_m" | "elevator_out">,
  index: number,
): string {
  const what = marked(option) ? legsSaid(option.legs ?? []) : option.label;
  const elevator = option.elevator_out ? `; ${ELEVATOR_OUT_SAID}` : "";
  return `${String.fromCharCode(65 + index)}. ${what}${hopWords(option)}: about ${option.minutes} min${busyText(option.busy_m, "on busy roads")}${elevator}`;
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

/**
 * A ride after the route's own line, cut into its coloured sections as the route is (its own bike
 * from the exit station, the far end's share bike; Stephen, v0.7.0: "it doesn't seem to include
 * the LTS of the section towards the destination"). Null for any other step, and for a ride the
 * API could not route in time, which is drawn as a plain line instead.
 */
export function rideSections(step: Pick<TransitStep, "mode" | "route_line" | "coordinates" | "stress_spans">): RouteSection[] | null {
  if (step.route_line || drawOf(step) !== "ride" || step.coordinates.length < 2) return null;
  return routeSections(step.coordinates, step.stress_spans ?? undefined);
}

/** Every later ride's coloured sections, in trip order, for the map's route sections beside the route's own. */
export function transitRideSections(plan: Pick<TransitPlan, "steps"> | null | undefined): RouteSection[] {
  return (plan?.steps ?? []).flatMap((step) => rideSections(step) ?? []);
}

/** The later rides drawn in the route's colours, as lines: the route's casing goes under them too. */
export function transitRideLines(plan: Pick<TransitPlan, "steps"> | null | undefined): LonLat[][] {
  return (plan?.steps ?? []).filter((step) => rideSections(step) !== null).map((step) => step.coordinates);
}

/**
 * The route's stress sections and every coloured later ride's after them, end to end, for the
 * legend's lengths: the legend names every colour on the map, the later rides' included. The
 * route's own where there are no coloured later rides.
 */
export function tripStressSpans(route: Pick<RouteResponse, "stress_spans"> & Partial<Pick<RouteResponse, "transit">>): StressSpan[] | undefined {
  const later = (route.transit?.steps ?? []).filter((step) => rideSections(step) !== null);
  if (later.length === 0) return route.stress_spans;
  const out: StressSpan[] = [];
  let at = 0;
  for (const spans of [route.stress_spans, ...later.map((step) => step.stress_spans)]) {
    if (!usableSpans(spans)) continue;
    for (const span of spans) out.push({ ...span, from_m: at + span.from_m, to_m: at + span.to_m });
    at += spans[spans.length - 1].to_m;
  }
  return out.length > 0 ? out : route.stress_spans;
}

/**
 * A ride step's traffic stress in words, as the route chart's summary says the route's
 * ("Traffic stress along it: 19% traffic-free path, 69% LTS 2, 12% LTS 3."), so a screen reader
 * hears every ride's stress the same way. `spans`: the route's own, for the route line's step.
 * Null where the step has none.
 */
export function stepStressSaid(step: Pick<TransitStep, "mode" | "route_line" | "coordinates" | "stress_spans">, routeSpans?: readonly StressSpan[]): string | null {
  if (drawOf(step) !== "ride") return null;
  const spans = step.route_line ? routeSpans : rideSections(step) ? step.stress_spans : null;
  if (!usableSpans(spans)) return null;
  const shares = stressShares(spans, 0);
  return shares ? `Traffic stress along it: ${shares}.` : null;
}

export function transitFeatures(plan: TransitPlan | null): TransitFeatureCollection {
  const features: TransitFeatureCollection["features"] = [];
  for (const step of plan?.steps ?? []) {
    const draw = drawOf(step);
    // A ride routed with its stress is drawn in the route's own colours (`transitRideSections`).
    if (!draw || step.route_line || step.coordinates.length < 2 || rideSections(step)) continue;
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
