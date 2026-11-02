/**
 * A transit trip kept checked while it is ridden (Stephen, 2026-11-02: "Also for transit, periodically check to see
 * if there's any changes such as delays and the like. Make adjustments if not on the best route"). Until the rider
 * boards the trip's first train or bus, the ride screen asks for the same trip again from where the rider is, leaving
 * now, every `TRIP_CHECK_MS`: the API's plan for now lays WMATA's predicted departures and its rail incidents over the
 * timetable (core/transit_live.py), so a late or missing train shows in it.
 *
 * - Another trip is quicker by `SWITCH_MIN_S` or more than this one is now, or this one is no longer offered (its
 *   train gone, its line suspended): the ride changes to it at once and says so ("Changed to a quicker trip: ...").
 *   No button: the change is the adjustment asked for, and the old trip is not offered back.
 * - This one is still the best but now arrives `LATE_TOLD_S` or more later than last said: the delay is said, with
 *   the new arrival.
 *
 * A Bikeshare + 🚶🚆🚌 trip is checked only on the walk to its first dock: once a share bike is taken, a new plan from
 * where the rider is would walk them to another. Walk has no transit to check.
 */
import type { TransitOption, TransitPlan } from "./api.ts";
import { locale, t } from "./i18n.ts";
import type { PresetId } from "./presets.ts";

/** How often the trip is checked: WMATA's predictions are kept 20 s on the server, a plan costs a few router calls. */
export const TRIP_CHECK_MS = 120_000;
/** The least another trip must save to replace this one: less is the predictions' own wobble. */
export const SWITCH_MIN_S = 180;
/** A delay this much past the arrival last said is said. */
export const LATE_TOLD_S = 180;

/** The ride types whose trips are checked. */
export const CHECKED_PRESETS: readonly PresetId[] = ["bike-transit", "bikeshare-transit", "walk-transit"];

export function tripChecked(preset: PresetId | null | undefined): boolean {
  return !!preset && CHECKED_PRESETS.includes(preset);
}

/** The trip being ridden, as a check compares it. */
export interface CheckedTrip {
  /** The chosen option's label ("Ride, Metro to Federal Triangle (Orange Line), ride"): the same trip in a new plan. */
  label: string;
  /** When it arrives, as last said (ms since the epoch). */
  arrivesAt: number;
}

export type TripVerdict =
  | { kind: "same" }
  | { kind: "late"; arrivesAt: number }
  | { kind: "switch"; label: string; savedS: number | null };

/** The trip a plan chose, or null for one with no options. */
export function chosenOf(plan: Pick<TransitPlan, "options">): TransitOption | null {
  return plan.options.find((o) => o.chosen) ?? null;
}

/** The trip ridden as a check starts it: its plan's chosen option, arriving its total time after `now`. */
export function checkedTripOf(plan: Pick<TransitPlan, "options" | "total_s">, now: number): CheckedTrip | null {
  const chosen = chosenOf(plan);
  return chosen ? { label: chosen.label, arrivesAt: now + plan.total_s * 1000 } : null;
}

/** What a fresh plan from where the rider is (`fresh`, asked at `now`) says of the trip ridden. */
export function tripVerdict(trip: CheckedTrip, fresh: Pick<TransitPlan, "options">, now: number): TripVerdict {
  const best = chosenOf(fresh);
  if (!best) return { kind: "same" };
  const mine = fresh.options.find((o) => o.label === trip.label) ?? null;
  if (best.label !== trip.label) {
    if (!mine) return { kind: "switch", label: best.label, savedS: null };
    if (best.total_s + SWITCH_MIN_S <= mine.total_s) return { kind: "switch", label: best.label, savedS: mine.total_s - best.total_s };
  }
  const arrivesAt = now + (mine ?? best).total_s * 1000;
  return arrivesAt - trip.arrivesAt >= LATE_TOLD_S * 1000 ? { kind: "late", arrivesAt } : { kind: "same" };
}

/** Said as the ride changes to the quicker trip. */
export function switchSaid(verdict: Extract<TripVerdict, { kind: "switch" }>): string {
  if (verdict.savedS === null) return t("Your trip is no longer running as planned. Changed to: {trip}.", { trip: verdict.label });
  return t("Changed to a quicker trip, about {minutes} min sooner: {trip}.", { minutes: Math.round(verdict.savedS / 60), trip: verdict.label });
}

/** Said of a delay on the trip ridden: "Delays on the way: now arriving about 8:42 am." */
export function lateSaid(arrivesAt: number, clock: (at: number) => string = clockTime): string {
  return t("Delays on the way: now arriving about {time}.", { time: clock(arrivesAt) });
}

/** A time of day in the rider's language: "8:42 am". */
export function clockTime(at: number): string {
  return new Date(at).toLocaleTimeString(locale(), { hour: "numeric", minute: "2-digit" }).toLowerCase();
}
