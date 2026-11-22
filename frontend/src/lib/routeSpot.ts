/**
 * What a tap on Go's map says about the route on it (Stephen, 2026-11-22: "When loading a saved route clicking again
 * in go should mainly let you query things about the route rather than new suggested changes"): the nearest point of
 * the route to the tap, how far along it is and how long from the start, the street there and its stress, and whether
 * the tap was on the route at all. GoSpotDialog.tsx shows it above the spot's address, and its Ride here becomes a
 * small "Ride here instead" at the foot, so a tap asks about the route rather than changing it.
 *
 * Plain data in, plain data out (no map), so node --test runs all of it.
 */
import { lineAlong } from "./navigate.ts";
import { spanAt } from "./profileChart.ts";
import { FACILITY_WORDS } from "./aheadGraph.ts";
import { formatDistance, formatDuration } from "./format.ts";
import type { LonLat } from "./geo.ts";
import type { RouteResponse, StressSpan } from "./api.ts";
import { t } from "./i18n.ts";

/**
 * A tap within this of the line is on the route, at any zoom (our default, unmeasured: about a fingertip at street
 * zoom). Zoomed out, App widens it to a fingertip on screen (routeSpotToleranceM).
 */
export const ON_ROUTE_M = 40;
/** A fingertip on screen, in CSS pixels (our default, unmeasured; the 44 px touch target's half, about). */
export const ON_ROUTE_PX = 24;

/** The tolerance at a zoom and latitude: ON_ROUTE_PX on screen (MapLibre's 512 px tiles), at least ON_ROUTE_M. */
export function routeSpotToleranceM(zoom: number, lat: number): number {
  const metresPerPx = (78271.517 * Math.cos((lat * Math.PI) / 180)) / 2 ** zoom;
  return Math.max(ON_ROUTE_M, ON_ROUTE_PX * metresPerPx);
}

export interface RouteSpot {
  /** Whether the tap was on the route (within the tolerance). */
  on: boolean;
  /** Metres from the tap to the route's nearest point. */
  offM: number;
  /** Metres along the route to that point, and the route's whole length. */
  atM: number;
  totalM: number;
  /** Seconds from the start to that point (the route's time marks, else spread evenly); null with no duration. */
  seconds: number | null;
  /** The street the route rides there, where the directions name one. */
  street: string | null;
  /** The stress section there, where the route has them. */
  span: StressSpan | null;
}

type SpotRoute = Pick<RouteResponse, "geometry" | "distance_m" | "duration_s"> & Partial<Pick<RouteResponse, "time_marks" | "stress_spans" | "description">>;

/** The route's nearest point to `point`, or null with no line. */
export function routeSpotAt(route: SpotRoute | null | undefined, point: LonLat, toleranceM = ON_ROUTE_M): RouteSpot | null {
  const line = (route?.geometry.coordinates ?? []) as LonLat[];
  if (!route || line.length < 2) return null;
  const along = lineAlong(line);
  const drawn = along[along.length - 1];
  if (!(drawn > 0)) return null;
  // Flat metres around the tap: plenty for the few hundred metres a tap is from a line.
  const kx = 111_320 * Math.cos((point[1] * Math.PI) / 180);
  const ky = 110_540;
  let best = Infinity;
  let bestAlong = 0;
  for (let i = 0; i < line.length - 1; i += 1) {
    const ax = (line[i][0] - point[0]) * kx;
    const ay = (line[i][1] - point[1]) * ky;
    const bx = (line[i + 1][0] - point[0]) * kx;
    const by = (line[i + 1][1] - point[1]) * ky;
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const f = len2 > 0 ? Math.min(1, Math.max(0, -(ax * dx + ay * dy) / len2)) : 0;
    const d = Math.hypot(ax + dx * f, ay + dy * f);
    if (d < best) {
      best = d;
      bestAlong = along[i] + (along[i + 1] - along[i]) * f;
    }
  }
  const fraction = bestAlong / drawn;
  // The route's own metres (the directions' and the stress sections'), scaled from the line as drawn.
  const traced = route.stress_spans?.length ? route.stress_spans[route.stress_spans.length - 1].to_m : route.distance_m > 0 ? route.distance_m : drawn;
  const totalM = route.distance_m > 0 ? route.distance_m : traced;
  const span = route.stress_spans?.length ? spanAt(route.stress_spans, fraction * traced) : null;
  const entries = (route.description ?? []).filter((e) => e.kind === "stretch");
  const described = entries.length ? Math.max(...entries.map((e) => e.to_m)) : 0;
  const atDescribed = fraction * described;
  const street = entries.find((e) => atDescribed >= e.from_m && atDescribed < e.to_m)?.street ?? (described > 0 && atDescribed >= described ? (entries[entries.length - 1].street ?? null) : null);
  return { on: best <= toleranceM, offM: best, atM: fraction * totalM, totalM, seconds: secondsAtFraction(route, fraction), street: street ?? null, span };
}

/** Seconds at a fraction of the line, from the route's time marks ([fraction, seconds]) or spread evenly. */
function secondsAtFraction(route: SpotRoute, fraction: number): number | null {
  const marks = route.time_marks;
  if (marks && marks.length >= 2) {
    if (fraction <= marks[0][0]) return marks[0][1];
    for (let i = 1; i < marks.length; i += 1) {
      if (fraction <= marks[i][0]) {
        const [f0, s0] = marks[i - 1];
        const [f1, s1] = marks[i];
        return f1 > f0 ? s0 + ((s1 - s0) * (fraction - f0)) / (f1 - f0) : s1;
      }
    }
    return marks[marks.length - 1][1];
  }
  return route.duration_s > 0 ? route.duration_s * fraction : null;
}

/** The card's heading for the route's lines. */
export const ROUTE_SPOT_HEADING = t("On your route");
/** Ride here, kept at the card's foot once a route is on the map: a new destination, never the card's first press. */
export const RIDE_HERE_INSTEAD = t("Ride here instead");

/** A stress section in a few words: "LTS 2 · Painted bike lane · Gravel"; null where it is not rated. */
export function spotSectionText(span: StressSpan | null): string | null {
  if (!span || span.tier === null) return null;
  const level = span.tier >= 5 ? t("Avoid") : `LTS ${span.half === true ? span.tier + 0.5 : span.tier}`;
  const way = span.facility && span.facility !== "none" ? FACILITY_WORDS[span.facility] : null;
  const surface = span.unpaved === true ? (span.rough === false ? t("Gravel") : span.rough === true ? t("Dirt") : t("Unpaved")) : null;
  return [level, way, surface].filter(Boolean).join(" · ");
}

/**
 * The card's lines: on the route, "4.2 mi (6.8 km) from the start, about 25 min", "8.4 mi (13.5 km) to the end" and
 * "Benning Road Northeast · LTS 2 · Painted bike lane"; off it, one line, "0.3 mi (0.5 km) from your route".
 */
export function routeSpotLines(spot: RouteSpot): string[] {
  if (!spot.on) return [t("{distance} from your route", { distance: formatDistance(spot.offM) })];
  const from = formatDistance(spot.atM);
  const lines = [
    spot.seconds !== null ? t("{distance} from the start, about {time}", { distance: from, time: formatDuration(spot.seconds) }) : t("{distance} from the start", { distance: from }),
    t("{distance} to the end", { distance: formatDistance(Math.max(0, spot.totalM - spot.atM)) }),
  ];
  const road = [spot.street, spotSectionText(spot.span)].filter(Boolean).join(" · ");
  if (road) lines.push(road);
  return lines;
}
