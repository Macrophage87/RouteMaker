/**
 * Where the next train or bus is, while the rider waits to board it (v0.9.0; the owner: "When waiting
 * for each, can you show where the next train or bus is?"). Ride mode, at the end of the ride to a Metro
 * or Metrobus boarding, asks GET /api/transit/next-vehicle about every `POLL_MS` (25 s) and stops when
 * the rider is no longer waiting there (boarded: the ride ended or moved on; left the screen; the page
 * hidden). The answer is a line of words ("Next Red Line train is at Dupont Circle, 2 stations away.";
 * "Bus 52 is 0.8 mi away (1.3 km), 3 stops back."), marked live and credited "Data: WMATA", and a mark
 * on the map with the same words as its name. The line is plain text that changes in place, not a live
 * region; it is said politely only when the count of stations or stops away changes (`vehicleSaid`),
 * never at every poll. No answer, no line and no mark. No button or switch.
 */
import type { NextVehicle, TransitPlan, TransitStep } from "./api.ts";
import type { LonLat } from "./geo.ts";

/** How often the page asks while its rider waits: the server keeps train positions 20 s, bus positions 20 s. */
export const POLL_MS = 25_000;
/** The systems WMATA says where the vehicles are for. */
export const LIVE_SYSTEMS = ["Metro", "Metrobus"] as const;

/** What the page asks about: the boarding step's system and line, its first stop and its last (its way). */
export interface NextVehicleAsk {
  system: (typeof LIVE_SYSTEMS)[number];
  line: string;
  from: LonLat;
  to: LonLat;
}

/** The boarding a rider waits at: the first transit step after `after` (the ridden line), if WMATA's. */
export function boardingAsk(plan: Pick<TransitPlan, "steps">, after: number): NextVehicleAsk | null {
  const step = plan.steps.find((s, i) => i > after && (s.mode === "metro" || s.mode === "bus" || isTransitMode(s)));
  if (!step) return null;
  return askOf(step);
}

function isTransitMode(step: Pick<TransitStep, "mode">): boolean {
  return step.mode === "rail" || step.mode === "light-rail" || step.mode === "subway";
}

/** One step's question, or null where it is not a Metro or Metrobus ride with its stops drawn. */
export function askOf(step: Pick<TransitStep, "system" | "lines" | "coordinates">): NextVehicleAsk | null {
  const system = LIVE_SYSTEMS.find((s) => s === step.system);
  const line = step.lines[0];
  if (!system || !line || step.coordinates.length < 2) return null;
  return { system, line, from: step.coordinates[0], to: step.coordinates[step.coordinates.length - 1] };
}

export function nextVehicleUrl(ask: NextVehicleAsk): string {
  const f = (v: number) => v.toFixed(5);
  const params = new URLSearchParams({
    system: ask.system,
    line: ask.line,
    lon: f(ask.from[0]),
    lat: f(ask.from[1]),
    to_lon: f(ask.to[0]),
    to_lat: f(ask.to[1]),
  });
  return `/api/transit/next-vehicle?${params.toString()}`;
}

type FetchLike = (url: string, init?: RequestInit) => Promise<Pick<Response, "ok" | "json">>;

function looksLikeVehicle(value: unknown): value is NextVehicle {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.text === "string" &&
    typeof v.label === "string" &&
    Array.isArray(v.point) &&
    v.point.length === 2 &&
    v.point.every((n) => typeof n === "number" && Number.isFinite(n)) &&
    (v.kind === "train" || v.kind === "bus")
  );
}

/** Where the next one is now, or null (no reading, none coming, or no answer): nothing is shown. */
export async function requestNextVehicle(
  ask: NextVehicleAsk,
  options: { fetchImpl?: FetchLike; signal?: AbortSignal } = {},
): Promise<NextVehicle | null> {
  const fetchImpl: FetchLike = options.fetchImpl ?? ((url, init) => fetch(url, init));
  try {
    const response = await fetchImpl(nextVehicleUrl(ask), { headers: { Accept: "application/json" }, signal: options.signal });
    if (!response.ok) return null;
    const body = (await response.json()) as { vehicle?: unknown } | null;
    return body && looksLikeVehicle(body.vehicle) ? body.vehicle : null;
  } catch {
    return null;
  }
}

/** Whether to keep asking: a WMATA boarding, the rider waiting at it, and the page in view. */
export function shouldPoll(state: { ask: NextVehicleAsk | null; waiting: boolean; hidden: boolean }): boolean {
  return state.ask !== null && state.waiting && !state.hidden;
}

/** The line shown: the words, then the credit as the Metro live lines carry it. */
export function vehicleShown(vehicle: NextVehicle): string {
  return `${vehicle.text} (${vehicle.credit}, live)`;
}

/**
 * What to say politely after a poll, or null: the line when the count of stations or stops away changes
 * (the first answer included), never the same count again, and nothing when the answer goes away.
 */
export function vehicleSaid(before: NextVehicle | null, now: NextVehicle | null): string | null {
  if (!now) return null;
  if (before && before.kind === now.kind && before.away === now.away) return null;
  return vehicleShown(now);
}

/** The map's mark for it: its point, its name for a screen reader, and its kind's badge. */
export interface VehicleMark {
  point: LonLat;
  label: string;
  kind: "train" | "bus";
}

export function vehicleMark(vehicle: NextVehicle | null): VehicleMark | null {
  return vehicle ? { point: vehicle.point, label: vehicle.label, kind: vehicle.kind } : null;
}

/** The badge in the mark (aria-hidden: the mark's name says it). */
export function vehicleBadge(kind: VehicleMark["kind"]): string {
  return kind === "bus" ? "Next bus" : "Next train";
}
