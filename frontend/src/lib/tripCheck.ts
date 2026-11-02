/**
 * A transit trip kept checked while it is ridden (Stephen, 2026-11-02: "Also for transit, periodically check to see
 * if there's any changes such as delays and the like. Make adjustments if not on the best route"). Until the rider
 * boards the trip's first train or bus, the ride screen asks for the same trip again from where the rider is, leaving
 * now, every `TRIP_CHECK_MS`: the API's plan for now lays WMATA's predicted departures and its rail incidents over the
 * timetable (core/transit_live.py), so a late or missing train shows in it.
 *
 * - Another trip is quicker by `SWITCH_MIN_S` or more than this one is now, or the API says this one is gone (its
 *   departure missed or no longer scheduled, `asked_gone`): the ride changes to it at once and says so ("Changed to
 *   a quicker trip: ..."), where the new trip still has its transit after its line (planned at the stop itself, its
 *   line would be the ride after the train). No button: the change is the adjustment asked for. A trip the rider
 *   picked is changed too: the ask is the best trip.
 * - This one is still the best but now arrives `LATE_TOLD_S` or more later than the first check found: the delay is
 *   said, with the new arrival.
 *
 * At the boarding stop, checks stop once the planned departure is near (`BOARDING_MS`): the rider may be boarding,
 * and a plan from the stop would see their train as gone.
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

/** At the boarding stop, the last check is this long before the planned departure. */
export const BOARDING_MS = 60_000;

/** The ride types whose trips are checked. */
export const CHECKED_PRESETS: readonly PresetId[] = ["bike-transit", "bikeshare-transit", "walk-transit"];

export function tripChecked(preset: PresetId | null | undefined): boolean {
  return !!preset && CHECKED_PRESETS.includes(preset);
}

/** The trip being ridden, as a check compares it. */
export interface CheckedTrip {
  /**
   * Its option's key, sent back as `transit_option`: the API then chooses the same trip (the same stops and lines,
   * core/transit.py same_trip) or says it is gone (`asked_gone`).
   */
  key: string;
  /** When it arrives, as last said (ms since the epoch); null before the first check, which only reads it. */
  arrivesAt: number | null;
}

export type TripVerdict =
  | { kind: "same"; arrivesAt: number; key: string }
  | { kind: "gone" }
  | { kind: "late"; arrivesAt: number; key: string }
  | { kind: "switch"; key: string; label: string; savedS: number | null };

/** The trip a plan chose, or null for one with no options. */
export function chosenOf(plan: Pick<TransitPlan, "options">): TransitOption | null {
  return plan.options.find((o) => o.chosen) ?? null;
}

/** The trip ridden as a check starts it: its plan's chosen trip, its arrival read at the first check. */
export function checkedTripOf(plan: Pick<TransitPlan, "key">): CheckedTrip {
  return { key: plan.key, arrivesAt: null };
}

/**
 * What a fresh plan from where the rider is (`fresh`, asked at `now` with the trip's key as `transit_option`) says of
 * the trip ridden. Its options are best first (the API's ranking: time, with busy riding and junction waits counted).
 * Only a trip with transit replaces it: riding or walking the whole way, though quicker, is the trip the rider did not
 * pick (the release review's S2), so a delay on their train is still said. Gone, with no other transit trip: said, and
 * the ride goes on as it is (`gone`).
 */
export function tripVerdict(trip: CheckedTrip, fresh: Pick<TransitPlan, "options" | "asked_gone">, now: number): TripVerdict | null {
  const best = fresh.options.find((o) => !o.direct && !o.walk);
  const mine = chosenOf(fresh);
  if (fresh.asked_gone) return best ? { kind: "switch", key: best.key, label: best.label, savedS: null } : { kind: "gone" };
  if (!best || !mine) return null;
  if (best.key !== mine.key && best.total_s + SWITCH_MIN_S <= mine.total_s) {
    return { kind: "switch", key: best.key, label: best.label, savedS: mine.total_s - best.total_s };
  }
  const arrivesAt = now + mine.total_s * 1000;
  const late = trip.arrivesAt !== null && arrivesAt - trip.arrivesAt >= LATE_TOLD_S * 1000;
  return { kind: late ? "late" : "same", arrivesAt, key: mine.key };
}

/** Said as the ride changes to the quicker trip. */
export function switchSaid(verdict: Extract<TripVerdict, { kind: "switch" }>): string {
  // What it changed to first: the toast shows the first sentence only (the release review's N3).
  if (verdict.savedS === null) return t("Changed to: {trip}. Your trip was no longer running as planned.", { trip: verdict.label });
  return t("Changed to a quicker trip, about {minutes} min sooner: {trip}.", { minutes: Math.round(verdict.savedS / 60), trip: verdict.label });
}

/** Said where the trip ridden is gone and no other transit trip is left: the ride goes on as it is. */
export const TRIP_GONE_SAID = t("Your trip is no longer running as planned.");

/** Said of a delay on the trip ridden: "Delays on the way: now arriving about 8:42 am." */
export function lateSaid(arrivesAt: number, clock: (at: number) => string = clockTime): string {
  return t("Delays on the way: now arriving about {time}.", { time: clock(arrivesAt) });
}

/** A time of day in the rider's language: "8:42 am". */
export function clockTime(at: number): string {
  return new Date(at).toLocaleTimeString(locale(), { hour: "numeric", minute: "2-digit" }).toLowerCase();
}
