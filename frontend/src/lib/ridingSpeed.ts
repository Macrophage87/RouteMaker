/**
 * The rider's own riding speed (the owner, 2026-10-27: "Some people who ride much faster than the defaults
 * would like to be able to override the speed as an advanced feature").
 *
 * One picker in the ride settings, under Hills (the owner: "next to hill speed or max grade"): the ride type's own pace (the default), or a speed on the flat from
 * `SPEED_MIN_MPH` to `SPEED_MAX_MPH`. The route is then timed at it (the API's `cycling_speed_kmh`, core
 * presets.rider_speed): the router's grade model still slows the climbs and the junction waits still count,
 * so the time, the arrival clock and the ride's to-go times all follow. Mass Ride keeps its speed band and a
 * share bike its own pace; the API ignores the speed there.
 *
 * Kept in this browser, and signed in with the account's settings ("speed", lib/accountSettings.ts), so it
 * follows the rider. Never in a plan link, which the reader's page plans again at their own speed; a saved
 * route or route post keeps the times it was planned with.
 */
import type { Dials } from "./dials.ts";
import type { PresetId } from "./presets.ts";
import { KMH_PER_MPH, formatSpeed } from "./format.ts";
import { browserStore, type KeyValueStore } from "./accessMode.ts";
import { t } from "./i18n.ts";

export const SPEED_STORAGE_KEY = "routemaker.speed";
/** The picker's range, whole mph: below the slowest ride type's pace is not "faster", and 30 mph is a fast pack. */
export const SPEED_MIN_MPH = 8;
export const SPEED_MAX_MPH = 30;
/**
 * What the key holds once the rider picked the ride type's own again: kept, not removed, so the account's
 * settings carry `speed: null` and another signed-in device goes back too instead of putting its own back.
 */
export const SPEED_OWN = "own";

/** Whole mph in the picker's range, or null for anything else (the ride type's own). */
export function speedOf(value: unknown): number | null {
  const mph = typeof value === "string" && value.trim() !== "" ? Number(value) : value;
  if (typeof mph !== "number" || !Number.isInteger(mph) || mph < SPEED_MIN_MPH || mph > SPEED_MAX_MPH) return null;
  return mph;
}

/** The kept speed in mph, or null for the ride type's own. */
export function readSpeed(store: KeyValueStore | null = browserStore()): number | null {
  try {
    return speedOf(store?.getItem(SPEED_STORAGE_KEY) ?? null);
  } catch {
    return null;
  }
}

/** The kept setting for the account: the speed, null once set back to the ride type's own, undefined when never set. */
export function speedSetting(raw: string | null): number | null | undefined {
  if (raw === null) return undefined;
  if (raw === SPEED_OWN) return null;
  return speedOf(raw) ?? undefined;
}

/** Keep it (null: back to the ride type's own). */
export function writeSpeed(mph: number | null, store: KeyValueStore | null = browserStore()): void {
  try {
    store?.setItem(SPEED_STORAGE_KEY, mph === null ? SPEED_OWN : String(mph));
  } catch {
    // Not kept: it holds for this visit.
  }
}

/** Mph as the API's km/h, to a tenth. */
export const speedKmh = (mph: number): number => Math.round(mph * KMH_PER_MPH * 10) / 10;

/** The dials a plan is sent with: the rider's speed added, or none (the ride type's own). Never in the link. */
export function withSpeed(dials: Dials, mph: number | null): Dials {
  const { ridingSpeedKmh: _ignored, ...rest } = dials;
  return mph === null ? rest : { ...rest, ridingSpeedKmh: speedKmh(mph) };
}

/** The picker's choices: "" is the ride type's own, then each whole mph, "16 mph (26 km/h)". */
export function speedOptions(): (readonly [string, string])[] {
  const options: (readonly [string, string])[] = [["", t("Ride type's speed")]];
  for (let mph = SPEED_MIN_MPH; mph <= SPEED_MAX_MPH; mph += 1) options.push([String(mph), formatSpeed(speedKmh(mph))]);
  return options;
}

/** The control's state and its change, as App hands it to the ride settings. */
export interface RidingSpeedControl {
  mph: number | null;
  onChange: (mph: number | null) => void;
}

/** Whether a ride type takes the rider's speed: not Mass Ride (its speed band) nor a share bike (core presets.rider_speed). */
export function takesRiderSpeed(preset: PresetId): boolean {
  return !["mass-ride", "bikeshare", "rebalance", "bikeshare-transit"].includes(preset);
}

export const SPEED_LABEL = t("Riding speed");
export const SPEED_HINT = t("Your usual pace on the flat, for ride times and arrival. Hills and stops still count. Saved to your account when signed in.");
