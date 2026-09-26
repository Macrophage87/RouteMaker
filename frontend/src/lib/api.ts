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
      message: "That trip is too long to plan in one go (more than about 150 km). Split it into shorter parts.",
    };
  }
  if (status === 400) {
    return {
      ...base,
      kind: "bad-input",
      title: "Can't plan that",
      message: said ? `The planner refused these points: ${said}.` : "The planner refused these points.",
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
    Array.isArray(r.attribution)
  );
}

type FetchLike = (url: string, init: RequestInit) => Promise<Response>;

export async function requestRoute(
  points: readonly LonLat[],
  preset: PresetId,
  options: { signal?: AbortSignal; fetchImpl?: FetchLike } = {},
): Promise<RouteResult> {
  const fetchImpl: FetchLike = options.fetchImpl ?? ((url, init) => fetch(url, init));
  let response: Response;
  try {
    response = await fetchImpl("/api/route", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ points, preset }),
      signal: options.signal,
    });
  } catch (failure) {
    if (failure instanceof DOMException && failure.name === "AbortError") {
      return { ok: false, error: { kind: "aborted", status: 0, title: "Cancelled", message: "Replaced by a newer request." } };
    }
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
  return { ok: false, error: describeError(status, body, response.headers.get("Retry-After")) };
}
