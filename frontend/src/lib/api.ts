/**
 * POST /api/route, and what each of its answers means to a rider.
 *
 * The request and response are the SHARED API CONTRACT's. PLAN.md wants these
 * types generated from the API's OpenAPI schema; until that step exists they
 * are written out here, against the contract rather than against a guess.
 */
import type { LonLat } from "./geo.ts";
import type { PresetId } from "./presets.ts";
import type { StressMetres } from "./stressBar.ts";

export interface RouteResponse {
  preset: PresetId;
  variant: "standard" | "no-trail" | "ebike";
  geometry: { type: "LineString"; coordinates: LonLat[] };
  distance_m: number;
  duration_s: number;
  climb_m: number;
  descent_m: number;
  stress_m: StressMetres;
  attribution: string[];
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
  | "network"
  | "aborted";

export interface RouteError {
  kind: ErrorKind;
  status: number;
  title: string;
  message: string;
  retryAfterS?: number;
  /** On "confirm-long": the straight-line span the API measured, in km. */
  spanKm?: number;
}

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
  const reason = said
    .split(";")[0]
    .replace(/^[\w.]+:\s*/, "")
    .replace(/^Value error,\s*/i, "")
    .trim();
  return reason ? `The planner could not use these points: ${reason}.` : "The planner could not use these points.";
}

function wait(retryAfterS: number | undefined, fallback: string): string {
  if (retryAfterS === undefined) return fallback;
  return retryAfterS <= 1 ? "Try again in a moment." : `Try again in ${retryAfterS} seconds.`;
}

export function describeError(status: number, body: unknown, retryAfter: string | null): RouteError {
  const said = serverSentence(body);
  const retryAfterS = parseRetryAfter(retryAfter);
  const base = { status, ...(retryAfterS === undefined ? {} : { retryAfterS }) };
  if (status === 400 && said && /too long/i.test(said)) {
    return {
      ...base,
      kind: "too-long",
      title: "Too long to plan",
      message: "Split the trip into shorter parts and plan each one.",
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
          : `This is a long ride (about ${spanKm} km in straight lines). Planning it may take a little longer.`,
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

function aborted(): RouteResult {
  return { ok: false, error: { kind: "aborted", status: 0, title: "Cancelled", message: "Replaced by a newer request." } };
}

function isAbort(failure: unknown): boolean {
  return failure instanceof DOMException && failure.name === "AbortError";
}

export async function requestRoute(
  points: readonly LonLat[],
  preset: PresetId,
  options: { signal?: AbortSignal; fetchImpl?: FetchLike; confirmLong?: boolean } = {},
): Promise<RouteResult> {
  const fetchImpl: FetchLike = options.fetchImpl ?? ((url, init) => fetch(url, init));
  let response: Response;
  try {
    response = await fetchImpl("/api/route", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      // confirm_long only when the rider said yes to a long plan (LONG-RIDE
      // contract); the API asks anonymous riders first with a 409.
      body: JSON.stringify(options.confirmLong ? { points, preset, confirm_long: true } : { points, preset }),
      signal: options.signal,
    });
  } catch (failure) {
    if (isAbort(failure)) return aborted();
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
  } catch (failure) {
    // An abort can land while the body is still arriving.
    if (isAbort(failure)) return aborted();
    body = null;
  }
  if (response.ok && looksLikeRoute(body)) return { ok: true, route: body };
  const status = response.ok ? 500 : response.status;
  return { ok: false, error: describeError(status, body, response.headers.get("Retry-After")) };
}
