/**
 * Rider-marked hazards on the Mass Ride map (FOLLOWUP-MASSRIDE-MAP part 3; OWNER-DECISIONS 325-327;
 * core/mass_hazards.py).
 *
 * "Some stretches can be marked as a caution or warning where we've had problems. They go along side like
 * a trail or pbl. If we've marked it avoid, It should be just marked avoid with no carrying capacity. These
 * hazards will be marked by riders and will be for this mode only." (325). Two levels chosen by the
 * reporter, with a reason (326: "Severity only"; both stay routable); near-black side rails, Caution
 * dotted and Warning dash-dot (327).
 *
 * A signed-in rider the settings allow (`Me.can_suggest`) marks the road piece in the road panel, on a
 * Mass Ride only; an instance admin reviews it with the suggestions' three actions (SuggestionReview.tsx,
 * `HAZARD_REVIEW`). The approved ones come from GET /api/mass-hazards, a small GeoJSON layer of their own
 * (not the tiles), and are named in words wherever they are drawn: the legend, the road panel, the route's
 * directions and the route's announcement. Never colour alone; US units first, metric in brackets.
 */
import { createElement as h, Fragment, type ReactElement } from "react";
import { MASS_HAZARDS, HAZARD_CASING_EXTRA_PX } from "../massStyle.js";
import type { MassHazardSpan, RouteResponse } from "./api.ts";
import { formatMileRange } from "./format.ts";
import { call, type ReviewAction } from "./suggestions.ts";

export type HazardLevel = "caution" | "warning";

/** What the legend, the panel and the description say of each level (core/mass_hazards.py LEVEL_WORDS). */
export const HAZARD_WORDS: Readonly<Record<HazardLevel, string>> = {
  caution: "Caution: riders have had problems here; take care",
  warning: "Warning: riders have had serious problems here",
};

/** One approved hazard, as the layer's feature carries it. */
export interface HazardProps {
  way: number;
  level: HazardLevel;
  level_name: string;
  words: string;
  reason: string;
  road: string;
}

export interface HazardCollection {
  type: "FeatureCollection";
  features: { type: "Feature"; id?: number; geometry: unknown; properties: HazardProps }[];
}

type Fetch = typeof fetch;

/** GET /api/mass-hazards: the approved hazards, or null where they could not be read (the map then draws none). */
export async function fetchHazards(origin: string, run: Fetch = fetch): Promise<HazardCollection | null> {
  try {
    const response = await run(`${origin}/api/mass-hazards`, { headers: { Accept: "application/geo+json, application/json" } });
    if (!response.ok) return null;
    const body = (await response.json()) as HazardCollection;
    return body && body.type === "FeatureCollection" && Array.isArray(body.features) ? body : null;
  } catch {
    return null;
  }
}

/** The approved hazard on this way, or null. */
export function hazardForWay(hazards: HazardCollection | null | undefined, way: number | null | undefined): HazardProps | null {
  if (!hazards || way == null) return null;
  return hazards.features.find((f) => f.properties?.way === way)?.properties ?? null;
}

/** The legend's row for a level: its look in words, then what it means. */
export function hazardLegendText(level: HazardLevel): string {
  const style = MASS_HAZARDS.find((s: { level: string }) => s.level === level);
  return `${HAZARD_WORDS[level]}. Drawn as ${style?.pattern ?? ""} black rails on both sides of the road.`;
}

export const HAZARD_LEGEND_TITLE = "Rider-marked hazards";
export const HAZARD_LEGEND_NOTE =
  "Marked by riders and checked by the map's admins, on the Mass Ride map only. A road marked Avoid shows only Avoid.";

/** The road panel's line: "Warning: riders have had serious problems here. Riders' reason: ...". */
export function hazardPanelText(hazard: HazardProps): string {
  return `${HAZARD_WORDS[hazard.level]}. Riders' reason: ${hazard.reason}`;
}

/** The road panel's status sentence adds this, so a screen reader hears it with the road. */
export function hazardSaid(hazard: HazardProps | null): string {
  return hazard ? `Rider-marked hazard: ${hazard.level_name}.` : "";
}

/** A hazard on the route, in the directions: "Warning on Oak Street, 0.6 to 0.8 mi (1.0 to 1.3 km): ...". */
export function hazardLine(span: MassHazardSpan): string {
  return `${span.level_name} on ${span.road}, ${formatMileRange(span.from_m, span.to_m)}: ${HAZARD_WORDS[span.level].split(": ")[1]}. Riders' reason: ${span.reason}`;
}

/** The directions' block: a heading line and one line a hazard in riding order; empty where none. */
export function hazardLines(route: Partial<Pick<RouteResponse, "mass_hazards">>): string[] {
  const found = route.mass_hazards ?? [];
  if (found.length === 0) return [];
  const n = found.length;
  return [`${n} rider-marked ${n === 1 ? "hazard" : "hazards"} on this route, in riding order:`, ...found.map(hazardLine)];
}

/** Said with the route (a polite announcement): "This route passes 2 rider-marked hazards: Warning on Oak Street, ...". */
export function hazardsSaid(route: Partial<Pick<RouteResponse, "mass_hazards">>): string | null {
  const found = route.mass_hazards ?? [];
  if (found.length === 0) return null;
  const n = found.length;
  const names = found.map((s) => `${s.level_name} on ${s.road}`).join(", ");
  return `This route passes ${n} rider-marked ${n === 1 ? "hazard" : "hazards"}: ${names}. The directions list ${n === 1 ? "it" : "them"}.`;
}

// ---- The legend's swatches (createElement, so a test renders them) ----

const SWATCH_W = 56;

/** A level's swatch: a grey road with the level's white-cased rail on each side, at the map's width and dash. */
export function HazardSwatch({ level }: { level: HazardLevel }): ReactElement {
  const style = MASS_HAZARDS.find((s: { level: string }) => s.level === level)!;
  const dash = style.dash.map((d: number) => d * style.rail).join(" ");
  const rail = (y: number) => [
    h("line", { key: `c${y}`, x1: 0, y1: y, x2: SWATCH_W, y2: y, stroke: style.casing, strokeWidth: style.rail + HAZARD_CASING_EXTRA_PX }),
    h("line", { key: `r${y}`, x1: 0, y1: y, x2: SWATCH_W, y2: y, stroke: style.color, strokeWidth: style.rail, strokeDasharray: dash }),
  ];
  return h(
    "svg",
    { width: SWATCH_W, height: 20, "aria-hidden": "true", className: `mass-swatch hazard-swatch hazard-swatch-${level}` },
    h("line", { x1: 0, y1: 10, x2: SWATCH_W, y2: 10, stroke: "#9ca3af", strokeWidth: 6 }),
    ...rail(3),
    ...rail(17),
  );
}

/** The Mass Ride legend's hazard rows, under the bands and Avoid. */
export function HazardLegend(): ReactElement {
  return h(
    Fragment,
    null,
    h(
      "ul",
      { className: "legend hazard-legend", "aria-label": HAZARD_LEGEND_TITLE },
      ...(["caution", "warning"] as const).map((level) =>
        h("li", { key: level }, h(HazardSwatch, { level }), h("span", { className: "stress-label" }, hazardLegendText(level))),
      ),
    ),
    h("p", { className: "hint hazard-legend-note" }, HAZARD_LEGEND_NOTE),
  );
}

// ---- The road panel's report form (HazardReport.tsx) ----

export const HAZARD_REPORT_TEXT = "Mark a hazard";
export const HAZARD_REPORT_HEADING = "Mark a hazard for Mass Rides";
export const HAZARD_LEVEL_LEGEND = "How serious is it?";
export const HAZARD_REASON_LABEL = "What happened here (required)";
export const HAZARD_REASON_MAX = 500;
export const HAZARD_PRIVACY =
  "An admin reviews every report before anything changes. The road and your reason may be shared in a public poll to ask other riders, never your name or the spot you clicked. Only the Mass Ride map shows hazards.";
export const HAZARD_SEND = "Send hazard report";

export interface HazardRequest {
  osm_way_id: number;
  lat: number;
  lon: number;
  level: HazardLevel;
  reason: string;
}

export type HazardOutcome = { kind: "sent"; message: string } | { kind: "refused"; status: number; message: string; field: string | null };

/** The form's own check before sending: the field and its sentence, or null. */
export function hazardProblem(level: HazardLevel | null, reason: string): { field: "level" | "reason"; message: string } | null {
  if (level === null) return { field: "level", message: "Choose Caution or Warning." };
  const text = reason.trim();
  if (!text) return { field: "reason", message: "Say what happened here, in a sentence or two." };
  if (text.length > HAZARD_REASON_MAX) return { field: "reason", message: `The reason is at most ${HAZARD_REASON_MAX} characters.` };
  return null;
}

/** POST /api/mass-hazards. */
export async function sendHazard(origin: string, request: HazardRequest, csrf: string | null, run: Fetch = fetch): Promise<HazardOutcome> {
  const r = await call<{ message: string }>(`${origin}/api/mass-hazards`, { method: "POST", body: JSON.stringify(request) }, csrf, run);
  return r.ok ? { kind: "sent", message: r.body.message } : { kind: "refused", status: r.status, message: r.message, field: r.field };
}

// ---- The admin's review (SuggestionReview.tsx with HAZARD_REVIEW) ----

export interface HazardReportItem {
  id: number;
  osm_way_id: number;
  road: string;
  lat: number | null;
  lon: number | null;
  level: HazardLevel;
  level_name: string;
  words: string;
  reason: string;
  status: "pending" | "sent_to_discord";
  created_at: string;
  sent_at: string | null;
}

/** GET /api/mass-hazards/open (instance admin). */
export async function fetchHazardReports(origin: string, run: Fetch = fetch): Promise<HazardReportItem[] | string> {
  const r = await call<{ hazards: HazardReportItem[] }>(`${origin}/api/mass-hazards/open`, { method: "GET" }, null, run);
  return r.ok ? r.body.hazards : r.message;
}

/** POST /api/mass-hazards/{id}/{action} (instance admin). */
export async function reviewHazard<T = { message: string; status: string }>(
  origin: string,
  id: number,
  action: ReviewAction,
  csrf: string | null,
  run: Fetch = fetch,
): Promise<{ ok: true; body: T } | { ok: false; message: string }> {
  const r = await call<T>(`${origin}/api/mass-hazards/${id}/${action}`, { method: "POST", body: "{}" }, csrf, run);
  return r.ok ? r : { ok: false, message: r.message };
}

/** A report in one line for its heading: "Oak Street: mark as Warning (riders have had serious problems here)". */
export function hazardReportLine(item: Pick<HazardReportItem, "road" | "level">): string {
  const [name, words] = HAZARD_WORDS[item.level].split(": ");
  return `${item.road}: mark as ${name} (${words})`;
}
