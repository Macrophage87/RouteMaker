/**
 * Asking before a long ride is planned (owner decisions, 2026-09-26: confirm
 * that a long ride is intended, "so it won't mess with processing time", and
 * "do that with anonymous visitors only").
 *
 * The API decides: an anonymous request whose points span more than 150 km in
 * straight lines gets a 409 with code "confirm_long" and the router is not
 * called; the same request with "confirm_long": true is planned, up to 300 km.
 * A signed-in rider never gets the 409, so never sees the question.
 *
 * Once a rider says yes, the answer holds for the current plan while its span
 * stays within the same 50 km step: a 160 km plan confirmed covers drags up to
 * 200 km, and a span past that asks again, since each step is a noticeably
 * bigger request. Clearing the points forgets it.
 */
import { pathLengthM, type LonLat } from "./geo.ts";

export const CONFIRM_STEP_KM = 50;

export function spanKm(points: readonly LonLat[]): number {
  return pathLengthM(points) / 1000;
}

/** The span a "yes" covers: up to the next 50 km step above what was asked. */
export function confirmedUpTo(askedSpanKm: number): number {
  return (Math.floor(askedSpanKm / CONFIRM_STEP_KM) + 1) * CONFIRM_STEP_KM;
}

/**
 * Should this request carry confirm_long, given what the rider has said yes
 * to? Not only above 150 km by our own measure: the API measures the span
 * itself, and a plan our arithmetic puts at 149.99 km that the API puts at
 * 150.01 would otherwise be asked about forever. confirm_long on a short plan
 * changes nothing (LONG-RIDE contract).
 */
export function sendsConfirmation(points: readonly LonLat[], confirmedKm: number | null): boolean {
  return confirmedKm !== null && spanKm(points) <= confirmedKm;
}
