/**
 * POST /api/route, and what each of its answers means to a rider.
 *
 * The request and response are the SHARED API CONTRACT's. PLAN.md wants these
 * types generated from the API's OpenAPI schema; until that step exists they
 * are written out here, against the contract rather than against a guess.
 */
import { formatRoughDistance } from "./format.ts";
import type { LonLat } from "./geo.ts";
import type { PresetId } from "./presets.ts";
import type { StressMetres } from "./stressBar.ts";
import type { FacilityMetres } from "./facilityBar.ts";
import { dialFields, type Carrying, type Dials, type When } from "./dials.ts";

export interface RouteResponse {
  preset: PresetId;
  variant: "standard" | "no-trail" | "ebike" | "weekend";
  geometry: { type: "LineString"; coordinates: LonLat[] };
  distance_m: number;
  duration_s: number;
  climb_m: number;
  descent_m: number;
  stress_m: StressMetres;
  /** Metres per facility class. Absent from an API older than the sliders. */
  facility_m?: FacilityMetres;
  /**
   * The curated stress adjustments the route rides over, in route order; the
   * why only for a public one whose words the owner approved (shown in the
   * route's summary: "Only provide the warnings if the route goes over the
   * road"). Absent from an older API. The card that shows it is to come.
   */
  stress_adjustments?: {
    adjustment_id: string;
    tier: number;
    adjusted: true;
    length_m: number;
    direction: "up" | "down" | "same" | null;
    category: string | null;
    public_note: string | null;
    display: "route_only" | "map" | null;
  }[];
  /** The positions the route was planned with. Absent from an older API. */
  dials?: { stress: number; hills: number; when: When; carrying: Carrying | null; assist?: boolean };
  /** Present when the hills slider was past its detent. */
  hills_seek?: {
    candidates: number;
    chosen: number;
    extra_climb_m: number;
    extra_distance_m: number;
    limited: "two_points" | "long_ride" | "timed_out" | null;
  } | null;
  /** Present when the hills slider was below its middle: sustained climbs and
   * brake-riding descents weighed among the router's alternatives. */
  hills_avoid?: {
    candidates: number;
    chosen: number;
    weight: number;
    brake_grade: number | null;
    grade_cost_s: number;
    direct_grade_cost_s: number;
    extra_distance_m: number;
    limited: "two_points" | "long_ride" | "timed_out" | null;
    /** The hills slider's middle route, kept because the hill-avoiding one was busier. */
    kept_middle?: boolean;
  } | null;
  attribution: string[];
  /**
   * Index in geometry.coordinates of each leg's last vertex (one per leg).
   * Additive to the contract, so an older API may leave it out; lineEdit.ts
   * checks it against the line before trusting it.
   */
  leg_ends?: number[];
}

export type ErrorKind =
  | "bad-input"
  | "too-long"
  | "confirm-long"
  | "no-route"
  | "rate-limited"
  | "router-down"
  | "timed-out"
  | "server"
  | "network";

export interface RouteError {
  kind: ErrorKind;
  status: number;
  title: string;
  message: string;
  retryAfterS?: number;
  /** On "confirm-long": the straight-line span the API measured, in km. */
  spanKm?: number;
  /**
   * Shown at once, never resent by the scheduler after its Retry-After: a
   * long ride that used its whole time budget (the API's code
   * "long_ride_timed_out") would most likely use it again, holding the one
   * long slot each time. "Try again" still waits the Retry-After out.
   */
  noAutoResend?: true;
}

/** The API's code on a long ride's 503 when its time budget ran out. */
export const LONG_RIDE_TIMED_OUT = "long_ride_timed_out";

export type RouteResult = { ok: true; route: RouteResponse } | { ok: false; error: RouteError };

/** Retry-After as seconds from now: either delta-seconds or an HTTP date. */
export function parseRetryAfter(header: string | null | undefined, now: number = Date.now()): number | undefined {
  if (header == null) return undefined;
  const text = header.trim();
  if (/^\d+$/.test(text)) return Number(text);
  if (!/[a-z]/i.test(text)) return undefined;
  const when = Date.parse(text);
  if (Number.isNaN(when)) return undefined;
  return Math.max(0, Math.round((when - now) / 1000));
}

/** The API's own `{"error": "..."}` sentence, when the body really is one. */
function serverSentence(body: unknown): string | undefined {
  if (body && typeof body === "object" && "error" in body) {
    const text = (body as { error: unknown }).error;
    if (typeof text === "string" && text.trim()) return text.trim();
  }
  return undefined;
}

/**
 * A validator's sentence without the field path and "Value error," Ninja puts
 * before it. The API strips them itself now; this is for an API that does not.
 */
function withoutValidatorPrefix(said: string): string {
  return said
    .replace(/^[\w.]+:\s*/, "")
    .replace(/^Value error,\s*/i, "")
    .trim();
}

/**
 * The validator's reason in words a rider can use. Ninja's messages carry a
 * field path and "Value error," ("points: Value error, point 1 is outside the
 * area this map covers"), which is for a developer.
 */
export function friendlyInput(said: string | undefined): string {
  if (!said) return "The planner could not use these points.";
  if (/outside the area/i.test(said)) {
    return "One of the points is outside the area this map covers. Move it back inside.";
  }
  if (/at least 2|too short|min_length/i.test(said)) return "Set a start and an end first.";
  if (/at most|too long|max_length/i.test(said)) return "That is more points than one route can take.";
  const reason = withoutValidatorPrefix(said.split(";")[0]);
  return reason ? `The planner could not use these points: ${reason}.` : "The planner could not use these points.";
}

/**
 * The longest Retry-After the planner honours. The API never asks for more
 * than a minute (src/core/ratelimit.py caps it at the limit's window); a
 * larger figure is a proxy's or a bug's, and taken as it stands it would hold
 * every plan for a day, or overflow the browser's timer and send at once.
 */
export const RETRY_AFTER_CAP_S = 60;

/** The API's sentence as a sentence: a capital first, a stop last. */
function asSentence(said: string): string {
  const text = said.charAt(0).toUpperCase() + said.slice(1);
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

function wait(retryAfterS: number | undefined, fallback: string): string {
  if (retryAfterS === undefined) return fallback;
  return retryAfterS <= 1 ? "Try again in a moment." : `Try again in ${retryAfterS} seconds.`;
}

export function describeError(status: number, body: unknown, retryAfter: string | null): RouteError {
  const said = serverSentence(body);
  const parsed = parseRetryAfter(retryAfter);
  const retryAfterS = parsed === undefined ? undefined : Math.min(parsed, RETRY_AFTER_CAP_S);
  const base = { status, ...(retryAfterS === undefined ? {} : { retryAfterS }) };
  if (status === 400 && said && /too long/i.test(said)) {
    return {
      ...base,
      kind: "too-long",
      title: "Too long to plan",
      // The API's own words: the ceiling is its to set, and it says what it is.
      message: asSentence(withoutValidatorPrefix(said)),
    };
  }
  if (status === 400) {
    return { ...base, kind: "bad-input", title: "Can't plan that", message: friendlyInput(said) };
  }
  const code = body && typeof body === "object" ? (body as { code?: unknown }).code : undefined;
  if (status === 409 && code === "confirm_long") {
    const span = (body as { span_km?: unknown }).span_km;
    const spanKm = typeof span === "number" && Number.isFinite(span) && span > 0 ? Math.round(span) : undefined;
    return {
      ...base,
      kind: "confirm-long",
      title: "A long ride",
      message:
        spanKm === undefined
          ? "This is a long ride. Planning it may take a little longer."
          : `This is a long ride: about ${formatRoughDistance(spanKm * 1000)} in straight lines. Planning it may take a little longer.`,
      ...(spanKm === undefined ? {} : { spanKm }),
    };
  }
  if (status === 404 || status === 422) {
    return {
      ...base,
      kind: "no-route",
      title: "No route found",
      message: said ?? "No route joins these points on this preset. Try moving a point or another preset.",
    };
  }
  if (status === 429) {
    return {
      ...base,
      kind: "rate-limited",
      title: "Slow down",
      message: `Too many route requests from this connection. ${wait(retryAfterS, "Try again in a minute.")}`,
    };
  }
  if (status === 502) {
    return {
      ...base,
      kind: "router-down",
      title: "Router unavailable",
      message: "The routing engine is not answering right now. Try again shortly.",
    };
  }
  if (status === 503 && code === LONG_RIDE_TIMED_OUT) {
    return {
      ...base,
      kind: "timed-out",
      title: "Long ride not planned",
      message: said ?? `Planning this long ride ran out of time. ${wait(retryAfterS, "Try again shortly.")}`,
      noAutoResend: true,
    };
  }
  if (status === 503 || status === 504) {
    return {
      ...base,
      kind: "timed-out",
      title: "Planner busy",
      message: `The planner is busy or ran out of time on this route. ${wait(retryAfterS, "Try again shortly.")}`,
    };
  }
  return {
    ...base,
    kind: "server",
    title: "Something went wrong",
    message: "The planner hit an unexpected problem. Try again, or try a different route.",
  };
}

function looksLikeRoute(value: unknown): value is RouteResponse {
  if (!value || typeof value !== "object") return false;
  const r = value as Partial<RouteResponse>;
  return (
    typeof r.distance_m === "number" &&
    typeof r.duration_s === "number" &&
    r.geometry?.type === "LineString" &&
    Array.isArray(r.geometry.coordinates) &&
    typeof r.stress_m === "object" &&
    r.stress_m !== null &&
    Array.isArray(r.attribution)
  );
}

type FetchLike = (url: string, init: RequestInit) => Promise<Response>;

export async function requestRoute(
  points: readonly LonLat[],
  preset: PresetId,
  // No abort signal: the scheduler never abandons a request, because an abort
  // in the browser does not free the API's in-flight slot (routeScheduler.ts).
  options: { fetchImpl?: FetchLike; confirmLong?: boolean; dials?: Dials } = {},
): Promise<RouteResult> {
  const fetchImpl: FetchLike = options.fetchImpl ?? ((url, init) => fetch(url, init));
  let response: Response;
  try {
    response = await fetchImpl("/api/route", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      // confirm_long only when the rider said yes to a long plan (LONG-RIDE
      // contract); the API asks anonymous riders first with a 409.
      body: JSON.stringify({
        points,
        preset,
        ...(options.dials ? dialFields(options.dials) : {}),
        ...(options.confirmLong ? { confirm_long: true } : {}),
      }),
    });
  } catch {
    return {
      ok: false,
      error: {
        kind: "network",
        status: 0,
        title: "Can't reach the planner",
        message: "The request did not get through. Check your connection and try again.",
      },
    };
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (response.ok && looksLikeRoute(body)) return { ok: true, route: body };
  const status = response.ok ? 500 : response.status;
  const error = describeError(status, body, response.headers.get("Retry-After"));
  // A confirmed long plan can be refused because a long ride is already
  // being planned (one per client, one per deployment: LONG-RIDE contract).
  // The API's sentence says so; "too many requests" would not.
  const said = serverSentence(body);
  // A long ride that ran out of time already has its own title and words.
  if (options.confirmLong && (status === 429 || status === 503) && said && !error.noAutoResend) {
    return { ok: false, error: { ...error, title: "Planner busy", message: said } };
  }
  return { ok: false, error };
}
