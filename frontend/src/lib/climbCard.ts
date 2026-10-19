/**
 * The climb card (the owner, 2026-10-12: "You should be able to click on a climb to see more about that
 * climb, such as elevation profile, and add it to a destination"). Pressing a climb on the map, its summit
 * marker or its line, opens it (climbInteraction.ts); so does the road panel's "Climb details" for the
 * keyboard (RoadInfoDialog.tsx, the climb at the map's center).
 *
 * It says the climb: its name ("Foxville Road up Catoctin Mountain", else "Category 4 climb"), category, length (miles
 * first, km in brackets), gain (feet first), the average grade beside the map's own shape for it with the
 * shape's meaning ("Moderate: 4 to 7.9%"; the owner: "note that the icon means steepness on the map") and
 * the steepest grade; and its elevation profile, drawn with the route chart's own parts
 * (lib/profileChart.ts) from GET /api/climbs/{id}/profile, the router's USGS 3DEP heights along the climb
 * (core.climbprofile), since the layer's file has no heights. The chart is a picture with a text
 * alternative ("Climbs 240 ft (73 m) over 0.8 mi (1.3 km), steepest 9%.").
 *
 * One action, "Ride this climb" (the owner's rule: streamline over bloat). In Plan it puts the climb's
 * bottom and top into the plan as the next two stops, bottom first, before the destination (rideClimbEdit);
 * in Go it plans from Go's start to the climb's top through its bottom at once (App.tsx, routeGo).
 *
 * Written with createElement so a test renders it, as climbsLegend.ts.
 */
import { createElement as h, useEffect, useRef, type ReactElement } from "react";
import type { RouteProfile } from "./api.ts";
import { formatClimb, formatDistance } from "./format.ts";
import { MAX_POINTS, haversineM, type LonLat } from "./geo.ts";
import { GRADE_BAND_FILL, elevationArea, elevationLine, elevationRange, gradeBandShapes, linear, axisDistance, type Plot } from "./profileChart.ts";
import { pointName } from "./summary.ts";
import { CLIMB_CAUTION, SHAPE_STEEPNESS, categoryName, climbShape, climbShown, type Climb, type ClimbCategory } from "./climbs.ts";
import { ClimbSwatch } from "./climbsLegend.ts";

/** GET /api/climbs/{id}/profile (core.api.ClimbProfileOut). */
export interface ClimbProfile {
  id: string;
  category: string;
  length_m: number;
  gain_m: number;
  avg_grade_pct: number;
  /** The steepest grade on it, percent, read across four samples as the route chart reads it. */
  max_grade_pct: number | null;
  interval_m: number;
  m: number[];
  elevation_m: (number | null)[];
  grade_pct: (number | null)[];
}

/** The profile's state on the card. */
export type ProfileState = { kind: "loading" } | { kind: "ready"; profile: ClimbProfile } | { kind: "none" } | { kind: "error" };

export const RIDE_CLIMB_TEXT = "Ride this climb";
/** The road panel's way to the card (RoadInfoDialog.tsx). */
export const CLIMB_DETAILS_TEXT = "Climb details";
export const PROFILE_LOADING = "Loading the elevation profile…";
export const PROFILE_NONE = "There is no elevation profile for this climb.";
export const PROFILE_ERROR = "The elevation profile is not available right now.";

// --- Words -----------------------------------------------------------------------

/**
 * The climb's own name from its roads and hill (pipeline.climb_names: "Foxville Road up Catoctin Mountain",
 * "Sugarloaf Mountain climb", "Climb near Thurmont"), else "Category 4 climb".
 */
export function climbTitle(c: Pick<Climb, "name" | "category">): string {
  return c.name ?? `${categoryName(c.category)} climb`;
}

/**
 * A climb's end as a place in the plan: "Top of Foxville Road up Catoctin Mountain", "Top of the Sugarloaf
 * Mountain climb", "Bottom of the climb near Thurmont", "Bottom of a Category 4 climb".
 */
export function climbEndName(c: Pick<Climb, "name" | "category">, end: string): string {
  if (!c.name) return `${end} of a ${categoryName(c.category)} climb`;
  if (c.name.startsWith("Climb ")) return `${end} of the c${c.name.slice(1)}`;
  return c.name.endsWith(" climb") ? `${end} of the ${c.name}` : `${end} of ${c.name}`;
}

/** A grade to a tenth, without a needless ".0": "9%", "5.4%". */
export function gradeText(pct: number): string {
  const tenth = Math.round(pct * 10) / 10;
  return `${Number.isInteger(tenth) ? tenth.toFixed(0) : tenth.toFixed(1)}%`;
}

export interface ClimbFact {
  label: string;
  value: string;
}

/** The card's facts, in order: category, length, gain, average and steepest grade (once known). */
export function climbFacts(c: Climb, state: ProfileState): ClimbFact[] {
  const out: ClimbFact[] = [
    { label: "Category", value: categoryName(c.category) },
    { label: "Length", value: formatDistance(c.lengthM) },
    { label: "Elevation gain", value: formatClimb(c.gainM) },
    { label: "Average grade", value: gradeText(c.gradePct) },
  ];
  if (state.kind === "ready" && state.profile.max_grade_pct !== null) {
    out.push({ label: "Steepest", value: gradeText(state.profile.max_grade_pct) });
  } else if (state.kind === "loading") {
    out.push({ label: "Steepest", value: "loading…" });
  }
  return out;
}

/** The chart's text alternative: "Climbs 240 ft (73 m) over 0.8 mi (1.3 km), steepest 9%." */
export function profileSummary(c: Pick<Climb, "gainM" | "lengthM">, profile: Pick<ClimbProfile, "max_grade_pct"> | null): string {
  const steepest = profile?.max_grade_pct;
  const tail = steepest === null || steepest === undefined ? "" : `, steepest ${gradeText(steepest)}`;
  return `Climbs ${formatClimb(c.gainM)} over ${formatDistance(c.lengthM)}${tail}.`;
}

// --- The profile -----------------------------------------------------------------

export function climbProfileUrl(id: string): string {
  return `/api/climbs/${encodeURIComponent(id)}/profile`;
}

function looksLikeProfile(body: unknown): body is ClimbProfile {
  const b = body as Partial<ClimbProfile> | null;
  return (
    !!b &&
    Array.isArray(b.m) &&
    Array.isArray(b.elevation_m) &&
    Array.isArray(b.grade_pct) &&
    b.m.length === b.elevation_m.length &&
    b.m.length === b.grade_pct.length &&
    b.elevation_m.some((e) => typeof e === "number")
  );
}

/** Ask the API for a climb's profile: ready, none (no such climb or no heights) or error (try later). */
export async function fetchClimbProfile(
  id: string,
  fetcher: (url: string, init?: RequestInit) => Promise<{ ok: boolean; status: number; json(): Promise<unknown> }> = (u, i) => fetch(u, i),
): Promise<ProfileState> {
  try {
    const response = await fetcher(climbProfileUrl(id), { headers: { Accept: "application/json" } });
    if (response.status === 404) return { kind: "none" };
    if (!response.ok) return { kind: "error" };
    const body = await response.json();
    return looksLikeProfile(body) ? { kind: "ready", profile: body } : { kind: "error" };
  } catch {
    return { kind: "error" };
  }
}

/** The profile as the route chart's helpers read one. */
export function asRouteProfile(p: ClimbProfile): RouteProfile {
  return { interval_m: p.interval_m, m: p.m, elevation_m: p.elevation_m, grade_pct: p.grade_pct, climbs: [] };
}

// --- Riding it -------------------------------------------------------------------

/** The bottom and top stops sit this far in from the climb's ends (metres), so the router snaps to the climb's road, not one across its end. */
export const END_INSET_M = 25;

function pointAlong(line: readonly LonLat[], metres: number): LonLat {
  let walked = 0;
  for (let i = 1; i < line.length; i += 1) {
    const step = haversineM(line[i - 1], line[i]);
    if (walked + step >= metres && step > 0) {
      const f = (metres - walked) / step;
      return [line[i - 1][0] + (line[i][0] - line[i - 1][0]) * f, line[i - 1][1] + (line[i][1] - line[i - 1][1]) * f];
    }
    walked += step;
  }
  return line[line.length - 1];
}

/** The climb's bottom and top as stops: on its line, END_INSET_M in from each end (a quarter of a short one). */
export function climbEnds(c: Pick<Climb, "line">): { bottom: LonLat; top: LonLat } {
  let total = 0;
  for (let i = 1; i < c.line.length; i += 1) total += haversineM(c.line[i - 1], c.line[i]);
  const inset = Math.min(END_INSET_M, total / 4);
  const round = ([lon, lat]: LonLat): LonLat => [Number(lon.toFixed(6)), Number(lat.toFixed(6))];
  return { bottom: round(pointAlong(c.line, inset)), top: round(pointAlong(c.line, total - inset)) };
}

export type RideClimbEdit = { next: LonLat[]; said: string } | { refused: string };

/**
 * Plan's "Ride this climb": the climb's bottom then its top as the next two stops before the destination,
 * so the ride goes up it on the way. With no destination yet they follow the start (the top becomes the
 * end); with nothing planned the ride is the climb, bottom to top. In a loop, which has no destination,
 * they are the last two stops before the ride closes on its start. Refused past the 25-point cap.
 */
export function rideClimbEdit(points: readonly LonLat[], ends: { bottom: LonLat; top: LonLat }, loop: boolean): RideClimbEdit {
  if (points.length + 2 > MAX_POINTS) return { refused: `A route can have at most ${MAX_POINTS} points; this climb needs two.` };
  const { bottom, top } = ends;
  const next = loop || points.length < 2 ? [...points, bottom, top] : [...points.slice(0, -1), bottom, top, points[points.length - 1]];
  const i = next.indexOf(bottom);
  const said = `${pointName(i, next.length, loop)} set at the bottom of the climb, ${pointName(i + 1, next.length, loop)} at its top.`;
  return { next, said };
}

// --- The keyboard's way to a climb -------------------------------------------------

/**
 * The card a press opens while a climb's card is open: the climb pressed, unless it is the one already shown
 * (that press only closes the card, rather than closing it and opening it again) or nothing was pressed.
 */
export function climbCardAfterClose(shownId: string | null, pressed: Climb | null): Climb | null {
  return pressed && pressed.id !== shownId ? pressed : null;
}

/** How near the map's center a climb must pass for the road panel to offer it (metres). */
export const CLIMB_NEAR_M = 50;

function distanceToSegmentM(p: LonLat, a: LonLat, b: LonLat): number {
  const kx = 111_320 * Math.cos((p[1] * Math.PI) / 180);
  const ky = 111_320;
  const ax = (a[0] - p[0]) * kx;
  const ay = (a[1] - p[1]) * ky;
  const bx = (b[0] - p[0]) * kx;
  const by = (b[1] - p[1]) * ky;
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2));
  return Math.hypot(ax + t * dx, ay + t * dy);
}

/** The shown climb whose line passes nearest `point`, within `tolM`, or null (the road panel's "Climb here"). */
export function climbNearSpot(climbs: readonly Climb[] | null, point: LonLat, from: ClimbCategory, tolM = CLIMB_NEAR_M): Climb | null {
  if (!climbs) return null;
  const padLat = tolM / 111_320;
  const padLon = padLat / Math.cos((point[1] * Math.PI) / 180);
  let best: Climb | null = null;
  let bestM = tolM;
  for (const c of climbs) {
    if (!climbShown(c, from)) continue;
    let near = false;
    for (const [lon, lat] of c.line) {
      if (Math.abs(lon - point[0]) <= padLon + 0.05 && Math.abs(lat - point[1]) <= padLat + 0.05) {
        near = true;
        break;
      }
    }
    if (!near) continue;
    for (let i = 1; i < c.line.length; i += 1) {
      const d = distanceToSegmentM(point, c.line[i - 1], c.line[i]);
      if (d <= bestM) {
        bestM = d;
        best = c;
      }
    }
  }
  return best;
}

// --- The card --------------------------------------------------------------------

const CHART_W = 280;
const CHART_H = 120;
const PLOT = { left: 44, right: CHART_W - 6, top: 8, bottom: 92, axisY: 112 };

/** The climb's profile, drawn with the route chart's parts: the area, the line and the 5% and 8% grade bands. */
export function ClimbProfileChart({ climb, profile, uid }: { climb: Climb; profile: ClimbProfile; uid: string }): ReactElement {
  return h(ElevationProfileChart, { profile, summary: profileSummary(climb, profile), uid });
}

/** The heights a profile chart draws (a climb's, or a tapped trail's: lib/trailProfile.ts). */
export type ChartProfile = Pick<ClimbProfile, "interval_m" | "m" | "elevation_m" | "grade_pct">;

/** An elevation profile with the route chart's parts, named by `summary` (its text alternative). */
export function ElevationProfileChart({ profile, summary, uid }: { profile: ChartProfile; summary: string; uid: string }): ReactElement {
  const route: RouteProfile = { interval_m: profile.interval_m, m: profile.m, elevation_m: profile.elevation_m, grade_pct: profile.grade_pct, climbs: [] };
  const total = Math.max(profile.m[profile.m.length - 1] ?? 0, 1);
  const range = elevationRange(route);
  const plot: Plot = {
    x: linear(0, total, PLOT.left, PLOT.right),
    y: linear(range.lo, range.hi, PLOT.bottom, PLOT.top),
    left: PLOT.left,
    right: PLOT.right,
    top: PLOT.top,
    bottom: PLOT.bottom,
  };
  const feetOnly = (m: number) => formatClimb(m).split(" (")[0];
  return h(
    "figure",
    { className: "climb-profile" },
    h(
      "svg",
      { viewBox: `0 0 ${CHART_W} ${CHART_H}`, className: "pc-svg", role: "img", "aria-label": summary },
      h(
        "defs",
        null,
        h("pattern", { id: `${uid}-dots`, width: 4, height: 4, patternUnits: "userSpaceOnUse" }, h("circle", { cx: 2, cy: 2, r: 0.8, fill: "#1b1e24", fillOpacity: 0.75 })),
        h(
          "pattern",
          { id: `${uid}-hatch`, width: 5, height: 5, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" },
          h("line", { x1: 0, y1: 0, x2: 0, y2: 5, stroke: "#1b1e24", strokeWidth: 2 }),
        ),
      ),
      h("text", { className: "pc-axis-text", x: 2, y: PLOT.top + 8 }, feetOnly(range.hi)),
      h("text", { className: "pc-axis-text", x: 2, y: PLOT.bottom }, feetOnly(range.lo)),
      h("line", { className: "pc-axis", x1: PLOT.left, y1: PLOT.bottom, x2: PLOT.right, y2: PLOT.bottom }),
      h("path", { className: "pc-area", d: elevationArea(route, plot) }),
      ...gradeBandShapes(route, plot).map((b, i) =>
        h(
          "g",
          { key: `band-${i}` },
          h("path", { d: b.d, fill: GRADE_BAND_FILL }),
          h("path", { d: b.d, fill: `url(#${uid}-${b.band === 2 ? "hatch" : "dots"})` }),
        ),
      ),
      h("path", { className: "pc-line", d: elevationLine(route, plot), fill: "none" }),
      h("text", { className: "pc-axis-text", x: PLOT.left, y: PLOT.axisY, textAnchor: "start" }, axisDistance(0)),
      h("text", { className: "pc-axis-text", x: PLOT.right, y: PLOT.axisY, textAnchor: "end" }, axisDistance(total)),
    ),
    // Shown for the eye; the picture's own name says it, so it is not read twice.
    h("figcaption", { id: `${uid}-profile-text`, className: "climb-profile-text", "aria-hidden": "true" }, summary),
    h("p", { className: "hint climb-profile-key" }, "Amber: 5% to 8% (dotted), 8% or more (hatched). Elevation: USGS 3DEP."),
  );
}

export interface ClimbCardProps {
  climb: Climb;
  state: ProfileState;
  /** Unique per card, for its ids. */
  uid: string;
  onRide: () => void;
  /** Take the focus once mounted (the road panel's "Climb details"), so the card's name is said first. */
  focusOnMount?: boolean;
}

/** The card's contents (climbInteraction.ts puts them in the map's popup). */
export function ClimbCardView({ climb, state, uid, onRide, focusOnMount = false }: ClimbCardProps): ReactElement {
  const shape = climbShape(climb.gradePct);
  const facts = climbFacts(climb, state);
  const self = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (focusOnMount) self.current?.focus();
    // Once, when the card is first drawn: a later draw (the profile coming in) leaves the focus where it is.
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return h(
    "div",
    { ref: self, className: "climb-popup", role: "group", "aria-labelledby": `${uid}-title`, tabIndex: -1 },
    h("strong", { className: "climb-title", id: `${uid}-title` }, climbTitle(climb)),
    h(
      "dl",
      { className: "climb-facts" },
      ...facts.map((f) => h("div", { key: f.label }, h("dt", null, f.label), h("dd", null, f.value))),
    ),
    h(
      "p",
      { className: "climb-steepness" },
      h(ClimbSwatch, { shape, number: climb.category }),
      h("span", null, h("span", { className: "visually-hidden" }, `Map marker: ${shape}. `), SHAPE_STEEPNESS[shape], " average"),
    ),
    climb.unpaved ? h("p", { className: "climb-detail" }, "Mostly unpaved.") : null,
    state.kind === "ready"
      ? h(ClimbProfileChart, { climb, profile: state.profile, uid })
      : h(
          "p",
          { className: "hint climb-profile-status", role: "status" },
          state.kind === "loading" ? PROFILE_LOADING : state.kind === "none" ? PROFILE_NONE : PROFILE_ERROR,
        ),
    h("p", { className: "climb-caution" }, CLIMB_CAUTION),
    h("div", { className: "station-actions" }, h("button", { type: "button", onClick: onRide }, RIDE_CLIMB_TEXT)),
  );
}
